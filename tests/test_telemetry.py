"""
OMEGA DRAKON • TESTS
Módulo: tests/test_telemetry.py
Descrição: Testes do Perception Syncer (tools/telemetry.py) — Fase 4,
           item 4.3: leitura de /proc (CPU, memória, rede, processos,
           uptime), uso de disco, sondas de porta TCP, status do Docker por
           socket e snapshot resiliente com proc_root injetável.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/perception.py (percepção holística)
  - ROADMAP_ABSORCAO.md Fase 4, item 4.3
"""

from __future__ import annotations

import os
import socket
import threading
from pathlib import Path

import pytest

from tools.telemetry import Telemetry, TelemetryError, TelemetrySnapshot


# ---------------------------------------------------------------------------
# Fixtures: /proc fictício
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_fake_proc(root: Path) -> Path:
    """Monta uma árvore /proc fictícia com valores determinísticos."""
    proc = root / "proc"
    _write(proc / "stat", "cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 50 0 50 400 0 0 0 0 0 0\n")
    _write(
        proc / "meminfo",
        "MemTotal:        1000 kB\n"
        "MemFree:          400 kB\n"
        "MemAvailable:     600 kB\n"
        "Buffers:           50 kB\n"
        "Cached:           300 kB\n"
        "SwapTotal:        500 kB\n"
        "SwapFree:         100 kB\n",
    )
    _write(proc / "loadavg", "0.25 0.50 0.75 1/10 12345\n")
    _write(proc / "uptime", "3600.00 7200.00\n")
    _write(
        proc / "net" / "dev",
        "Inter-|   Receive                                                |  Transmit\n"
        " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
        "  eth0: 1000      10    0    0    0     0          0         0     2000      20    0    0    0     0       0          0\n"
        "    lo:  500       5    0    0    0     0          0         0      500       5    0    0    0     0       0          0\n",
    )
    _write(proc / "100" / "comm", "python3\n")
    _write(proc / "100" / "cmdline", "python3\\0-x\\0")
    _write(proc / "200" / "comm", "nginx\n")
    _write(proc / "notaproc" / "comm", "x\n")
    return proc


class TestTelemetryValidation:
    """Validação de construção."""

    def test_invalid_timeout_raises(self) -> None:
        with pytest.raises(TelemetryError):
            Telemetry(port_timeout=0)

    def test_defaults(self) -> None:
        telemetry = Telemetry()
        assert telemetry.proc_root == Path("/proc")
        assert telemetry.port_timeout > 0


class TestTelemetryFakeProc:
    """Leituras determinísticas de /proc."""

    def _telemetry(self, tmp_path: Path) -> Telemetry:
        proc = build_fake_proc(tmp_path)
        return Telemetry(
            proc_root=proc, disk_paths=(str(tmp_path),)
        )

    def test_cpu_first_sample_zero(self, tmp_path: Path) -> None:
        telemetry = self._telemetry(tmp_path)
        assert telemetry.cpu_usage() == 0.0  # primeira amostra é baseline

    def test_cpu_delta_computed(self, tmp_path: Path) -> None:
        proc = build_fake_proc(tmp_path)
        telemetry = Telemetry(proc_root=proc)
        assert telemetry.cpu_usage() == 0.0  # baseline
        # segunda amostra: +100 de total, 0 de idle → 100% de uso
        _write(proc / "stat", "cpu  100 0 200 800 0 0 0 0 0 0\n")
        assert telemetry.cpu_usage() == 100.0

    def test_load_averages(self, tmp_path: Path) -> None:
        telemetry = self._telemetry(tmp_path)
        assert telemetry.load_averages() == (0.25, 0.50, 0.75)

    def test_memory_values_in_bytes(self, tmp_path: Path) -> None:
        telemetry = self._telemetry(tmp_path)
        mem = telemetry.memory()
        assert mem["ok"] is True
        assert mem["total"] == 1000 * 1024
        assert mem["available"] == 600 * 1024
        assert mem["used"] == 400 * 1024
        assert mem["percent"] == 40.0
        assert mem["swap_total"] == 500 * 1024
        assert mem["swap_used"] == 400 * 1024
        assert mem["swap_percent"] == 80.0

    def test_network_interfaces(self, tmp_path: Path) -> None:
        telemetry = self._telemetry(tmp_path)
        net = telemetry.network()
        assert net["ok"] is True
        by_name = {i["name"]: i for i in net["interfaces"]}
        assert by_name["eth0"]["rx_bytes"] == 1000
        assert by_name["eth0"]["tx_bytes"] == 2000
        assert by_name["lo"]["rx_bytes"] == 500

    def test_processes_counted(self, tmp_path: Path) -> None:
        telemetry = self._telemetry(tmp_path)
        procs = telemetry.processes(("python", "nginx"))
        assert procs["ok"] is True
        assert procs["total"] == 2  # diretórios numéricos apenas
        assert procs["by_name"]["python"] == 1
        assert procs["by_name"]["nginx"] == 1

    def test_processes_without_names(self, tmp_path: Path) -> None:
        telemetry = self._telemetry(tmp_path)
        procs = telemetry.processes()
        assert procs["ok"] is True
        assert procs["total"] == 2
        assert procs["by_name"] == {}

    def test_host_section(self, tmp_path: Path) -> None:
        telemetry = self._telemetry(tmp_path)
        host = telemetry.host()
        assert host["ok"] is True
        assert host["uptime_s"] == 3600.0
        assert host["hostname"]
        assert host["system"]

    def test_disk_section(self, tmp_path: Path) -> None:
        telemetry = self._telemetry(tmp_path)
        disks = telemetry.disk()
        assert len(disks) == 1
        entry = disks[0]
        assert entry["path"] == str(tmp_path)
        assert entry["ok"] is True
        assert entry["total"] > 0
        assert entry["percent"] >= 0

    def test_missing_file_section_fails_gracefully(self, tmp_path: Path) -> None:
        proc = build_fake_proc(tmp_path)
        (proc / "net" / "dev").unlink()
        telemetry = Telemetry(proc_root=proc, disk_paths=(str(tmp_path),))
        net = telemetry.network()
        assert net["ok"] is False
        assert "error" in net
        # collect() não levanta e reporta o erro parcial
        snap = telemetry.collect()
        assert isinstance(snap, TelemetrySnapshot)
        assert any("network" in e for e in snap.errors)
        assert snap.cpu["ok"] is True  # demais seções seguem coletando


