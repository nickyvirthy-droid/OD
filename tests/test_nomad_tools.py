"""
OMEGA DRAKON • TESTS
Módulo: tests/test_nomad_tools.py
Descrição: Testes das ferramentas do stack Nômade monitoradas pelo
           od-core (DECISÃO FINAL 12/10 — core/nomad_tools.py +
           sonda `tool:<nome>` no ProactiveNotifier + bloco no
           /dashboard/stats). Cobre: catálogo das 9 (portas do compose),
           sonda HTTP hermética (viva < 500, 5xx/erro = fora), cache TTL,
           contrato do HealthMonitor (nunca crítico), probe com servidor
           HTTP real em porta efêmera, anti-spam do notifier (emit_after_s
           120s + cooldown) e o gate OD_NOMAD_TOOLS=0 no launcher.
           Motivação registrada: Stirling PDF 1.917 restarts e Kiwix 763
           em crash loop sem ninguém receber alerta (12/10).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/nomad_tools.py · integrations/notifier.py (_check_tools)
  - runtime/launcher.py (register_nomad_health_checks)
  - docker/tools-compose.yaml (as 9 ferramentas)
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core.nomad_tools import (
    FERRAMENTAS_NOMAD,
    FerramentaNomad,
    NomadToolsMonitor,
    monitor_padrao,
    resetar_monitor,
)
from integrations.notifier import (
    SEVERITY_WARN,
    NotifierConfig,
    ProactiveNotifier,
    _check_tools,
)
from observability.health import (
    STATUS_DEGRADED,
    STATUS_UP,
    HealthMonitor,
)
from runtime import launcher


# ---------------------------------------------------------------------------
# Fixtures / utilitários
# ---------------------------------------------------------------------------

class _Clock:
    """Relógio determinístico (monotonic fake) — padrão do test_notifier."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def avanca(self, segundos: float) -> None:
        self.now += segundos


def _monitor_com_sonda(
    sonda, *, clock=None, ferramentas=FERRAMENTAS_NOMAD,
    cache_ttl_s: float = 10.0,
) -> NomadToolsMonitor:
    return NomadToolsMonitor(
        ferramentas=ferramentas,
        sonda=sonda,
        clock=clock or _Clock(),
        cache_ttl_s=cache_ttl_s,
    )


class _Handler200(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — nome do http.server
        corpo = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args) -> None:  # silencia o stderr do servidor
        pass


@pytest.fixture()
def servidor_http():
    """Servidor HTTP real em porta efêmera (127.0.0.1) — sobe e derruba."""
    srv = HTTPServer(("127.0.0.1", 0), _Handler200)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _porta_livre() -> int:
    """Porta efêmera que ACABOU de ser liberada (conexão recusada)."""
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return porta


# ---------------------------------------------------------------------------
# Catálogo — as 9 ferramentas da DECISÃO FINAL
# ---------------------------------------------------------------------------

class TestCatalogo:
    def test_tem_as_9_ferramentas(self) -> None:
        assert len(FERRAMENTAS_NOMAD) == 9
        nomes = {f.nome for f in FERRAMENTAS_NOMAD}
        assert nomes == {
            "kiwix", "cyberchef", "it-tools", "flatnotes", "stirling-pdf",
            "filebrowser", "calibre-web", "homebox", "vaultwarden",
        }

    def test_portas_distintas_e_do_compose(self) -> None:
        portas = [f.porta for f in FERRAMENTAS_NOMAD]
        assert len(set(portas)) == 9  # nenhuma colisão
        por_nome = {f.nome: f.porta for f in FERRAMENTAS_NOMAD}
        # Portas conferidas no docker inspect (bind 127.0.0.1) em 15/10.
        assert por_nome["kiwix"] == 8090
        assert por_nome["stirling-pdf"] == 8400
        assert por_nome["vaultwarden"] == 8480

    def test_url_e_nome_check(self) -> None:
        ferramenta = next(f for f in FERRAMENTAS_NOMAD if f.nome == "kiwix")
        assert ferramenta.url == "http://127.0.0.1:8090/"
        stirling = next(f for f in FERRAMENTAS_NOMAD if f.nome == "stirling-pdf")
        assert stirling.nome_check == "tool_stirling_pdf"

    def test_vaultwarden_sonda_no_alive(self) -> None:
        vw = next(f for f in FERRAMENTAS_NOMAD if f.nome == "vaultwarden")
        assert vw.caminho == "/alive"  # rota de health do Vaultwarden

    def test_dataclass_ferramenta_e_imutavel(self) -> None:
        ferramenta = FerramentaNomad("x", 1)
        with pytest.raises(AttributeError):
            ferramenta.porta = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Sondagem hermética — viva < 500, 5xx/erro = fora
