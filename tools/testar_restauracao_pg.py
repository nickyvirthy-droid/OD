#!/usr/bin/env python3
"""Prova de restauração do backup do Postgres — cluster TEMPORÁRIO.

Por que existe (P1 nº 7 de `docs/ANALISE_SISTEMA_TODO.md`): o dump diário do
banco `od` existe desde 13/11 e nunca tinha sido restaurado. Backup que nunca
foi restaurado é esperança, não backup.

Como funciona (sem superusuário e sem tocar no banco de produção):

1. `initdb` num diretório temporário (`/tmp/od-restore-*`), porta livre;
2. cria o papel `od` (o dump faz `OWNER TO od`) e o banco `od_restore`;
3. restaura o dump mais recente de `data/pg_dumps/` com `ON_ERROR_STOP=1`;
4. compara a lista de tabelas e as contagens de linha com o banco `od` vivo;
5. derruba o cluster e apaga o diretório — sempre, inclusive em falha.

Saída: `RESTORE OK` (código 0) quando o restore termina sem erro e todas as
contagens batem; `DIFERENCA`/`FALHA` (código 1) caso contrário.

Uso:
    python3 tools/testar_restauracao_pg.py
    python3 tools/testar_restauracao_pg.py --dump data/pg_dumps/od-....sql.gz
"""

from __future__ import annotations

import argparse
import glob
import gzip
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

#: Candidatos do binário (o PATH do systemd é mínimo).
_CANDIDATOS_PG = (
    "/usr/lib/postgresql/16/bin",
    "/usr/lib/postgresql/15/bin",
    "/usr/lib/postgresql/14/bin",
)


def achar_bin() -> str:
    for pasta in _CANDIDATOS_PG:
        if Path(pasta, "initdb").is_file():
            return pasta
    achado = shutil.which("initdb")
    if achado:
        return str(Path(achado).parent)
    raise SystemExit("PostgreSQL não encontrado (initdb/pg_ctl).")


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _rodar(comando: list[str], **kwargs) -> subprocess.CompletedProcess:
    # errors="replace": o aviso do psql vem na locale do servidor e pode
    # trazer byte latin-1; sem isto o verificador morre com UnicodeDecodeError
    # em vez de mostrar o erro real do restore.
    return subprocess.run(
        comando, capture_output=True, text=True, errors="replace", **kwargs
    )


def contar_linhas_do_dump(caminho: Path) -> dict[str, int]:
    """Linhas de dados por tabela, lidas dos blocos COPY do próprio dump.

    É a comparação exata: o banco vivo pode ter avançado desde 02:50, então
    contar contra ele acusaria "diferença" que é só o tempo passar. O dump
    diz quantas linhas cada tabela tinha; o restaurado tem de ter as mesmas.
    """
    contagem: dict[str, int] = {}
    tabela = ""
    with gzip.open(caminho, "rt", encoding="utf-8", errors="replace") as fh:
        for linha in fh:
            if linha.startswith("COPY "):
                # COPY public.tabela (colunas) FROM stdin;
                tabela = linha.split()[1].split(".")[-1]
                contagem.setdefault(tabela, 0)
            elif linha.rstrip("\n") == "\\.":
                tabela = ""
            elif tabela:
                contagem[tabela] += 1
    return contagem