class TestTelemetrySocketProbes:
    """Sondas reais de porta TCP e socket unix do Docker."""

    def test_open_port_detected(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            telemetry = Telemetry(port_timeout=2.0)
            assert telemetry.probe_port("127.0.0.1", port) is True
        finally:
            listener.close()

    def test_closed_port_not_detected(self) -> None:
        # porta liberada: conecta em algo que não escuta → recusa
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        telemetry = Telemetry(port_timeout=0.5)
        assert telemetry.probe_port("127.0.0.1", port) is False

    def test_check_ports_results(self, tmp_path: Path) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        open_port = listener.getsockname()[1]
        try:
            closed = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            closed.bind(("127.0.0.1", 0))
            closed_port = closed.getsockname()[1]
            closed.close()

            telemetry = Telemetry(port_timeout=0.5)
            section = telemetry.check_ports("127.0.0.1", [open_port, closed_port])
            assert section["ok"] is True
            assert section["results"][str(open_port)] is True
            assert section["results"][str(closed_port)] is False
        finally:
            listener.close()

    def test_docker_socket_up(self, tmp_path: Path) -> None:
        sock_path = tmp_path / "docker.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(1)
        try:
            telemetry = Telemetry(docker_socket=str(sock_path), port_timeout=1.0)
            status = telemetry.docker_status()
            assert status["ok"] is True
            assert status["up"] is True
        finally:
            server.close()

    def test_docker_socket_absent(self, tmp_path: Path) -> None:
        telemetry = Telemetry(
            docker_socket=str(tmp_path / "inexistente.sock")
        )
        status = telemetry.docker_status()
        assert status["up"] is False
        assert "não encontrado" in status["error"]


class TestTelemetryCollect:
    """Snapshot completo e resiliente."""

    def test_collect_full_snapshot(self, tmp_path: Path) -> None:
        proc = build_fake_proc(tmp_path)
        telemetry = Telemetry(
            proc_root=proc,
            docker_socket=str(tmp_path / "docker.sock"),
            disk_paths=(str(tmp_path),),
        )
        # sobe um socket unix para o docker "up"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(tmp_path / "docker.sock"))
        server.listen(1)
        try:
            snap = telemetry.collect(
                ports=("127.0.0.1", []),
                process_names=("python", "nginx"),
            )
        finally:
            server.close()

        data = snap.to_dict()
        assert data["cpu"]["load1"] == 0.25
        assert data["memory"]["total"] == 1000 * 1024
        assert data["host"]["uptime_s"] == 3600.0
        assert data["processes"]["by_name"]["python"] == 1
        assert data["processes"]["by_name"]["nginx"] == 1
        assert data["docker"]["up"] is True
        assert data["disk"][0]["ok"] is True
        assert data["ports"]["ok"] is True
        assert data["network"]["ok"] is True
        assert data["errors"] == []

    def test_collect_without_proc_is_resilient(self, tmp_path: Path) -> None:
        # proc_root vazio (sem arquivos) → seções falham sem derrubar
        empty = tmp_path / "vazio"
        empty.mkdir()
        telemetry = Telemetry(
            proc_root=empty,
            docker_socket=str(tmp_path / "sem_docker.sock"),
        )
        snap = telemetry.collect()
        data = snap.to_dict()
        assert data["cpu"]["ok"] is False
        assert data["memory"]["ok"] is False
        assert data["network"]["ok"] is False
        assert data["processes"]["ok"] is True  # dir vazio → ok, 0 procs
        assert data["docker"]["up"] is False
        assert any("cpu" in e for e in data["errors"])
        assert any("memory" in e for e in data["errors"])
        assert any("network" in e for e in data["errors"])
        assert any("docker" in e for e in data["errors"])

    def test_collect_no_proc_dir(self, tmp_path: Path) -> None:
        telemetry = Telemetry(
            proc_root=tmp_path / "nao_existe",
            docker_socket=str(tmp_path / "sem_docker.sock"),
        )
        snap = telemetry.collect()
        assert snap.docker["ok"] is False  # socket inexistente
        assert snap.processes["ok"] is False  # /proc inexistente
        assert isinstance(snap.to_dict()["ts"], float)

    def test_dump_is_dict(self, tmp_path: Path) -> None:
        telemetry = Telemetry(proc_root=build_fake_proc(tmp_path))
        dump = telemetry.dump()
        assert isinstance(dump, dict)
        assert "cpu" in dump and "memory" in dump
