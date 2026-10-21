"""
OMEGA DRAKON * TESTS
Modulo: tests/test_network_watchdog.py
Descricao: Testes do Vigia da Rede (tools/monitor/network_watchdog.py) —
           funções puras com dados REAIS capturados em produção (21/10/2026:
           saída de `ip neigh`, linhas da grade do mapa de rede do Archer C6,
           log do roteador e journal do sshd) e ciclo completo em sandbox
           (rede injetável, log em tmp_path, sem rede externa).

           O vigia é a resposta ao pedido do dono: "o sistema consegue saber
           todos os dispositivos da rede e avisar se alguém tentou invadir?"
           — e "alerta primeiro" (o dono escolheu; o bloqueio é operador).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "monitor" / "network_watchdog.py"

sys.path.insert(0, str(REPO_ROOT / "tools" / "monitor"))

import network_watchdog as vw  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# Saída REAL de `ip neigh` neste servidor (21/10/2026) — com vizinhos LAN,
# pontes docker (172.x), IPv6 e o próprio roteador.
IP_NEIGH_REAL = """\
192.168.0.202 dev wlx000f0037acf0 lladdr 94:3a:91:53:e2:8e STALE
172.19.0.2 dev br-b7119289ffc4 lladdr a6:ba:7d:6e:02:73 DELAY
192.168.0.1 dev wlx000f0037acf0 lladdr 5c:62:8b:b7:0e:5c REACHABLE
192.168.0.111 dev wlx000f0037acf0 lladdr 20:57:9e:d6:d7:a3 REACHABLE
192.168.0.99 dev wlx000f0037acf0 lladdr aa:bb:cc:dd:ee:ff FAILED
192.168.0.136 dev wlx000f0037acf0 lladdr dc:54:d7:7b:25:cf STALE
2804:428:27d:8600:1887:4929:f680:6a7e dev wlx000f0037acf0 lladdr 42:70:6b:7d:7f:e9 router STALE
192.168.0.77 dev wlx000f0037acf0 FAILED
"""

# Linhas da grade "Clientes" do Archer C6 (formato real: MAC colado no IP).
LINHAS_CLIENTES_REAIS = [
    "DESKTOP-8EC1J05 | DESKTOP-8EC1J05 | 00-0F-00-37-AC-F0192.168.0.250 |"
    " DESKTOP-8EC1J0500-0F-00-37-AC-F0192.168.0.250 | 0.52Kbps5.1Kbps |",
    "Luz-Cozinha | Luz-Cozinha | 2C-F4-32-BF-0D-8E192.168.0.176 |"
    " Luz-Cozinha2C-F4-32-BF-0D-8E192.168.0.176 | 0Kbps0Kbps |",
    "Desconhecido | Desconhecido | AC-A7-04-F0-8F-88192.168.0.224 |"
    " DesconhecidoAC-A7-04-F0-8F-88192.168.0.224 | 0Kbps0Kbps |",
]


def _roda_sandbox(tmp_path: Path, **env_extra: str) -> subprocess.CompletedProcess:
    """Roda o vigia em sandbox: log/estado em tmp_path, sem rede externa."""
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "OD_LOG_DIR": str(tmp_path),
        "OD_VIGIA_RICH": "0",          # sem chromium nos testes
        "OD_VIGIA_OUI": "0",           # sem consulta externa de fabricante
        "HOME": str(tmp_path),
        **env_extra,
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--once"],
        capture_output=True, text=True, timeout=60, env=env,
    )


# ---------------------------------------------------------------------------
# normaliza_mac / prefixo_oui
# ---------------------------------------------------------------------------


class TestMac:
    def test_normaliza_colon(self) -> None:
        assert vw.normaliza_mac("94:3a:91:53:e2:8e") == "94:3A:91:53:E2:8E"

    def test_normaliza_hifen_e_colado(self) -> None:
        assert vw.normaliza_mac("00-0F-00-37-AC-F0") == "00:0F:00:37:AC:F0"

    def test_normaliza_invalido_devolve_intacto(self) -> None:
        assert vw.normaliza_mac("abc") == "ABC"

    def test_prefixo_oui(self) -> None:
        assert vw.prefixo_oui("AC:A7:04:F0:8F:88") == "ACA704"
        assert vw.prefixo_oui("00-0f-00-37-ac-f0") == "000F00"


# ---------------------------------------------------------------------------
# vizinhos_lan — com a saída real de `ip neigh`
# ---------------------------------------------------------------------------


class TestVizinhosLan:
    def test_so_lan_com_mac(self) -> None:
        vizinhos = vw.vizinhos_lan(IP_NEIGH_REAL)
        # LAN filtrada: .202, .1, .111, .136 (o FAILED .99 e o .77 sem mac caem)
        assert set(vizinhos) == {
            "94:3A:91:53:E2:8E", "5C:62:8B:B7:0E:5C",
            "20:57:9E:D6:D7:A3", "DC:54:D7:7B:25:CF",
        }
        assert vizinhos["94:3A:91:53:E2:8E"] == "192.168.0.202"

    def test_docker_e_ipv6_fora(self) -> None:
        vizinhos = vw.vizinhos_lan(IP_NEIGH_REAL)
        assert not any(ip.startswith("172.") for ip in vizinhos.values())

    def test_failed_excluido(self) -> None:
        assert "AA:BB:CC:DD:EE:FF" not in vw.vizinhos_lan(IP_NEIGH_REAL)

    def test_texto_vazio(self) -> None:
        assert vw.vizinhos_lan("") == {}


# ---------------------------------------------------------------------------
# classificar_novos
# ---------------------------------------------------------------------------


class TestClassificar:
    def test_tudo_novo_sem_inventario(self) -> None:
        novos, vistos = vw.classificar_novos(
            {"94:3A:91:53:E2:8E": "192.168.0.202"}, {}
        )
        assert len(novos) == 1 and vistos == []
        assert novos[0]["mac"] == "94:3A:91:53:E2:8E"

    def test_conhecido_vai_para_vistos(self) -> None:
        inventario = {"94:3A:91:53:E2:8E": {"conhecido": True}}
        novos, vistos = vw.classificar_novos(
            {"94:3A:91:53:E2:8E": "192.168.0.202"}, inventario
        )
        assert novos == [] and vistos == ["94:3A:91:53:E2:8E"]


# ---------------------------------------------------------------------------
# evento_seguranca — ruído real do roteador vs eventos de verdade
# ---------------------------------------------------------------------------


class TestEventosSeguranca:
    def test_dhcpv6_e_ruido_do_log_roteador(self) -> None:
        assert vw.evento_seguranca(
            "DHCPv6client: parse option 5 error.", "roteador") is None
        assert vw.evento_seguranca(
            "Auto update prepare to upgrade, user call download firmware "
            "service.", "roteador") is None
        assert vw.evento_seguranca("", "roteador") is None

    def test_login_ilegal_do_roteador(self) -> None:
        ev = vw.evento_seguranca(
            "illegal login attempt from 192.168.0.50.", "roteador")
        assert ev is not None and ev["origem"] == "roteador"
        assert "illegal" in ev["msg"]

    def test_ssid_bloqueado(self) -> None:
        ev = vw.evento_seguranca(
            "wireless client C4-82-E1-E5-C9-F1 blocked by access control.",
            "roteador")
        assert ev is not None

    def test_ssha_failed_password(self) -> None:
        ev = vw.evento_seguranca(
            "Failed password for invalid user admin from 192.168.0.50 port "
            "50000 ssh2", "sshd")
        assert ev is not None and ev["origem"] == "sshd"

    def test_ssh_ok_e_pam_nao_pegam(self) -> None:
        assert vw.evento_seguranca(
            "Accepted password for alex from 192.168.0.111 port 64417 ssh2",
            "sshd") is None
        assert vw.evento_seguranca(
            "pam_unix(sshd:session): session opened for user alex(uid=1000)",
            "sshd") is None


# ---------------------------------------------------------------------------
# parse_linhas_clientes — formato real da grade do Archer
# ---------------------------------------------------------------------------


class TestParseClientes:
    def test_extrai_nome_mac_ip(self) -> None:
        clientes = vw.parse_linhas_clientes(LINHAS_CLIENTES_REAIS)
        assert len(clientes) == 3
        assert clientes[0]["mac"] == "00:0F:00:37:AC:F0"
        assert clientes[0]["ip"] == "192.168.0.250"
        assert clientes[0]["nome"] == "DESKTOP-8EC1J05"

    def test_desconhecido_vira_nome_vazio(self) -> None:
        clientes = vw.parse_linhas_clientes(LINHAS_CLIENTES_REAIS)
        assert clientes[2]["mac"] == "AC:A7:04:F0:8F:88"
        assert clientes[2]["nome"] == ""

    def test_linha_sem_mac_ignorada(self) -> None:
        assert vw.parse_linhas_clientes(["sem mac aqui", ""]) == []


# ---------------------------------------------------------------------------
# fabricante_de — cache e falha nunca derrubam o ciclo
# ---------------------------------------------------------------------------


class TestFabricante:
    def test_cache_hit_sem_consulta(self) -> None:
        cache = {"ACA704": "Espressif Inc."}
        chamadas = []

        def consulta(_p: str) -> None:
            chamadas.append(_p)
            return None

        assert vw.fabricante_de("AC:A7:04:F0:8F:88", cache, consulta) == \
            "Espressif Inc."
        assert chamadas == []

    def test_cache_miss_consulta_e_guarda(self) -> None:
        cache: dict[str, str] = {}
        assert vw.fabricante_de(
            "AC:A7:04:F0:8F:88", cache, lambda p: "Espressif Inc.") == \
            "Espressif Inc."
        assert cache["ACA704"] == "Espressif Inc."

    def test_falha_de_rede_vira_desconhecido_e_cacheia(self) -> None:
        cache: dict[str, str] = {}

        def consulta(_p: str) -> None:
            raise OSError("sem internet")

        assert vw.fabricante_de("AA:BB:CC:00:11:22", cache, consulta) == \
            "desconhecido"
        assert cache["AABBCC"] == "desconhecido"

    def test_sem_consulta_none(self) -> None:
        assert vw.fabricante_de("AA:BB:CC:00:11:22", {}, None) == "desconhecido"


# ---------------------------------------------------------------------------
# rotacao do log
# ---------------------------------------------------------------------------


class TestRotacao:
    def test_log_grande_rotaciona(self, tmp_path: Path) -> None:
        log = tmp_path / "network_watchdog.log"
        log.write_text("x" * 2000)
        vw.rotaciona_log(log, max_bytes=1000)
        assert log.with_suffix(".log.1").exists()
        assert not log.exists()

    def test_log_pequeno_fica(self, tmp_path: Path) -> None:
        log = tmp_path / "network_watchdog.log"
        log.write_text("x" * 10)
        vw.rotaciona_log(log, max_bytes=1000)
        assert log.exists()


# ---------------------------------------------------------------------------
# Ciclo completo em sandbox (rede injetável, sem rede externa)
# ---------------------------------------------------------------------------


class TestCicloSandbox:
    REDE_TESTE = (
        '{"94:3A:91:53:E2:8E": "192.168.0.202",'
        ' "2C:F4:32:BF:0D:8E": "192.168.0.176"}'
    )

    def _estado(self, tmp_path: Path) -> dict:
        return json.loads(
            (tmp_path / "network_watchdog_estado.json").read_text("utf-8"))

    def _linhas(self, tmp_path: Path) -> list[dict]:
        return [
            json.loads(l) for l in
            (tmp_path / "network_watchdog.log").read_text("utf-8").splitlines()
        ]

    def test_ciclo_novo_dispositivo_fica_pendente(self, tmp_path: Path) -> None:
        proc = _roda_sandbox(
            tmp_path, OD_VIGIA_VIZINHOS_JSON=self.REDE_TESTE)
        assert proc.returncode == 0, proc.stderr
        estado = self._estado(tmp_path)
        assert len(estado["dispositivos"]) == 2
        assert len(estado["pendentes_novos"]) == 2
        tipos = [l["tipo"] for l in self._linhas(tmp_path)]
        assert "dispositivo_novo" in tipos and "estado" in tipos
        # último registro é sempre a linha de estado (contrato da sonda)
        assert self._linhas(tmp_path)[-1]["tipo"] == "estado"
        assert self._linhas(tmp_path)[-1]["pendentes_novos"]

    def test_segundo_ciclo_nao_repete_alarme(self, tmp_path: Path) -> None:
        _roda_sandbox(tmp_path, OD_VIGIA_VIZINHOS_JSON=self.REDE_TESTE)
        segunda = _roda_sandbox(tmp_path, OD_VIGIA_VIZINHOS_JSON=self.REDE_TESTE)
        assert segunda.returncode == 0
        estado = self._estado(tmp_path)
        # continua pendente (ninguém reconheceu) mas NAO duplica
        assert len(estado["pendentes_novos"]) == 2
        novos = [l for l in self._linhas(tmp_path)
                 if l["tipo"] == "dispositivo_novo"]
        assert len(novos) == 2  # só do primeiro ciclo

    def test_conhecer_limpa_pendencia(self, tmp_path: Path) -> None:
        _roda_sandbox(tmp_path, OD_VIGIA_VIZINHOS_JSON=self.REDE_TESTE)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--conhecer", "94:3A:91:53:E2:8E",
             "Echo-Sala"],
            capture_output=True, text=True, timeout=30,
            env={"PATH": "/usr/bin:/bin", "OD_LOG_DIR": str(tmp_path),
                 "HOME": str(tmp_path)},
        )
        assert proc.returncode == 0
        estado = self._estado(tmp_path)
        alvo = estado["dispositivos"]["94:3A:91:53:E2:8E"]
        assert alvo["conhecido"] is True and alvo["nome"] == "Echo-Sala"
        assert [p for p in estado["pendentes_novos"]
                if p["mac"] == "94:3A:91:53:E2:8E"] == []

    def test_seed_reconhece_tudo(self, tmp_path: Path) -> None:
        env = {"OD_VIGIA_VIZINHOS_JSON": self.REDE_TESTE}
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--seed"],
            capture_output=True, text=True, timeout=60,
            env={"PATH": "/usr/bin:/bin", "OD_LOG_DIR": str(tmp_path),
                 "OD_VIGIA_RICH": "0", "OD_VIGIA_OUI": "0",
                 "HOME": str(tmp_path), **env},
        )
        assert proc.returncode == 0, proc.stderr
        estado = self._estado(tmp_path)
        assert all(d["conhecido"] for d in estado["dispositivos"].values())
        assert estado["pendentes_novos"] == []

    def test_ack_seguranca(self, tmp_path: Path) -> None:
        _roda_sandbox(tmp_path, OD_VIGIA_VIZINHOS_JSON=self.REDE_TESTE)
        estado = self._estado(tmp_path)
        estado["pendentes_seguranca"] = [
            {"origem": "sshd", "msg": "Failed password ...", "ts_evento": "t"}]
        (tmp_path / "network_watchdog_estado.json").write_text(
            json.dumps(estado), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--ack-seguranca"],
            capture_output=True, text=True, timeout=30,
            env={"PATH": "/usr/bin:/bin", "OD_LOG_DIR": str(tmp_path),
                 "HOME": str(tmp_path)},
        )
        assert proc.returncode == 0
        assert self._estado(tmp_path)["pendentes_seguranca"] == []

    def test_report_roda(self, tmp_path: Path) -> None:
        _roda_sandbox(tmp_path, OD_VIGIA_VIZINHOS_JSON=self.REDE_TESTE)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--report"],
            capture_output=True, text=True, timeout=30,
            env={"PATH": "/usr/bin:/bin", "OD_LOG_DIR": str(tmp_path),
                 "HOME": str(tmp_path)},
        )
        assert proc.returncode == 0
        assert "Inventário" in proc.stdout
        assert "DESCONHECIDO" in proc.stdout

    def test_rede_fora_nao_derruba_o_ciclo(self, tmp_path: Path) -> None:
        """Rede injetada vazia (tudo caiu) → ciclo sai 0 e registra estado.

        Observação: a varredura real lê o `ip neigh` do kernel (estado do
        host), então este caso injeta o resultado diretamente — sem tocar
        na rede viva da produção.
        """
        proc = _roda_sandbox(tmp_path, OD_VIGIA_VIZINHOS_JSON="{}")
        assert proc.returncode == 0, proc.stderr
        linhas = self._linhas(tmp_path)
        assert linhas[-1]["tipo"] == "estado"
        assert linhas[-1]["ativos"] == 0
        assert linhas[-1]["pendentes_novos"] == []
