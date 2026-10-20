"""Guarda de segredos — o repo nunca ganha um segredo novo sem alarme.

Ordem do dono (20/10, "pode implementar o CI"): varre TODOS os arquivos
RASTREADOS pelo git (o que de fato vai para o GitHub) por padrões de
segredo conhecidos e FALHA (exit 1) se achar. Roda:

  * no CI (.github/workflows/ci.yml) a cada push/PR — o build fica
    vermelho com o endereço exato arquivo:linha;
  * localmente (`python tools/secret_guard.py`) — antes de commitar.

Escopo deliberado: só a árvore ATUAL (HEAD). O histórico já foi auditado
à parte (20/10, varredura dos 483 commits) e os segredos que existiram
lá foram rotacionados; o que esta guarda impede é o **deslize novo** —
segredo vivo entrando agora, num repo público.

Padrões cobertos: chave privada (PEM), GitHub (`ghp_`/`gho_`/`ghu_`/
`ghs_`/`ghr_`/`github_pat_`), OpenAI (`sk-`), Google/Gemini (`AIza`),
token de bot Telegram (`id:token`), AWS (`AKIA`), Slack (`xox...`) e
GitLab (`glpat-`). Falsos positivos evitados pela construção: os
próprios padrões no fonte são literais com colchetes/chaves que não casam
(comprovado pelo teste vivo: o repo inteiro precisa varrer limpo).

Testado em `tests/test_secret_guard.py` — incluindo o teste de que o
REPO ATUAL está limpo (falha primeiro aqui do que no GitHub).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# (nome_do_padrao, regex) — ordem só para o relatório ser estável.
PADROES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "chave-privada-PEM",
        re.compile(r"-----BEGIN[A-Z0-9 ]{0,20}PRIVATE KEY-----"),
    ),
    (
        "github-token",
        re.compile(r"(?<![A-Za-z0-9])gh[opusr]_[A-Za-z0-9]{36}(?![A-Za-z0-9])"
                   r"|(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{22,}(?![A-Za-z0-9])"),
    ),
    (
        "openai-key",
        # lookbehind exclui também "-"/"_" (senão `task-sk-...` viraria
        # falso positivo — pegue no teste)
        re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9])"),
    ),
    (
        "google-key",
        re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9])"),
    ),
    (
        "telegram-bot-token",
        re.compile(r"(?<![0-9])\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"),
    ),
    (
        "aws-access-key",
        re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])"),
    ),
    (
        "slack-token",
        re.compile(r"(?<![A-Za-z0-9])xox[bapr]-[A-Za-z0-9-]{10,}(?![A-Za-z0-9])"),
    ),
    (
        "gitlab-pat",
        re.compile(r"(?<![A-Za-z0-9])glpat-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9])"),
    ),
)


class GuardError(RuntimeError):
    """A guarda não pôde rodar (ex.: fora de um repo git)."""


@dataclass(frozen=True)
class Achado:
    arquivo: str  # caminho relativo ao repo
    linha: int  # 1-based
    padrao: str  # nome do padrão que casou


def arquivos_rastreados(raiz: Path) -> list[str]:
    """O que de fato vai para o GitHub (`git ls-files`).

    Só rastreados de propósito: não varre `.venv/`, `backups/` (17 GB),
    `captures/` nem nada que o gitignorado esconde — a guarda protege o
    repositório, não o disco.
    """
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(raiz),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise GuardError(
            "git ls-files falhou — a guarda precisa de um repo git"
        )
    return [n for n in proc.stdout.decode("utf-8", "replace").split("\0") if n]


def achar_em_texto(texto: str, nome: str) -> list[Achado]:
    """Todos os segredos do texto (nome = caminho p/ o relatório)."""
    achados: list[Achado] = []
    for numero, linha in enumerate(texto.splitlines(), start=1):
        for padrao, regex in PADROES:
            if regex.search(linha):
                achados.append(Achado(nome, numero, padrao))
    return achados


def varrer(raiz: Path, arquivos: list[str] | None = None) -> list[Achado]:
    """Varre os arquivos rastreados (ou `arquivos` explícitos, p/ teste).

    Binários/não-UTF-8 são pulados em silêncio: segredo binário não nasce
    num texto — e um PNG não carrega token.
    """
    if arquivos is None:
        arquivos = arquivos_rastreados(raiz)
    achados: list[Achado] = []
    for nome in arquivos:
        caminho = raiz / nome
        try:
            bruto = caminho.read_bytes()
        except OSError:  # arquivo rastreado sumiu do disco — não é daqui
            continue
        try:
            texto = bruto.decode("utf-8")
        except UnicodeDecodeError:
            continue
        achados.extend(achar_em_texto(texto, nome))
    return achados


def main(argv: list[str] | None = None) -> int:
    """CLI: 0 = limpo, 1 = achou segredo, 2 = não pôde rodar."""
    raiz = Path(__file__).resolve().parents[1]
    try:
        arquivos = arquivos_rastreados(raiz)
    except GuardError as exc:
        print(f"Guarda de segredos: {exc}", file=sys.stderr)
        return 2

    achados = varrer(raiz, arquivos)
    if not achados:
        print(f"Guarda de segredos: {len(arquivos)} arquivos rastreados, "
              "0 achados (limpo).")
        return 0

    ci = bool(os.environ.get("CI"))
    for a in achados:
        msg = f"segredo [{a.padrao}] em {a.arquivo}:{a.linha}"
        print(f"::error title=Guarda de segredos::{msg}" if ci else msg)
    print(f"Guarda de segredos: {len(achados)} achado(s) em "
          f"{len(arquivos)} arquivos — NÃO commitar esse segredo; "
          "rotacione se o valor for vivo.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
