"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: tools/telemetry.py
Descrição: Perception Syncer — coleta de telemetria de hardware/serviços
           (CPU, memória, disco, rede, portas abertas, Docker via socket e
           processos). Fonte de percepção contínua do estado da máquina —
           alimenta Self Repair (4.2) e monitoramento. Implementação 100%
           stdlib (leitura de /proc, socket, shutil), resiliente: falha de
           uma sonda nunca derruba o snapshot.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/perception.py (percepção holística: hardware, Docker, portas,
    rede, processos)
  - OMEGADRAKON_SPEC.md §7 (sem execução externa; apenas leitura)
  - ROADMAP_ABSORCAO.md Fase 4, item 4.3 (depende de Config; alimenta 4.2)

Architecture:
    Um `Telemetry` coleta um `TelemetrySnapshot` com seções independentes:

      - cpu      — % de uso (delta entre amostras de /proc/stat), load
                   average 1/5/15, nº de núcleos;
      - memory   — total/available/used/percent + swap (/proc/meminfo);
      - disk     — uso por caminho configurado (shutil.disk_usage);
      - network  — bytes rx/tx por interface (/proc/net/dev);
      - ports    — sonda TCP (socket connect com timeout) por porta;
      - docker   — daemon acessível? (probe de socket unix, sem SDK);
      - processes— contagem por nome de processo (/proc/*/comm);
      - host     — hostname, sistema, release, uptime (/proc/uptime).

    Cada sonda é isolada: se um arquivo de /proc não existir ou uma porta
    estiver fechada, a seção reporta ok=False com erro — nunca levanta
    exceção durante `collect()` (percepção resiliente). `proc_root` é
    injetável (tests usam /proc fictício para determinismo).

Usage:
    from tools.telemetry import Telemetry

    perception = Telemetry()
    snap = perception.collect()
    snap.to_dict()["cpu"]["percent"]   # 0.0 na 1ª amostra, delta depois
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.tools.telemetry")

DEFAULT_PROC_ROOT = "/proc"
DEFAULT_DOCKER_SOCKET = "/var/run/docker.sock"
DEFAULT_PORT_TIMEOUT = 1.0
DEFAULT_DISK_PATHS = ("/",)


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------


class TelemetryError(Exception):
    """Erro base do Perception Syncer."""


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TelemetrySnapshot:
    """Snapshot de percepção coletado em um instante.

    Cada seção é um dict com pelo menos `ok` (bool); seções com falha
    carregam também `error`. Falhas parciais são acumuladas em `errors`.
    """

    ts: float = field(default_factory=time.time)
    host: dict[str, Any] = field(default_factory=dict)
    cpu: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    disk: list[dict[str, Any]] = field(default_factory=list)
    network: dict[str, Any] = field(default_factory=dict)
    ports: dict[str, Any] = field(default_factory=dict)
    docker: dict[str, Any] = field(default_factory=dict)
    processes: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": round(self.ts, 6),
            "host": dict(self.host),
            "cpu": dict(self.cpu),
            "memory": dict(self.memory),
            "disk": [dict(d) for d in self.disk],
            "network": dict(self.network),
            "ports": dict(self.ports),
            "docker": dict(self.docker),
            "processes": dict(self.processes),
            "errors": list(self.errors),
        }


def _percent(used: float, total: float) -> float:
    """Percentual usado/total (0.0 quando total inválido)."""
    if total <= 0:
        return 0.0
    return round(100.0 * used / total, 1)


# ---------------------------------------------------------------------------
# Telemetry (Perception Syncer)
# ---------------------------------------------------------------------------


class Telemetry:
    """Coletor de telemetria de hardware/serviços (percepção).

    Attributes:
        proc_root:      Raiz do /proc (injetável para testes/determinismo).
        docker_socket:  Caminho do socket unix do Docker daemon.
        port_timeout:   Timeout (s) de cada sonda de porta TCP.
        disk_paths:     Caminhos monitorados por shutil.disk_usage.
    """

    def __init__(
        self,
        *,
        proc_root: Union[str, Path] = DEFAULT_PROC_ROOT,
        docker_socket: str = DEFAULT_DOCKER_SOCKET,
        port_timeout: float = DEFAULT_PORT_TIMEOUT,
        disk_paths: tuple[str, ...] = DEFAULT_DISK_PATHS,
    ) -> None:
        if port_timeout <= 0:
            raise TelemetryError("port_timeout deve ser > 0")
        self.proc_root = Path(proc_root)
        self.docker_socket = docker_socket
        self.port_timeout = port_timeout
        self.disk_paths = tuple(disk_paths) or DEFAULT_DISK_PATHS

        self._lock = threading.Lock()
        self._cpu_baseline: Optional[tuple[float, float]] = None

    # -- Leitura de /proc ----------------------------------------------------

    def _read(self, rel: str) -> str:
        """Lê um arquivo sob proc_root (UTF-8, tolerant a bytes inválidos)."""
        path = self.proc_root / rel
        return path.read_text(encoding="utf-8", errors="replace")

    # -- CPU -----------------------------------------------------------------

    def _cpu_totals(self) -> tuple[float, float]:
        """Lê /proc/stat e retorna (total, idle) acumulados da primeira CPU."""
        line = ""
        for raw in self._read("stat").splitlines():
            if raw.startswith("cpu "):
                line = raw
                break
        parts = line.split()
        if len(parts) < 5:
            raise TelemetryError("formato inesperado em /proc/stat")
        values = [float(v) for v in parts[1:]]
        # guest já está contido em user/nice; usa os 8 primeiros campos
        total = sum(values[:8])
        idle = values[3] + values[4]  # idle + iowait
        return total, idle

    def cpu_usage(self) -> float:
        """% de uso de CPU por delta entre amostras (0.0 na primeira)."""
        with self._lock:
            try:
                total, idle = self._cpu_totals()
            except Exception:
                return 0.0
            baseline = self._cpu_baseline
            self._cpu_baseline = (total, idle)
            if baseline is None:
                return 0.0
            total_delta = total - baseline[0]
            idle_delta = idle - baseline[1]
            if total_delta <= 0:
                return 0.0
            return round(100.0 * (1.0 - idle_delta / total_delta), 1)

    def load_averages(self) -> tuple[float, float, float]:
        """Load average 1/5/15 minutos (/proc/loadavg)."""
        parts = self._read("loadavg").split()
        if len(parts) < 3:
            raise TelemetryError("formato inesperado em /proc/loadavg")
        return tuple(float(p) for p in parts[:3])  # type: ignore[return-value]

    def _cpu_section(self) -> dict[str, Any]:
        section: dict[str, Any] = {"ok": False, "cores": os.cpu_count() or 0}
        try:
            percent = self.cpu_usage()
            load1, load5, load15 = self.load_averages()
            section.update(
                {
                    "ok": True,
                    "percent": percent,
                    "load1": load1,
                    "load5": load5,
                    "load15": load15,
                }
            )
        except Exception as exc:
            section["error"] = f"{type(exc).__name__}: {exc}"
        return section

    # -- Memória -------------------------------------------------------------

    def memory(self) -> dict[str, Any]:
        """Leitura de /proc/meminfo (valores em bytes)."""
        section: dict[str, Any] = {"ok": False}
        try:
            raw = self._read("meminfo")
            fields: dict[str, int] = {}
            for line in raw.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].endswith(":"):
                    try:
                        fields[parts[0][:-1]] = int(parts[1]) * 1024  # kB→bytes
                    except ValueError:
                        continue
            total = fields.get("MemTotal", 0)
            available = fields.get("MemAvailable", fields.get("MemFree", 0))
            swap_total = fields.get("SwapTotal", 0)
            swap_free = fields.get("SwapFree", 0)
            swap_used = max(0, swap_total - swap_free)
            section.update(
                {
                    "ok": True,
                    "total": total,
                    "available": available,
                    "used": max(0, total - available),
                    "percent": _percent(total - available, total),
                    "swap_total": swap_total,
                    "swap_used": swap_used,
                    "swap_percent": _percent(swap_used, swap_total),
                }
            )
        except Exception as exc:
            section["error"] = f"{type(exc).__name__}: {exc}"
        return section

    # -- Disco ---------------------------------------------------------------

    def disk(self) -> list[dict[str, Any]]:
        """Uso de disco por caminho (shutil.disk_usage, stdlib)."""
        result: list[dict[str, Any]] = []
        for path in self.disk_paths:
            entry: dict[str, Any] = {"path": path, "ok": False}
            try:
                usage = shutil.disk_usage(path)
                entry.update(
                    {
                        "ok": True,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "percent": _percent(usage.used, usage.total),
                    }
                )
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            result.append(entry)
        return result

    # -- Rede ----------------------------------------------------------------

    def network(self) -> dict[str, Any]:
        """Bytes rx/tx por interface (/proc/net/dev)."""
        section: dict[str, Any] = {"ok": False, "interfaces": []}
        try:
            raw = self._read("net/dev")
            interfaces: list[dict[str, Any]] = []
            for line in raw.splitlines()[2:]:  # pula cabeçalhos
                if ":" not in line:
                    continue
                name, rest = line.split(":", 1)
                values = rest.split()
                if len(values) < 9:
                    continue
                try:
                    rx, tx = int(values[0]), int(values[8])
                except ValueError:
                    continue
                interfaces.append(
                    {
                        "name": name.strip(),
                        "rx_bytes": rx,
                        "tx_bytes": tx,
                    }
                )
            section.update({"ok": True, "interfaces": interfaces})
        except Exception as exc:
            section["error"] = f"{type(exc).__name__}: {exc}"
        return section

    # -- Portas --------------------------------------------------------------

    def probe_port(self, host: str, port: int, timeout: Optional[float] = None) -> bool:
        """True se a porta TCP está aberta (socket connect com timeout)."""
        timeout = timeout if timeout is not None else self.port_timeout
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False
        finally:
            sock.close()

    def check_ports(self, host: str, ports: list[int]) -> dict[str, Any]:
        """Sonda uma lista de portas TCP no host."""
        section: dict[str, Any] = {"ok": False, "host": host, "results": {}}
        try:
            results: dict[str, bool] = {}
            for port in ports:
                try:
                    results[str(port)] = self.probe_port(host, port)
                except Exception:
                    results[str(port)] = False
            section.update({"ok": True, "results": results})
        except Exception as exc:
            section["error"] = f"{type(exc).__name__}: {exc}"
        return section

    # -- Docker --------------------------------------------------------------

    def docker_status(self) -> dict[str, Any]:
        """Daemon acessível? Probe de socket unix (sem SDK externo)."""
        section: dict[str, Any] = {
            "ok": False,
            "socket": self.docker_socket,
        }
        try:
            if not Path(self.docker_socket).exists():
                section.update({"up": False, "error": "socket não encontrado"})
                return section
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.settimeout(self.port_timeout)
                sock.connect(self.docker_socket)
                section.update({"ok": True, "up": True})
            except OSError as exc:
                section.update({"up": False, "error": f"{type(exc).__name__}: {exc}"})
            finally:
                sock.close()
        except Exception as exc:
            section.update({"up": False, "error": f"{type(exc).__name__}: {exc}"})
        return section

    # -- Processos -----------------------------------------------------------

    def processes(self, names: tuple[str, ...] = ()) -> dict[str, Any]:
        """Contagem de processos por nome (/proc/*/comm e cmdline)."""
        section: dict[str, Any] = {"ok": False, "by_name": {}}
        names = tuple(names)
        try:
            counts = {name: 0 for name in names}
            total = 0
            for entry in self.proc_root.iterdir():
                if not entry.name.isdigit():
                    continue
                total += 1
                try:
                    comm = (entry / "comm").read_text(
                        encoding="utf-8", errors="replace"
                    ).strip()
                except OSError:
                    comm = ""
                for name in names:
                    if comm.startswith(name):
                        counts[name] += 1
            section.update(
                {
                    "ok": True,
                    "total": total,
                    "by_name": counts,
                }
            )
        except Exception as exc:
            section["error"] = f"{type(exc).__name__}: {exc}"
        return section

    # -- Host ----------------------------------------------------------------

    def host(self) -> dict[str, Any]:
        """Identificação do host e uptime."""
        section: dict[str, Any] = {"ok": False}
        try:
            uptime = 0.0
            parts = self._read("uptime").split()
            if parts:
                uptime = float(parts[0])
            uname = os.uname()
            section.update(
                {
                    "ok": True,
                    "hostname": socket.gethostname(),
                    "system": uname.sysname,
                    "release": uname.release,
                    "machine": uname.machine,
                    "uptime_s": uptime,
                    "python": platform.python_version(),
                }
            )
        except Exception as exc:
            section["error"] = f"{type(exc).__name__}: {exc}"
        return section

    # -- Snapshot ------------------------------------------------------------

    def collect(
        self,
        *,
        ports: Optional[tuple[str, list[int]]] = None,
        process_names: tuple[str, ...] = (),
    ) -> TelemetrySnapshot:
        """Coleta o snapshot completo de percepção (resiliente).

        Args:
            ports:          (host, [portas]) para sondar, ex: ("127.0.0.1", [80]).
            process_names:  Nomes de processos a contar (ex: ("python",)).
        """
        errors: list[str] = []
        snap = TelemetrySnapshot()

        sections: dict[str, dict[str, Any]] = {}

        def probe(name: str, fn: Any) -> dict[str, Any]:
            try:
                return fn()
            except Exception as exc:  # nunca deixa a sonda derrubar o snapshot
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        snap.host = probe("host", self.host)
        snap.cpu = probe("cpu", self._cpu_section)
        snap.memory = probe("memory", self.memory)
        snap.network = probe("network", self.network)
        snap.processes = probe(
            "processes", lambda: self.processes(process_names)
        )

        # disco é lista — trata separadamente
        try:
            snap.disk = self.disk()
        except Exception as exc:
            errors.append(f"disk: {type(exc).__name__}: {exc}")

        if ports is not None:
            host, port_list = ports
            snap.ports = probe("ports", lambda: self.check_ports(host, port_list))

        snap.docker = probe("docker", self.docker_status)

        # Seções que falharam internamente (sem exceção) também entram na
        # lista de erros do snapshot — percepção observável.
        for name, section in (
            ("host", snap.host),
            ("cpu", snap.cpu),
            ("memory", snap.memory),
            ("network", snap.network),
            ("processes", snap.processes),
            ("ports", snap.ports),
            ("docker", snap.docker),
        ):
            if not isinstance(section, dict) or section.get("ok") is not False:
                continue
            message = section.get("error")
            if message and f"{name}: {message}" not in errors:
                errors.append(f"{name}: {message}")

        snap.errors = errors
        return snap

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        """Snapshot diagnóstico (atalho para collect().to_dict())."""
        return self.collect().to_dict()