# ---------------------------------------------------------------------------

class TestSondagem:
    def test_200_e_viva(self) -> None:
        monitor = _monitor_com_sonda(lambda h, p, c, t: 200)
        resultado = monitor.sondar("kiwix")
        assert resultado["ok"] is True
        assert resultado["status"] == "up"
        assert "kiwix ok (HTTP 200)" in resultado["detail"]

    @pytest.mark.parametrize("status", [302, 401, 403, 404])
    def test_status_de_auth_ou_redirect_e_vida(self, status: int) -> None:
        # Calibre Web responde 302 na raiz (redirect do login) e
        # ferramentas com auth respondem 401/403 — recusar seria alerta
        # falso eterno.
        monitor = _monitor_com_sonda(lambda h, p, c, t: status)
        assert monitor.sondar("calibre-web")["ok"] is True

    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_5xx_e_fora(self, status: int) -> None:
        monitor = _monitor_com_sonda(lambda h, p, c, t: status)
        resultado = monitor.sondar("kiwix")
        assert resultado["ok"] is False
        assert f"HTTP {status}" in resultado["detail"]

    def test_erro_de_rede_e_fora_com_detalhe(self) -> None:
        def recusa(host, porta, caminho, timeout):
            raise ConnectionRefusedError("conexão recusada")

        monitor = _monitor_com_sonda(recusa)
        resultado = monitor.sondar("homebox")
        assert resultado["ok"] is False
        assert resultado["status"] == "down"
        assert "homebox fora (ConnectionRefusedError" in resultado["detail"]
        assert "http://127.0.0.1:8470/" in resultado["detail"]

    def test_timeout_e_fora(self) -> None:
        def estoura(host, porta, caminho, timeout):
            raise TimeoutError("timed out")

        monitor = _monitor_com_sonda(estoura)
        assert monitor.sondar("kiwix")["ok"] is False

    def test_ferramenta_desconhecida_levanta_keyerror(self) -> None:
        monitor = _monitor_com_sonda(lambda h, p, c, t: 200)
        with pytest.raises(KeyError):
            monitor.sondar("nao-existe")

    def test_estado_cobre_as_9_em_ordem(self) -> None:
        monitor = _monitor_com_sonda(lambda h, p, c, t: 200)
        nomes = [r["nome"] for r in monitor.estado()]
        assert nomes == [f.nome for f in FERRAMENTAS_NOMAD]

    def test_resumo_conta_fora(self) -> None:
        def sonda(host, porta, caminho, timeout):
            return 503 if porta == 8090 else 200  # kiwix fora

        monitor = _monitor_com_sonda(sonda)
        resumo = monitor.resumo()
        assert resumo == {"total": 9, "up": 8, "fora": ["kiwix"]}


# ---------------------------------------------------------------------------
# Cache TTL — notifier e /health dividem a mesma sondagem na janela
# ---------------------------------------------------------------------------

