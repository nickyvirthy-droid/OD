"""OMEGA DRAKON • RUNTIME
Módulo: runtime/pg_dump_diario.py — dump diário do Postgres `od`
(ordem do dono, 13/11, fechando o achado da auditoria de `backups/`).

Por que existe (MEDIDO em 13/11, não presumido): nenhum dump automático
existia em lugar nenhum — `pg_dump` só em `runtime/install_postgres.sh`
(instalação), sem crontab nem timer; o tar diário (`core/backup.py`) leva
`.env` + `data/` (SQLite) e o snapshot das HDs (`core/hd_backup.py`) não
inclui `/var/lib/postgresql`. O único dump era o manual de 16/10.

O oneshot roda no timer `od-pg-dump` (02:50 — 10 min antes do tar das
03:00) e grava em `data/pg_dumps/`. Estar DENTRO de `data/` é o desenho:
sem código extra nenhum, o dump vai junto em

  * **tar diário (03:00)** — `data/pg_dumps` não está em
    `EXCLUIDOS_PADRAO` nem em `IGNORAR_SUFIXOS` (guardado pelo teste
    `test_nao_excluido_do_tar_do_backup`);
  * **canal do Telegram (offsite)** — o `tick()` manda o tar mais novo;
  * **snapshot das HDs (03:44)** — o rsync exclui só `backups/` e
    `data/vector_memory`.

Contrato:
  * `executar()` chama `pg_dump` em LISTA de argumentos (sem shell), o
    gzip é feito em Python, grava `.tmp` e só renomeia no fim — dump
    interrompido nunca fica com nome de pronto para restaurar — e devolve
    `{arquivo, bytes, sha256}`.
  * `rodar()` tenta 2× (10 s de folga: no boot o timer `Persistent` e o
    postgres sobem juntos), poda para os `OD_PG_DUMP_MANTER` mais novos
    (default 14 ≈ 450 KB), grava `data/pg_dumps/estado.json` e, na
    falha, **1 aviso no Telegram a cada 6 h** (mesmo cooldown do
    `core/backup.py` — backup que falha em silêncio é o pior) e exit 1
    (o motivo fica no journal do unit).
  * restauração (a parte que ninguém lembra até precisar):
    `gunzip -c od-AAAA-MM-DD_HHMM.sql.gz | psql "$OD_DB_URL"`.

DSN: `OD_DB_URL` do ambiente (o unit carrega `EnvironmentFile=.env`),
senão do `.env` via `runtime.launcher.load_env` (roda manual). Sem dsn →
erro honesto e exit 1; nunca inventa dump.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, BinaryIO, Callable

from runtime.launcher import load_env

DIR_PADRAO = Path("data/pg_dumps")
MANTER_PADRAO = 14
TENTATIVAS_PADRAO = 2
ESPERA_PADRAO_S = 10.0
COOLDOWN_AVISO_S = 6 * 3600.0
PREFIXO_PADRAO = "od-"
SUFIXO_PADRAO = ".sql.gz"
MENSAGEM_MAX = 200
PG_DUMP_CANDIDATOS = ("/usr/lib/postgresql/16/bin/pg_dump", "/usr/bin/pg_dump")

# Contrato do gerador: recebe (dsn, arquivo-binário de saída) e escreve o
# SQL cru por lá; o gzip é papel de `executar()`.
Gerador = Callable[[str, BinaryIO], None]


class FalhaDump(RuntimeError):
    """O dump não foi produzido — estado gravado e dono avisado."""


def nome_de(agora: float) -> str:
    """Nome cronológico `od-AAAA-MM-DD_HHMM.sql.gz` — ordena = mais novo."""
    selo = time.strftime("%Y-%m-%d_%H%M", time.localtime(agora))
    return f"{PREFIXO_PADRAO}{selo}{SUFIXO_PADRAO}"


def caminho_para(dir: Path, agora: float) -> Path:
    return dir / nome_de(agora)


def listar_dumps(dir: Path) -> list[Path]:
    """Só o padrão de dump — `estado.json` e o que mais estiver lá não conta."""
    return sorted(dir.glob(f"{PREFIXO_PADRAO}*{SUFIXO_PADRAO}"))


def podar(dir: Path, manter: int) -> list[Path]:
    """Mantém os `manter` mais novos; devolve o que foi apagado.

    Nomes ordenam cronologicamente, então "mais novos" = fim da lista.
    `manter < 1` vira 1: apagar TUDO num dump é acidente, não política.
    """
    dumps = listar_dumps(dir)
    manter = max(1, int(manter))
    victimas = dumps[: len(dumps) - manter] if len(dumps) > manter else []
    for caminho in victimas:
        caminho.unlink(missing_ok=True)
    return victimas


def executar(*, dsn: str, destino: Path, gerador: Gerador) -> dict[str, Any]:
    """Grava o dump em `.tmp` → renomeia; devolve `{arquivo, bytes, sha256}`.

    O `.tmp` só vira arquivo pronto no fim: um dump interrompido (máquina
    caiu, pg_dump morreu) nunca aparece com nome restaurável.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".tmp")
    try:
        with open(tmp, "wb") as bruto:
            # filename="" e mtime=0: o cabeçalho gzip não carrega hora nem
            # nome de temp — sha256 estável para o mesmo conteúdo.
            with gzip.GzipFile(filename="", mode="wb", fileobj=bruto, mtime=0) as gz:
                gerador(dsn, gz)
        digesto = hashlib.sha256(tmp.read_bytes()).hexdigest()
        tmp.replace(destino)
    except FalhaDump:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as erro:
        tmp.unlink(missing_ok=True)
        raise FalhaDump(f"dump não completou: {erro}") from erro
    return {
        "arquivo": destino.name,
        "bytes": destino.stat().st_size,
        "sha256": digesto,
    }


