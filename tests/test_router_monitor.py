"""
OMEGA DRAKON * TESTS
Modulo: tests/test_router_monitor.py
Descricao: Testes do monitor do roteador (tools/monitor/router_monitor.sh) —
           execução real do script em sandbox (diretório temporário e gateway
           de teste), validando o contrato do log JSON-lines consumido pelo
           `--report`.

Histórico (2026-09-18): o script rodou 17h em produção com 1086 registros
"up" e ZERO "down". Causa: `set -e` + `x=$(ping ...)` — o ping que falhava
(roteador fora) derrubava o script ANTES do registro, e um `cat` de interface
ausente abortava antes da linha da interface. Os dois casos têm teste próprio
aqui: são a razão de este arquivo existir.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "monitor" / "router_monitor.sh"

# Bloco de documentação: rede de teste do RFC 5737 (nunca responde).
GATEWAY_INALCANCAVEL = "192.0.2.1"
GATEWAY_OK = "127.0.0.1"


def _ping_disponivel(destino: str) -> bool:
    if shutil.which("ping") is None:
        return False
    return subprocess.run(
        ["ping", "-c", "1", "-W", "1", destino],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def _roda_once(tmp_path: Path, **env_extra: str) -> subprocess.CompletedProcess:
    """Executa o monitor em sandbox (log em tmp_path, sem tocar em produção)."""
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "OD_LOG_DIR": str(tmp_path),
        **env_extra,
    }
    return subprocess.run(
        ["bash", str(SCRIPT), "--once"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _linhas(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    return [
        json.loads(linha)
        for linha in caminho.read_text(encoding="utf-8").splitlines()
        if linha.strip()
    ]


# ---------------------------------------------------------------------------
# Script: caminho do roteador fora (o bug que deixava o monitor cego)
# ---------------------------------------------------------------------------


class TestRoteadorInalcancavel:
    def test_registra_down_sem_abortar(self, tmp_path: Path) -> None:
        """O caso que falhava: ping falho NÃO pode matar o script antes do log."""
        resultado = _roda_once(tmp_path, OD_ROUTER_IP=GATEWAY_INALCANCAVEL)

        assert resultado.returncode == 0, resultado.stderr
        registros = _linhas(tmp_path / "router_monitor.log")
        assert len(registros) == 1, "o registro do down é o objetivo do monitor"
        assert registros[0]["status"] == "down"
        assert registros[0]["detail"] == "ping_failed"
        assert registros[0]["gateway"] == GATEWAY_INALCANCAVEL
        assert registros[0]["latency_ms"] >= 0

    def test_interface_tambem_e_registrada_no_mesmo_ciclo(self, tmp_path: Path) -> None:
        _roda_once(tmp_path, OD_ROUTER_IP=GATEWAY_INALCANCAVEL)

        assert _linhas(tmp_path / "interface_monitor.log"), (
            "roteador fora não pode impedir o registro da interface"
        )

    def test_saida_do_terminal_mostra_down(self, tmp_path: Path) -> None:
        resultado = _roda_once(tmp_path, OD_ROUTER_IP=GATEWAY_INALCANCAVEL)
        assert "Router DOWN" in resultado.stdout


# ---------------------------------------------------------------------------
# Script: interface ausente (o segundo caminho que abortava)
# ---------------------------------------------------------------------------


class TestInterfaceAusente:
    def test_interface_inexistente_nao_aborta(self, tmp_path: Path) -> None:
        resultado = _roda_once(
            tmp_path,
            OD_ROUTER_IP=GATEWAY_OK,
            OD_NETWORK_INTERFACE="interface-que-nao-existe0",
        )

        assert resultado.returncode == 0, resultado.stderr
        registros = _linhas(tmp_path / "interface_monitor.log")
        assert len(registros) == 1
        assert registros[0]["state"] == "unknown"
        # carrier/speed entram no JSON sem aspas: precisam ser número.
        assert registros[0]["carrier"] == 0
        assert registros[0]["speed"] == 0
        assert registros[0]["interface"] == "interface-que-nao-existe0"

    def test_router_ainda_e_verificado(self, tmp_path: Path) -> None:
        _roda_once(tmp_path, OD_NETWORK_INTERFACE="interface-que-nao-existe0")
        assert _linhas(tmp_path / "router_monitor.log")


# ---------------------------------------------------------------------------
# Contrato do log (o que o `--report` consome)
# ---------------------------------------------------------------------------


class TestContratoDoLog:
    def test_toda_linha_e_json_com_os_campos_esperados(self, tmp_path: Path) -> None:
        _roda_once(tmp_path, OD_ROUTER_IP=GATEWAY_INALCANCAVEL)

        for registro in _linhas(tmp_path / "router_monitor.log"):
            assert set(registro) >= {"ts", "local", "gateway", "status", "latency_ms"}
            assert registro["status"] in {"up", "down"}
            assert isinstance(registro["latency_ms"], (int, float))
            assert registro["ts"].endswith("Z")

        for registro in _linhas(tmp_path / "interface_monitor.log"):
            assert set(registro) >= {"ts", "local", "interface", "state", "carrier", "speed"}

    @pytest.mark.skipif(
        not _ping_disponivel(GATEWAY_OK), reason="sem ping no loopback neste host"
    )
    def test_roteador_de_pe_registra_up(self, tmp_path: Path) -> None:
        _roda_once(tmp_path, OD_ROUTER_IP=GATEWAY_OK)

        registros = _linhas(tmp_path / "router_monitor.log")
        assert len(registros) == 1
        assert registros[0]["status"] == "up"
        assert "detail" not in registros[0]

    def test_rotacao_do_log(self, tmp_path: Path) -> None:
        """Log acima do limite vira `.1` (senão cresce sem teto: ~130 MB/ano)."""
        log = tmp_path / "router_monitor.log"
        log.write_text("x" * 400 + "\n", encoding="utf-8")

        _roda_once(
            tmp_path,
            OD_ROUTER_IP=GATEWAY_INALCANCAVEL,
            OD_MONITOR_MAX_BYTES="200",
        )

        assert (tmp_path / "router_monitor.log.1").exists()
        assert len(log.read_text(encoding="utf-8")) < 400


# ---------------------------------------------------------------------------
# --report
# ---------------------------------------------------------------------------


class TestRelatorio:
    def test_sem_log_avisa(self, tmp_path: Path) -> None:
        resultado = subprocess.run(
            ["bash", str(SCRIPT), "--report"],
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "OD_LOG_DIR": str(tmp_path)},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert resultado.returncode == 0
        assert "Nenhum dado de monitoramento encontrado" in resultado.stdout

    def test_conta_up_e_down_e_lista_incidentes(self, tmp_path: Path) -> None:
        linhas = [
            '{"ts":"2026-09-18T07:00:00Z","local":"2026-09-18 04:00:00 -0300",'
            '"gateway":"192.168.0.1","status":"up","latency_ms":1.2}',
            '{"ts":"2026-09-18T07:01:00Z","local":"2026-09-18 04:01:00 -0300",'
            '"gateway":"192.168.0.1","status":"down","latency_ms":2001,'
            '"detail":"ping_failed"}',
            '{"ts":"2026-09-18T07:02:00Z","local":"2026-09-18 04:02:00 -0300",'
            '"gateway":"192.168.0.1","status":"up","latency_ms":1.5}',
        ]
        (tmp_path / "router_monitor.log").write_text(
            "\n".join(linhas) + "\n", encoding="utf-8"
        )

        resultado = subprocess.run(
            ["bash", str(SCRIPT), "--report"],
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "OD_LOG_DIR": str(tmp_path)},
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert resultado.returncode == 0
        saida = resultado.stdout
        assert "Total de verificações: 3" in saida
        assert "Router UP: 2" in saida
        assert "Router DOWN: 1" in saida
        assert "2026-09-18: 1 registro(s) down" in saida
        assert "ping_failed" in saida

    def test_reporte_ignora_linha_corrompida(self, tmp_path: Path) -> None:
        (tmp_path / "router_monitor.log").write_text(
            "isso não é json\n"
            '{"ts":"2026-09-18T07:00:00Z","local":"2026-09-18 04:00:00 -0300",'
            '"gateway":"192.168.0.1","status":"up","latency_ms":1.0}\n',
            encoding="utf-8",
        )

        resultado = subprocess.run(
            ["bash", str(SCRIPT), "--report"],
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "OD_LOG_DIR": str(tmp_path)},
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert resultado.returncode == 0
        assert "Router UP: 1" in resultado.stdout


# ---------------------------------------------------------------------------
# Robustez do próprio script
# ---------------------------------------------------------------------------


class TestScript:
    def test_arquivo_existe_e_e_executavel_por_bash(self) -> None:
        assert SCRIPT.exists()
        assert subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True
        ).returncode == 0

    def test_nao_usa_set_e(self) -> None:
        """`set -e` foi a causa raiz do monitor cego — não pode voltar."""
        fonte = SCRIPT.read_text(encoding="utf-8")
        assert "set -euo pipefail" not in fonte
        assert "set -uo pipefail" in fonte

    def test_modo_desconhecido_cai_no_loop_continuo(self) -> None:
        # Guarda contra mudança acidental da interface: `--once` e `--report`
        # estão cobertos acima; aqui só garantimos que o script reconhece os
        # dois flags (o modo contínuo é infinito e não é executado em teste).
        fonte = SCRIPT.read_text(encoding="utf-8")
        assert '--report)' in fonte
        assert '--once)' in fonte

    def test_readme_documenta_o_historico(self) -> None:
        readme = REPO_ROOT / "tools" / "monitor" / "README.md"
        assert readme.exists()
        texto = readme.read_text(encoding="utf-8")
        assert "set -e" in texto
        assert "1086" in texto


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