class TestCache:
    def test_cache_evita_nova_sonda_na_janela(self) -> None:
        chamadas: list[int] = []

        def sonda(host, porta, caminho, timeout):
            chamadas.append(porta)
            return 200

        clock = _Clock()
        monitor = _monitor_com_sonda(sonda, clock=clock)
        monitor.sondar("kiwix")
        monitor.sondar("kiwix")
        assert chamadas == [8090]  # 2ª leitura veio do cache

    def test_cache_expira_e_ressonda(self) -> None:
        chamadas: list[int] = []

        def sonda(host, porta, caminho, timeout):
            chamadas.append(porta)
            return 200

        clock = _Clock()
        monitor = _monitor_com_sonda(sonda, clock=clock)
        monitor.sondar("kiwix")
        clock.avanca(11.0)  # > TTL 10s
        monitor.sondar("kiwix")
        assert chamadas == [8090, 8090]

    def test_cache_por_ferramenta_independente(self) -> None:
        monitor = _monitor_com_sonda(lambda h, p, c, t: 200)
        monitor.sondar("kiwix")
        monitor.sondar("cyberchef")  # não lê o cache do kiwix
        assert monitor.resumo()["up"] == 9

    def test_limpar_cache_ressonda(self) -> None:
        chamadas: list[int] = []

        def sonda(host, porta, caminho, timeout):
            chamadas.append(porta)
            return 200

        monitor = _monitor_com_sonda(sonda)
        monitor.sondar("kiwix")
        monitor.limpar_cache()
        monitor.sondar("kiwix")
        assert chamadas == [8090, 8090]


# ---------------------------------------------------------------------------
# Probe real — http.server em porta efêmera (rede de verdade, sem
# dependência do stack)
# ---------------------------------------------------------------------------

class TestSondaReal:
    def test_servidor_local_responde_viva(
        self, servidor_http: HTTPServer
    ) -> None:
        porta = servidor_http.server_address[1]
        monitor = NomadToolsMonitor(
            ferramentas=(FerramentaNomad("fake", porta, "/"),),
        )
        resultado = monitor.sondar("fake")
        assert resultado["ok"] is True
        assert "HTTP 200" in resultado["detail"]

    def test_porta_fechara_e_fora(self) -> None:
        monitor = NomadToolsMonitor(
            ferramentas=(FerramentaNomad("morto", _porta_livre(), "/"),),
            timeout_s=0.5,
        )
        resultado = monitor.sondar("morto")
        assert resultado["ok"] is False
        assert "fora (" in resultado["detail"]


# ---------------------------------------------------------------------------
# HealthMonitor — 9 checks não-críticos (degrada, nunca derruba)
# ---------------------------------------------------------------------------

class TestHealthMonitor:
    def test_registra_as_9_nao_criticas(self) -> None:
        monitor = _monitor_com_sonda(lambda h, p, c, t: 200)
        health = HealthMonitor()
        nomes = monitor.registrar_no_health(health)
        assert nomes == [f.nome_check for f in FERRAMENTAS_NOMAD]
        assert set(health.components) == {
            "tool_kiwix", "tool_cyberchef", "tool_it_tools",
            "tool_flatnotes", "tool_stirling_pdf", "tool_filebrowser",
            "tool_calibre_web", "tool_homebox", "tool_vaultwarden",
        }

    @pytest.mark.asyncio
    async def test_todas_up_agrega_up(self) -> None:
        monitor = _monitor_com_sonda(lambda h, p, c, t: 200)
        health = HealthMonitor()
        monitor.registrar_no_health(health)
        agregado = await health.health()
        assert agregado["status"] == STATUS_UP
        assert all(c["ok"] for c in agregado["checks"].values())

    @pytest.mark.asyncio
    async def test_uma_fora_degrada_e_aponta_a_ferramenta(self) -> None:
        def sonda(host, porta, caminho, timeout):
            return 503 if porta == 8400 else 200  # stirling-pdf fora

        monitor = _monitor_com_sonda(sonda)
        health = HealthMonitor()
        monitor.registrar_no_health(health)
        agregado = await health.health()
        # Não-crítico: degrada o /health em vez de derrubá-lo.
        assert agregado["status"] == STATUS_DEGRADED
        assert agregado["checks"]["tool_stirling_pdf"]["ok"] is False
        assert "HTTP 503" in agregado["checks"]["tool_stirling_pdf"]["detail"]
        assert agregado["checks"]["tool_kiwix"]["ok"] is True

    @pytest.mark.asyncio
    async def test_check_quebrado_nunca_derruba_o_monitor(self) -> None:
        def sonda(host, porta, caminho, timeout):
            raise RuntimeError("bug de sonda")

        monitor = _monitor_com_sonda(sonda)
        health = HealthMonitor()
        monitor.registrar_no_health(health)
        agregado = await health.health()
        assert agregado["status"] == STATUS_DEGRADED
        assert len(agregado["checks"]) == 9


