"""
OMEGA DRAKON • TESTS
Módulo: tests/test_capabilities.py
Descrição: Testes do manifesto de capacidades (core/capabilities.py) —
           inventário estruturado do sistema consultável por CLI
           (launcher capabilities), API (GET /capabilities) e bot
           (/capacidades). Verifica integridade do manifesto (contagens,
           status, categorias, origem/fase/caminho), o resumo legível e a
           exposição via API e Telegram.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/capabilities.py (manifesto)
  - ROADMAP_ABSORCAO.md (37/37 capacidades)
  - docs/CAPACIDADES.md
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.capabilities import (
    ACTIVE,
    AVAILABLE,
    DORMANT,
    OD_VERSION,
    PARTIAL,
    CAPABILITIES,
    capabilities_manifest,
    render_json,
    render_text,
)
from core.orchestrator import Orchestrator, RecordingProvider
from integrations.api import APIConfig, APIServer
from integrations.telegram.commands import (
    build_default_commands,
)
from integrations.telegram.bot import TelegramBot
from integrations.telegram.transport import InMemoryTransport


# ---------------------------------------------------------------------------
# Manifesto — integridade
# ---------------------------------------------------------------------------

class TestCapabilitiesManifest:
    """Integridade estrutural do manifesto."""

    def test_capabilities_list_shape(self) -> None:
        """Toda capacidade tem os campos obrigatórios e status válido."""
        required = {"id", "name", "category", "description",
                    "source", "phase", "status", "path"}
        valid_statuses = {ACTIVE, AVAILABLE, PARTIAL, DORMANT}
        ids = set()
        for cap in CAPABILITIES:
            assert required <= set(cap), f"faltam campos em {cap.get('id')}"
            assert cap["status"] in valid_statuses, cap["id"]
            assert cap["category"] in {
                "core", "memory", "orchestration", "execution",
                "integrations", "sensorial", "observability", "runtime",
            }, cap["id"]
            assert cap["id"] not in ids, f"id duplicado: {cap['id']}"
            ids.add(cap["id"])

    def test_manifest_counts(self) -> None:
        """Contagens internas coerentes: by_status + by_category == total."""
        m = capabilities_manifest()
        counts = m["counts"]
        assert counts["capabilities"] == len(CAPABILITIES)
        assert sum(counts["by_status"].values()) == counts["capabilities"]
        assert sum(counts["by_category"].values()) == counts["capabilities"]
        # 37 capacidades do roadmap estão inventariadas (mínimo realista)
        assert counts["capabilities"] >= 37
        # catálogo de actions
        assert counts["actions"] == 57
        assert m["actions"]["count"] == 57

    def test_manifest_metadata(self) -> None:
        """Metadados: sistema, versão e timestamp ISO."""
        m = capabilities_manifest()
        assert m["system"] == "Omega Drakon"
        assert m["version"] == OD_VERSION
        assert "T" in m["generated_at"]  # timestamp ISO

    def test_manifest_roadmap_e_auto_recovery(self) -> None:
        """Roadmap 37/37 e o loop de auto-recuperação FECHADO (v0.27.4)."""
        m = capabilities_manifest()
        assert m["roadmap"]["capacities"] == "37/37"
        assert m["auto_recovery"]["loop_fechado"] is True
        assert m["dormant"] == []
        # Componentes do loop agora ativos
        status = {c["id"]: c["status"] for c in m["capabilities"]}
        for cap_id in ("self-repair", "perception", "auto-extension",
                       "notifier", "recovery-loop"):
            assert status[cap_id] == ACTIVE, cap_id

    def test_render_text_resumo(self) -> None:
        """Resumo legível cobre as contagens principais."""
        text = render_text()
        assert "OMEGA DRAKON — Capacidades" in text
        assert "57 actions" in text
        assert OD_VERSION in text
        assert "dormente" in text  # status dormantes visíveis

    def test_render_json_serializable(self) -> None:
        """render_json produz JSON válido com o manifesto completo."""
        data = json.loads(render_json())
        assert data["counts"]["actions"] == 57
        assert len(data["capabilities"]) == len(CAPABILITIES)


# ---------------------------------------------------------------------------
# Exposição via API REST (GET /capabilities)
# ---------------------------------------------------------------------------

def _request(port, method, path, api_key=None):
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{port}{path}"
    request = urllib.request.Request(url, method=method)
    if api_key:
        request.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


class TestCapabilitiesAPI:
    """GET /capabilities na API REST."""

    @pytest.fixture()
    def server(self):
        api = APIServer(
            Orchestrator(providers=[RecordingProvider("echo", reply="ok")]),
            config=APIConfig(api_key="chave-teste", port=0),
        )
        api.serve_background()
        yield api
        api.stop()

    def test_capabilities_requires_key(self, server) -> None:
        """Sem X-API-Key → 401."""
        status, _, _ = _request(server.bound_port, "GET", "/capabilities")
        assert status == 401

    def test_capabilities_returns_manifest(self, server) -> None:
        """Com chave → 200 + manifesto JSON com contagens reais."""
        status, body, _ = _request(
            server.bound_port, "GET", "/capabilities", api_key="chave-teste"
        )
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert data["system"] == "Omega Drakon"
        assert data["version"] == OD_VERSION
        assert data["counts"]["actions"] == 57
        assert len(data["capabilities"]) == len(CAPABILITIES)
        assert data["auto_recovery"]["loop_fechado"] is True


# ---------------------------------------------------------------------------
# Exposição via Telegram (/capacidades)
# ---------------------------------------------------------------------------

class TestCapabilitiesTelegram:
    """Comando /capacidades (admin) reporta o manifesto."""

    def test_command_registered(self) -> None:
        """build_default_commands inclui /capacidades (admin)."""
        commands = build_default_commands()
        by_name = {c.name: c for c in commands}
        assert "capacidades" in by_name
        assert by_name["capacidades"].admin_only is True

    @pytest.mark.asyncio
    async def test_capacidades_reply(self) -> None:
        """Admin recebe o resumo do manifesto via /capacidades."""
        transport = InMemoryTransport()
        bot = TelegramBot(transport, None, admin_ids={1})
        transport.add_message(1, "/capacidades", user_id=1)
        await bot.run(interval=0.01, max_updates=1)
        text = transport.sent_texts[-1]
        assert "OMEGA DRAKON — Capacidades" in text
        assert "57 actions" in text
        bot.close()

    @pytest.mark.asyncio
    async def test_capacidades_admin_gate(self) -> None:
        """Usuário não-admin é bloqueado."""
        transport = InMemoryTransport()
        bot = TelegramBot(transport, None, admin_ids={1})
        transport.add_message(1, "/capacidades", user_id=2)
        await bot.run(interval=0.01, max_updates=1)
        text = transport.sent_texts[-1]
        assert "⛔" in text
        assert bot.metrics.errors == 1
        bot.close()