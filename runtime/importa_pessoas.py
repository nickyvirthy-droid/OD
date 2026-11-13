"""
OMEGA DRAKON • RUNTIME
Tecnologia que respira.
Módulo: runtime/importa_pessoas.py
Descrição: cria a tabela `pessoas` no banco do OD e importa o efetivo
           policial extraído de `analise/Projeti/Cod` (efetivo.txt,
           MapaForca*.txt, Mapa.csv/txt e as saídas dos notebooks) —
           idempotente por matrícula: re-rodar mescla sem duplicar e só
           atualiza o que mudou.
           DADO SENSÍVEL (regra 16): a tabela mora só no Postgres `od`
           (actions `database_*` são admin) e `analise/` é gitignored —
           nunca publicar conteúdo em git/site.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Uso:
    .venv/bin/python -m runtime.importa_pessoas                  # Postgres (OD_DB_URL)
    .venv/bin/python -m runtime.importa_pessoas --db data/od.db   # SQLite
    .venv/bin/python -m runtime.importa_pessoas --dir OUTRO_DIR
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import time

from storage import Database

__signature__ = "OD // CORE"

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DIR_PADRAO = REPO_ROOT / "analise" / "Projeti" / "Cod"

# Linha do efetivo: "2º SGT PM 100001-7 ALFA" (dv pode ser letra: 100002-A).
_RE_EFETIVO = re.compile(
    r"^(?P<posto>[0-9A-Za-zÀ-ÿº°.\s]+?PM)\s+(?P<mat>\d{4,7})-"
    r"(?P<dv>[0-9A-Za-z])\s+(?P<nome>.+)$"
)
# Token de colchete: [CB_PM_100004_DELTA], [2.SGT_PM_100001_ALFA],
# [SD_PM_-_1C_100005_ECHO] (trecho "-_1C_" ignorado) e nomes com espaço.
_RE_TOKEN = re.compile(
    r"\[(?P<posto>[A-Z0-9.]+)_PM_(?:-_[A-Z0-9]+_)?(?P<mat>\d{4,7})_(?P<nome>[^\]]+)\]"
)
# Viatura entre colchetes: [I-90001], [88-901], [I-90002-11].
_RE_VTR_COLCHETE = re.compile(r"\[((?:I-)?\d+(?:-\d+)*)\]")
# Primeira coluna (tabulada) quando não há colchete: SD90001, 66-77, 88-902.
_RE_VTR_COL0 = re.compile(r"^(?:[A-Z]{2,4})?\d+(?:-\d+)?$")
# Mapa.csv: viatura na coluna 8 (0-based) e matrícula nas colunas 11/13.
_RE_VTR_LINHA = re.compile(r"^(?:I-)?\d+(?:-\d+)?$")
_RE_MAT = re.compile(r"^\d{4,7}$")

SCHEMA = {
    "id": "INTEGER PRIMARY KEY",
    "nome": "TEXT NOT NULL DEFAULT ''",
    "posto": "TEXT NOT NULL DEFAULT ''",
    "matricula": "TEXT NOT NULL DEFAULT ''",
    "dv": "TEXT NOT NULL DEFAULT ''",
    "viatura": "TEXT NOT NULL DEFAULT ''",
    "unidade": "TEXT NOT NULL DEFAULT ''",
    "fonte": "TEXT NOT NULL DEFAULT ''",
    "atualizado_em": "REAL NOT NULL DEFAULT 0",
}

_TABELA = "pessoas"
_COLUNAS = ("nome", "posto", "matricula", "dv", "viatura", "unidade", "fonte")


# -- Extração ---------------------------------------------------------------


def _viatura_da_linha(linha: str) -> str:
    """Viatura da linha: colchete primeiro, senão a col0 tabulada."""
    achou = _RE_VTR_COLCHETE.search(linha)
    if achou:
        return achou.group(1)
    if "\t" in linha:
        col0 = linha.split("\t", 1)[0].strip()
        if _RE_VTR_COL0.match(col0):
            return col0
    return ""


def _registro(**campos: str) -> dict:
    reg = {"nome": "", "posto": "", "matricula": "", "dv": "", "unidade": ""}
    reg.update(campos)
    reg["viatura"] = [campos["viatura"]] if campos.get("viatura") else []
    reg["fonte"] = [campos["fonte"]] if campos.get("fonte") else []
    return reg


def extrai_pessoas(texto: str, fonte: str, *, unidade: str = "") -> list[dict]:
    """Linhas de efetivo/token (efetivo.txt, MapaForca*.txt, saídas .ipynb).

    Viatura por linha (colchete ou col0); linha de viatura sem pessoas deixa
    a viatura "pendente" para a linha seguinte — é assim que o efetivo agrupa
    `[88-901]` seguido dos policiais daquela viatura.
    """
    registros: list[dict] = []
    pendente = ""
    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha:
            continue
        vtr = _viatura_da_linha(linha)
        if vtr:
            pendente = vtr
        tokens = list(_RE_TOKEN.finditer(linha))
        if tokens:
            for m in tokens:
                registros.append(
                    _registro(
                        posto=m.group("posto"),
                        matricula=m.group("mat"),
                        nome=m.group("nome").strip(),
                        viatura=vtr or pendente,
                        unidade=unidade,
                        fonte=fonte,
                    )
                )
            pendente = ""
            continue
        efetivo = _RE_EFETIVO.match(linha)
        if efetivo:
            registros.append(
                _registro(
                    posto=efetivo.group("posto").strip(),
                    matricula=efetivo.group("mat"),
                    dv=efetivo.group("dv").upper(),
                    nome=efetivo.group("nome").strip(),
                    unidade=unidade,
                    fonte=fonte,
                )
            )
    return registros


def extrai_mapa_csv(texto: str, fonte: str) -> list[dict]:
    """Mapa.csv/Mapa.txt: vínculo matrícula→viatura+unidade (sem nome).

    O cabeçalho tem 14 campos e os dados 15 (o cabeçalho não nomeia a coluna
    da OPM) — por índice 0-based dos dados: unidade=3, viatura=8, re=11, re2=13.
    """
    registros: list[dict] = []
    for bruta in texto.splitlines():
        linha = bruta.strip()
        if not linha:
            continue
        if linha.startswith('"') and linha.endswith('"'):
            linha = linha[1:-1]
        campos = [c.strip() for c in linha.split(",")]
        if len(campos) < 14:
            continue
        vtr = campos[8]
        if not _RE_VTR_LINHA.match(vtr):
            continue
        for idx in (11, 13):
            if idx >= len(campos):
                continue
            mat = campos[idx]
            if _RE_MAT.match(mat):
                registros.append(
                    _registro(
                        matricula=mat,
                        viatura=vtr,
                        unidade=campos[3],
                        fonte=fonte,
                    )
                )
    return registros


def _opm_do_cabecalho(texto: str) -> str:
    """Valor do bloco `OPM` do cabeçalho do efetivo ("42.BPM/I 3.CIA PM")."""
    linhas = [l.strip() for l in texto.splitlines()]
    for i, atual in enumerate(linhas):
        if atual == "OPM":
            for prox in linhas[i + 1 :]:
                if prox:
                    return prox
    return ""


def _textos_do_notebook(caminho: pathlib.Path) -> str:
    """Só as saídas (outputs) dos notebooks — o source é código, não dado."""
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    partes: list[str] = []
    for celula in dados.get("cells", []) or []:
        for saida in celula.get("outputs", []) or []:
            texto = saida.get("text")
            if texto is None:
                texto = (saida.get("data") or {}).get("text/plain")
            if isinstance(texto, list):
                texto = "".join(texto)
            if isinstance(texto, str):
                partes.append(texto)
    return "\n".join(partes)


def carrega(diretorio: pathlib.Path) -> list[dict]:
    """Todas as fontes do diretório, na ordem de precedência do merge.

    O efetivo vem primeiro de propósito: ele traz posto legível, dv e nome
    em caixa mista, que vencem os tokens em caixa alta dos MapaForca.
    """
    registros: list[dict] = []

    def _ler(nome: str) -> str:
        return (diretorio / nome).read_text(encoding="utf-8", errors="replace")

    efetivo = diretorio / "efetivo.txt"
    if efetivo.exists():
        texto = _ler("efetivo.txt")
        registros += extrai_pessoas(
            texto, "efetivo.txt", unidade=_opm_do_cabecalho(texto)
        )
    for nome in ("MapaForca.txt", "MapaForcaTudo.txt"):
        if (diretorio / nome).exists():
            registros += extrai_pessoas(_ler(nome), nome)
    for notebook in sorted(diretorio.glob("*.ipynb")):
        texto = _textos_do_notebook(notebook)
        if texto:
            registros += extrai_pessoas(texto, notebook.name)
    for nome in ("Mapa.csv", "Mapa.txt"):
        if (diretorio / nome).exists():
            registros += extrai_mapa_csv(_ler(nome), nome)
    return registros


# -- Merge e persistência ---------------------------------------------------


def _funde(destino: dict, origem: dict) -> bool:
    """Preenche vazios da `destino` com a `origem`; lista somam sem repetir.

    Retorna se algo mudou (para não tocar `atualizado_em` à toa).
    """
    mudou = False
    for campo in _COLUNAS:
        if campo in ("viatura", "fonte"):
            for item in origem.get(campo) or []:
                if item and item not in destino[campo]:
                    destino[campo].append(item)
                    mudou = True
        elif not destino.get(campo) and origem.get(campo):
            destino[campo] = origem[campo]
            mudou = True
    return mudou


def _chave(registro: dict) -> str:
    return (registro.get("matricula") or "").strip() or (
        registro.get("nome") or ""
    ).strip().lower()


def _lista_csv(valor: str) -> list[str]:
    return [v.strip() for v in (valor or "").split(",") if v.strip()]


def importa(db: Database, registros: list[dict]) -> dict[str, int]:
    """Cria a tabela (se preciso) e mescla por matrícula — idempotente."""
    db.create_table(_TABELA, SCHEMA, if_not_exists=True)

    agrupadas: dict[str, dict] = {}
    ordem: list[str] = []
    for registro in registros:
        chave = _chave(registro)
        if not chave:
            continue
        atual = agrupadas.get(chave)
        if atual is None:
            atual = _registro(fonte="")
            agrupadas[chave] = atual
            ordem.append(chave)
        _funde(atual, registro)

    existentes: dict[str, dict] = {}
    for linha in db.query(f"SELECT * FROM {_TABELA}"):
        existentes[_chave(linha)] = linha

    inseridos = atualizados = 0
    agora = time.time()
    for chave in ordem:
        nova = agrupadas[chave]
        existente = existentes.get(chave)
        if existente is None:
            db.execute(
                f"INSERT INTO {_TABELA} "
                f"(nome, posto, matricula, dv, viatura, unidade, fonte, atualizado_em) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    nova["nome"],
                    nova["posto"],
                    nova["matricula"],
                    nova["dv"],
                    ", ".join(nova["viatura"]),
                    nova["unidade"],
                    ", ".join(nova["fonte"]),
                    agora,
                ),
            )
            inseridos += 1
            continue
        fundido = dict(existente)
        fundido["viatura"] = _lista_csv(existente.get("viatura", ""))
        fundido["fonte"] = _lista_csv(existente.get("fonte", ""))
        if not _funde(fundido, nova):
            continue
        db.execute(
            f"UPDATE {_TABELA} SET nome = ?, posto = ?, dv = ?, viatura = ?, "
            f"unidade = ?, fonte = ?, atualizado_em = ? WHERE id = ?",
            (
                fundido["nome"],
                fundido["posto"],
                fundido["dv"],
                ", ".join(fundido["viatura"]),
                fundido["unidade"],
                ", ".join(fundido["fonte"]),
                agora,
                existente["id"],
            ),
        )
        atualizados += 1

    total = int(db.scalar(f"SELECT COUNT(*) FROM {_TABELA}") or 0)
    return {"inseridos": inseridos, "atualizados": atualizados, "total": total}


# -- CLI --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Importa o efetivo policial para a tabela `pessoas` (idempotente)."
    )
    parser.add_argument(
        "--db", default="", help="caminho SQLite (default: OD_DB_URL/Postgres)"
    )
    parser.add_argument(
        "--dir",
        default=str(DIR_PADRAO),
        help="diretório com as fontes (default: analise/Projeti/Cod)",
    )
    args = parser.parse_args(argv)

    diretorio = pathlib.Path(args.dir)
    if not diretorio.is_dir():
        print(f"Diretório não encontrado: {diretorio}")
        return 2

    if args.db:
        db = Database(args.db)
        fonte = args.db
    else:
        dsn = os.environ.get("OD_DB_URL", "")
        if not dsn:
            print("OD_DB_URL ausente — passe --db <sqlite> ou exporte a URL.")
            return 2
        db = Database(dsn=dsn)
        fonte = "Postgres (OD_DB_URL)"

    try:
        registros = carrega(diretorio)
        stats = importa(db, registros)
    finally:
        db.close()

    print(f"Fonte: {fonte}")
    print(f"Fontes lidas: {diretorio}")
    print(
        f"  {_TABELA}: {stats['total']} pessoa(s) — "
        f"{stats['inseridos']} nova(s), {stats['atualizados']} atualizada(s) "
        f"(extraídas: {len(registros)} registro(s))"
    )
    if not registros:
        print("  aviso: nenhuma fonte reconhecida no diretório")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
