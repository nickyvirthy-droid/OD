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
import time
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
            self._notificar("🔧 OSUpdater", "Iniciando atualização semanal do sistema...")

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
                self._notificar(
                    "⚠️ OSUpdater",
                    f"Atualizações aplicadas. Reboot necessário.\n"
                    f"Kernel: {resultados['kernel_antes']} → {resultados['kernel_depois']}\n"
                    f"Pacotes: {len(upgradable)}\n"
                    f"Firmware: {len(firmware_antes)}"
                )
                # Agenda reboot para daqui a 5 min (dá tempo de notificação chegar)
                if not self.dry_run:
                    _executar(["shutdown", "-r", "+5", "OSUpdater: atualizações aplicadas"])
                    resultados["reboot_executado"] = True
                    self._estado.ultimo_reboot = time.time()
                    self._estado.pendente_reboot = False
                    self._registrar_secao("reboot", True, "agendado +5min")
            else:
                self._notificar(
                    "✅ OSUpdater",
                    f"Atualizações concluídas sem necessidade de reboot.\n"
                    f"Pacotes: {len(upgradable)} | Firmware: {len(firmware_antes)}"
                )

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


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="OSUpdater - Atualização semanal do SO")
    parser.add_argument("--executar", action="store_true", help="Executa ciclo agora")
    parser.add_argument("--forcar", action="store_true", help="Força execução ignorando agendamento")
    parser.add_argument("--status", action="store_true", help="Mostra status")
    parser.add_argument("--dry-run", action="store_true", help="Modo simulação (sem I/O real)")
    parser.add_argument("--schedule", choices=["weekly", "daily"], default="weekly", help="Agendamento")
    parser.add_argument("--day", type=int, default=6, help="Dia da semana (0=seg, 6=dom)")
    parser.add_argument("--hour", type=int, default=3, help="Hora (0-23)")
    args = parser.parse_args()

    updater = OSUpdater(
        schedule=args.schedule,
        day=args.day,
        hour=args.hour,
        dry_run=args.dry_run,
    )

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