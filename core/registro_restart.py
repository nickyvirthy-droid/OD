"""
OMEGA DRAKON • CORE
Módulo: core/registro_restart.py
Descrição: auto-registro do restart do `od-core` em `iniciar/session.json`.
           A regra 4 do projeto depende de quem reinicia lembrar de registrar
           PID/commit/horário — e às vezes não lembra (o restart das 15:01 de
           18/11 ficou fora do `iniciar/`, e o checkpoint seguinte ainda o
           dava como pendente). Este gancho roda uma vez no boot do serviço e
           grava o fato: PID, commit, branch, horário, host e motivo (quando
           passado por `OD_RESTART_MOTIVO`).

           Guarda os últimos 30 restarts numa lista (`restarts_od_core`) em
           vez de uma chave por restart — `session.json` já tem centenas de
           entradas e o registro não pode inflá-lo para sempre.

           Nunca derruba o boot: qualquer erro vira log de aviso.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projetti
"""

from __future__ import annotations

import fcntl
import json
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.logger import get_logger

log = get_logger("omega.core.registro_restart")

RAIZ = Path(__file__).resolve().parent.parent
SESSAO = RAIZ / "iniciar" / "session.json"
CHAVE = "restarts_od_core"
LIMITE = 30


def _git(*args: str) -> str:
    """Saída curta de um comando git (vazio se falhar)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(RAIZ), *args],
            capture_output=True, text=True, timeout=5,
        )
        return (r.stdout or "").strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def registrar_restart(
    *,
    caminho: Optional[Path] = None,
    pid: Optional[int] = None,
    commit: Optional[str] = None,
    agora: Optional[datetime] = None,
    motivo: Optional[str] = None,
    limite: int = LIMITE,
) -> Optional[dict[str, Any]]:
    """Grava o boot atual em `iniciar/session.json` (idempotente por PID).

    Returns:
        A entrada gravada, ou None quando não havia o que gravar (mesmo PID
        já registrado, arquivo ilegível ou falha de escrita).
    """
    sessao = Path(caminho or SESSAO)
    pid_atual = int(pid if pid is not None else os.getpid())
    instante = (agora or datetime.now().astimezone()).isoformat(timespec="seconds")

    entrada: dict[str, Any] = {
        "pid": pid_atual,
        "commit": commit if commit is not None else (_git("rev-parse", "--short", "HEAD") or "?"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD") or "?",
        "iniciado_em": instante,
        "host": platform.node(),
        "modo": os.getenv("OD_MODO", "all"),
        "usuario": os.getenv("USER", ""),
    }
    motivo_final = motivo if motivo is not None else os.getenv("OD_RESTART_MOTIVO", "")
    if motivo_final:
        entrada["motivo"] = motivo_final[:200]

    try:
        if not sessao.exists():
            log.warn("session.json ausente — restart não registrado", caminho=str(sessao))
            return None
        with sessao.open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                dados = json.load(fh)
                if not isinstance(dados, dict):
                    log.warn("session.json sem objeto raiz — restart não registrado")
                    return None
                historico = dados.get(CHAVE)
                registros = list(historico) if isinstance(historico, list) else []
                if registros and int(registros[-1].get("pid", 0) or 0) == pid_atual:
                    return None  # mesmo processo: não duplica
                registros.append(entrada)
                dados[CHAVE] = registros[-max(1, limite):]
                fh.seek(0)
                fh.truncate()
                json.dump(dados, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
    except (OSError, ValueError, TypeError) as exc:
        log.warn("Falha ao registrar o restart", error=str(exc))
        return None

    log.info(
        "Restart do od-core registrado em iniciar/session.json",
        commit=entrada["commit"], pid=pid_atual,
    )
    return entrada