# ---------------------------------------------------------------------------
# Notifier — alerta no Telegram com emit_after_s e anti-spam
# ---------------------------------------------------------------------------

class TestNotifierTools:
    def _notifier(self, monitor, clock) -> ProactiveNotifier:
        return ProactiveNotifier(
            None,
            config=NotifierConfig(default_cooldown_s=3600.0),
            checks=[_check_tools],  # só a sonda em teste (sem orchestrator)
            clock=clock,
            nomad_tools=monitor,
        )

    def test_check_tools_sem_monitor_e_vazio(self) -> None:
        notifier = ProactiveNotifier(None)
        assert _check_tools(notifier) == []

    def test_check_tools_devolve_as_9(self) -> None:
        monitor = _monitor_com_sonda(lambda h, p, c, t: 200)
        notifier = self._notifier(monitor, _Clock())
        resultados = _check_tools(notifier)
        assert len(resultados) == 9
        assert all(r.ok for r in resultados)
        assert all(r.key.startswith("tool:") for r in resultados)

    def test_check_tools_fora_e_warn_com_chave(self) -> None:
        def sonda(host, porta, caminho, timeout):
            raise ConnectionRefusedError("recusada")

        monitor = _monitor_com_sonda(sonda)
        notifier = self._notifier(monitor, _Clock())
        problemas = [r for r in _check_tools(notifier) if not r.ok]
        assert len(problemas) == 9
        assert problemas[0].key == "tool:kiwix"
        assert problemas[0].severity == SEVERITY_WARN
        assert problemas[0].emit_after_s == 120.0  # compose up não grita

    def test_default_checks_so_ganha_tools_com_monitor(self) -> None:
        sem = ProactiveNotifier(None)
        com = self._notifier(_monitor_com_sonda(lambda h, p, c, t: 200), _Clock())
        assert len(sem._default_checks()) == 6
        assert len(com._default_checks()) == 7  # + _check_tools

    @pytest.mark.asyncio
    async def test_alerta_so_apos_persistencia_de_120s(self) -> None:
        def sonda(host, porta, caminho, timeout):
            if porta == 8090:  # só o kiwix fora
                raise ConnectionRefusedError("recusada")
            return 200

        clock = _Clock()
        monitor = _monitor_com_sonda(sonda, clock=clock)
        notifier = self._notifier(monitor, clock)
        # 1º tick: problema registrado, mas abaixo do emit_after_s.
        assert await notifier.tick() == []
        # Passados 120s: vira alerta (uma vez só).
        clock.avanca(121.0)
        alertas = await notifier.tick()
        assert len(alertas) == 1
        assert alertas[0].key == "tool:kiwix"
        # Repetição no tick seguinte: anti-spam (cooldown 1h).
        clock.avanca(1.0)
        assert await notifier.tick() == []
        assert notifier.metrics.alerts_blocked >= 1

    @pytest.mark.asyncio
    async def test_ferramenta_volta_limpa_o_problema(self) -> None:
        estado = {"fora": True}

        def sonda(host, porta, caminho, timeout):
            if estado["fora"] and porta == 8090:
                raise ConnectionRefusedError("recusada")
            return 200

        clock = _Clock()
        monitor = _monitor_com_sonda(sonda, clock=clock)
        notifier = self._notifier(monitor, clock)
        await notifier.tick()
        clock.avanca(121.0)
        assert len(await notifier.tick()) == 1  # alerta emitido
        estado["fora"] = False
        monitor.limpar_cache()
        assert await notifier.tick() == []  # voltou: sem alerta
        assert monitor.resumo()["fora"] == []

    @pytest.mark.asyncio
    async def test_tick_com_todas_up_emite_nada(self) -> None:
        monitor = _monitor_com_sonda(lambda h, p, c, t: 200)
        notifier = self._notifier(monitor, _Clock())
        assert await notifier.tick() == []
        assert notifier.metrics.alerts_emitted == 0


# ---------------------------------------------------------------------------
# Launcher — wiring no /health e gate OD_NOMAD_TOOLS=0
# ---------------------------------------------------------------------------