def comparar(prod: list[str], temp: list[str], env: dict[str, str]) -> tuple[list[str], list[str]]:
    """Lista de tabelas e divergências de contagem (produção × restaurada)."""
    def q(cmd: list[str], sql: str) -> str:
        return _rodar(cmd + ["-c", sql], env=env).stdout.strip()

    tabelas = q(
        prod, "select tablename from pg_tables where schemaname='public' order by 1"
    ).split()
    divergencias: list[str] = []
    for tabela in tabelas:
        origem = q(prod, f'select count(*) from "{tabela}"')
        copia = q(temp, f'select count(*) from "{tabela}"')
        if origem != copia:
            divergencias.append(f"{tabela}: produção={origem} restaurada={copia}")
    return tabelas, divergencias


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump", default="", help="dump .sql.gz (padrão: o mais recente)")
    ap.add_argument("--manter", action="store_true",
                    help="não apaga o cluster temporário (diagnóstico)")
    args = ap.parse_args(argv)

    bin_pg = achar_bin()
    dumps = sorted(glob.glob(str(RAIZ / "data/pg_dumps/od-*.sql.gz")))
    if not dumps:
        print("FALHA: nenhum dump em data/pg_dumps/")
        return 1
    dump = Path(args.dump) if args.dump else Path(dumps[-1])
    if not dump.is_file():
        print(f"FALHA: dump não existe: {dump}")
        return 1

    from dotenv import load_dotenv  # import tardio: só o verificador precisa

    load_dotenv(RAIZ / ".env")
    dsn = os.environ.get("OD_DB_URL", "")
    if not dsn:
        print("FALHA: OD_DB_URL ausente no .env")
        return 1
    url = urllib.parse.urlparse(dsn)
    env_prod = dict(os.environ, PGPASSWORD=urllib.parse.unquote(url.password or ""))

    temporario = tempfile.mkdtemp(prefix="od-restore-")
    porta = porta_livre()
    iniciado = False
    try:
        init = _rodar([f"{bin_pg}/initdb", "-D", temporario, "-A", "trust",
                       "-U", "postgres"])
        if init.returncode != 0:
            print("FALHA: initdb\n" + (init.stderr or "")[-400:])
            return 1
        start = _rodar([f"{bin_pg}/pg_ctl", "-D", temporario, "-o",
                        f"-p {porta} -k /tmp -c listen_addresses=",
                        "-l", f"{temporario}/log", "start"])
        if start.returncode != 0:
            print("FALHA: pg_ctl start\n" + (start.stdout or start.stderr or "")[-400:])
            return 1
        iniciado = True
        time.sleep(1)

        def psql(banco: str, *args: str, stdin=None) -> subprocess.CompletedProcess:
            # stdin em TEXTO via `input=`: passar o arquivo do gzip como stdin
            # entrega o DESCRITOR COMPRIMIDO ao psql (GzipFile.fileno), e ele
            # recebia bytes de gzip — "invalid command \\6".
            comando = [f"{bin_pg}/psql", "-h", "/tmp", "-p", str(porta),
                       "-U", "postgres", "-d", banco, "-v",
                       "ON_ERROR_STOP=1", *args]
            if stdin is not None:
                return _rodar(comando, input=stdin.read())
            return _rodar(comando)

        if psql("postgres", "-c", "CREATE ROLE od").returncode != 0:
            print("FALHA: criar papel od no cluster temporário")
            return 1
        if psql("postgres", "-c", "CREATE DATABASE od_restore OWNER od").returncode != 0:
            print("FALHA: criar banco od_restore")
            return 1

        inicio = time.monotonic()
        with gzip.open(dump, "rt", encoding="utf-8", errors="replace") as fh:
            restore = psql("od_restore", stdin=fh)
        segundos = round(time.monotonic() - inicio, 2)
        if restore.returncode != 0:
            print(f"FALHA: restore de {dump.name} (rc={restore.returncode})")
            print((restore.stderr or "")[-600:])
            return 1

        temp = [f"{bin_pg}/psql", "-h", "/tmp", "-p", str(porta), "-U",
                "postgres", "-d", "od_restore", "-tA"]
        prod = ["psql", "-h", url.hostname or "127.0.0.1", "-p",
                str(url.port or 5432), "-U", url.username or "od", "-d",
                (url.path or "/od").lstrip("/"), "-tA"]
        # (a) fidelidade: restaurado × o que o PRÓPRIO dump declara ter.
        esperado = contar_linhas_do_dump(dump)
        divergencias: list[str] = []
        for tabela in sorted(esperado):
            resultado = psql("od_restore", "-tAc",
                             f'select count(*) from "{tabela}"')
            if resultado.returncode != 0:
                divergencias.append(f"{tabela}: não existe no restaurado")
                continue
            obtido = int(resultado.stdout.strip() or -1)
            if obtido != esperado[tabela]:
                divergencias.append(
                    f"{tabela}: dump={esperado[tabela]} restaurada={obtido}"
                )
        # (b) informação: quanto o banco vivo andou desde o dump.
        tabelas, drift = comparar(prod, temp, env_prod)

        print(f"DUMP {dump.name} ({dump.stat().st_size} B)")
        print(f"RESTORE OK em {segundos} s · {len(tabelas)} tabelas · "
              f"porta {porta}")
        if divergencias:
            print(f"FALHA DE FIDELIDADE em {len(divergencias)} tabela(s):")
            for linha in divergencias:
                print(f"  {linha}")
            return 1
        print(f"FIDELIDADE OK: {sum(esperado.values())} linhas em "
              f"{len(esperado)} tabelas batem com o dump")
        if drift:
            print(f"INFO: {len(drift)} tabela(s) avançaram no banco vivo desde "
                  "o dump (esperado, não é falha)")
        return 0
    finally:
        if iniciado and not args.manter:
            _rodar([f"{bin_pg}/pg_ctl", "-D", temporario, "stop", "-m", "immediate"])
        if not args.manter:
            shutil.rmtree(temporario, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
