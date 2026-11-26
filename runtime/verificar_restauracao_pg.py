#!/usr/bin/env python3
"""Verificação SEMANAL da restauração do backup do Postgres.

Por que existe (19/11/2026): o dump diário do banco `od` era restaurado só
manualmente — e backup que nunca é restaurado não é backup. Este runner roda
`tools/testar_restauracao_pg.py` (cluster temporário, sem tocar no banco de
produção) e **avisa no Telegram quando a restauração falha**, com a saída do
verificador no corpo da mensagem.

Regra de silêncio: sucesso não gera mensagem (o `/health` e o journal bastam);
falha gera **uma** mensagem por rodada. O estado fica em
`data/pg_restore_verificacao.json` para o painel/journal conferirem a última
execução sem rodar o restore.

Uso:
    python -m runtime.verificar_restauracao_pg           # produção (timer)
    python -m runtime.verificar_restauracao_pg --dry-run # não envia Telegram
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

RAIZ = Path(__file__).resolve().parents[1]
ESTADO_PADRAO = RAIZ / "data" / "pg_restore_verificacao.json"
VERIFICADOR = RAIZ / "tools" / "testar_restauracao_pg.py"
TIMEOUT_S = 300
TRECHO_SAIDA = 1200

# --- Guarda de off-site (item 4 da fila, 26/11) ---------------------------
# O verificador semanal só olhava o restore do Postgres. Um backup que restaura
# mas saiu corrompido/truncado da máquina não é backup: aqui ele roda também o
# `tools/checar_offsite_pg.py` (sha256 do dump no canal do Telegram e nos
# snapshots das 2 HDs) e avisa quando o arquivo de fora NÃO é o dump atual.
#
# Deliberadamente NÃO alarma "aguardando" nem "ausente": HD desplugada ou
# snapshot ainda não feito são verdade, não defeito — alarme falso treina o
# dono a ignorar o canal.
CHECADOR_OFFSITE = RAIZ / "tools" / "checar_offsite_pg.py"
TIMEOUT_OFFSITE_S = 180

log = logging.getLogger("od.verificar_restauracao_pg")


def carregar_estado(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def gravar_estado(caminho: Path, estado: dict) -> None:
    """Escrita atômica (tmp + replace): estado truncado mentiria na próxima."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporario, caminho)


def rodar_verificador(dump: str = "") -> tuple[int, str]:
    """Executa o verificador e devolve (código, saída combinada).

    `dump` vazio = o mais recente de `data/pg_dumps/` (produção). Um caminho
    explícito serve para o teste de falha controlada (dump corrompido).
    """
    comando = [sys.executable, str(VERIFICADOR)]
    if dump:
        comando += ["--dump", dump]
    resultado = subprocess.run(
        comando,
        cwd=RAIZ,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=TIMEOUT_S,
    )
    saida = "\n".join(
        parte for parte in (resultado.stdout, resultado.stderr) if parte
    ).strip()
    return resultado.returncode, saida


def montar_enviar() -> Callable[[str], None] | None:
    """Telegram do dono, no mesmo desenho do aviso do dump diário.

    Devolve None quando falta token/chat — o runner segue, registra a falha no
    estado e no journal, mas não inventa canal.
    """
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("OD_TELEGRAM_ADMINS") or "").split(",")[0].strip()
    if not token or not chat:
        return None

    def enviar(texto: str) -> None:
        import urllib.parse
        import urllib.request

        dados = urllib.parse.urlencode({"chat_id": chat, "text": texto}).encode()
        requisicao = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=dados
        )
        with urllib.request.urlopen(requisicao, timeout=30) as resposta:
            corpo = json.loads(resposta.read().decode("utf-8"))
        if not corpo.get("ok"):
            raise RuntimeError(f"Telegram recusou: {str(corpo)[:200]}")

    return enviar


def verificar_offsite() -> dict:
    """Roda o `tools/checar_offsite_pg.py --json` e resume para o runner.

    Devolve `{ok, divergente, provado, problemas, canal, hds}`. `ok` aqui
    significa "nada divergente"; **não** significa "cópia provada" (HD fora do
    ar deixa `provado=False` sem virar alarme). JSON ilegível vira problema:
    relatório que não sai também é sinal de que a guarda parou.
    """
    try:
        resultado = subprocess.run(
            [sys.executable, str(CHECADOR_OFFSITE), "--json"],
            cwd=RAIZ,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT_OFFSITE_S,
        )
    except Exception as exc:
        return {
            "ok": False, "divergente": True, "provado": False,
            "problemas": [f"checador não rodou: {type(exc).__name__}: {exc}"],
            "canal": {}, "hds": [],
        }
    try:
        resumo = json.loads(resultado.stdout)
    except ValueError:
        return {
            "ok": False, "divergente": True, "provado": False,
            "problemas": [
                "checador não devolveu JSON (código "
                f"{resultado.returncode}): {(resultado.stderr or '')[-200:]}"
            ],
            "canal": {}, "hds": [],
        }
    problemas: list[str] = []
    canal = resumo.get("canal") or {}
    if canal.get("status") == "divergente":
        problemas.append(f"canal: {canal.get('motivo')}")
    for hd in resumo.get("hds") or []:
        if hd.get("status") == "divergente":
            problemas.append(f"HD {hd.get('alvo')}: {hd.get('motivo')}")
    divergente = bool(resumo.get("divergente")) or bool(problemas)
    return {
        "ok": not divergente,
        "divergente": divergente,
        "provado": bool(resumo.get("ok")),
        "dump": resumo.get("dump"),
        "problemas": problemas,
        "canal": canal,
        "hds": resumo.get("hds") or [],
    }


