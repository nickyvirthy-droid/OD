# ---------------------------------------------------------------------------
# Casa de Limitações (v1.13.0) — o sistema percebe o que não sabe
# ---------------------------------------------------------------------------
#
# Pedido do dono (2026-09-30): "o sistema deve perceber suas limitações e
# procurar melhorar. vamos aproveitar o arquivo txt.txt e usar ele para
# interação". Decisão do dono (mesma conversa):
#   - `txt.txt`       → canal do DONO (ideias / pedidos de informação);
#   - `limitacoes.txt` → registro AUTOMÁTICO do sistema (este módulo).
#
# O que entra aqui (hooks no core/orchestrator.py):
#   1. Fallback honesto esgotado (EXTERNAL_UNAVAILABLE_MESSAGE) — o modelo
#      recusou/generou vazio nas 3 gerações e o dono viu o "tente de novo";
#   2. Action de fastpath degradada (format_intent_result → None) — a
#      intenção foi detectada mas o dado real falhou (sem rede, fonte
#      indisponível, contrato quebrado).
#
# Regras de construção (padrão da casa):
#   - NUNCA derruba o pipeline: qualquer exceção é engolida com log;
#   - Append ATÔMICO (tmp + rename) — leitores (painel) nunca veem meia linha;
#   - Dedup por (motivo, pergunta normalizada) dentro da janela de dedup;
#   - Teto de arquivo (LIMITACOES_MAX_BYTES): cheio, o registro mais antigo
#     é podado (sempre guarda o mais recente);
#   - Formato por entrada: bloco "## [ISO] motivo" + "pergunta" — legível
#     no painel sem parser.
# ---------------------------------------------------------------------------

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from core.logger import get_logger

log = get_logger(__name__)

#: Arquivo do registro automático (raiz do projeto, ao lado do txt.txt).
LIMITACOES_FILE = Path("limitacoes.txt")

#: Teto do arquivo (~128 KB) — podado pela frente quando estoura.
LIMITACOES_MAX_BYTES = 128 * 1024

#: Dedup: mesma (motivo, pergunta) dentro desta janela não re-registra.
DEDUP_WINDOW_S = 6 * 3600  # 6h

#: Estado em memória do último registro por chave de dedup (não persistido:
#: o custo de um duplicado após restart é uma linha repetida — aceitável).
_ultimo_registro: dict[str, float] = {}

#: Linha de cabeçalho de uma entrada.
_CABECALHO_RE = re.compile(r"^## \[(?P<iso>[^\]]+)\] (?P<motivo>.+)$")


def _normalizar_pergunta(texto: str) -> str:
    """Normaliza pergunta para dedup (minúsculas, espaços colapsados)."""
    return re.sub(r"\s+", " ", (texto or "").strip().lower())


def _agora_iso() -> str:
    """Timestamp ISO-8601 local (sem dependência externa)."""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _parse_entrada(bloco: str) -> Optional[dict[str, str]]:
    """Converte um bloco '## [iso] motivo\\ncorpo' em dict (ou None)."""
    linhas = bloco.strip().splitlines()
    if not linhas:
        return None
    m = _CABECALHO_RE.match(linhas[0].strip())
    if not m:
        return None
    return {
        "ts": m.group("iso"),
        "motivo": m.group("motivo").strip(),
        "pergunta": "\n".join(linhas[1:]).strip(),
    }


def _iter_entradas(conteudo: str):
    """Divide o arquivo em entradas (blocos separados por linha em branco)."""
    for bloco in re.split(r"\n\s*\n", conteudo.strip()):
        entrada = _parse_entrada(bloco)
        if entrada is not None:
            yield entrada


def registrar_limitacao(motivo: str, pergunta: str) -> bool:
    """Registra uma limitação do sistema em `limitacoes.txt`.

    Args:
        motivo: Motivo curto e estável (ex: "fallback_honesto_esgotado",
            "action_degradada:weather_city").
        pergunta: A pergunta/mensagem original do usuário.

    Returns:
        True quando a entrada foi gravada; False quando dedupada, vazia
        ou em caso de falha (nunca propaga exceção — o pipeline segue).
    """
    try:
        pergunta_limpa = (pergunta or "").strip()
        motivo_limpo = (motivo or "").strip()
        if not pergunta_limpa or not motivo_limpo:
            return False

        chave = f"{motivo_limpo}|{_normalizar_pergunta(pergunta_limpa)}"
        agora = time.time()
        ultimo = _ultimo_registro.get(chave)
        if ultimo is not None and (agora - ultimo) < DEDUP_WINDOW_S:
            return False

        entrada = (
            f"## [{_agora_iso()}] {motivo_limpo}\n{pergunta_limpa}\n"
        )
        _append_atomico(entrada)
        _ultimo_registro[chave] = agora
        log.info(
            "Limitação registrada para melhoria",
            motivo=motivo_limpo,
            pergunta=pergunta_limpa[:120],
        )
        return True
    except Exception as exc:  # pragma: no cover - defesa do pipeline
        log.warn("Falha ao registrar limitação", error=str(exc))
        return False


def _append_atomico(entrada: str) -> None:
    """Append com escrita atômica + poda pelo teto (garante o recente)."""
    atual = ""
    if LIMITACOES_FILE.is_file():
        atual = LIMITACOES_FILE.read_text(
            encoding="utf-8", errors="replace"
        )
    conteudo = (atual.rstrip("\n") + "\n\n" + entrada) if atual.strip() else entrada
    # Teto: podando as entradas mais antigas até caber (com folga).
    while (
        len(conteudo.encode("utf-8")) > LIMITACOES_MAX_BYTES
        and "\n\n" in conteudo
    ):
        _, resto = conteudo.split("\n\n", 1)
        conteudo = resto
    tmp = LIMITACOES_FILE.with_suffix(".txt.tmp")
    tmp.write_text(conteudo, encoding="utf-8")
    tmp.replace(LIMITACOES_FILE)


def ler_limitacoes(limite: int = 200) -> dict[str, Any]:
    """Lê o registro para o painel admin.

    Returns:
        {ok, existe, entradas: [{ts, motivo, pergunta}], total} — entradas
        em ordem CRONOLÓGICA (mais antiga primeiro; o painel mostra o
        recente no fim, como uma trilha).
    """
    if not LIMITACOES_FILE.is_file():
        return {"ok": True, "existe": False, "entradas": [], "total": 0}
    bruto = LIMITACOES_FILE.read_text(encoding="utf-8", errors="replace")
    entradas = list(_iter_entradas(bruto))
    return {
        "ok": True,
        "existe": True,
        "entradas": entradas[-limite:],
        "total": len(entradas),
        "bytes": len(bruto.encode("utf-8")),
    }


def limpar_limitacoes() -> dict[str, Any]:
    """Zera o registro (idempotente, igual DELETE /admin/dev/pedido)."""
    tmp = LIMITACOES_FILE.with_suffix(".txt.tmp")
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
    LIMITACOES_FILE.write_text("", encoding="utf-8")
    _ultimo_registro.clear()
    log.info("Registro de limitações limpo pelo painel admin")
    return {"ok": True, "total": 0}


def registrar_fallback_honesto(pergunta: str) -> bool:
    """Hook do Orchestrator: fallback honesto esgotado (§external)."""
    return registrar_limitacao("fallback_honesto_esgotado", pergunta)


def registrar_action_degradada(action: str, pergunta: str) -> bool:
    """Hook do Orchestrator: action de fastpath degradou (dado real falhou)."""
    return registrar_limitacao(f"action_degradada:{action}", pergunta)
