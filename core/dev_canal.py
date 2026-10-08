# ---------------------------------------------------------------------------
# Canal de desenvolvimento on-demand (2026-10-08) — histórico de ideias
# ---------------------------------------------------------------------------
#
# Pedido do dono (2026-10-08, txt.txt/chat): o botão ▶ Ativar desenvolvimento
# do painel /admin tem três comportamentos:
#   1. `txt.txt` VAZIO  → não faz nada (sem sessão, sem diálogo);
#   2. ideia IGUAL a uma sessão já CONCLUÍDA → avisa "já foi implementado"
#      e pergunta se ele quer limpar o txt.txt (não roda de novo);
#   3. ideia NOVA → a CLI analisa viabilidade/prós/contras/alternativas e
#      implementa a melhor opção.
#
# Este módulo é a parte 2: o HISTÓRICO que torna o passo 2 possível. Ele é
# compartilhado de propósito — quem escreve é o runner (orquestrador.py, ao
# fim de cada sessão concluída) e quem lê é o painel (integrations/api/server,
# no clique do ▶); os dois precisam da MESMA normalização, senão "mesma ideia"
# vira duas ideias diferentes.
#
# Regras de construção (padrão da casa):
#   - Comparação por hash da forma normalizada (espaços/quebras colapsados,
#     caixa ignorada) — formatação do dono não muda o significado;
#   - Só `status == "concluido"` vale como "já implementado" — sessão que
#     falhou pode ser tentada de novo;
#   - Escrita ATÔMICA (tmp + rename) e leitura tolerante: arquivo ausente ou
#     corrompido → lista vazia, nunca exceção (o canal não quebra por dado);
#   - Arquivo em data/ (gitignored) — estado de runtime, não código.
# ---------------------------------------------------------------------------

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from core.logger import get_logger

log = get_logger(__name__)

#: Histórico de ideias concluídas — escrito pelo orquestrador ao fim da
#: sessão e lido pelo painel no clique de Ativar (caminho relativo à raiz,
#: igual a data/dev_sessao.json e data/dev_caixa.json).
HISTORICO_FILE: Path = Path("data/dev_historico.json")

#: Teto de entradas guardadas (arquivo é humano-legível; a mais antiga sai).
HISTORICO_MAX: int = 200


def normalizar_ideia(texto: Optional[str]) -> str:
    r"""Forma canônica da ideia para comparação.

    `re.sub(r"\s+", " ")` + `strip` + `casefold`: "Criar   botão\r\n NOVO"
    e "criar botão novo" são a MESMA ideia para o aviso de já-implementado.
    """
    return re.sub(r"\s+", " ", (texto or "")).strip().casefold()


def hash_ideia(texto: Optional[str]) -> str:
    """SHA-256 da forma normalizada — chave de deduplicação do histórico."""
    normal = normalizar_ideia(texto)
    if not normal:
        return ""
    return hashlib.sha256(normal.encode("utf-8")).hexdigest()


def carregar_historico(arquivo: Path = HISTORICO_FILE) -> list[dict]:
    """Histórico gravado; ausente/inválido → lista vazia (nunca levanta)."""
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(dados, list):
        return []
    return [entrada for entrada in dados if isinstance(entrada, dict)]


def ideia_ja_implementada(
    texto: Optional[str], arquivo: Path = HISTORICO_FILE
) -> Optional[dict]:
    """Entrada do histórico cuja ideia É esta, se a sessão tiver CONCLUÍDO.

    Devolve a entrada (com ts/commit/motivo para o painel mostrar) ou None.
    Só `status == "concluido"` bloqueia: o que falhou não é "implementado".
    """
    alvo = hash_ideia(texto)
    if not alvo:
        return None
    for entrada in carregar_historico(arquivo):
        if entrada.get("hash") == alvo and entrada.get("status") == "concluido":
            return entrada
    return None


def registrar_ideia(
    texto: Optional[str],
    estado: Optional[dict],
    arquivo: Path = HISTORICO_FILE,
) -> Optional[dict]:
    """Grava a ideia no histórico quando a sessão terminou CONCLUÍDA.

    Devolve a entrada gravada ou None (sessão falhou/interrompida ou ideia
    vazia — nada a registrar). Regravar a MESMA ideia substitui a entrada
    (dedup por hash: vale a conclusão mais recente).
    """
    if not normalizar_ideia(texto):
        return None
    if not estado or estado.get("status") != "concluido":
        return None
    entrada: dict[str, Any] = {
        "hash": hash_ideia(texto),
        "ideia": (texto or "").strip(),
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "concluido",
        "motivo": str(estado.get("motivo") or ""),
        "commit": str(estado.get("commit") or ""),
        "cli": str(estado.get("cli_usada") or estado.get("cli") or ""),
    }
    historico = [
        e for e in carregar_historico(arquivo) if e.get("hash") != entrada["hash"]
    ]
    historico.append(entrada)
    historico = historico[-HISTORICO_MAX:]
    try:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = arquivo.with_suffix(arquivo.suffix + ".tmp")
        tmp.write_text(
            json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(arquivo)
    except OSError as erro:  # o canal não quebra por causa do histórico
        log.warn("Não gravou o histórico de ideias", erro=str(erro))
        return None
    log.info(
        "Ideia registrada no histórico",
        ts=entrada["ts"],
        commit=entrada["commit"] or "-",
        motivo=entrada["motivo"],
    )
    return entrada
