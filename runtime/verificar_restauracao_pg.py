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
) -> int:
    """Uma rodada: verifica, registra o estado e avisa se falhar."""
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
    return rodar(enviar=enviar, verificador=verificador)


if __name__ == "__main__":
    raise SystemExit(main())
