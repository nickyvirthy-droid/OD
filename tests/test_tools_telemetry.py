"""
OMEGA DRAKON • TESTS
Módulo: tests/test_tools_telemetry.py
Descrição: Testes do Perception Syncer (tools/telemetry.py) — Fase 4,
           item 4.3: leitura de /proc (CPU, memória, rede, processos,
           uptime), uso de disco, sondas de porta TCP, status do Docker por
           socket e snapshot resiliente com proc_root injetável.

           Os testes de base foram ressuscitados do histórico (apagados pelo
           rewrite de c65223e que trocou o tema de tests/test_telemetry.py
           para o núcleo OTel) e complementados com novos casos para os
           caminhos ainda descobertos do módulo: entradas malformadas de
           /proc, percentuais com total zero, sondas de porta com falha,
           Docker com exceção inesperada e seções que levantam dentro de
           collect().
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/perception.py (percepção holística)
  - ROADMAP_ABSORCAO.md Fase 4, item 4.3
"""

from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.telemetry as telemetry_module
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

    def test_disk_paths_vazio_vira_padrao(self) -> None:
        """disk_paths=() cai no DEFAULT_DISK_PATHS ("/",)."""
        telemetry = Telemetry(disk_paths=())
        assert telemetry.disk_paths == ("/",)


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

    def test_cpu_sem_delta_entre_amostras_zera(self, tmp_path: Path) -> None:
        """Amostra idêntica à baseline → total_delta <= 0 → 0.0 (sem erro)."""
        telemetry = Telemetry(proc_root=build_fake_proc(tmp_path))
        telemetry.cpu_usage()  # baseline
        assert telemetry.cpu_usage() == 0.0

    def test_cpu_stat_malformado_zera_sem_levantar(self, tmp_path: Path) -> None:
        """linha 'cpu' sem campos suficientes: cpu_usage devolve 0.0."""
        proc = build_fake_proc(tmp_path)
        _write(proc / "stat", "cpu\n")
        telemetry = Telemetry(proc_root=proc)
        assert telemetry.cpu_usage() == 0.0

    def test_cpu_totais_levanta_em_formato_inesperado(self, tmp_path: Path) -> None:
        proc = build_fake_proc(tmp_path)
        _write(proc / "stat", "cpu 1 2\n")
        telemetry = Telemetry(proc_root=proc)
        with pytest.raises(TelemetryError):
            telemetry._cpu_totals()

    def test_load_averages(self, tmp_path: Path) -> None:
        telemetry = self._telemetry(tmp_path)
        assert telemetry.load_averages() == (0.25, 0.50, 0.75)

    def test_loadavg_malformado_levanta_telemetry_error(self, tmp_path: Path) -> None:
        proc = build_fake_proc(tmp_path)
        _write(proc / "loadavg", "0.25 0.50\n")  # faltam campos
        telemetry = Telemetry(proc_root=proc)
        with pytest.raises(TelemetryError):
            telemetry.load_averages()

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

    def test_memory_sem_memavailable_usa_memfree(self, tmp_path: Path) -> None:
        """Sem MemAvailable, o fallback é MemFree."""
        proc = build_fake_proc(tmp_path)
        _write(
            proc / "meminfo",
            "MemTotal:        1000 kB\n"
            "MemFree:          250 kB\n"
            "SwapTotal:          0 kB\n"
            "SwapFree:           0 kB\n",
        )
        telemetry = Telemetry(proc_root=proc)
        mem = telemetry.memory()
        assert mem["ok"] is True
        assert mem["available"] == 250 * 1024
        # total de swap zero → percentual 0.0 (sem divisão por zero)
        assert mem["swap_total"] == 0
        assert mem["swap_used"] == 0
        assert mem["swap_percent"] == 0.0

    def test_memory_linha_invalida_e_ignorada(self, tmp_path: Path) -> None:
        """Campo não numérico em /proc/meminfo não derruba a seção."""
        proc = build_fake_proc(tmp_path)
        _write(
            proc / "meminfo",
            "MemTotal:        1000 kB\n"
            "Weird:           not-a-number kB\n"
            "MemAvailable:     600 kB\n",
        )
        telemetry = Telemetry(proc_root=proc)
        mem = telemetry.memory()
        assert mem["ok"] is True
        assert mem["total"] == 1000 * 1024
        assert mem["available"] == 600 * 1024

    def test_memory_sem_meminfo_reporta_erro(self, tmp_path: Path) -> None:
        proc = build_fake_proc(tmp_path)
        (proc / "meminfo").unlink()
        telemetry = Telemetry(proc_root=proc)
        mem = telemetry.memory()
        assert mem["ok"] is False
        assert "error" in mem

    def test_network_interfaces(self, tmp_path: Path) -> None:
        telemetry = self._telemetry(tmp_path)
        net = telemetry.network()
        assert net["ok"] is True
        by_name = {i["name"]: i for i in net["interfaces"]}
        assert by_name["eth0"]["rx_bytes"] == 1000
        assert by_name["eth0"]["tx_bytes"] == 2000
        assert by_name["lo"]["rx_bytes"] == 500

    def test_network_pula_linhas_malformadas(self, tmp_path: Path) -> None:
        """Linhas sem ':', com poucos campos ou não numéricas são puladas."""
        proc = build_fake_proc(tmp_path)
        _write(
            proc / "net" / "dev",
            "Inter-|   Receive\n"
            " face |bytes\n"
            "linha sem separador\n"
            "eth0: 1000 10\n"  # poucos campos
            "wlan0: x y z a b c d e f\n"  # rx não numérico\n"
            "  lo:  500 5 0 0 0 0 0 0 500 5 0 0 0 0 0 0\n",
        )
        telemetry = Telemetry(proc_root=proc)
        net = telemetry.network()
        assert net["ok"] is True
        names = [i["name"] for i in net["interfaces"]]
        assert names == ["lo"]

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

    def test_processes_comm_ausente_conta_como_vazio(self, tmp_path: Path) -> None:
        """Diretório numérico sem /comm não derruba a contagem."""
        proc = build_fake_proc(tmp_path)
        _write(proc / "300" / "marker", "x\n")  # 300 sem comm
        telemetry = Telemetry(proc_root=proc)
        procs = telemetry.processes(("python",))
        assert procs["ok"] is True
        assert procs["total"] == 3
        assert procs["by_name"]["python"] == 1

    def test_host_section(self, tmp_path: Path) -> None:
        telemetry = self._telemetry(tmp_path)
        host = telemetry.host()
        assert host["ok"] is True
        assert host["uptime_s"] == 3600.0
        assert host["hostname"]
        assert host["system"]

    def test_host_uptime_vazio_fica_zero(self, tmp_path: Path) -> None:
        """/proc/uptime vazio → uptime_s 0.0 (sem exceção)."""
        proc = build_fake_proc(tmp_path)
        _write(proc / "uptime", "")
        telemetry = Telemetry(proc_root=proc)
        host = telemetry.host()
        assert host["ok"] is True
        assert host["uptime_s"] == 0.0

    def test_disk_section(self, tmp_path: Path) -> None:
        telemetry = self._telemetry(tmp_path)
        disks = telemetry.disk()
        assert len(disks) == 1
        entry = disks[0]
        assert entry["path"] == str(tmp_path)
        assert entry["ok"] is True
        assert entry["total"] > 0
        assert entry["percent"] >= 0

    def test_disk_caminho_inexistente_reporta_erro(self, tmp_path: Path) -> None:
        """Campos monitorados com falha viram ok=False, sem levantar."""
        telemetry = Telemetry(disk_paths=(str(tmp_path / "nao_existe"),))
        disks = telemetry.disk()
        assert len(disks) == 1
        assert disks[0]["ok"] is False
        assert "error" in disks[0]

    def test_disk_total_zero_percent_zera(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """shutil.disk_usage com total 0 → percent 0.0 (sem ZeroDivision)."""
        fake = SimpleNamespace(total=0, used=0, free=0)
        monkeypatch.setattr(
            telemetry_module.shutil, "disk_usage", lambda _p: fake
        )
        telemetry = Telemetry(disk_paths=(str(tmp_path),))
        entry = telemetry.disk()[0]
        assert entry["ok"] is True
        assert entry["percent"] == 0.0

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

    def test_probe_port_com_timeout_explicito(self) -> None:
        """Timeout por chamada sobrepõe o default do construtor."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        telemetry = Telemetry(port_timeout=30.0)  # default alto, não usado
        assert telemetry.probe_port("127.0.0.1", port, timeout=0.3) is False

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

    def test_check_ports_sonda_quebrada_vira_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exceção dentro de probe_port é capturada por porta (False)."""
        def _boom(self, host, port, timeout=None):
            raise OSError("rede indisponível")

        monkeypatch.setattr(Telemetry, "probe_port", _boom)
        section = Telemetry(port_timeout=0.5).check_ports("127.0.0.1", [80])
        assert section["ok"] is True
        assert section["results"] == {"80": False}

    def test_check_ports_entrada_nao_iteravel(self) -> None:
        """Entrada inválida (None) vira seção com erro, sem levantar."""
        section = Telemetry().check_ports("127.0.0.1", None)  # type: ignore[arg-type]
        assert section["ok"] is False
        assert "error" in section

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

    def test_docker_socket_arquivo_comum_levanta_oserror(
        self, tmp_path: Path
    ) -> None:
        """Arquivo comum no lugar do socket → connect falha, seção ok=False."""
        sock_path = tmp_path / "docker.sock"
        sock_path.write_text("nao sou um socket", encoding="utf-8")
        telemetry = Telemetry(docker_socket=str(sock_path), port_timeout=0.5)
        status = telemetry.docker_status()
        assert status["ok"] is False
        assert status["up"] is False
        assert "error" in status

    def test_docker_status_erro_inesperado_capturado(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Qualquer exceção fora do connect (aqui: Path) vira erro da seção."""
        class _PathQuebrado:
            def __init__(self, *_args):
                pass

            def exists(self) -> bool:
                raise RuntimeError("filesystem inacessível")

        telemetry = Telemetry(docker_socket=str(tmp_path / "docker.sock"))
        monkeypatch.setattr(telemetry_module, "Path", _PathQuebrado)
        status = telemetry.docker_status()
        assert status["up"] is False
        assert status["error"] == "RuntimeError: filesystem inacessível"


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

    def test_collect_secao_quebra_erro_unico(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exceção dentro de uma sonda entra em errors uma única vez."""
        def _host_quebrado(self):
            raise RuntimeError("host indisponível")

        monkeypatch.setattr(Telemetry, "host", _host_quebrado)
        telemetry = Telemetry(
            proc_root=build_fake_proc(tmp_path),
            docker_socket=str(tmp_path / "sem_docker.sock"),
        )
        snap = telemetry.collect()
        assert snap.host["ok"] is False
        esperado = "host: RuntimeError: host indisponível"
        assert snap.errors.count(esperado) == 1
        # demais seções seguem coletando normalmente
        assert snap.cpu["ok"] is True

    def test_collect_disco_quebra_sem_derrubar(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exceção em disk() é acumulada em errors e não derruba o snapshot."""
        def _disco_quebrado(self):
            raise OSError("disco indisponível")

        monkeypatch.setattr(Telemetry, "disk", _disco_quebrado)
        telemetry = Telemetry(
            proc_root=build_fake_proc(tmp_path),
            docker_socket=str(tmp_path / "sem_docker.sock"),
        )
        snap = telemetry.collect()
        assert snap.disk == []
        assert any(e.startswith("disk: OSError") for e in snap.errors)
        assert snap.cpu["ok"] is True

    def test_collect_secao_nao_dict_e_pulada(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sonda que devolve algo que não é dict é ignorada no ciclo de erros."""
        monkeypatch.setattr(
            Telemetry, "check_ports", lambda self, host, ports: []
        )
        telemetry = Telemetry(
            proc_root=build_fake_proc(tmp_path),
            docker_socket=str(tmp_path / "sem_docker.sock"),
        )
        snap = telemetry.collect(ports=("127.0.0.1", [80]))
        assert snap.ports == []
        assert not any(e.startswith("ports:") for e in snap.errors)

    def test_dump_is_dict(self, tmp_path: Path) -> None:
        telemetry = Telemetry(proc_root=build_fake_proc(tmp_path))
        dump = telemetry.dump()
        assert isinstance(dump, dict)
        assert "cpu" in dump and "memory" in dump
