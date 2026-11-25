#!/usr/bin/env python3
"""Guarda do OFF-SITE do dump do Postgres — o arquivo que saiu da máquina.

Por que existe (25/11, fechando o "offsite físico" do P1 nº 7): o dump diário
do banco `od` já viaja para fora da máquina por dois caminhos, mas ninguém
conferia se o arquivo que CHEGOU é o mesmo que foi gerado. Backup que viaja
corrompido, truncado ou que não é o dump do dia é backup que não existe —
e o silêncio só aparece no dia do desastre.

Caminhos verificados (medidos, não presumidos):

  * **HD externo** — o snapshot diário (`core/hd_backup.py`, rsync para
    `/home/alex/dados/od_snapshots/` e `/mnt/Arquivos/od_snapshots/`, disco
    separado do sistema) leva o repo inteiro, logo `data/pg_dumps/`;
  * **canal privado do Telegram** — o tar diário (`core/backup.py` 03:00 →
    `core/offsite.py`) leva `data/` junto; o que foi enviado fica registrado
    em `data/offsite_state.json` (nome + sha256).

Comparação por **sha256**, não por tamanho e nunca por nome: é o mesmo
critério do `core/offsite.py` e do `runtime/pg_dump_diario.py`.

Uso:
    python3 tools/checar_offsite_pg.py                 # dump mais novo
    python3 tools/checar_offsite_pg.py --dump <arquivo> --json
    python3 tools/checar_offsite_pg.py --snapshots /outro/od_snapshots

Saída: `OFFSITE OK` (código 0) ou `OFFSITE DIVERGENTE` (código 1) — só
divergência de fato derruba; HD desplugada ou snapshot ainda não feito
aparecem como `aguardando`/`ausente`, que é a verdade e não um defeito.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
DUMPS_PADRAO = RAIZ / "data" / "pg_dumps"
ESTADO_OFFSITE_PADRAO = RAIZ / "data" / "offsite_state.json"
TAR_DIR_PADRAO = RAIZ / "backups" / "auto"
SNAPSHOTS_PADRAO = (
    "/home/alex/dados/od_snapshots",
    "/mnt/Arquivos/od_snapshots",
)
# Dentro do snapshot o repo aparece no caminho absoluto completo (rsync -R).
REPO_NO_SNAPSHOT = Path("home") / "alex" / "OmegaDrakon"
PADRAO_DUMP = re.compile(r"od-(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})\.sql\.gz$")
PADRAO_SNAPSHOT = re.compile(r"snapshot_od-(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})$")


def sha256_de(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def selo_do_nome(nome: str, padrao: re.Pattern[str]) -> str:
    """`AAAA-MM-DD_HHMM` do nome — string ordenável, sem depender do mtime."""
    achado = padrao.search(nome)
    if not achado:
        return ""
    return f"{achado.group(1)}_{achado.group(2)}{achado.group(3)}"


def dump_mais_novo(dir_dumps: Path) -> Path | None:
    """Só nome canônico (`od-AAAA-MM-DD_HHMM.sql.gz`) conta como dump."""
    dumps = sorted(
        p for p in dir_dumps.glob("od-*.sql.gz") if PADRAO_DUMP.search(p.name)
    )
    return dumps[-1] if dumps else None


def sha256_do_membro_tar(tar_path: Path, membro: str) -> str | None:
    """sha256 do arquivo dentro do tar (sem extrair para o disco)."""
    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            for item in tf:
                if not item.isfile():
                    continue
                nome = item.name.lstrip("./")
                if nome.endswith(membro):
                    try:
                        fh = tf.extractfile(item)
                    except (KeyError, tarfile.TarError):
                        return None
                    if fh is None:
                        return None
                    h = hashlib.sha256()
                    with fh:
                        for bloco in iter(lambda: fh.read(1 << 20), b""):
                            h.update(bloco)
                    return h.hexdigest()
    except (OSError, tarfile.TarError):
        return None
    return None


def checar_snapshot(dump: Path, raiz: Path) -> dict[str, Any]:
    """O dump está no snapshot MAIS NOVO desse HD, com o mesmo sha256?"""
    alvo = {"alvo": str(raiz), "status": "ausente", "snapshot": "",
            "motivo": "ponto de montagem ausente ou sem snapshot (HD fora?)"}
    if not raiz.is_dir():
        return alvo
    snapshots = sorted(p for p in raiz.iterdir()
                       if p.is_dir() and PADRAO_SNAPSHOT.search(p.name))
    if not snapshots:
        return alvo
    novo = snapshots[-1]
    alvo["snapshot"] = novo.name
    selo_snapshot = selo_do_nome(novo.name, PADRAO_SNAPSHOT)
    selo_dump = selo_do_nome(dump.name, PADRAO_DUMP)
    if selo_snapshot and selo_dump and selo_snapshot < selo_dump:
        # Snapshot de antes do dump existir: nada a provar ainda (não é falha).
        alvo.update(status="aguardando",
                    motivo=f"snapshot {selo_snapshot} é anterior ao dump {selo_dump}")
        return alvo
    copia = novo / REPO_NO_SNAPSHOT / "data" / "pg_dumps" / dump.name
    if not copia.is_file():
        alvo.update(status="divergente",
                    motivo=f"{dump.name} não está no snapshot {novo.name}")
        return alvo
    local = sha256_de(dump)
    remoto = sha256_de(copia)
    if local != remoto:
        alvo.update(status="divergente",
                    motivo=f"sha256 diferente ({local[:12]} × {remoto[:12]})")
        return alvo
    alvo.update(status="ok", motivo=f"sha256 {local[:12]} idêntico")
    return alvo


def checar_canal(
    dump: Path,
    *,
    estado_path: Path = ESTADO_OFFSITE_PADRAO,
    tar_dir: Path = TAR_DIR_PADRAO,
) -> dict[str, Any]:
    """O tar que o offsite diz ter enviado existe, é o mesmo e leva este dump?"""
    resultado: dict[str, Any] = {
        "status": "ausente", "tar": "", "motivo": "sem registro de envio",
    }
    try:
        estado = json.loads(estado_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return resultado
    diario = estado.get("diario") or {}
    nome_tar = str(diario.get("arquivo") or "")
    digest_tar = str(diario.get("sha256") or "")
    if not nome_tar or not digest_tar:
        return resultado
    resultado["tar"] = nome_tar
    tar_path = tar_dir / nome_tar
    if not tar_path.is_file():
        resultado.update(
            status="divergente",
            motivo=f"tar {nome_tar} registrado como enviado não existe em {tar_dir}",
        )
        return resultado
    sha_local = sha256_de(tar_path)
    if sha_local != digest_tar:
        resultado.update(
            status="divergente",
            motivo=("tar em disco não é o que foi enviado "
                    f"({sha_local[:12]} × {digest_tar[:12]})"),
        )
        return resultado
    sha_membro = sha256_do_membro_tar(tar_path, dump.name)
    if sha_membro is None:
        resultado.update(
            status="divergente",
            motivo=f"{dump.name} não está dentro do tar enviado {nome_tar}",
        )
        return resultado
    sha_dump = sha256_de(dump)
    if sha_membro != sha_dump:
        resultado.update(
            status="divergente",
            motivo=(f"{dump.name} dentro do tar tem sha256 diferente "
                    f"({sha_membro[:12]} × {sha_dump[:12]})"),
        )
        return resultado
    resultado.update(status="ok", motivo=f"sha256 {sha_membro[:12]} idêntico")
    return resultado


def verificar(
    dump: Path,
    *,
    snapshots: tuple[str, ...] = SNAPSHOTS_PADRAO,
    estado_path: Path = ESTADO_OFFSITE_PADRAO,
    tar_dir: Path = TAR_DIR_PADRAO,
) -> dict[str, Any]:
    """Resumo completo: canal + cada HD. `ok` só cai em divergência real."""
    hds = [checar_snapshot(dump, Path(raiz)) for raiz in snapshots]
    canal = checar_canal(dump, estado_path=estado_path, tar_dir=tar_dir)
    divergente = canal["status"] == "divergente" or any(
        hd["status"] == "divergente" for hd in hds
    )
    provado = canal["status"] == "ok" or any(hd["status"] == "ok" for hd in hds)
    return {
        "ok": not divergente and provado,
        "divergente": divergente,
        "dump": dump.name,
        "bytes": dump.stat().st_size if dump.is_file() else 0,
        "sha256": sha256_de(dump) if dump.is_file() else "",
        "canal": canal,
        "hds": hds,
    }


def imprimir(resumo: dict[str, Any]) -> None:
    print(f"DUMP {resumo['dump']} ({resumo['bytes']} B) sha256 "
          f"{resumo['sha256'][:12]}…")
    canal = resumo["canal"]
    print(f"CANAL {canal['status']}: {canal['tar'] or '(nada)'} — {canal['motivo']}")
    for hd in resumo["hds"]:
        print(f"HD {hd['status']}: {hd['alvo']} — {hd['motivo']}")
    if resumo["divergente"]:
        print("OFFSITE DIVERGENTE: o arquivo fora da máquina não é o dump atual.")
    elif resumo["ok"]:
        print("OFFSITE OK: o dump atual existe fora da máquina com o mesmo sha256.")
    else:
        print("OFFSITE NÃO PROVADO: nenhum destino com cópia conferível agora.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump", default="",
                    help="dump .sql.gz (padrão: o mais recente de data/pg_dumps)")
    ap.add_argument("--snapshots", default="",
                    help="raízes dos snapshots (vírgula; padrão: as 2 HDs)")
    ap.add_argument("--estado", default=str(ESTADO_OFFSITE_PADRAO),
                    help="estado do offsite (padrão: data/offsite_state.json)")
    ap.add_argument("--tar-dir", default=str(TAR_DIR_PADRAO),
                    help="onde ficam os tars do backup (padrão: backups/auto)")
    ap.add_argument("--json", action="store_true", help="resumo em JSON")
    args = ap.parse_args(argv)

    dump = Path(args.dump) if args.dump else dump_mais_novo(DUMPS_PADRAO)
    if dump is None or not dump.is_file():
        print(f"FALHA: dump não encontrado ({dump or 'nenhum em data/pg_dumps'})",
              file=sys.stderr)
        return 1
    raizes = tuple(s.strip() for s in args.snapshots.split(",") if s.strip())
    resumo = verificar(
        dump,
        snapshots=raizes or SNAPSHOTS_PADRAO,
        estado_path=Path(args.estado),
        tar_dir=Path(args.tar_dir),
    )
    if args.json:
        print(json.dumps(resumo, ensure_ascii=False, indent=2))
    else:
        imprimir(resumo)
    return 1 if resumo["divergente"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
