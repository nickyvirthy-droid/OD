#!/usr/bin/env python3
"""
OMEGA DRAKON • SYSTEMS
Ferramenta: tools/brief_multi_ia.py
Descrição: BRIEF ÚNICO das IAs que trabalham no OD.

           O dono constrói o OmegaDrakon com várias IAs ao mesmo tempo, quase
           sempre em ferramentas gratuitas cujos créditos acabam no meio do
           serviço. Sem um ponto de partida comum, cada IA inventa uma direção
           — e algumas chegam a reescrever arquivos por cima do trabalho das
           outras (caso real de 18/11: `orquestrador.py` regredido de 1654 para
           251 linhas, sem registro).

           Este script monta, do ESTADO REAL do repositório, o briefing que
           toda IA recebe antes de tocar em qualquer coisa:
             - versão e commit publicados;
             - árvore suja (trabalho parcial de outra IA) — não reverter;
             - checkpoint vigente (`iniciar/session.json`);
             - últimas atribuições (`iniciar/ATRIBUICOES.md`);
             - prioridades abertas (`docs/ANALISE_SISTEMA_TODO.md`);
             - as regras de convivência que valem para TODAS as IAs.

           Uso:
             python3 tools/brief_multi_ia.py           # imprime o brief
             python3 tools/brief_multi_ia.py --json    # versão estruturada

           O `orquestrador.py` chama `montar_brief()` e injeta o resultado no
           prompt de TODA CLI da cascata — a próxima IA começa de onde a
           anterior parou, com as mesmas regras.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

RAIZ = Path(__file__).resolve().parent.parent
# Rodando como script, o sys.path[0] é `tools/` — o pacote `core` mora na raiz.
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
SESSION_FILE = RAIZ / "iniciar" / "session.json"
ATRIBUICOES_FILE = RAIZ / "iniciar" / "ATRIBUICOES.md"
TODO_FILE = RAIZ / "docs" / "ANALISE_SISTEMA_TODO.md"
RULES_FILE = RAIZ / "iniciar" / "RULES.md"

#: Quantos arquivos da árvore suja listar (o resto vira "+N").
MAX_SUJOS = 8
#: Quantas atribuições recentes do livro-caixa mostrar.
MAX_ATRIBUICOES = 2
#: Orçamento do brief em caracteres — prompt de modelo gratuito é curto.
MAX_CHARS = 6000

REGRAS_DE_CONVIVENCIA = (
    "Regras que valem para TODAS as IAs (iniciar/RULES.md, regra 24):",
    "1. Ler este brief ANTES de qualquer mudança; ele é a fonte do estado.",
    "2. NUNCA reescrever um arquivo inteiro por cima do que existe: editar "
    "cirurgicamente. Reescrita maciça (>70% do arquivo) é bloqueada e a "
    "sessão falha sem commitar — se for mesmo necessário, peça [AUTORIZACAO].",
    "3. Trabalho parcial de outra IA (árvore suja) NÃO se reverte: registre "
    "como origem desconhecida em iniciar/ATRIBUICOES.md e siga a partir dele.",
    "4. Toda entrega registra AUTOR, ARQUIVOS criados/modificados e "
    "INTENÇÃO + ESTADO (pronto/pela metade) em iniciar/ATRIBUICOES.md, "
    "session.json e transcrição do dia (regra 23).",
    "5. Validar antes de publicar: suíte/gate verde e diff revisado; nada de "
    "teste desativado nem asserção enfraquecida para 'passar'.",
    "6. Se a cota acabar no meio: NÃO apague o que fez. Deixe a árvore com o "
    "trabalho parcial, registre o próximo passo exato e saia; a próxima IA "
    "continua daí até concluir.",
    "7. Deploy/restart e ação destrutiva exigem ordem do dono (regra 7).",
    "8. Versão: bump SemVer só no deploy da mudança (iniciar/RULES.md 12).",
)


def _rodar(cmd: list[str]) -> str:
    try:
        r = subprocess.run(
            cmd, cwd=RAIZ, capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (r.stdout or "").strip()


def _versao() -> str:
    try:
        from core.capabilities import OD_VERSION

        return str(OD_VERSION)
    except Exception:  # noqa: BLE001 — brief não pode derrubar nada
        return "desconhecida"


def _arvore_suja() -> list[str]:
    saida = _rodar(["git", "status", "--porcelain"])
    return [linha for linha in saida.splitlines() if linha.strip()]


def _checkpoint() -> dict[str, Any]:
    """Checkpoint mais recente do `session.json` (por `updated_at`, se houver)."""
    try:
        dados = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(dados, dict):
        return {}
    entradas = [
        (chave, valor) for chave, valor in dados.items() if isinstance(valor, dict)
    ]
    if not entradas:
        return {}

    def atualidade(item: tuple[str, dict]) -> str:
        return str(item[1].get("updated_at") or "")

    # Checkpoint de SESSÃO tem `estado_encontrado` (o retrato do turno);
    # entradas de recomendação/decisão são menores e não servem de búscula.
    com_retrato = [e for e in entradas if "estado_encontrado" in e[1]] or entradas
    chave, valor = max(com_retrato, key=atualidade)
    return {"chave": chave, **valor}


def _atribuicoes(n: int = MAX_ATRIBUICOES) -> list[str]:
    """Títulos das últimas entradas do livro-caixa compartilhado."""
    try:
        texto = ATRIBUICOES_FILE.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    titulos = re.findall(r"^## (.+)$", texto, flags=re.MULTILINE)
    return titulos[:n]


def _prioridades() -> list[str]:
    """Itens P0/P1 abertos do TODO (o que a próxima IA deve pegar primeiro)."""
    try:
        texto = TODO_FILE.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    linhas = texto.splitlines()
    itens: list[str] = []
    secao = ""
    for linha in linhas:
        if linha.startswith("#### P0"):
            secao = "P0"
            continue
        if linha.startswith("#### P1"):
            secao = "P1"
            continue
        if linha.startswith("#### P2") or linha.startswith("---"):
            secao = ""
            continue
        if secao and linha.startswith("| ") and not linha.startswith("| #"):
            colunas = [c.strip() for c in linha.strip("|").split("|")]
            if colunas and colunas[0].isdigit():
                itens.append(f"{secao} nº {colunas[0]}: {colunas[1]}")
    return itens


def montar_brief(incluir_prioridades: bool = True) -> str:
    """Briefing textual do estado real — injetado no prompt de cada CLI."""
    partes: list[str] = ["# BRIEF MULTI-IA — OmegaDrakon (leia antes de mudar)"]

    commit = _rodar(["git", "rev-parse", "--short", "HEAD"]) or "?"
    origin = _rodar(["git", "rev-parse", "--short", "origin/master"]) or "?"
    estado_git = "sincronizado" if commit == origin else "DIVERGENTE do origin"
    partes.append(f"Versão: {_versao()} · HEAD: {commit} · origin/master: {origin} "
                  f"({estado_git})")

    sujos = _arvore_suja()
    if sujos:
        lista = "\n".join(f"  {linha}" for linha in sujos[:MAX_SUJOS])
        extra = "" if len(sujos) <= MAX_SUJOS else f"\n  (+{len(sujos) - MAX_SUJOS})"
        partes.append(
            f"Árvore suja ({len(sujos)} arquivo(s)) — provável trabalho parcial de "
            f"outra IA; NÃO reverter, continuar daí:\n{lista}{extra}"
        )
    else:
        partes.append("Árvore limpa.")

    checkpoint = _checkpoint()
    if checkpoint:
        partes.append(
            "Checkpoint vigente (iniciar/session.json): "
            f"{checkpoint.get('chave', '?')}\n"
            f"  pedido: {str(checkpoint.get('pedido', ''))[:220]}\n"
            f"  estado: {str(checkpoint.get('estado_encontrado', checkpoint.get('estado', '')))[:220]}\n"
            f"  em aberto: {str(checkpoint.get('em_aberto', checkpoint.get('pendente', '')))[:220]}"
        )

    titulos = _atribuicoes()
    if titulos:
        partes.append("Últimas entregas registradas (iniciar/ATRIBUICOES.md):\n  - "
                      + "\n  - ".join(titulos))

    if incluir_prioridades:
        itens = _prioridades()
        if itens:
            partes.append("Prioridades P0/P1 abertas (docs/ANALISE_SISTEMA_TODO.md):\n  - "
                          + "\n  - ".join(itens[:6]))

    partes.append("\n".join(REGRAS_DE_CONVIVENCIA))
    texto = "\n\n".join(partes)
    if len(texto) > MAX_CHARS:
        texto = texto[:MAX_CHARS] + "\n…(brief truncado)"
    return texto


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--json" in argv:
        checkpoint = _checkpoint()
        print(json.dumps(
            {
                "versao": _versao(),
                "head": _rodar(["git", "rev-parse", "--short", "HEAD"]),
                "origin": _rodar(["git", "rev-parse", "--short", "origin/master"]),
                "arvore_suja": _arvore_suja(),
                "checkpoint": checkpoint.get("chave", ""),
                "atribuicoes": _atribuicoes(),
                "prioridades": _prioridades() if "--com-prioridades" in argv else [],
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    print(montar_brief())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
