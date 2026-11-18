#!/usr/bin/env python3
"""
OMEGA DRAKON • SYSTEMS
Ferramenta: tools/trava_reescrita.py
Descrição: TRAVA DE REESCRITA MACIÇA — a mesma do orquestrador, agora no git.

           Em 18/11 outra ferramenta regrediu `orquestrador.py` de 1654 para
           251 linhas (a versão de fila removida em 08/10) e a suíte passou a
           quebrar na coleta. O orquestrador ganhou a trava
           (`_reescritas_em_massa`), mas ela só valia para sessões
           `--sessao` — IA que trabalha fora dele podia commitar a regressão.

           Este módulo é a FONTE ÚNICA da regra:
             - reescrita suspeita = arquivo rastreado que tinha >= 100 linhas
               e ficou com menos de 30% delas;
             - `--staged` (hook pre-commit) confere o que está em stage;
             - `--worktree` (orquestrador) confere o working tree.

           Escape consciente (decisão do dono, registrada):
             OD_TRAVA_OFF=1 git commit ...   ou   git commit --no-verify
           Ajuste fino sem código: OD_TRAVA_LIMIAR (0.30) e
           OD_TRAVA_MIN_LINHAS (100).

Uso:
    python3 tools/trava_reescrita.py --staged     # hook: 0 ok, 1 bloqueia
    python3 tools/trava_reescrita.py --worktree   # orquestrador
Interface Viva: Nicky Virthy
Arquiteto: Alex Projetti
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional

#: Fração mínima que o arquivo precisa MANTER para não ser suspeito.
LIMIAR_PADRAO = 0.30
#: Só vale a pena vigiar arquivos com este tamanho mínimo.
MIN_LINHAS_PADRAO = 100


def limiar() -> float:
    try:
        return float(os.environ.get("OD_TRAVA_LIMIAR", LIMIAR_PADRAO))
    except ValueError:
        return LIMIAR_PADRAO


def min_linhas() -> int:
    try:
        return int(os.environ.get("OD_TRAVA_MIN_LINHAS", MIN_LINHAS_PADRAO))
    except ValueError:
        return MIN_LINHAS_PADRAO


def avaliar(
    candidatos: Iterable[tuple[str, int, int]],
    limiar_: Optional[float] = None,
    minimo: Optional[int] = None,
) -> list[str]:
    """Núcleo puro: (caminho, linhas_antes, linhas_depois) → suspeitos.

    Separado do git para ser testável sem repositório e para o orquestrador e
    o hook usarem exatamente a mesma régua.
    """
    limiar_ = limiar() if limiar_ is None else limiar_
    minimo = min_linhas() if minimo is None else minimo
    suspeitos: list[str] = []
    for caminho, antes, depois in candidatos:
        if antes < minimo:
            continue
        if depois < antes * limiar_:
            suspeitos.append(f"{caminho}: antes={antes} depois={depois}")
    return suspeitos


def _git(repo: Path, *args: str) -> str:
    try:
        r = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True,
            timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout or ""


def _linhas(texto: str) -> int:
    return len(texto.splitlines())


def _numstat(repo: Path, staged: bool) -> list[tuple[str, int]]:
    """Arquivos MODIFICADOS no stage (ou no worktree), sem binários."""
    args = ["diff", "--numstat", "--diff-filter=M"]
    if staged:
        args.append("--cached")
    itens: list[tuple[str, int]] = []
    for linha in _git(repo, *args).splitlines():
        partes = linha.split("\t")
        if len(partes) != 3:
            continue
        adicionadas, removidas, caminho = partes
        if adicionadas.isdigit() and removidas.isdigit():
            itens.append((caminho, int(removidas)))
    return itens


def _linhas_no_head(repo: Path, caminho: str) -> int:
    return _linhas(_git(repo, "show", f"HEAD:{caminho}"))


def _linhas_no_stage(repo: Path, caminho: str) -> int:
    return _linhas(_git(repo, "show", f":{caminho}"))


def _linhas_no_disco(repo: Path, caminho: str) -> int:
    alvo = repo / caminho
    if not alvo.exists():
        return 0
    try:
        return sum(1 for _ in alvo.open(encoding="utf-8", errors="ignore"))
    except OSError:
        return 0


def verificar(repo: Path = Path("."), staged: bool = True) -> list[str]:
    """Reescritas em massa no stage (staged=True) ou no worktree."""
    ler_depois: Callable[[Path, str], int] = (
        _linhas_no_stage if staged else _linhas_no_disco
    )
    candidatos = [
        (caminho, _linhas_no_head(repo, caminho), ler_depois(repo, caminho))
        for caminho, removidas in _numstat(repo, staged)
        if removidas > 0
    ]
    return avaliar(candidatos)


MENSAGEM = (
    "⛔ COMMIT BLOQUEADO pela trava de reescrita maciça "
    "(docs/PROTOCOLO_MULTI_IA.md, regra 24).\n"
    "{lista}\n\n"
    "Um arquivo rastreado perdeu mais de {perda:.0%} das linhas. Isso apaga\n"
    "trabalho de outra IA sem registro — foi assim que o orquestrador.py caiu\n"
    "de 1654 para 251 linhas em 18/11.\n\n"
    "Se a reescrita é intencional e o dono autorizou:\n"
    "  OD_TRAVA_OFF=1 git commit ...   (ou)   git commit --no-verify\n"
    "e registre em iniciar/ATRIBUICOES.md o autor, os arquivos e o motivo.\n"
)


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    staged = "--worktree" not in argv  # hook usa o default (stage)
    if os.environ.get("OD_TRAVA_OFF", "").strip() in {"1", "true", "sim", "yes"}:
        return 0
    suspeitos = verificar(Path("."), staged=staged)
    if not suspeitos:
        return 0
    onde = "no stage" if staged else "no working tree"
    print(MENSAGEM.format(
        lista="\n".join(f"  - {s}" for s in suspeitos), perda=1 - limiar()
    ) + f"Arquivos {onde}.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
