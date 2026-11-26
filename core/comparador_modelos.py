"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/comparador_modelos.py
Descrição: Comparador de modelos lado a lado (fila item 5, 26/11). O mesmo
           prompt vai para 2+ modelos da MESMA cadeia do chat, em paralelo,
           e cada resposta volta com a latência medida — é a diferença
           entre escolher a IA por log antigo e ver ao vivo.

Contrato (pensado para o painel /admin):
    modelos_disponiveis() -> [{"nome", "modelo"}, ...]
    comparar(prompt, nomes=[...]) -> {
        "ok": bool,              # pelo menos um modelo respondeu
        "prompt": str,
        "comparado_em": iso8601,
        "modelos": [{"nome", "modelo", "ok", "resposta", "latencia_ms",
                     "erro", "hardware": {...}|None}, ...],
    }

Custo de máquina (monitor de hardware, 26/11): enquanto cada modelo responde,
`_ColetorHardware` amostra `/proc/stat` (CPU do servidor inteiro) e
`/proc/meminfo` (RAM usada = MemTotal - MemAvailable) a cada 250 ms, e o
resultado leva média e pico de CPU, RAM usada e o DELTA de RAM sobre o valor
de partida (o que a chamada realmente acrescentou). `hardware` é None quando
`/proc` não existe — medir não pode derrubar a comparação.

VRAM não é medida: o LLM local roda em CPU e a máquina não tem contador de
GPU exposto (`nvidia-smi` ausente). Se entrar GPU, o lugar é `_snapshot()`.
O percentual de CPU é do servidor inteiro (a máquina é compartilhada com o
od-core); não é o consumo isolado do modelo.

Regras:
  * MENOS de 2 modelos não é comparação — ValueError (o painel devolve 400
    em vez de fingir que comparou);
  * um modelo que falha não derruba os outros: erro vira campo `erro` e
    `latencia_ms` mede até a falha;
  * `timeout_s` é teto por modelo (asyncio.wait_for) — o local pode ter
    timeout próprio de 240 s e travaria a comparação sozinho;
  * nada é persistido: a comparação é um retrato do agora.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

MIN_MODELOS = 2
MAX_MODELOS = 4
MAX_PROMPT = 4000
TIMEOUT_PADRAO_S = 90.0
INTERVALO_HW_S = 0.25

_PROC_STAT = Path("/proc/stat")
_PROC_MEMINFO = Path("/proc/meminfo")


class ComparadorError(ValueError):
    """Pedido inválido (prompt vazio, menos de 2 modelos, nome desconhecido)."""


def _provedores() -> list[Any]:
    """Cadeia real do chat — a MESMA que responde às mensagens do dono."""
    from runtime.launcher import build_llm_providers

    return build_llm_providers()


def _snapshot() -> Optional[dict[str, float]]:
    """Leitura crua de CPU e RAM do servidor; None sem `/proc` (outro SO)."""
    try:
        linha = _PROC_STAT.read_text(encoding="ascii", errors="replace").splitlines()[0]
        campos = [float(x) for x in linha.split()[1:]]
        memoria = {}
        for item in _PROC_MEMINFO.read_text(encoding="ascii", errors="replace").splitlines():
            chave, _, valor = item.partition(":")
            memoria[chave] = float(valor.split()[0])  # kB
    except (OSError, IndexError, ValueError):
        return None
    idle = campos[3] + (campos[4] if len(campos) > 4 else 0.0)  # idle + iowait
    total_kb = memoria.get("MemTotal", 0.0)
    livre_kb = memoria.get("MemAvailable", 0.0)
    return {
        "cpu_total": sum(campos),
        "cpu_idle": idle,
        "ram_total_mb": total_kb / 1024.0,
        "ram_usada_mb": max(0.0, total_kb - livre_kb) / 1024.0,
    }