def _gerador_padrao(pg_dump: str, *, popen: Callable = subprocess.Popen) -> Gerador:
    """`pg_dump <dsn>` em lista de argumentos (sem shell), stdout → gzip.

    stderr vai para arquivo temporário e não para PIPE: um pipe de stderr
    cheio enquanto o stdout é lido trava o processo — arquivo não trava.
    """
    def gerar(dsn: str, saida: BinaryIO) -> None:
        with tempfile.TemporaryFile() as erro:
            proc = popen([pg_dump, dsn], stdout=subprocess.PIPE, stderr=erro)
            for bloco in iter(lambda: proc.stdout.read(1 << 20), b""):
                saida.write(bloco)
            codigo = proc.wait()
            if codigo != 0:
                erro.seek(0)
                texto = erro.read().decode("utf-8", "replace").strip()
                raise FalhaDump(
                    f"pg_dump saiu com {codigo}: {texto[:MENSAGEM_MAX] or '(sem stderr)'}"
                )
    return gerar


def pg_dump_de(env: dict[str, str]) -> str:
    """Binário: `OD_PG_DUMP_BIN` → PATH → caminhos fixos do Postgres 16

    (o PATH do systemd é minúsculo — o `/usr/bin/pg_dump` existe, mas o
    candidato fixo cobre o caso de PATH ausente).
    """
    explicito = (env.get("OD_PG_DUMP_BIN") or "").strip()
    if explicito:
        return explicito
    achado = shutil.which("pg_dump")
    if achado:
        return achado
    for caminho in PG_DUMP_CANDIDATOS:
        if Path(caminho).exists():
            return caminho
    raise FalhaDump(
        "pg_dump não encontrado (OD_PG_DUMP_BIN, PATH e "
        f"{'/'.join(PG_DUMP_CANDIDATOS)} falharam)"
    )


def estado_inicial() -> dict[str, Any]:
    return {
        "falhas": 0,
        "rodadas": 0,
        "ultimo_arquivo": "",
        "ultimo_bytes": 0,
        "ultimo_sha256": "",
        "ultimo_erro": "",
        "ultimo_sucesso": 0.0,
        "ultimo_aviso_em": 0.0,
    }


def carregar_estado(path: Path) -> dict[str, Any]:
    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else estado_inicial()
    except (OSError, ValueError):
        return estado_inicial()