def mensagem_offsite(resultado: dict) -> str:
    linhas = "\n".join(f"• {p}" for p in resultado.get("problemas") or [])
    return (
        "🧭 Off-site DIVERGENTE (junto do verificador semanal)\n\n"
        "O arquivo que saiu da máquina não é o dump atual (sha256 diferente, "
        "truncado ou ausente). Restore OK não cobre isso: no dia do desastre "
        "seria cópia velha ou quebrada.\n\n"
        f"{linhas}"
    )


def mensagem_falha(codigo: int, saida: str) -> str:
    trecho = saida[-TRECHO_SAIDA:] if saida else "(sem saída)"
    return (
        "🚨 Backup do Postgres NÃO restaura\n\n"
        f"O verificador semanal saiu com código {codigo}. O dump diário "
        "existe, mas a restauração falhou — isso precisa de conserto antes "
        "do próximo apagão.\n\n"
        f"Saída:\n{trecho}"
    )


def rodar(
    *,
    estado_path: Path = ESTADO_PADRAO,
    verificador: Callable[[], tuple[int, str]] | None = None,
    enviar: Callable[[str], None] | None = None,
    agora: float | None = None,
    offsite: Callable[[], dict] | None = None,
) -> int:
    """Uma rodada: verifica restore + off-site, registra o estado e avisa.

    `offsite` é injetável para teste; por padrão audita o estado do serviço
    de off-site. Falha de off-site **não** muda o código de saída do restore
    (são problemas diferentes), mas vai no estado e no Telegram.
    """
    agora = time.time() if agora is None else agora
    verificador = verificador or rodar_verificador
    estado = carregar_estado(estado_path)
    estado["ultima_execucao_em"] = agora
    estado["rodadas"] = int(estado.get("rodadas") or 0) + 1
    try:
        codigo, saida = verificador()
    except Exception as exc:                    # nunca deixa o timer sem estado
        codigo, saida = 1, f"{type(exc).__name__}: {exc}"
    estado["ultimo_codigo"] = codigo
    estado["ultima_saida"] = saida[-TRECHO_SAIDA:]
    estado["ok"] = codigo == 0

    if codigo != 0:
        estado["falhas"] = int(estado.get("falhas") or 0) + 1
        texto = mensagem_falha(codigo, saida)
        if enviar is not None:
            try:
                enviar(texto)
                estado["ultimo_aviso_em"] = agora
            except Exception as exc:            # canal fora não esconde a falha
                estado["erro_aviso"] = f"{type(exc).__name__}: {exc}"[:300]
                log.warning("aviso de falha do restore não saiu: %s", exc)
        else:
            log.warning("sem canal de Telegram configurado para avisar")
        log.error("restore do Postgres FALHOU (código %s)", codigo)
    else:
        estado["ultimo_sucesso_em"] = agora
        estado.pop("erro_aviso", None)
        log.info("restore do Postgres OK")

    # Guarda de off-site na MESMA rodada (26/11). Silêncio quando está em dia.
    # `offsite=None` (chamada de teste sem a guarda) não audita nada.
    if offsite is not None:
        try:
            audit = offsite()
        except Exception as exc:  # auditoria quebrada não esconde o restore
            audit = {"ok": False, "problemas": [f"auditoria falhou: {exc}"],
                     "perfis": {}}
        estado["offsite"] = audit
        if not audit.get("ok"):
            estado["offsite_ok"] = False
            texto = mensagem_offsite(audit)
            if enviar is not None:
                try:
                    enviar(texto)
                    estado["offsite_aviso_em"] = agora
                except Exception as exc:
                    estado["offsite_erro_aviso"] = (
                        f"{type(exc).__name__}: {exc}"[:300]
                    )
                    log.warning("aviso de off-site não saiu: %s", exc)
            else:
                log.warning(
                    "off-site atrasado e sem canal de Telegram para avisar"
                )
            log.error(
                "off-site atrasado: %s", "; ".join(audit.get("problemas") or [])
            )
        else:
            # sem alarme: inclui "HD fora do ar" e "snapshot pendente"
            estado["offsite_ok"] = True
            estado.pop("offsite_erro_aviso", None)
            estado.pop("offsite_aviso_em", None)

    gravar_estado(estado_path, estado)
    return codigo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="não envia Telegram (só verifica e registra)")
    ap.add_argument("--dump", default="",
                    help="dump específico (padrão: o mais recente)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Execução manual (sem `EnvironmentFile` do systemd) precisa do .env para
    # achar o canal; `load_dotenv` NÃO sobrescreve o que já está no ambiente.
    if not (os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("OD_TELEGRAM_ADMINS")):
        try:
            from dotenv import load_dotenv

            load_dotenv(RAIZ / ".env")
        except Exception:
            pass
    enviar = None if args.dry_run else montar_enviar()
    verificador = (lambda: rodar_verificador(args.dump)) if args.dump else None
    return rodar(
        enviar=enviar,
        verificador=verificador,
        # produção: guarda de off-site junto do restore (26/11)
        offsite=verificar_offsite,
    )


if __name__ == "__main__":
    raise SystemExit(main())