class _ColetorHardware:
    """Amostra CPU/RAM enquanto UMA chamada de modelo acontece.

    Um leitor de `/proc` a cada 250 ms é barato (duas leituras de arquivo) e
    roda no mesmo event loop; o pico pega o instante em que o modelo local
    está compilando prompt/gerando token.
    """

    def __init__(self, intervalo_s: float = INTERVALO_HW_S) -> None:
        self.intervalo_s = max(0.05, float(intervalo_s))
        self._inicial = _snapshot()
        self._anterior = self._inicial
        self._amostras: list[dict[str, float]] = []
        self._ultima_s: float = time.monotonic()
        self._tarefa: Optional[asyncio.Task[None]] = None

    @property
    def disponivel(self) -> bool:
        return self._inicial is not None

    def _amostra(self) -> None:
        atual = _snapshot()
        if atual is None or self._anterior is None:
            return
        delta_total = atual["cpu_total"] - self._anterior["cpu_total"]
        delta_idle = atual["cpu_idle"] - self._anterior["cpu_idle"]
        cpu = 0.0 if delta_total <= 0 else 100.0 * (1.0 - delta_idle / delta_total)
        self._amostras.append({
            "cpu_pct": min(100.0, max(0.0, cpu)),
            "ram_usada_mb": atual["ram_usada_mb"],
        })
        self._anterior = atual
        self._ultima_s = time.monotonic()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.intervalo_s)
            self._amostra()

    def iniciar(self) -> None:
        if self.disponivel:
            self._tarefa = asyncio.create_task(self._loop())

    def parar(self) -> None:
        if self._tarefa is not None:
            self._tarefa.cancel()
            self._tarefa = None
        if not self.disponivel:
            return
        # amostra final só quando o intervalo passou: numa chamada curta o
        # delta já está na primeira amostra, e um janela de 5 ms viraria pico
        # falso de 100%.
        if not self._amostras or time.monotonic() - self._ultima_s >= self.intervalo_s * 0.5:
            self._amostra()

    def resumo(self) -> Optional[dict[str, Any]]:
        if not self.disponivel or self._inicial is None or not self._amostras:
            return None
        cpu = [a["cpu_pct"] for a in self._amostras]
        ram = [a["ram_usada_mb"] for a in self._amostras]
        ram_inicial = self._inicial["ram_usada_mb"]
        total = self._inicial["ram_total_mb"] or 1.0
        return {
            "cpu_pct_medio": round(sum(cpu) / len(cpu), 1),
            "cpu_pct_pico": round(max(cpu), 1),
            "ram_usada_mb_medio": round(sum(ram) / len(ram), 1),
            "ram_usada_mb_pico": round(max(ram), 1),
            "ram_inicial_mb": round(ram_inicial, 1),
            "ram_delta_mb_pico": round(max(0.0, max(ram) - ram_inicial), 1),
            "ram_pct_pico": round(max(ram) / total * 100.0, 1),
            "ram_total_mb": round(total, 1),
            "nucleos": os.cpu_count() or 0,
            "amostras": len(self._amostras),
            "intervalo_ms": int(self.intervalo_s * 1000),
        }


def _descrever(provider: Any) -> dict[str, str]:
    return {
        "nome": str(getattr(provider, "name", "") or "?"),
        "modelo": str(getattr(provider, "model", "") or ""),
    }


def modelos_disponiveis(providers: Optional[Sequence[Any]] = None) -> list[dict[str, str]]:
    """Modelos que respondem AGORA (a cadeia já exclui provider sem chave)."""
    lista = list(providers) if providers is not None else _provedores()
    return [_descrever(p) for p in lista]


