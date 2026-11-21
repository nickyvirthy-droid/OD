"""
OMEGA DRAKON • CORE
Módulo: core/colapso.py
Descrição: modo colapso DECLARADO (P1 nº 6 da revisão de 17/11). Quando a
           nuvem (LLM) falha repetidas vezes — ou por ordem do dono — o OD
           para de tentar provedores externos, passa a responder só com a IA
           local e DIZ isso na resposta e no /health, em vez de improvisar
           em silêncio.

           Declaração automática: N falhas de provedor de nuvem (padrão 3)
           dentro da janela corrente. Declaração manual: action ``colapso``
           com ``acao="ligar"`` (fica valendo até ``desligar`` — nuvem
           voltando não revoga um pedido do dono).

           O sinal de internet é uma sonda TCP simples (1.1.1.1:443), usada
           só para decidir quando revogar o colapso automático. Nada aqui
           chama LLM.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/llm.py / core/orchestrator.py (cadeia de providers, fallback)
  - docs/CONTINUIDADE.md §5 (modo colapso: trocar para a cadeia local e
    avisar no chat/UI)
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.logger import get_logger

log = get_logger("omega.core.colapso")

ARQUIVO = Path("data/colapso.json")

# Providers que são LOCAIS por definição (nome ou URL). O resto é nuvem.
NOMES_LOCAIS = {"local", "gemma-local", "llama", "qwen", "qwen-local"}


def _bool_env(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome)
    if valor is None or valor == "":
        return padrao
    return valor.strip().lower() not in ("0", "false", "nao", "não", "off")


@dataclass
class ConfigColapso:
    falhas_para_declarar: int = 3
    probe_timeout_s: float = 1.5
    probes_para_revogar: int = 2
    intervalo_s: float = 30.0

    @classmethod
    def do_ambiente(cls) -> "ConfigColapso":
        try:
            falhas = max(1, int(os.getenv("OD_COLAPSO_FALHAS", "3")))
        except ValueError:
            falhas = 3
        return cls(
            falhas_para_declarar=falhas,
            intervalo_s=max(5.0, float(os.getenv("OD_COLAPSO_INTERVALO_S", "30"))),
        )


@dataclass
class EstadoColapso:
    """Estado persistido — sobrevive a restart (o colapso não "some")."""

    ativo: bool = False
    motivo: str = ""
    origem: str = ""            # "automatico" ou "manual"
    desde: str = ""
    falhas_seguidas: int = 0
    ultimo_provider_com_falha: str = ""
    atualizado_em: str = ""

    def como_dict(self) -> dict[str, Any]:
        return {
            "ativo": self.ativo,
            "motivo": self.motivo,
            "origem": self.origem,
            "desde": self.desde,
            "falhas_seguidas": self.falhas_seguidas,
            "ultimo_provider_com_falha": self.ultimo_provider_com_falha,
            "atualizado_em": self.atualizado_em,
        }


_ESTADO: Optional[EstadoColapso] = None
_CONFIG: Optional[ConfigColapso] = None


def config() -> ConfigColapso:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = ConfigColapso.do_ambiente()
    return _CONFIG


def resetar() -> None:
    """Esquece o estado em memória (testes)."""
    global _ESTADO, _CONFIG
    _ESTADO = None
    _CONFIG = None


def _carregar() -> EstadoColapso:
    global _ESTADO
    if _ESTADO is not None:
        return _ESTADO
    try:
        dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        _ESTADO = EstadoColapso(
            ativo=bool(dados.get("ativo")),
            motivo=str(dados.get("motivo", "")),
            origem=str(dados.get("origem", "")),
            desde=str(dados.get("desde", "")),
            falhas_seguidas=int(dados.get("falhas_seguidas", 0) or 0),
            ultimo_provider_com_falha=str(dados.get("ultimo_provider_com_falha", "")),
            atualizado_em=str(dados.get("atualizado_em", "")),
        )
    except (OSError, ValueError, TypeError):
        _ESTADO = EstadoColapso()
    return _ESTADO


def _salvar(estado: EstadoColapso) -> None:
    global _ESTADO
    estado.atualizado_em = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _ESTADO = estado
    try:
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        ARQUIVO.write_text(
            json.dumps(estado.como_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warn("Não consegui gravar o estado do colapso", error=str(exc))


def estado() -> dict[str, Any]:
    return _carregar().como_dict()


def ativo() -> bool:
    return _carregar().ativo


def eh_local(provider: Any) -> bool:
    """Provider local? (nome conhecido ou URL em localhost)."""
    nome = str(getattr(provider, "name", provider) or "").lower()
    if nome in NOMES_LOCAIS:
        return True
    base = str(getattr(provider, "base_url", "") or "").lower()
    return "127.0.0.1" in base or "localhost" in base


def declarar(motivo: str, *, origem: str = "manual") -> dict[str, Any]:
    """Liga o modo colapso (idempotente)."""
    est = _carregar()
    if est.ativo:
        return est.como_dict()
    est.ativo = True
    est.motivo = motivo
    est.origem = origem
    est.desde = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _salvar(est)
    log.warn("Modo colapso DECLARADO", motivo=motivo, origem=origem)
    return est.como_dict()


def revogar(motivo: str = "nuvem de volta") -> dict[str, Any]:
    """Desliga o modo colapso (idempotente)."""
    est = _carregar()
    if not est.ativo:
        return est.como_dict()
    est.ativo = False
    est.falhas_seguidas = 0
    _salvar(est)
    log.info("Modo colapso revogado", motivo=motivo)
    return est.como_dict()


def internet_ok(timeout_s: Optional[float] = None) -> bool:
    """Sonda TCP simples (sem DNS) — só para decidir revogação automática."""
    tempo = timeout_s or config().probe_timeout_s
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=tempo):
            return True
    except OSError:
        return False


def registrar_falha(provider: str) -> dict[str, Any]:
    """Conta falha de provider de NUVEM; declara ao passar do limite."""
    nome = str(provider or "")
    if nome.lower() in NOMES_LOCAIS:
        return _carregar().como_dict()
    est = _carregar()
    est.falhas_seguidas += 1
    est.ultimo_provider_com_falha = nome
    _salvar(est)
    if est.falhas_seguidas >= config().falhas_para_declarar and not est.ativo:
        return declarar(
            f"{est.falhas_seguidas} falhas seguidas de nuvem "
            f"(último: {nome})",
            origem="automatico",
        )
    return est.como_dict()


def registrar_sucesso(provider: str) -> None:
    """Sucesso de nuvem zera a contagem (mas não revoga pedido manual)."""
    est = _carregar()
    if est.falhas_seguidas:
        est.falhas_seguidas = 0
        _salvar(est)
    if est.ativo and est.origem == "automatico":
        # A própria chamada deu certo: a nuvem voltou.
        revogar(f"provider {provider} respondeu")


class MonitorColapso:
    """Loop: enquanto o colapso automático está ativo, sonda a internet e
    revoga quando ela volta (2 sondas seguidas). Não toca em colapso manual.
    """

    def __init__(
        self,
        *,
        sink: Optional[Any] = None,
        probe: Optional[Any] = None,
        arquivo: Path = ARQUIVO,
    ) -> None:
        self.cfg = config()
        self._sink = sink
        self._probe = probe or internet_ok
        self._arquivo = arquivo
        self._ok_seguidos = 0

    def _notificar(self, texto: str) -> None:
        if self._sink is None:
            return
        try:
            resultado = self._sink(texto)
            if hasattr(resultado, "__await__"):
                import asyncio

                try:
                    asyncio.get_running_loop().create_task(resultado)  # type: ignore[arg-type]
                except RuntimeError:
                    asyncio.run(resultado)  # type: ignore[arg-type]
        except Exception as exc:
            log.error("Falha ao avisar sobre colapso", error=str(exc))

    def tick(self) -> dict[str, Any]:
        est = _carregar()
        if not est.ativo:
            self._ok_seguidos = 0
            return est.como_dict()
        if est.origem != "automatico":
            return est.como_dict()
        if self._probe():
            self._ok_seguidos += 1
            if self._ok_seguidos >= self.cfg.probes_para_revogar:
                revogar("internet de volta")
                self._ok_seguidos = 0
                self._notificar(
                    "🌐 Nuvem de volta — modo colapso encerrado."
                )
        else:
            self._ok_seguidos = 0
        return _carregar().como_dict()


def declarar_pelo_dono(ligar: bool) -> dict[str, Any]:
    """Action: liga/desliga pelo dono (manual)."""
    if ligar:
        dados = declarar("declarado pelo dono", origem="manual")
        return {**dados, "mensagem": "Modo colapso ligado (só IA local)."}
    dados = revogar("desligado pelo dono")
    return {**dados, "mensagem": "Modo colapso desligado."}


def resumo_para_resposta() -> str:
    """Prefixo curto que aparece no chat quando o colapso está ativo."""
    est = _carregar()
    if not est.ativo:
        return ""
    return "⚡ modo colapso — respondendo só com a IA local"
