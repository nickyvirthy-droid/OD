#!/usr/bin/env python3
"""
OMEGA DRAKON • CORE
Módulo: core/os_updater.py
Descrição: Atualização automática do SISTEMA OPERACIONAL (apt + firmware)
           com reboot semanal agendado. Roda como systemd timer/service
           ou via od-core (thread daemon).

Funcionalidades:
  - apt update + apt full-upgrade -y (semanal)
  - fwupdmgr refresh + fwupdmgr update (firmware)
  - Verifica necessidade de reboot (/var/run/reboot-required)
  - Reboot agendado se necessário
  - Notificação Telegram antes/depois
  - Log estruturado + estado persistido
  - Dry-run para testes

Baseado em: txt.txt (09/11) — 45 updates pendentes, 2 firmware upgrades
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from core.logger import get_logger

log = get_logger("omega.core.os_updater")

# --- Configurações -----------------------------------------------------------

ESTADO_ARQUIVO = Path("data/os_updater_estado.json")
DEFAULT_SCHEDULE = "weekly"           # weekly, daily
DEFAULT_DAY = 6                       # 0=seg ... 6=dom (domingo)
DEFAULT_HOUR = 3                      # 03:00 da manhã
DEFAULT_WINDOW_HOURS = 4              # janela de 4h para concluir

# --- Estado persistido -------------------------------------------------------


@dataclass
class OSUpdaterState:
    ultima_execucao: float = 0.0
    ultima_tentativa: float = 0.0
    sucessos_consecutivos: int = 0
    falhas_consecutivas: int = 0
    ultima_versao_kernel: str = ""
    pendente_reboot: bool = False
    ultimo_reboot: float = 0.0
    secoes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ultima_execucao": self.ultima_execucao,
            "ultima_tentativa": self.ultima_tentativa,
            "sucessos_consecutivos": self.sucessos_consecutivos,
            "falhas_consecutivas": self.falhas_consecutivas,
            "ultima_versao_kernel": self.ultima_versao_kernel,
            "pendente_reboot": self.pendente_reboot,
            "ultimo_reboot": self.ultimo_reboot,
            "secoes": self.secoes[-50:],  # mantém últimas 50
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OSUpdaterState":
        s = cls()
        for k, v in d.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s


# --- Utilitários -------------------------------------------------------------


def _executar(cmd: list[str], timeout: int = 600, dry_run: bool = False) -> tuple[int, str, str]:
    """Executa comando e retorna (exit_code, stdout, stderr)."""
    if dry_run:
        log.info("[DRY-RUN] " + " ".join(cmd))
        return 0, f"[DRY-RUN] {cmd}", ""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timeout após {timeout}s"
    except Exception as exc:
        return -1, "", f"{type(exc).__name__}: {exc}"


def _kernel_atual() -> str:
    """Retorna versão do kernel atual."""
    code, out, _ = _executar(["uname", "-r"])
    return out.strip() if code == 0 else ""


def _precisa_reboot() -> bool:
    """Verifica se há flag de reboot necessário."""
    return Path("/var/run/reboot-required").exists()


# Cache da sondagem de pacotes/firmware usada pelo /health. `apt list` custa
# ~0,55 s medidos nesta máquina — barato, mas o /health roda a cada 8 s; a
# sondagem vale por 30 min e o valor anterior é reaproveitado em falha.
INTERVALO_SONDAGEM_S = 1800.0
_SONDAGEM: dict[str, Any] = {
    "ts": 0.0,
    "upgradable": None,
    "firmware": None,
    "em_curso": False,
}


def _sondar_pacotes_e_firmware() -> None:
    """Executa a sondagem cara (apt + fwupdmgr) e atualiza o cache."""
    try:
        code, _out, _ = _executar(["apt", "list", "--upgradable"], timeout=60)
        if code == 0:
            _SONDAGEM["upgradable"] = len(_apt_lista_upgradable())
        code, _out, _ = _executar(["fwupdmgr", "get-upgrades"], timeout=60)
        if code == 0:
            _SONDAGEM["firmware"] = len(_fwupdmgr_upgrades())
        _SONDAGEM["ts"] = time.time()
    except Exception as exc:  # sonda é enfeite: o check não pode cair por ela
        log.debug("OSUpdater: sondagem de pacotes falhou", erro=str(exc)[:120])
    finally:
        _SONDAGEM["em_curso"] = False


def aquecer_sondagem() -> None:
    """Dispara a sondagem em thread separada (chamada no boot do launcher)."""
    if _SONDAGEM["em_curso"]:
        return
    _SONDAGEM["em_curso"] = True
    threading.Thread(
        target=_sondar_pacotes_e_firmware, name="od-sondagem-so", daemon=True
    ).start()


def _contar_pacotes_e_firmware(agora: float, intervalo: float) -> tuple[Optional[int], Optional[int]]:
    """Devolve o cache e, se vencido, renova em SEGUNDO PLANO.

    Nunca executa apt/fwupdmgr na thread chamadora: o /health é medido
    (p95) e um `apt list` de 0,55 s dentro da requisição derrubava o check
    `latencia` para `degraded` — medido no release 1.47.0.
    """
    vencido = agora - float(_SONDAGEM["ts"]) >= intervalo
    if _SONDAGEM["upgradable"] is None or vencido:
        aquecer_sondagem()
    return _SONDAGEM["upgradable"], _SONDAGEM["firmware"]


#: Unit root que aplica o ciclo AGORA (ignora o agendamento). O painel dispara
#: por `sudo -n systemctl start --no-block` — apt/dpkg exigem root, e o od-core
#: roda como `alex` (regra do sudoers em /etc/sudoers.d/od-os-updater).
UNIDADE_FORCAR = "od-os-updater-forcar.service"
SYSTEMCTL = "/usr/bin/systemctl"


def iniciar_ciclo_forcado() -> tuple[bool, str]:
    """Pede ao systemd o ciclo forçado (root). Devolve (ok, motivo).

    `--no-block` responde na hora: o ciclo é oneshot e pode durar minutos
    (apt full-upgrade). Quem acompanha é `status_painel()`/`/health`.
    """
    code, out, err = _executar(
        ["sudo", "-n", SYSTEMCTL, "start", "--no-block", UNIDADE_FORCAR],
        timeout=30,
    )
    if code == 0:
        return True, "ciclo solicitado"
    return False, (err or out or f"exit {code}").strip()[:300]


# `is-active` responde `activating` no arranque e `reloading` ao
# recarregar: para quem acompanha o painel, isso É ciclo em andamento —
# tratar só `active` deixava a primeira leitura pós-clique já "parada".
_ESTADOS_EM_ANDAMENTO = ("", "active", "activating", "reloading")


UNIDADES_CICLO = ("od-os-updater.service", "od-os-updater-forcar.service")


def avisar_falha(unidades: tuple[str, ...] = UNIDADES_CICLO) -> dict[str, Any]:
    """Avisa no Telegram que um ciclo MORREU antes do fim (OnFailure da unit).

    O aviso final do `executar_ciclo` só sai se o processo chega ao fim. Se o
    Python for morto (OOM, `TimeoutStartSec=3600`, crash), o dono não sabia de
    nada — este é o caminho de `OnFailure=od-os-updater-falha.service`.

    Lê `systemctl show` (estado/resultado) e as últimas linhas do journal da
    unit que falhou. Devolve `{"ok": bool, "unidade": str, "texto": str}`.
    """
    falhas: list[tuple[str, str, str]] = []
    for unidade in unidades:
        code, out, _ = _executar(
            ["systemctl", "show", unidade, "-p", "ActiveState", "-p", "Result"],
            timeout=10,
        )
        info = dict(
            linha.split("=", 1) for linha in out.splitlines() if "=" in linha
        )
        estado = info.get("ActiveState", "?")
        resultado = info.get("Result", "?")
        if estado == "failed" or resultado not in ("success", "", "?"):
            falhas.append((unidade, estado, resultado))

    if not falhas:
        return {"ok": True, "unidade": "", "texto": "nenhuma unit em falha"}

    unidade, estado, resultado = falhas[0]
    _, journal, _ = _executar(
        ["journalctl", "-u", unidade, "-n", "8", "--no-pager", "-o", "cat"],
        timeout=20,
    )
    secoes = ""
    try:
        caminho = Path(ESTADO_ARQUIVO)
        if caminho.exists():
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            ultimas = (dados.get("secoes") or [])[-3:]
            secoes = "\n".join(
                f"• {s.get('acao')}: {'ok' if s.get('ok') else 'FALHOU'} "
                f"{(str(s.get('detalhes') or ''))[:120]}"
                for s in ultimas
            )
    except Exception:  # pragma: no cover - estado ilegível não impede o aviso
        secoes = ""

    cauda = "\n".join((journal or "").strip().splitlines()[-6:])[:1200]
    partes = [
        f"Ciclo do SO morreu antes do fim ({unidade}).",
        f"systemd: estado={estado} resultado={resultado}",
    ]
    if secoes:
        partes.append("Últimas seções:\n" + secoes)
    if cauda:
        partes.append("Journal:\n" + cauda)
    texto = "\n".join(partes)
    enviado = notificar_telegram("❌ OSUpdater\n" + texto)
    return {"ok": bool(enviado), "unidade": unidade, "texto": texto}


def unidade_em_andamento() -> bool:
    """True enquanto a unit do ciclo forçado estiver ativa (ou arrancando)."""
    code, out, _ = _executar(
        [SYSTEMCTL, "is-active", "--quiet", UNIDADE_FORCAR], timeout=10
    )
    return code == 0 and out.strip() in _ESTADOS_EM_ANDAMENTO


def status_painel(estado_arquivo: Path = ESTADO_ARQUIVO) -> dict[str, Any]:
    """Status barato para a rota/painel do atualizador (sem rodar o ciclo)."""
    resumo = resumo_health(estado_arquivo)
    estado: dict[str, Any] = {}
    try:
        caminho = Path(estado_arquivo)
        if caminho.exists():
            estado = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:  # estado ilegível → só os campos do resumo
        estado = {}
    secoes = estado.get("secoes") or []
    return {
        **resumo,
        "schedule": DEFAULT_SCHEDULE,
        "day": DEFAULT_DAY,
        "hour": DEFAULT_HOUR,
        "ultima_tentativa": float(estado.get("ultima_tentativa", 0.0) or 0.0),
        "secoes": secoes[-5:],
        "unidade": UNIDADE_FORCAR,
        "em_andamento": unidade_em_andamento(),
    }


def resumo_health(
    estado_arquivo: Path = ESTADO_ARQUIVO,
    *,
    agora: Optional[float] = None,
    intervalo_sondagem: float = INTERVALO_SONDAGEM_S,
) -> dict[str, Any]:
    """Resumo do atualizador para o check `os_updater` do /health.

    Barato de propósito: lê o JSON de estado (sem apt/fwupdmgr por chamada —
    a contagem tem cache de `intervalo_sondagem`) e o flag de reboot. Nunca
    levanta exceção: estado ausente/ilegível vira zeros honestos.
    """
    agora = time.time() if agora is None else agora
    estado: dict[str, Any] = {}
    try:
        caminho = Path(estado_arquivo)
        if caminho.exists():
            estado = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as exc:  # estado corrompido não derruba o /health
        log.warn("OSUpdater: estado ilegível no /health", erro=str(exc)[:120])
    upgradable, firmware = _contar_pacotes_e_firmware(agora, intervalo_sondagem)
    return {
        "precisa_reboot": _precisa_reboot(),
        "pendente_reboot": bool(estado.get("pendente_reboot", False)),
        "upgradable": upgradable,
        "firmware_upgrades": firmware,
        "falhas_consecutivas": int(estado.get("falhas_consecutivas", 0) or 0),
        "sucessos_consecutivos": int(estado.get("sucessos_consecutivos", 0) or 0),
        "ultima_execucao": float(estado.get("ultima_execucao", 0.0) or 0.0),
        "kernel": _kernel_atual(),
    }


def _env(clave: str) -> str:
    """Lê do ambiente e, se faltar (execução manual), do .env do projeto."""
    valor = (os.environ.get(clave) or "").strip()
    if valor:
        return valor
    try:
        from runtime.launcher import load_env  # import tardio: launcher é pesado

        return (load_env().get(clave) or "").strip()
    except Exception:  # noqa: BLE001 - sem .env legível simplesmente não há canal
        return ""


def notificar_telegram(texto: str) -> bool:
    """Aviso no Telegram do dono (regra 15). Sem canal → False, nunca exceção.

    O serviço systemd carrega o `.env` por `EnvironmentFile`; na execução
    manual as chaves vêm do `.env` via `runtime.launcher.load_env`.
    """
    token = _env("TELEGRAM_BOT_TOKEN")
    chat = _env("OD_TELEGRAM_ADMINS").split(",")[0].strip()
    if not token or not chat:
        log.warn("OSUpdater: sem Telegram configurado — aviso só no journal")
        return False
    try:
        corpo = json.dumps({"chat_id": int(chat), "text": texto[:4000]}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=corpo,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=25.0) as resp:
            return resp.status == 200
    except (ValueError, urllib.error.URLError, OSError) as exc:
        log.warn("OSUpdater: aviso Telegram falhou", erro=str(exc)[:200])
        return False


def _apt_lista_upgradable() -> list[str]:
    """Lista pacotes atualizáveis."""
    code, out, _ = _executar(["apt", "list", "--upgradable"])
    if code != 0:
        return []
    linhas = out.strip().split("\n")
    return [l.split("/")[0] for l in linhas[1:] if "/" in l]  # pula header


def _fwupdmgr_upgrades() -> list[str]:
    """Lista firmware upgrades disponíveis."""
    code, out, _ = _executar(["fwupdmgr", "get-upgrades"])
    if code != 0:
        return []
    # fwupdmgr output parsing simples
    return [l.strip() for l in out.split("\n") if l.strip() and not l.startswith(" ")]


# --- Atualizador Principal ---------------------------------------------------


class OSUpdater:
    """Atualizador do sistema operacional (apt + firmware)."""

    def __init__(
        self,
        estado_arquivo: Path = ESTADO_ARQUIVO,
        schedule: str = DEFAULT_SCHEDULE,
        day: int = DEFAULT_DAY,
        hour: int = DEFAULT_HOUR,
        window_hours: int = DEFAULT_WINDOW_HOURS,
        notificador_telegram: Optional[callable] = None,
        dry_run: bool = False,
    ) -> None:
        self.estado_arquivo = Path(estado_arquivo)
        self.schedule = schedule
        self.day = day  # 0-6 (seg-dom)
        self.hour = hour
        self.window_hours = window_hours
        self._notificador = notificador_telegram
        self.dry_run = dry_run
        self._estado = self._carregar_estado()
        self._lock = __import__("threading").RLock()

    def _carregar_estado(self) -> OSUpdaterState:
        try:
            if self.estado_arquivo.exists():
                dados = json.loads(self.estado_arquivo.read_text(encoding="utf-8"))
                return OSUpdaterState.from_dict(dados)
        except Exception as exc:
            log.warn("Falha ao carregar estado OSUpdater", erro=str(exc))
        return OSUpdaterState()

    def _salvar_estado(self) -> None:
        self.estado_arquivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.estado_arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._estado.to_dict(), indent=1), encoding="utf-8")
        tmp.replace(self.estado_arquivo)

    def _notificar(self, titulo: str, mensagem: str) -> None:
        if self.dry_run:
            # Contrato do dry-run: nenhum I/O real — nem comando, nem mensagem.
            log.info("[DRY-RUN] notificação suprimida", titulo=titulo)
            return
        if self._notificador:
            try:
                self._notificador(f"{titulo}\n{mensagem}")
            except Exception as exc:
                log.warn("Falha ao notificar Telegram", erro=str(exc))

    def _registrar_secao(self, acao: str, ok: bool, detalhes: str = "") -> None:
        secao = {
            "timestamp": time.time(),
            "acao": acao,
            "ok": ok,
            "detalhes": detalhes[:500],
        }
        self._estado.secoes.append(secao)
        self._salvar_estado()

    # --- Passos individuais --------------------------------------------------

    def _apt_update(self) -> tuple[bool, str]:
        code, out, err = _executar(["apt", "update"], timeout=120, dry_run=self.dry_run)
        return code == 0, out if code == 0 else err

    def _apt_full_upgrade(self) -> tuple[bool, str]:
        code, out, err = _executar(
            ["apt", "full-upgrade", "-y"],
            timeout=1800,
            dry_run=self.dry_run,
        )
        return code == 0, out if code == 0 else err

    def _apt_autoremove(self) -> tuple[bool, str]:
        code, out, err = _executar(
            ["apt", "autoremove", "-y"],
            timeout=300,
            dry_run=self.dry_run,
        )
        return code == 0, out if code == 0 else err

    def _fwupdmgr_refresh(self) -> tuple[bool, str]:
        code, out, err = _executar(["fwupdmgr", "refresh"], timeout=120, dry_run=self.dry_run)
        return code == 0, out if code == 0 else err

    def _fwupdmgr_update(self) -> tuple[bool, str]:
        code, out, err = _executar(["fwupdmgr", "update", "-y"], timeout=600, dry_run=self.dry_run)
        return code == 0, out if code == 0 else err

    def _notificar_resultado(self, resultados: dict[str, Any], forcar: bool) -> None:
        """Aviso FINAL do ciclo: terminou ou falhou, e em que passo (regra 15).

        Antes, o ciclo com erro no `apt update` ainda mandava "✅ concluídas" —
        o dono lia sucesso onde houve falha. Agora o desfecho é um só: falha
        (com as seções que quebraram), sucesso com reboot agendado, ou sucesso
        sem reboot. `forcar` identifica o ciclo disparado pelo painel.
        """
        erros = [str(e) for e in (resultados.get("erros") or [])]
        pacotes = len(resultados.get("pacotes_atualizados") or [])
        firmware = len(resultados.get("firmware_atualizados") or [])
        origem = " (pedido pelo painel)" if forcar else ""
        if resultados.get("reboot_executado"):
            reboot = "Reboot agendado para +5 min."
        elif resultados.get("reboot_necessario"):
            reboot = "Reboot pendente — reinicia no próximo boot."
        else:
            reboot = ""

        if erros:
            # as seções que falharam são mais úteis que a mensagem crua
            falhas = [s for s in self._estado.secoes[-6:] if not s.get("ok")]
            if falhas:
                linhas = "\n".join(
                    f"• {s.get('acao')}: {str(s.get('detalhes') or '')[:160]}"
                    for s in falhas
                )
            else:  # pragma: no cover - seções sempre existem com erro
                linhas = "\n".join(f"• {e[:180]}" for e in erros)
            partes = [
                f"Ciclo terminou COM FALHA{origem}.",
                f"{len(erros)} erro(s):",
                linhas,
                f"Pacotes: {pacotes} | Firmware: {firmware}",
            ]
            if reboot:
                partes.append(reboot)
            self._notificar("❌ OSUpdater", "\n".join(partes))
        elif resultados.get("reboot_necessario"):
            self._notificar(
                "⚠️ OSUpdater",
                "Atualizações aplicadas" + origem + ". Reboot necessário.\n"
                f"Kernel: {resultados.get('kernel_antes')} → "
                f"{resultados.get('kernel_depois')}\n"
                f"Pacotes: {pacotes}\nFirmware: {firmware}\n{reboot}",
            )
        else:
            self._notificar(
                "✅ OSUpdater",
                "Atualizações concluídas sem necessidade de reboot" + origem + ".\n"
                f"Pacotes: {pacotes} | Firmware: {firmware}",
            )

    def _verificar_reboot(self) -> bool:
        return _precisa_reboot()

    def _reboot(self) -> tuple[bool, str]:
        if self.dry_run:
            return True, "[DRY-RUN] reboot agendado"
        log.crit("REBOOT DO SISTEMA INICIADO pelo OSUpdater")
        self._notificar("⚠️ OSUpdater", "Reboot do sistema iniciado após atualizações.")
        code, out, err = _executar(["systemctl", "reboot"], timeout=30, dry_run=self.dry_run)
        return code == 0, out if code == 0 else err

    # --- Ciclo principal -----------------------------------------------------

    def executar_ciclo(self, forcar: bool = False) -> dict[str, Any]:
        """Executa ciclo completo de atualização."""
        with self._lock:
            agora = time.time()

            # Verifica agendamento (se não forçado)
            if not forcar and not self._deve_executar(agora):
                return {
                    "ok": True,
                    "acao": "aguardar",
                    "proxima_execucao": self._proxima_execucao(agora),
                }

            self._estado.ultima_tentativa = agora
            self._salvar_estado()

            log.info("OSUpdater: iniciando ciclo", forcar=forcar)
            self._notificar(
                "🔧 OSUpdater",
                "Iniciando atualização semanal do sistema..."
                + (" (pedido pelo painel)" if forcar else ""),
            )

            resultados = {
                "apt_update": False,
                "apt_upgrade": False,
                "apt_autoremove": False,
                "fwupdmgr_refresh": False,
                "fwupdmgr_update": False,
                "reboot_necessario": False,
                "reboot_executado": False,
                "pacotes_atualizados": [],
                "firmware_atualizados": [],
                "kernel_antes": _kernel_atual(),
                "kernel_depois": "",
                "erros": [],
            }

            # 1. apt update
            ok, msg = self._apt_update()
            resultados["apt_update"] = ok
            if not ok:
                resultados["erros"].append(f"apt update: {msg}")
                self._registrar_secao("apt_update", False, msg)
            else:
                self._registrar_secao("apt_update", True, msg[:200])

            # 2. Lista upgradable antes
            upgradable = _apt_lista_upgradable()
            resultados["pacotes_atualizados"] = upgradable

            # 3. apt full-upgrade
            ok, msg = self._apt_full_upgrade()
            resultados["apt_upgrade"] = ok
            if not ok:
                resultados["erros"].append(f"apt full-upgrade: {msg}")
                self._registrar_secao("apt_upgrade", False, msg)
            else:
                self._registrar_secao("apt_upgrade", True, f"{len(upgradable)} pacotes")

            # 4. apt autoremove
            ok, msg = self._apt_autoremove()
            resultados["apt_autoremove"] = ok
            self._registrar_secao("apt_autoremove", ok, msg[:200])

            # 5. Firmware
            ok, msg = self._fwupdmgr_refresh()
            resultados["fwupdmgr_refresh"] = ok
            self._registrar_secao("fwupdmgr_refresh", ok, msg[:200])

            firmware_antes = _fwupdmgr_upgrades()
            resultados["firmware_atualizados"] = firmware_antes

            ok, msg = self._fwupdmgr_update()
            resultados["fwupdmgr_update"] = ok
            self._registrar_secao("fwupdmgr_update", ok, msg[:200])

            # 6. Kernel novo?
            resultados["kernel_depois"] = _kernel_atual()
            kernel_mudou = resultados["kernel_antes"] != resultados["kernel_depois"]

            # 7. Verifica reboot
            precisa_reboot = self._verificar_reboot() or kernel_mudou
            resultados["reboot_necessario"] = precisa_reboot

            if precisa_reboot:
                self._estado.pendente_reboot = True
                self._salvar_estado()
                # Agenda reboot para daqui a 5 min (dá tempo do aviso sair)
                if not self.dry_run:
                    _executar(["shutdown", "-r", "+5", "OSUpdater: atualizações aplicadas"])
                    resultados["reboot_executado"] = True
                    self._estado.ultimo_reboot = time.time()
                    self._estado.pendente_reboot = False
                    self._registrar_secao("reboot", True, "agendado +5min")

            # Um aviso final só, já com o desfecho (sucesso ou falha). Vai
            # ANTES do shutdown em +5 min terminar o serviço.
            self._notificar_resultado(resultados, forcar=forcar)

            # Atualiza estado
            self._estado.ultima_execucao = agora
            if resultados["erros"]:
                self._estado.falhas_consecutivas += 1
                self._estado.sucessos_consecutivos = 0
            else:
                self._estado.sucessos_consecutivos += 1
                self._estado.falhas_consecutivas = 0
            self._salvar_estado()

            log.info("OSUpdater: ciclo finalizado", erros=len(resultados["erros"]), reboot=precisa_reboot)
            return {"ok": len(resultados["erros"]) == 0, **resultados}

    def _deve_executar(self, agora: float) -> bool:
        """Verifica se é hora de executar baseado no agendamento."""
        if self._estado.ultima_execucao == 0:
            return True  # primeira execução

        dt_agora = datetime.fromtimestamp(agora)
        dt_ultima = datetime.fromtimestamp(self._estado.ultima_execucao)

        if self.schedule == "daily":
            return dt_agora.date() > dt_ultima.date()

        # weekly: mesmo dia da semana e hora passada
        if dt_agora.weekday() != self.day:
            return False
        if dt_agora.hour < self.hour:
            return False
        # Se já executou hoje nessa janela
        if dt_ultima.date() == dt_agora.date() and dt_ultima.weekday() == self.day:
            return False
        return True

    def _proxima_execucao(self, agora: float) -> float:
        dt = datetime.fromtimestamp(agora)
        if self.schedule == "daily":
            prox = dt.replace(hour=self.hour, minute=0, second=0, microsecond=0)
            if prox <= dt:
                prox += timedelta(days=1)
            return prox.timestamp()

        # weekly: próximo domingo às 03:00
        dias_ate_domingo = (self.day - dt.weekday()) % 7
        if dias_ate_domingo == 0 and dt.hour >= self.hour:
            dias_ate_domingo = 7
        prox = dt.replace(hour=self.hour, minute=0, second=0, microsecond=0) + timedelta(days=dias_ate_domingo)
        return prox.timestamp()

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "schedule": self.schedule,
            "day": self.day,
            "hour": self.hour,
            "window_hours": self.window_hours,
            "ultima_execucao": self._estado.ultima_execucao,
            "ultima_tentativa": self._estado.ultima_tentativa,
            "sucessos_consecutivos": self._estado.sucessos_consecutivos,
            "falhas_consecutivas": self._estado.falhas_consecutivas,
            "pendente_reboot": self._estado.pendente_reboot,
            "ultimo_reboot": self._estado.ultimo_reboot,
            "kernel_atual": _kernel_atual(),
            "precisa_reboot": _precisa_reboot(),
            "upgradable": len(_apt_lista_upgradable()),
            "firmware_upgrades": len(_fwupdmgr_upgrades()),
            "proxima_execucao": self._proxima_execucao(time.time()),
            "dry_run": self.dry_run,
        }


# --- CLI ---------------------------------------------------------------------


def relatorio_simulacao(agora: Optional[float] = None) -> dict[str, Any]:
    """Roda o ciclo em `dry_run` e devolve um resumo LEGÍVEL (nada aplicado).

    O `--dry-run` já existia, mas só imprimia o JSON cru: o dono queria ver
    *o que* seria instalado antes de apertar o botão. Aqui as listas de
    pacotes/firmwares (leitura real, sem escrita) viram texto.
    O estado vai para arquivo temporário: simulação não polui as seções reais.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        up = OSUpdater(
            estado_arquivo=Path(tmp) / "simulacao.json",
            dry_run=True,
            notificador_telegram=None,  # simulação não notifica (contrato)
        )
        r = up.executar_ciclo(forcar=True)

    pacotes = list(r.get("pacotes_atualizados") or [])
    firmwares = list(r.get("firmware_atualizados") or [])
    reboot = bool(r.get("reboot_necessario"))
    linhas = [
        "Simulação do ciclo do SO (nada foi aplicado):",
        f"• pacotes: {len(pacotes)}",
        f"• firmwares: {len(firmwares)}",
        f"• reboot previsto: {'sim' if reboot else 'não'}",
    ]
    if r.get("erros"):
        linhas.append("• erros: " + "; ".join(str(e)[:100] for e in r["erros"]))
    if pacotes:
        linhas.append("Pacotes:")
        linhas.extend(f"  - {p}" for p in pacotes)
    if firmwares:
        linhas.append("Firmwares:")
        linhas.extend(f"  - {f}" for f in firmwares)
    return {
        "ok": not r.get("erros"),
        "texto": "\n".join(linhas),
        "pacotes": pacotes,
        "firmwares": firmwares,
        "reboot_previsto": reboot,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="OSUpdater - Atualização semanal do SO")
    parser.add_argument("--executar", action="store_true", help="Executa ciclo agora")
    parser.add_argument("--forcar", action="store_true", help="Força execução ignorando agendamento")
    parser.add_argument("--status", action="store_true", help="Mostra status")
    parser.add_argument(
        "--avisar-falha",
        action="store_true",
        help="Avisa no Telegram que a unit do ciclo falhou (OnFailure)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Modo simulação (sem I/O real)")
    parser.add_argument(
        "--relatorio",
        action="store_true",
        help="Simula o ciclo e mostra o resumo legível (nada é aplicado)",
    )
    parser.add_argument("--schedule", choices=["weekly", "daily"], default="weekly", help="Agendamento")
    parser.add_argument("--day", type=int, default=6, help="Dia da semana (0=seg, 6=dom)")
    parser.add_argument("--hour", type=int, default=3, help="Hora (0-23)")
    args = parser.parse_args()

    updater = OSUpdater(
        schedule=args.schedule,
        day=args.day,
        hour=args.hour,
        dry_run=args.dry_run,
        # Sem canal o ciclo das 03:00 aplicaria updates em silêncio (regra 15)
        notificador_telegram=notificar_telegram,
    )

    if args.relatorio:
        print(relatorio_simulacao()["texto"])
        return 0

    if args.avisar_falha:
        print(json.dumps(avisar_falha(), indent=2, ensure_ascii=False))
        return 0

    if args.status:
        print(json.dumps(updater.status(), indent=2, ensure_ascii=False))
        return 0

    if args.executar or args.forcar:
        resultado = updater.executar_ciclo(forcar=args.forcar)
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
        return 0 if resultado.get("ok") else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())