def _selecionar(
    providers: Sequence[Any], nomes: Optional[Sequence[str]]
) -> list[Any]:
    """Filtra a cadeia pelos nomes pedidos, preservando a ordem dela."""
    if not nomes:
        return list(providers)
    pedidos = [str(n).strip().lower() for n in nomes if str(n).strip()]
    if len(pedidos) < MIN_MODELOS:
        raise ComparadorError(
            f"escolha pelo menos {MIN_MODELOS} modelos para comparar"
        )
    if len(pedidos) > MAX_MODELOS:
        raise ComparadorError(f"no máximo {MAX_MODELOS} modelos por vez")
    por_nome = {str(getattr(p, "name", "")).lower(): p for p in providers}
    desconhecidos = [n for n in pedidos if n not in por_nome]
    if desconhecidos:
        raise ComparadorError(
            "modelo(s) indisponível(is): " + ", ".join(desconhecidos)
        )
    return [por_nome[n] for n in pedidos]


async def _comparar_um(
    provider: Any, prompt: str, timeout_s: float
) -> dict[str, Any]:
    """Uma chamada, medida — falha e timeout são resultado, não exceção."""
    inicio = time.perf_counter()
    descricao = _descrever(provider)
    coletor = _ColetorHardware()
    coletor.iniciar()
    try:
        texto = await asyncio.wait_for(
            provider.generate(prompt), timeout=timeout_s
        )
    except asyncio.TimeoutError:
        return {
            **descricao,
            "ok": False,
            "resposta": "",
            "latencia_ms": round((time.perf_counter() - inicio) * 1000.0, 1),
            "erro": f"tempo esgotado em {timeout_s:g}s",
            "hardware": _resumo_hardware(coletor),
        }
    except Exception as exc:  # provider quebrado não derruba a comparação
        return {
            **descricao,
            "ok": False,
            "resposta": "",
            "latencia_ms": round((time.perf_counter() - inicio) * 1000.0, 1),
            "erro": f"{type(exc).__name__}: {exc}",
            "hardware": _resumo_hardware(coletor),
        }
    finalmente = time.perf_counter()
    return {
        **descricao,
        "ok": bool((texto or "").strip()),
        "resposta": (texto or "").strip(),
        "latencia_ms": round((finalmente - inicio) * 1000.0, 1),
        "erro": "" if (texto or "").strip() else "resposta vazia",
        "hardware": _resumo_hardware(coletor),
    }


def _resumo_hardware(coletor: _ColetorHardware) -> Optional[dict[str, Any]]:
    """Fecha o coletor e devolve o resumo — sempre, inclusive no timeout."""
    coletor.parar()
    return coletor.resumo()


async def comparar_async(
    prompt: str,
    nomes: Optional[Sequence[str]] = None,
    providers: Optional[Sequence[Any]] = None,
    timeout_s: float = TIMEOUT_PADRAO_S,
) -> dict[str, Any]:
    """Versão async (testes e chamadores dentro de event loop)."""
    texto = (prompt or "").strip()
    if not texto:
        raise ComparadorError("prompt vazio")
    if len(texto) > MAX_PROMPT:
        raise ComparadorError(f"prompt acima de {MAX_PROMPT} caracteres")
    cadeia = list(providers) if providers is not None else _provedores()
    selecionados = _selecionar(cadeia, nomes)
    if len(selecionados) < MIN_MODELOS:
        raise ComparadorError(
            f"menos de {MIN_MODELOS} modelos disponíveis para comparar"
        )
    resultados = await asyncio.gather(
        *(_comparar_um(p, texto, float(timeout_s)) for p in selecionados)
    )
    return {
        "ok": any(r["ok"] for r in resultados),
        "prompt": texto,
        "comparado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timeout_s": float(timeout_s),
        "modelos": list(resultados),
    }


def comparar(
    prompt: str,
    nomes: Optional[Sequence[str]] = None,
    providers: Optional[Sequence[Any]] = None,
    timeout_s: float = TIMEOUT_PADRAO_S,
) -> dict[str, Any]:
    """Versão síncrona para o handler HTTP (thread sem event loop)."""
    return asyncio.run(
        comparar_async(prompt, nomes=nomes, providers=providers, timeout_s=timeout_s)
    )