def gravar_estado(path: Path, estado: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(estado, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(path)


def avisar(
    estado: dict[str, Any],
    texto: str,
    *,
    agora: float,
    enviar: Callable[[str], None],
    cooldown: float = COOLDOWN_AVISO_S,
) -> bool:
    """1 aviso por `cooldown` — a mesma regra do `core/backup.py`.

    Sem isso, um banco quebrado chamaria o dono 96×/dia. Grava
    `ultimo_aviso_em` no estado; devolve se o aviso foi de fato enviado.
    """
    ultimo = float(estado.get("ultimo_aviso_em") or 0.0)
    if ultimo > 0.0 and agora - ultimo <= cooldown:
        return False
    enviar(texto)
    estado["ultimo_aviso_em"] = agora
    return True


def montar_enviar(
    env: dict[str, str], *, abrir: Callable = urllib.request.urlopen
) -> Callable[[str], None]:
    """Push no Telegram (regra 15: falha de backup não é silêncio)."""
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (env.get("OD_TELEGRAM_ADMINS") or "").split(",")[0].strip()
    if not token or not chat:
        raise FalhaDump(
            "TELEGRAM_BOT_TOKEN/OD_TELEGRAM_ADMINS ausentes — sem canal não há aviso"
        )

    def enviar(texto: str) -> None:
        dados = urllib.parse.urlencode({"chat_id": chat, "text": texto}).encode()
        requisicao = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=dados
        )
        with abrir(requisicao, timeout=30) as resposta:
            corpo = json.loads(resposta.read().decode("utf-8"))
        if not corpo.get("ok"):
            raise FalhaDump(f"Telegram recusou o aviso: {str(corpo)[:MENSAGEM_MAX]}")

    return enviar


def rodar(
    env: dict[str, str],
    *,
    dir: Path | str = DIR_PADRAO,
    manter: int = MANTER_PADRAO,
    agora: float | None = None,
    gerador: Gerador | None = None,
    enviar: Callable[[str], None] | None = None,
    espera: Callable[[float], None] = time.sleep,
) -> int:
    """Uma rodada completa: dump → poda → estado (e aviso na falha).

    `gerador`/`enviar`/`espera` são injetados pelos testes; o padrão de
    produção é pg_dump de verdade + Telegram real.
    """
    agora = time.time() if agora is None else agora
    raiz = Path(dir)
    raiz.mkdir(parents=True, exist_ok=True)
    estado_path = raiz / "estado.json"
    estado = carregar_estado(estado_path)
    estado["rodadas"] = int(estado.get("rodadas") or 0) + 1
    destino = caminho_para(raiz, agora)
    try:
        dsn = (env.get("OD_DB_URL") or "").strip()
        if not dsn:
            raise FalhaDump(
                "OD_DB_URL ausente (nem no ambiente nem no .env) — "
                "sem dsn não há como falar com o Postgres"
            )
        uso_gerador = gerador or _gerador_padrao(pg_dump_de(env))
        falha: FalhaDump | None = None
        for tentativa in range(TENTATIVAS_PADRAO):
            try:
                info = executar(dsn=dsn, destino=destino, gerador=uso_gerador)
                falha = None
                break
            except FalhaDump as erro:
                falha = erro
                if tentativa + 1 < TENTATIVAS_PADRAO:
                    espera(ESPERA_PADRAO_S)
        if falha is not None:
            raise falha
        podados = podar(raiz, manter)
        estado.update(
            {
                "ultimo_arquivo": info["arquivo"],
                "ultimo_bytes": info["bytes"],
                "ultimo_sha256": info["sha256"],
                "ultimo_erro": "",
                "ultimo_sucesso": agora,
            }
        )
        gravar_estado(estado_path, estado)
        print(
            f"OD // PG DUMP OK {info['arquivo']} {info['bytes']} B "
            f"sha256={info['sha256'][:12]} podados={len(podados)}"
        )
        return 0
    except FalhaDump as erro:
        estado["falhas"] = int(estado.get("falhas") or 0) + 1
        estado["ultimo_erro"] = str(erro)[:MENSAGEM_MAX]
        texto = f"OD // PG DUMP FALHOU — {erro}"
        try:
            # O aviso nunca mascara a falha original: se o Telegram também
            # estiver fora, o journal fica com as duas e o exit continua 1.
            avisar(estado, texto, agora=agora, enviar=(enviar or montar_enviar(env)))
        except Exception as falha_aviso:
            print(f"OD // aviso não enviado: {falha_aviso}", file=sys.stderr)
        gravar_estado(estado_path, estado)
        print(texto, file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m runtime.pg_dump_diario [--dir D] [--manter N]`."""
    ap = argparse.ArgumentParser(
        description="Dump diário do Postgres od (timer od-pg-dump, 02:50)"
    )
    ap.add_argument(
        "--dir", default=str(DIR_PADRAO), help="diretório dos dumps (default data/pg_dumps)"
    )
    ap.add_argument(
        "--manter", type=int, default=MANTER_PADRAO, help="dumps a manter (default 14)"
    )
    args = ap.parse_args(argv)
    # Ambiente vence .env (o unit já carrega EnvironmentFile=.env; na
    # roda manual o .env cobre a falta).
    env: dict[str, str] = {**load_env(), **os.environ}
    return rodar(env, dir=args.dir, manter=args.manter)


if __name__ == "__main__":
    raise SystemExit(main())