class TestLauncherWiring:
    def test_registra_as_9_no_health_e_devolve_monitor(self) -> None:
        health = HealthMonitor()
        monitor = launcher.register_nomad_health_checks(health)
        assert isinstance(monitor, NomadToolsMonitor)
        assert "tool_kiwix" in health.components
        assert "tool_vaultwarden" in health.components

    def test_health_none_devolve_none(self) -> None:
        assert launcher.register_nomad_health_checks(None) is None

    def test_od_nomad_tools_0_desliga(self, monkeypatch) -> None:
        cache = dict(launcher._ENV_CACHE or {})
        cache["OD_NOMAD_TOOLS"] = "0"
        monkeypatch.setattr(launcher, "_ENV_CACHE", cache)
        health = HealthMonitor()
        assert launcher.register_nomad_health_checks(health) is None
        assert health.components == []  # nada registrado

    def test_monitor_padrao_e_singleton(self) -> None:
        resetar_monitor()
        try:
            primeiro = monitor_padrao()
            assert monitor_padrao() is primeiro
            assert len(primeiro.ferramentas) == 9
        finally:
            resetar_monitor()

    def test_build_notifier_carrega_a_sonda(self) -> None:
        monitor = _monitor_com_sonda(lambda h, p, c, t: 200)
        notifier = launcher.build_notifier(None, nomad_tools=monitor)
        try:
            assert notifier is not None
            assert notifier.nomad_tools is monitor
            assert len(notifier._default_checks()) == 7
        finally:
            notifier.stop()

    def test_build_notifier_sem_monitor_sem_sonda(self) -> None:
        notifier = launcher.build_notifier(None)
        try:
            assert notifier is not None
            assert notifier.nomad_tools is None
            assert len(notifier._default_checks()) == 6
        finally:
            notifier.stop()


# ---------------------------------------------------------------------------
# API — bloco nomad_tools no /dashboard/stats
# ---------------------------------------------------------------------------

@pytest.fixture()
def serve_api():
    """Sobe APIServer sob demanda (mesmo padrão do test_api.py)."""
    from integrations.api import APIServer

    servers = []

    def _start(orch, *, config=None):
        from integrations.api import APIConfig

        cfg = config or APIConfig(port=0, rate_limit_max=0)
        srv = APIServer(orch, config=cfg)
        srv.serve_background()
        servers.append(srv)
        return srv

    yield _start
    for srv in servers:
        try:
            srv.stop()
        except Exception:  # pragma: no cover — teardown defensivo
            pass


class TestAPIDashboardStats:
    def test_stats_sem_monitor_nao_traz_o_bloco(self, serve_api, tmp_path) -> None:
        from tests.test_api import _json_response, _request, make_orch

        orch = make_orch(tmp_path)
        srv = serve_api(orch)
        status, body, _ = _request(srv.bound_port, "GET", "/dashboard/stats")
        data = _json_response((status, body, _))
        assert "nomad_tools" not in data

    def test_stats_com_monitor_mostra_total_e_fora(self, serve_api, tmp_path) -> None:
        from tests.test_api import _json_response, _request, make_orch

        def sonda(host, porta, caminho, timeout):
            return 503 if porta == 8200 else 200  # flatnotes fora

        monitor = _monitor_com_sonda(sonda)
        from integrations.api import APIConfig

        orch = make_orch(tmp_path)
        cfg = APIConfig(port=0, rate_limit_max=0, nomad_tools=monitor)
        srv = serve_api(orch, config=cfg)
        status, body, _ = _request(srv.bound_port, "GET", "/dashboard/stats")
        data = _json_response((status, body, _))
        assert data["nomad_tools"] == {
            "total": 9, "up": 8, "fora": ["flatnotes"],
        }

    def test_painel_admin_traz_a_secao_nomad(self, serve_api, tmp_path) -> None:
        from tests.test_api import _request, make_orch

        orch = make_orch(tmp_path)
        srv = serve_api(orch)
        status, body, _ = _request(srv.bound_port, "GET", "/admin")
        assert status == 200
        assert b"nomadTools" in body
        assert "Stack Nômade".encode("utf-8") in body or \
            "Stack N\\u00f4made".encode() in body or b"Nomade" in body
