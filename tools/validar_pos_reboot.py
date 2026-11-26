#!/usr/bin/env python3
"""Validação PÓS-REBOOT do Omega Drakon — roda sozinha no boot.

Por que existe (26/11): o dono autorizou aplicar as atualizações, o reboot
seguia pendente e a pergunta certa era "o que voltou?". Em vez de descobrir
isso no chat (que depende da sessão sobreviver ao reboot), uma unit oneshot
roda este script logo após a rede subir, espera o `od-core` responder,
confere serviços/timers/health e **manda o veredito no Telegram**.

O que confere:
  * uptime do boot (prova de que é pós-reboot, não checagem manual);
  * `/health` (com `X-API-Key`) e quantos checks estão `ok` — com carência
    própria para os checks de container/broker (`tool_*`, `mqtt`), que sobem
    DEPOIS do od-core: no boot de 26/11 eles ainda estavam começando e o
    veredito saiu "degraded" com 6 checks, sem nada realmente quebrado;
  * serviços de usuário (`od-core`, `od-llm`, `od-orchestrator`,
    `od-azura-proxy`) e de sistema (`postgresql`, `docker`);
  * timers (`od-os-updater.timer`, `od-io-probe.timer`) ativos;
  * `/var/run/reboot-required` (deve ter sumido) e kernel em execução.

Estado em `data/pos_reboot.json` (o painel/journal conferem depois) e uma
mensagem no Telegram. Código 0 = tudo essencial ok; 1 = algo falhou.

Uso:
    python3 tools/validar_pos_reboot.py            # checagem + Telegram
    python3 tools/validar_pos_reboot.py --sem-envio # só registra
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
ESTADO = RAIZ / "data" / "pos_reboot.json"
# `od-orchestrator.service` fica FORA de propósito: o Orchestrator roda
# embutido no od-core e essa unit está inactive em operação normal (medido
# 26/11) — cobrá-la aqui daria alarme falso a cada boot.
SERVICOS_USUARIO = ("od-core.service", "od-llm.service", "od-azura-proxy.service")
SERVICOS_SISTEMA = ("postgresql.service", "docker.service")
TIMERS_SISTEMA = ("od-os-updater.timer", "od-io-probe.timer")
ESPERA_CORE_S = 180
# Nomes REAIS dos checks do /health (medidos 26/11; `od-core`/`postgres`/`disco`
# não existem — usar nome inventado acusaria falta sempre).
CHECKS_OBRIGATORIOS = ("database", "orchestrator", "backup", "offsite",
                       "units_instaladas")
# Checks que dependem de container/broker e por isso sobem DEPOIS do od-core.
# Medido no boot de 26/11: às 22 s de uptime seis deles ainda falhavam e todos
# ficaram `up` em seguida. Só estes ganham carência; banco, orchestrator e
# backup continuam alarmando na hora — falha real não pode esperar para avisar.
CHECKS_TRANSITORIOS = ("mqtt",)  # broker no Docker
PREFIXO_TRANSITORIO = "tool_"   # ferramentas em container
# Teto da carência: 180 s (core) + 60 s (containers) cabem no TimeoutStartSec
# da unit com folga para Telegram.
JANELA_TRANSITORIOS_S = 60
INTERVALO_TRANSITORIOS_S = 5


def eh_check_transitorio(nome: str) -> bool:
    """Check que pode estar apenas começando poucos segundos após o boot."""
    return nome in CHECKS_TRANSITORIOS or nome.startswith(PREFIXO_TRANSITORIO)


def uptime_s() -> float:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError):
        return 0.0


def _cmd(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"


def reboot_pendente() -> bool:
    """Flag do apt/dpkg — depois do reboot ela deve ter sumido."""
    return Path("/var/run/reboot-required").exists()


def _is_active_usuario(nome: str) -> str:
    """Estado de unit de USUÁRIO mesmo rodando como root.

    `systemctl --user` como root não acha o bus do alex (`Failed to connect
    to bus`) — medido em 26/11, e isso virou falso alarme no primeiro teste.
    A consulta tem de ser feita como o dono da sessão, com o
    XDG_RUNTIME_DIR dele.
    """
    if os.geteuid() == 0:
        comando = [
            "runuser", "-u", "alex", "--",
            "env", "XDG_RUNTIME_DIR=/run/user/1000",
            "systemctl", "--user", "is-active", nome,
        ]
    else:
        comando = ["systemctl", "--user", "is-active", nome]
    codigo, saida = _cmd(comando)
    return saida or f"erro ({codigo})"


def _env(chave: str) -> str:
    valor = (os.environ.get(chave) or "").strip()
    if valor:
        return valor
    try:
        for linha in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
            if linha.startswith(chave + "="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _ler_health(timeout: int = 10) -> dict[str, Any]:
    """Uma leitura do `/health`; levanta exceção se o core não responder."""
    chave = _env("OD_API_KEY")
    req = urllib.request.Request(
        "http://127.0.0.1:8000/health", headers={"X-API-Key": chave}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def esperar_health(timeout_s: int = ESPERA_CORE_S) -> dict[str, Any]:
    """Tenta o `/health` até o od-core responder (ele sobe depois do boot)."""
    inicio = time.time()
    ultimo_erro = "sem tentativa"
    while time.time() - inicio < timeout_s:
        try:
            dados = _ler_health()
            dados["_espera_s"] = round(time.time() - inicio, 1)
            return dados
        except Exception as exc:  # core ainda subindo
            ultimo_erro = f"{type(exc).__name__}: {exc}"
            time.sleep(3)
    return {"_erro": ultimo_erro, "_espera_s": round(time.time() - inicio, 1)}


def aguardar_transitorios(
    saude: dict[str, Any], timeout_s: int | None = None
) -> dict[str, Any]:
    """Espera os checks de container/broker terminarem de subir.

    Só espera quando **todos** os checks falhando são transitórios: se o banco,
    o orchestrator ou o backup já falham, o relatório sai na hora (misturar
    carência com falha real esconderia o problema). Se o `/health` parar de
    responder no meio, devolve a última leitura e o relatório marca o que viu.
    """
    if timeout_s is None:
        timeout_s = JANELA_TRANSITORIOS_S
    inicio = time.time()
    dados = saude
    while True:
        checks = dados.get("checks") or {}
        falhando = [k for k, v in checks.items() if not v.get("ok")]
        restantes = [k for k in falhando if eh_check_transitorio(k)]
        if not restantes or len(restantes) != len(falhando):
            break
        if time.time() - inicio >= timeout_s:
            break
        time.sleep(min(INTERVALO_TRANSITORIOS_S, max(0.0, timeout_s - (time.time() - inicio))))
        try:
            dados = _ler_health()
        except Exception:
            break
    resultado = dict(dados)
    resultado["_espera_transitorios_s"] = round(time.time() - inicio, 1)
    return resultado


def coletar() -> dict[str, Any]:
    uptime = uptime_s()
    saude = esperar_health()
    if "_erro" not in saude:
        saude = aguardar_transitorios(saude)
    checks = saude.get("checks") or {}
    falhando = [k for k, v in checks.items() if not v.get("ok")]
    transitorios_pendentes = [k for k in falhando if eh_check_transitorio(k)]
    reais_falhando = [k for k in falhando if not eh_check_transitorio(k)]

    servicos: dict[str, str] = {}
    for nome in SERVICOS_USUARIO:
        servicos[nome] = _is_active_usuario(nome)
    for nome in SERVICOS_SISTEMA:
        _, out = _cmd(["systemctl", "is-active", nome])
        servicos[nome] = out

    timers: dict[str, str] = {}
    for nome in TIMERS_SISTEMA:
        _, out = _cmd(["systemctl", "is-active", nome])
        timers[nome] = out

    _, kernel = _cmd(["uname", "-r"])
    flag = reboot_pendente()

    problemas: list[str] = []
    if "_erro" in saude:
        problemas.append(f"/health não respondeu: {saude['_erro']}")
    for chave in CHECKS_OBRIGATORIOS:
        if checks and not (checks.get(chave) or {}).get("ok"):
            problemas.append(f"check {chave} não está ok")
    for chave in reais_falhando:
        if chave not in CHECKS_OBRIGATORIOS:
            problemas.append(f"check {chave} não está ok")
    if transitorios_pendentes:
        # Esgotou a carência (ou nem houve carência porque uma falha real já
        # apareceu): o container/broker continua fora — é pendência de verdade.
        problemas.append(
            "containers/broker ainda falhando: "
            + ", ".join(transitorios_pendentes)
        )
    for nome, estado in servicos.items():
        if estado != "active":
            problemas.append(f"serviço {nome}: {estado}")
    for nome, estado in timers.items():
        if estado not in ("active", "waiting"):
            problemas.append(f"timer {nome}: {estado}")
    if flag:
        problemas.append("reboot ainda pendente (/var/run/reboot-required existe)")

    return {
        "quando": time.time(),
        "uptime_s": round(uptime, 1),
        "recem_iniciado": uptime < 900,
        "health_status": saude.get("status"),
        "checks": len(checks),
        "checks_falhando": falhando,
        "containers_pendentes": transitorios_pendentes,
        "espera_core_s": saude.get("_espera_s"),
        "espera_transitorios_s": saude.get("_espera_transitorios_s"),
        "servicos": servicos,
        "timers": timers,
        "kernel": kernel,
        "reboot_pendente": flag,
        "problemas": problemas,
        "ok": not problemas,
    }


def texto_relatorio(r: dict[str, Any]) -> str:
    # Tolerante a relatório parcial: texto de aviso nunca deve estourar.
    minutos = float(r.get("uptime_s") or 0.0) / 60.0
    titulo = (
        "🟢 Pós-reboot OK" if r.get("ok") else "🟠 Pós-reboot com pendências"
    )
    cabecalho = (
        f"{titulo} (uptime {minutos:.1f} min)"
        if r.get("recem_iniciado")
        else f"{titulo} — checagem manual, uptime {minutos:.0f} min"
    )
    linhas = [
        cabecalho,
        f"/health: {r.get('health_status')} · {r.get('checks', 0)} checks"
        f" (esperou {r.get('espera_core_s')}s)",
        "serviços: "
        + ", ".join(
            f"{k.split('.')[0]}={v}" for k, v in (r.get("servicos") or {}).items()
        ),
        "timers: " + ", ".join(
            f"{k.split('.')[0]}={v}" for k, v in (r.get("timers") or {}).items()
        ),
        f"kernel: {r.get('kernel')} · reboot pendente: "
        + ("sim" if r.get("reboot_pendente") else "não"),
    ]
    if r.get("containers_pendentes"):
        linhas.append(
            "containers ainda fora do ar: " + ", ".join(r["containers_pendentes"])
        )
    elif (r.get("espera_transitorios_s") or 0) >= INTERVALO_TRANSITORIOS_S:
        linhas.append(
            "containers: subiram em ~"
            f"{r['espera_transitorios_s']}s (espera do boot)"
        )
    if r.get("checks_falhando"):
        linhas.append("checks falhando: " + ", ".join(r["checks_falhando"]))
    if r.get("problemas"):
        linhas.append("problemas:")
        linhas.extend(f"• {p}" for p in r["problemas"])
    return "\n".join(linhas)


def enviar_telegram(texto: str) -> bool:
    token = _env("TELEGRAM_BOT_TOKEN")
    chat = (_env("OD_TELEGRAM_ADMINS").split(",")[0] or "").strip()
    if not token or not chat:
        return False
    dados = urllib.parse.urlencode({"chat_id": chat, "text": texto}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=dados
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return bool(json.loads(resp.read().decode("utf-8")).get("ok"))
    except Exception:
        return False


def gravar(r: dict[str, Any]) -> None:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ESTADO)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sem-envio", action="store_true", help="não manda Telegram")
    args = ap.parse_args(argv)

    r = coletar()
    gravar(r)
    print(texto_relatorio(r))
    if not args.sem_envio:
        enviado = enviar_telegram(texto_relatorio(r))
        r["telegram"] = enviado
        gravar(r)
        print(f"telegram: {'enviado' if enviado else 'NÃO enviado'}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
