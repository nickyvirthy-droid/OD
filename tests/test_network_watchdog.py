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


# ---------------------------------------------------------------------------
# Em processo — o ciclo inteiro medido (sandbox roda em SUBPROCESSO e o
# coverage só mede o processo do pytest; sem isto o vigia fica "feito mas
# não testado" no gate: 39% em 21/10).
# ---------------------------------------------------------------------------


class _FakeRespostaUrl:
    """Context manager mínimo p/ urllib.request.urlopen nos testes."""

    def __init__(self, corpo: bytes):
        self._corpo = corpo

    def __enter__(self) -> "_FakeRespostaUrl":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._corpo


class TestVigiaEmProcesso:
    """Bordas injetadas: rede, chromium, journal, OUI e destinos de log."""

    @pytest.fixture()
    def vigia(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(vw, "LOG_DIR", tmp_path)
        monkeypatch.setattr(vw, "LOG_FILE", tmp_path / "network_watchdog.log")
        monkeypatch.setattr(vw, "ESTADO_FILE", tmp_path / "estado.json")
        monkeypatch.setattr(vw, "OUI_HABILITADO", False)   # sem rede externa
        monkeypatch.setattr(vw, "RICH_HABILITADO", False)  # sem chromium
        return vw

    @staticmethod
    def _linhas(tmp_path: Path) -> list[dict]:
        log = tmp_path / "network_watchdog.log"
        if not log.exists():
            return []
        return [json.loads(l) for l in log.read_text("utf-8").splitlines()]

    @staticmethod
    def _estado(tmp_path: Path) -> dict:
        return json.loads((tmp_path / "estado.json").read_text("utf-8"))

    # -- camada rápida ---------------------------------------------------

    def test_ciclo_em_processo_alarma_e_estado(
        self, vigia, tmp_path: Path, monkeypatch,
    ) -> None:
        monkeypatch.setenv(
            "OD_VIGIA_VIZINHOS_JSON",
            '{"94:3A:91:53:E2:8E": "192.168.0.202",'
            ' "2C:F4:32:BF:0D:8E": "192.168.0.176"}',
        )
        r = vigia.ciclo()
        assert r == {"ativos": 2, "novos": 2, "rico": False,
                     "pendentes_novos": 2, "pendentes_seguranca": 0}
        estado = self._estado(tmp_path)
        assert estado["ciclos"] == 1
        assert estado["ultima_varredura"] == {
            "ts": estado["ultima_varredura"]["ts"],
            "ativos": 2, "novos": 2, "rico": False,
        }
        tipos = [l["tipo"] for l in self._linhas(tmp_path)]
        assert tipos[-2:] == ["varredura", "estado"]
        # sem consulta OUI o fabricante é honesto, não inventado
        assert all(d["fabricante"] == "desconhecido"
                   for d in estado["dispositivos"].values())

    def test_ciclo_conhecido_atualiza_ip_e_ultima_vez(
        self, vigia, tmp_path: Path, monkeypatch,
    ) -> None:
        monkeypatch.setenv(
            "OD_VIGIA_VIZINHOS_JSON", '{"94:3A:91:53:E2:8E": "192.168.0.202"}')
        vigia.ciclo()
        monkeypatch.setenv(
            "OD_VIGIA_VIZINHOS_JSON", '{"94:3A:91:53:E2:8E": "192.168.0.210"}')
        r = vigia.ciclo()
        assert r["novos"] == 0 and r["pendentes_novos"] == 1  # segue pendente
        alvo = self._estado(tmp_path)["dispositivos"]["94:3A:91:53:E2:8E"]
        assert alvo["ip"] == "192.168.0.210" and alvo["ultima_vez"]

    def test_ciclo_passa_o_alcance_do_env_para_a_varredura(
        self, vigia, tmp_path: Path, monkeypatch,
    ) -> None:
        visto: dict = {}

        def varre(rede, alcance=None):
            visto["rede"], visto["alcance"] = rede, alcance
            return {}

        monkeypatch.setattr(vw, "varre_lan", varre)
        monkeypatch.setenv("OD_VIGIA_ALCANCE", "192.168.0.2,192.168.0.3")
        vigia.ciclo()
        assert visto["alcance"] == ["192.168.0.2", "192.168.0.3"]
        assert visto["rede"] == vw.REDE

    # -- camada rica -----------------------------------------------------

    def test_ciclo_rico_enriquece_ui_e_arma_seguranca(
        self, vigia, tmp_path: Path, monkeypatch,
    ) -> None:
        monkeypatch.setattr(vw, "RICH_HABILITADO", True)
        monkeypatch.setattr(vw, "RICH_A_CADA", 1)
        monkeypatch.setenv(
            "OD_VIGIA_VIZINHOS_JSON", '{"94:3A:91:53:E2:8E": "192.168.0.202"}')
        monkeypatch.setattr(vw, "rodar_rich", lambda senha, timeout=150: {
            "clientes": [
                {"mac": "94:3A:91:53:E2:8E", "nome": "Echo-Sala",
                 "ip": "192.168.0.202"},
                # dormindo: não respondeu ao ping, só aparece na UI
                # (o vigia_rich emite MAC já normalizado — parser único)
                {"mac": "AC:A7:04:F0:8F:88", "nome": "Celular",
                 "ip": "192.168.0.224"},
            ],
            "log_roteador": [
                "illegal login attempt from 192.168.0.50.",
                "Auto update prepare to upgrade, user call download "
                "firmware service.",          # ruído: NÃO vira evento
            ],
        })
        monkeypatch.setattr(
            vw, "journal_sshd",
            # stdout INTEIRO como o journalctl devolve (multi-linha): o
            # "Accepted" tem de ser ignorado e o "Failed" vira evento —
            # iterar a string crua seria iterar caracteres (o defeito).
            lambda desde: "Accepted password for alex from 192.168.0.111 "
                          "port 64417 ssh2\n"
                          "Failed password for root from 192.168.0.60 port "
                          "22 ssh2\n",
        )
        r = vigia.ciclo()
        assert r["rico"] is True and r["pendentes_novos"] == 2
        estado = self._estado(tmp_path)
        assert estado["dispositivos"]["94:3A:91:53:E2:8E"]["nome"] == \
            "Echo-Sala"
        assert estado["dispositivos"]["AC:A7:04:F0:8F:88"]["nota"] == \
            "visto só na UI do roteador"
        seg = {(p["origem"], p["msg"]) for p in estado["pendentes_seguranca"]}
        assert ("roteador", "illegal login attempt from 192.168.0.50.") in seg
        assert any(m == "Failed password for root from 192.168.0.60 port 22 "
                      "ssh2" for _, m in seg)
        assert all("Accepted" not in m and "firmware" not in m
                   for _, m in seg)
        assert estado["sshd_desde"]  # janela do próximo ciclo anda
        eventos = [l for l in self._linhas(tmp_path) if l["tipo"] == "seguranca"]
        assert len(eventos) == 2

    def test_ciclo_rico_nao_duplica_seguranca_ja_pendente(
        self, vigia, tmp_path: Path, monkeypatch,
    ) -> None:
        monkeypatch.setattr(vw, "RICH_HABILITADO", True)
        monkeypatch.setattr(vw, "RICH_A_CADA", 1)
        monkeypatch.setenv("OD_VIGIA_VIZINHOS_JSON", "{}")
        monkeypatch.setattr(vw, "rodar_rich", lambda senha, timeout=150: {
            "clientes": [],
            "log_roteador": ["illegal login attempt from 192.168.0.50."],
        })
        monkeypatch.setattr(vw, "journal_sshd", lambda desde: "")
        vigia.ciclo()
        vigia.ciclo()
        assert len(self._estado(tmp_path)["pendentes_seguranca"]) == 1

    def test_ciclo_rich_erro_registra_e_nao_derruba(
        self, vigia, tmp_path: Path, monkeypatch,
    ) -> None:
        monkeypatch.setattr(vw, "RICH_HABILITADO", True)
        monkeypatch.setattr(vw, "RICH_A_CADA", 1)
        monkeypatch.setenv("OD_VIGIA_VIZINHOS_JSON", "{}")
        monkeypatch.setattr(
            vw, "rodar_rich", lambda senha, timeout=150: {"_erro": "boom"})
        r = vigia.ciclo()
        assert r["rico"] is False
        erro = [l for l in self._linhas(tmp_path) if l["tipo"] == "rich_erro"]
        assert erro and erro[0]["detalhe"] == "boom"

    def test_ciclo_rich_forcado_no_seed(
        self, vigia, tmp_path: Path, monkeypatch,
    ) -> None:
        """Seed SEMPRE tenta a camada rica (primeira leitura da casa)."""
        monkeypatch.setattr(vw, "RICH_HABILITADO", True)
        monkeypatch.setenv("OD_VIGIA_VIZINHOS_JSON", "{}")
        monkeypatch.setattr(
            vw, "rodar_rich", lambda senha, timeout=150: {"clientes": []})
        monkeypatch.setattr(vw, "journal_sshd", lambda desde: "")
        r = vigia.ciclo(seed=True)
        assert r["rico"] is True
        assert self._estado(tmp_path)["rich_ultima"]

    def test_seed_zera_toda_pendencia(
        self, vigia, tmp_path: Path, monkeypatch,
    ) -> None:
        monkeypatch.setenv(
            "OD_VIGIA_VIZINHOS_JSON", '{"94:3A:91:53:E2:8E": "192.168.0.202"}')
        vigia.ciclo()
        estado = self._estado(tmp_path)
        estado["pendentes_seguranca"] = [
            {"origem": "sshd", "msg": "x", "ts_evento": "t"}]
        (tmp_path / "estado.json").write_text(json.dumps(estado), "utf-8")
        vigia.ciclo(seed=True)
        estado = self._estado(tmp_path)
        assert all(d["conhecido"] for d in estado["dispositivos"].values())
        assert estado["pendentes_novos"] == [] and \
            estado["pendentes_seguranca"] == []

    # -- I/O: estado, log, journal, OUI ----------------------------------

    def test_estado_corrompido_vira_padrao(self, vigia, tmp_path: Path) -> None:
        (tmp_path / "estado.json").write_text("{{{", encoding="utf-8")
        estado = vigia.carregar_estado()
        assert estado["dispositivos"] == {} and estado["ciclos"] == 0
        assert estado["vendor_cache"] == {}

    def test_salvar_estado_atomico_e_sem_lixeira(
        self, vigia, tmp_path: Path,
    ) -> None:
        vigia.salvar_estado({"ciclos": 7})
        assert self._estado(tmp_path)["ciclos"] == 7
        assert not list(tmp_path.glob("*.tmp"))

    def test_registrar_vazio_nao_cria_log(self, vigia, tmp_path: Path) -> None:
        vigia.registrar([])
        assert not (tmp_path / "network_watchdog.log").exists()

    def test_registrar_acrescenta_e_rotaciona(
        self, vigia, tmp_path: Path, monkeypatch,
    ) -> None:
        monkeypatch.setattr(vw, "MAX_LOG_BYTES", 10)
        vigia.registrar([{"tipo": "a"}, {"tipo": "b"}])
        vigia.registrar([{"tipo": "c"}])
        assert (tmp_path / "network_watchdog.log.1").exists()
        assert [l["tipo"] for l in self._linhas(tmp_path)] == ["c"]

    def test_rotacao_com_erro_de_so_nao_levanta(
        self, vigia, tmp_path: Path, monkeypatch,
    ) -> None:
        log = tmp_path / "log.txt"
        log.write_text("x" * 50)
        monkeypatch.setattr(
            Path, "rename", lambda *a, **k: (_ for _ in ()).throw(OSError()))
        vigia.rotaciona_log(log, 10)   # não pode levantar

    def test_journal_sshd_devolve_o_stdout(self, monkeypatch) -> None:
        class _Proc:
            stdout = "Failed password for admin from 10.0.0.1 port 1 ssh2"

        monkeypatch.setattr(vw.subprocess, "run", lambda *a, **k: _Proc())
        assert "Failed password" in vw.journal_sshd("2026-10-21 00:00:00")

    def test_journal_sshd_falha_devolve_vazio(self, monkeypatch) -> None:
        def quebra(*a, **k):
            raise OSError("sem journalctl")
        monkeypatch.setattr(vw.subprocess, "run", quebra)
        assert vw.journal_sshd("2026-10-21 00:00:00") == ""

    def test_varre_lan_pinga_o_alcance_e_lê_o_kernel(self, monkeypatch) -> None:
        chamados: list[list[str]] = []

        class _Proc:
            stdout = IP_NEIGH_REAL

        def falso_run(cmd, **kwargs):
            chamados.append(list(cmd))
            return _Proc()

        monkeypatch.setattr(vw.subprocess, "run", falso_run)
        vizinhos = vw.varre_lan("192.168.0.", ["192.168.0.2", "192.168.0.3"])
        pings = [c for c in chamados if c[0] == "ping"]
        assert sorted(c[-1] for c in pings) == ["192.168.0.2", "192.168.0.3"]
        assert chamados[-1][:2] == ["ip", "neigh"]
        assert vizinhos["94:3A:91:53:E2:8E"] == "192.168.0.202"

    def test_varre_lan_sem_ip_neigh_devolve_vazio(self, monkeypatch) -> None:
        def falso_run(cmd, **kwargs):
            if cmd[0] == "ip":
                raise OSError("sem ip neigh")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        monkeypatch.setattr(vw.subprocess, "run", falso_run)
        assert vw.varre_lan("192.168.0.", ["192.168.0.2"]) == {}

    def test_oui_encontra_e_nao_encontra(self, monkeypatch) -> None:
        monkeypatch.setattr(
            vw.urllib.request, "urlopen",
            lambda url, timeout: _FakeRespostaUrl(
                b'{"found": true, "company": "  TP-Link  "}'))
        assert vw.consulta_oui_maclookup("000F00") == "TP-Link"
        monkeypatch.setattr(
            vw.urllib.request, "urlopen",
            lambda url, timeout: _FakeRespostaUrl(b'{"found": false}'))
        assert vw.consulta_oui_maclookup("FFFFFF") is None
        monkeypatch.setattr(
            vw.urllib.request, "urlopen",
            lambda url, timeout: _FakeRespostaUrl(
                b'{"found": true, "company": "  "}'))
        assert vw.consulta_oui_maclookup("FFFFFF") is None

    # -- camada rica: o executor -----------------------------------------

    def test_rodar_rich_sem_venv_ou_sem_senha_e_none(self, tmp_path: Path,
                                                     monkeypatch) -> None:
        monkeypatch.setattr(vw, "VENV_PY", str(tmp_path / "nao_existe"))
        assert vw.rodar_rich("senha") is None
        monkeypatch.setattr(vw, "VENV_PY", sys.executable)  # venv "existe"
        assert vw.rodar_rich("") is None

    def test_rodar_rich_saida_nao_zero_vira_erro(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        venv = tmp_path / "python"
        venv.write_text("x")
        monkeypatch.setattr(vw, "VENV_PY", str(venv))

        class _Proc:
            returncode = 1
            stderr = "Traceback: chromium caiu"
            stdout = ""

        monkeypatch.setattr(vw.subprocess, "run", lambda *a, **k: _Proc())
        assert vw.rodar_rich("senha")["_erro"] == "Traceback: chromium caiu"

    def test_rodar_rich_json_quebrado_vira_erro(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        venv = tmp_path / "python"
        venv.write_text("x")
        monkeypatch.setattr(vw, "VENV_PY", str(venv))

        class _Proc:
            returncode = 0
            stderr = ""
            stdout = "não é json"

        monkeypatch.setattr(vw.subprocess, "run", lambda *a, **k: _Proc())
        assert "_erro" in vw.rodar_rich("senha")

    def test_rodar_rich_sucesso_devolve_o_json(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        venv = tmp_path / "python"
        venv.write_text("x")
        monkeypatch.setattr(vw, "VENV_PY", str(venv))
        capturado: dict = {}

        class _Proc:
            returncode = 0
            stderr = ""
            stdout = json.dumps({"clientes": [], "log_roteador": []})

        def falso_run(cmd, **kwargs):
            capturado["env"] = kwargs.get("env", {})
            return _Proc()

        monkeypatch.setattr(vw.subprocess, "run", falso_run)
        assert vw.rodar_rich("s3nh4") == {"clientes": [], "log_roteador": []}
        assert capturado["env"]["ROUTER_PASS"] == "s3nh4"

    # -- modos de operador (em processo) ---------------------------------

    def test_conhecer_sem_nome_e_com_nome(self, vigia, tmp_path: Path,
                                         monkeypatch, capsys) -> None:
        monkeypatch.setenv(
            "OD_VIGIA_VIZINHOS_JSON", '{"94:3A:91:53:E2:8E": "192.168.0.202"}')
        vigia.ciclo()
        vigia.conhecer("94-3a-91-53-e2-8e")
        estado = self._estado(tmp_path)
        assert estado["dispositivos"]["94:3A:91:53:E2:8E"]["conhecido"] is True
        assert "reconhecido" in capsys.readouterr().out
        vigia.conhecer("94:3A:91:53:E2:8E", "Echo Sala")
        assert self._estado(tmp_path)["dispositivos"][
            "94:3A:91:53:E2:8E"]["nome"] == "Echo Sala"

    def test_conhecer_fora_do_inventario_avisa_e_nao_grava(
        self, vigia, tmp_path: Path, capsys,
    ) -> None:
        vigia.conhecer("AA:BB:CC:DD:EE:FF")
        assert "não está no inventário" in capsys.readouterr().out
        assert not (tmp_path / "estado.json").exists()

    def test_ack_seguranca_imprime_quantos(
        self, vigia, tmp_path: Path, capsys,
    ) -> None:
        vigia.salvar_estado({"pendentes_seguranca": [{"origem": "sshd"}]})
        vigia.ack_seguranca()
        assert "1 evento(s)" in capsys.readouterr().out
        assert self._estado(tmp_path)["pendentes_seguranca"] == []

    def test_report_lista_pendencias_e_seguranca(
        self, vigia, tmp_path: Path, capsys,
    ) -> None:
        vigia.salvar_estado({
            "ciclos": 3,
            "dispositivos": {
                "AC:A7:04:F0:8F:88": {
                    "ip": "192.168.0.224", "nome": "", "conhecido": False,
                    "fabricante": "Espressif Inc."},
                "94:3A:91:53:E2:8E": {
                    "ip": "192.168.0.202", "nome": "Echo-Sala",
                    "conhecido": True, "fabricante": "Amazon"},
            },
            "pendentes_novos": [
                {"mac": "AC:A7:04:F0:8F:88", "fabricante": "Espressif Inc.",
                 "ip": "192.168.0.224", "desde": "2026-10-21T10:00:00"}],
            "pendentes_seguranca": [
                {"origem": "roteador", "msg": "illegal login attempt"}],
        })
        vigia.report()
        saida = capsys.readouterr().out
        assert "Inventário: 2 dispositivo(s)" in saida
        assert "DESCONHECIDO" in saida and "Echo-Sala" in saida
        assert "1 dispositivo(s) novo(s)" in saida
        assert "SEGURANÇA [roteador]" in saida

    def test_bloquear_sem_senha_retorna_2(
        self, monkeypatch, capsys,
    ) -> None:
        monkeypatch.delenv("ROUTER_ADMIN_PASSWORD", raising=False)
        assert vw.main(["--bloquear", "AA:BB:CC:DD:EE:FF"]) == 2
        assert "FALHA" in capsys.readouterr().out

    def test_bloquear_operador_manda_o_mac_normalizado(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        venv = tmp_path / "python"
        venv.write_text("x")
        monkeypatch.setattr(vw, "VENV_PY", str(venv))
        monkeypatch.setenv("ROUTER_ADMIN_PASSWORD", "s3nh4")
        capturado: dict = {}

        class _Proc:
            returncode = 0
            stdout = "AA:BB:CC:DD:EE:FF bloqueado; releitura: 1 entrada."
            stderr = ""

        def falso_run(cmd, **kwargs):
            capturado["cmd"] = cmd
            capturado["env"] = kwargs.get("env", {})
            return _Proc()

        monkeypatch.setattr(vw.subprocess, "run", falso_run)
        assert vw.main(["--bloquear", "aa-bb-cc-dd-ee-ff"]) == 0
        assert capturado["cmd"][-1] == "AA:BB:CC:DD:EE:FF"
        assert capturado["env"]["ROUTER_PASS"] == "s3nh4"

    def test_main_once_devolve_o_json_do_ciclo(
        self, vigia, tmp_path: Path, monkeypatch, capsys,
    ) -> None:
        monkeypatch.setattr(
            vw, "ciclo", lambda seed=False: {"ativos": 1, "novos": 0})
        assert vw.main(["--once"]) == 0
        assert json.loads(capsys.readouterr().out) == {
            "ativos": 1, "novos": 0}

    def test_main_ciclo_excecao_sai_zero_e_registra(
        self, vigia, tmp_path: Path, monkeypatch,
    ) -> None:
        def explode(**kwargs):
            raise RuntimeError("boom")
        monkeypatch.setattr(vw, "ciclo", explode)
        assert vw.main([]) == 0                      # monitor sobrevive
        ultimo = self._linhas(tmp_path)[-1]
        assert ultimo["tipo"] == "ciclo_erro" and "boom" in ultimo["detalhe"]

    def test_main_conhecer_e_ack_sabem_os_dois_args(
        self, vigia, tmp_path: Path, monkeypatch,
    ) -> None:
        monkeypatch.setenv(
            "OD_VIGIA_VIZINHOS_JSON", '{"94:3A:91:53:E2:8E": "192.168.0.202"}')
        vigia.ciclo()
        assert vw.main(["--conhecer", "94:3A:91:53:E2:8E", "Echo"]) == 0
        assert vw.main(["--ack-seguranca"]) == 0
        assert vw.main(["--report"]) == 0

    def test_main_seed_passa_seed_ao_ciclo(
        self, vigia, tmp_path: Path, monkeypatch, capsys,
    ) -> None:
        visto: dict = {}
        monkeypatch.setattr(
            vw, "ciclo", lambda seed=False: visto.update(seed=seed) or {})
        assert vw.main(["--seed"]) == 0 and visto["seed"] is True
