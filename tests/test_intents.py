"""
OMEGA DRAKON • TESTS
Módulo: tests/test_intents.py
Descrição: Testes do FAST PATH determinístico (core/intents.py, v0.27.5) —
           detecção de intenções operacionais (rede/processos/memória/cpu/
           disco/uptime/sistema), matemática básica segura (ast), formatação
           de resultados e a integração da etapa 3.5 no pipeline do
           Orchestrator (resposta SEM LLM quando o ActionRegistry está
           conectado; fallback para LLM nos demais casos).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/intents.py (detect_action_intent, safe_math, format_intent_result)
  - core/orchestrator.py (etapa 3.5 — action_intents)
  - tools/actions/actions.py (network_hosts e demais actions de leitura)
"""

from __future__ import annotations

import pytest

from core.intents import (
    FASTPATH_ACTIONS,
    detect_action_intent,
    format_intent_result,
    safe_math,
)
from core.orchestrator import Orchestrator, StaticProvider
from core.security import SecurityManager
from tools.actions import build_registry

# Amostra da tabela ARP do kernel (cabeçalho + 3 vizinhos).
ARP_SAMPLE = (
    "IP address       HW type     Flags       HW address            Mask     Device\n"
    "192.168.0.1      0x1         0x2         00:11:22:33:44:55     *        enp2s0\n"
    "192.168.0.20     0x1         0x2         aa:bb:cc:dd:ee:ff     *        enp2s0\n"
    "192.168.0.99     0x1         0x0         11:22:33:44:55:66     *        wlx1\n"
    "192.168.0.200    0x1         0x2         00:00:00:00:00:00     *        enp2s0\n"
)


# ---------------------------------------------------------------------------
# Detecção de intenções
# ---------------------------------------------------------------------------

class TestDetectActionIntent:
    """Mapeamento PT-BR de perguntas operacionais → actions de leitura."""

    @pytest.mark.parametrize("text", [
        "quantas pessoas estão conectadas na rede?",
        "quantos dispositivos tem na rede local",
        "quem está conectado na wifi?",
        "quais equipamentos estão na rede?",
        "quantos pcs estão conectados na lan",
        "quantas máquinas estão na rede agora",
    ])
    def test_rede_detecta(self, text: str) -> None:
        assert detect_action_intent(text) == ("network_hosts", {})

    @pytest.mark.parametrize("text", [
        "me conta uma piada sobre redes",
        "como funciona a rede neural?",
        "qual o melhor roteador do mercado",
    ])
    def test_rede_nao_confunde(self, text: str) -> None:
        assert detect_action_intent(text) is None

    def test_processos(self) -> None:
        assert detect_action_intent("quantos processos estão rodando?") == (
            "process_list", {}
        )
        assert detect_action_intent("lista os processos ativos") == (
            "process_list", {}
        )

    def test_memoria(self) -> None:
        assert detect_action_intent("quanta memória está em uso?") == (
            "memory_usage", {}
        )
        assert detect_action_intent("como está a RAM do servidor?") == (
            "memory_usage", {}
        )

    def test_cpu(self) -> None:
        assert detect_action_intent("quanto está a carga da CPU?") == (
            "cpu_info", {}
        )
        assert detect_action_intent("como está o processador?") == (
            "cpu_info", {}
        )

    def test_disco(self) -> None:
        assert detect_action_intent("quanto de disco está livre?") == (
            "disk_usage", {"path": "/"}
        )
        assert detect_action_intent("como está o espaço do HD?") == (
            "disk_usage", {"path": "/"}
        )

    def test_uptime(self) -> None:
        assert detect_action_intent("há quanto tempo o sistema está ligado?") == (
            "uptime", {}
        )
        assert detect_action_intent("uptime do servidor") == ("uptime", {})

    def test_sistema(self) -> None:
        assert detect_action_intent("informações sobre o sistema") == (
            "system_info", {}
        )
        assert detect_action_intent("o que essa máquina tem?") == (
            "system_info", {}
        )

    def test_vazio_e_nao_intencao(self) -> None:
        assert detect_action_intent("") is None
        assert detect_action_intent("   ") is None
        assert detect_action_intent("qual a capital do Brasil?") is None
        assert detect_action_intent("me escreva um poema") is None

    def test_allowlist_so_leitura(self) -> None:
        """Fast path só contém actions de LEITURA — nenhuma destrutiva."""
        assert "filesystem_write" not in FASTPATH_ACTIONS
        assert "filesystem_delete" not in FASTPATH_ACTIONS
        assert "process_kill" not in FASTPATH_ACTIONS
        assert "git_push" not in FASTPATH_ACTIONS
        assert "database_query" not in FASTPATH_ACTIONS


# ---------------------------------------------------------------------------
# Matemática segura
# ---------------------------------------------------------------------------

class TestSafeMath:
    """'quanto é X' avaliado com nós numéricos apenas (ast)."""

    @pytest.mark.parametrize("text,expected", [
        ("quanto é 2+2", "2+2 = 4"),
        ("quanto é 2+2*3?", "2+2*3 = 8"),
        ("quanto é 10/4", "10/4 = 2.5"),
        ("quanto é 7 % 3", "7 % 3 = 1"),
        ("quanto é 2**10", "2**10 = 1024"),
        ("quanto é (2+3)*4", "(2+3)*4 = 20"),
        ("quanto é 1,5 + 2,5", "1.5 + 2.5 = 4"),
    ])
    def test_math_ok(self, text: str, expected: str) -> None:
        assert safe_math(text) == expected

    @pytest.mark.parametrize("text", [
        "quanto é __import__('os').system('x')",
        "quanto é open('/etc/passwd')",
        "quanto é [1,2,3]",
        "quanto é 'a' * 3",
        "quanto é x + 1",
    ])
    def test_math_inseguro_rejeitado(self, text: str) -> None:
        assert safe_math(text) is None

    def test_nao_casa(self) -> None:
        assert safe_math("qual o sentido da vida?") is None
        assert safe_math("") is None

    def test_expressao_longa_rejeitada(self) -> None:
        """Expressões >120 chars saem (defesa contra abuso de CPU)."""
        assert safe_math("quanto é " + "2" * 121) is None

    def test_erro_aritmetico_retorna_none(self) -> None:
        """Divisão por zero NUNCA estoura — devolve None."""
        assert safe_math("quanto é 1/0") is None


# ---------------------------------------------------------------------------
# Formatação de resultados
# ---------------------------------------------------------------------------

class TestFormatIntentResult:
    """Respostas PT-BR curtas a partir dos dados das actions."""

    def test_network_hosts_com_hosts(self) -> None:
        data = {
            "ok": True,
            "count": 2,
            "hosts": [
                {"ip": "192.168.0.1", "mac": "00:11:22:33:44:55",
                 "interface": "enp2s0", "state": "reachable"},
                {"ip": "192.168.0.20", "mac": "aa:bb:cc:dd:ee:ff",
                 "interface": "enp2s0", "state": "stale"},
            ],
        }
        text = format_intent_result("network_hosts", data)
        assert text is not None
        assert "2 dispositivo(s)" in text
        assert "192.168.0.1" in text
        assert "00:11:22:33:44:55" in text

    def test_network_hosts_vazio(self) -> None:
        text = format_intent_result(
            "network_hosts", {"ok": True, "count": 0, "hosts": []}
        )
        assert text is not None
        assert "Nenhum dispositivo" in text

    def test_process_list(self) -> None:
        text = format_intent_result(
            "process_list", {"ok": True, "count": 42, "processes": []}
        )
        assert text == "📊 42 processos ativos no sistema."

    def test_memory_usage(self) -> None:
        text = format_intent_result("memory_usage", {
            "ok": True, "percent": 42.5, "used": 8 * 1024 ** 3,
            "total": 16 * 1024 ** 3, "swap_percent": 0.0,
        })
        assert text is not None
        assert "42.5%" in text and "8.0 GB de 16.0 GB" in text

    def test_network_hosts_mais_de_dez_trunca(self) -> None:
        """>10 vizinhos: lista até 10 + linha '... e mais N'."""
        hosts = [
            {"ip": f"192.168.0.{i}", "mac": f"00:11:22:33:44:{i:02x}",
             "interface": "enp2s0", "state": "reachable"}
            for i in range(1, 12)
        ]
        text = format_intent_result(
            "network_hosts", {"ok": True, "count": 11, "hosts": hosts}
        )
        assert text is not None
        assert "11 dispositivo(s)" in text
        assert text.count("192.168.0.") == 10
        assert "... e mais 1" in text

    def test_cpu_info(self) -> None:
        text = format_intent_result("cpu_info", {
            "ok": True, "cores": 8, "load1": 0.42,
            "model": "AMD Ryzen 7 5700G",
        })
        assert text == "⚙️ CPU: 8 núcleos · load 0.42 · AMD Ryzen 7 5700G"

    def test_cpu_info_modelo_longo_trunca(self) -> None:
        """Modelo >40 chars é truncado com '…'."""
        text = format_intent_result("cpu_info", {
            "ok": True, "cores": 4, "load1": 0.1,
            "model": "M" * 60,
        })
        assert text is not None
        assert "M" * 40 + "…" in text
        assert "M" * 41 not in text

    def test_disk_usage(self) -> None:
        text = format_intent_result("disk_usage", {
            "ok": True, "percent": 63.2, "free": 512 * 1024 ** 3,
            "total": 1024 * 1024 ** 3, "path": "/",
        })
        assert text == "💾 Disco /: 63.2% usado · 512.0 GB livres de 1024.0 GB"

    def test_uptime(self) -> None:
        text = format_intent_result("uptime", {
            "ok": True, "days": 3.4, "seconds": 294_000,
        })
        assert text is not None
        assert "3.4 dia(s)" in text and "294000 s" in text

    def test_system_info(self) -> None:
        text = format_intent_result("system_info", {
            "ok": True, "system": "Linux", "release": "6.8.0",
            "node": "nicky-server", "cores": 8, "python": "3.12.3",
        })
        assert text == ("🖥️ Linux 6.8.0 (nicky-server) · 8 núcleos · "
                        "Python 3.12.3")

    def test_fallback_generico(self) -> None:
        text = format_intent_result("action_estranha", {
            "nome": "alex", "ativo": 1, "_interno": True,
            "aninhado": {"a": 1},
        })
        assert text == "nome: alex; ativo: 1"

    def test_fallback_sem_pares_escalares(self) -> None:
        assert format_intent_result("action_estranha", {
            "aninhado": {"a": 1},
        }) is None

    def test_dados_invalidos_ou_degradados(self) -> None:
        assert format_intent_result("network_hosts", None) is None
        assert format_intent_result("network_hosts", "texto") is None
        assert format_intent_result(
            "network_hosts", {"ok": False, "error": "sem /proc"}
        ) is None


# ---------------------------------------------------------------------------
# Integração no pipeline do Orchestrator (etapa 3.5)
# ---------------------------------------------------------------------------

class TestFastPathOrchestrator:
    """Respostas operacionais SEM LLM quando o registry está conectado."""

    @staticmethod
    def _orch(monkeypatch, *, registry=True) -> Orchestrator:
        orch = Orchestrator(
            providers=[StaticProvider("test", "resposta-llm")],
            action_registry=build_registry(security=SecurityManager(mode="strict"))
            if registry else None,
        )
        if registry:
            monkeypatch.setattr(
                "tools.actions.actions._read_proc", lambda name: ARP_SAMPLE
            )
        return orch

    @pytest.mark.asyncio
    async def test_rede_responde_sem_llm(self, monkeypatch) -> None:
        """'quantas pessoas na rede?' → action_intent (nunca chama o LLM)."""
        orch = self._orch(monkeypatch)
        result = await orch.process("u1", "guardian", "quantas pessoas estão conectadas na rede?")
        assert result.route == "action_intent"
        assert result.llm_used == "fastpath:network_hosts"
        assert "3 dispositivo(s)" in result.message
        assert orch.metrics.intents == 1
        assert orch.metrics.llm == 0

    @pytest.mark.asyncio
    async def test_matematica_responde_sem_llm(self, monkeypatch) -> None:
        orch = self._orch(monkeypatch)
        result = await orch.process("u1", "guardian", "quanto é 2+2*3?")
        assert result.route == "action_intent"
        assert result.message == "2+2*3 = 8"
        assert orch.metrics.intents == 1
        assert orch.metrics.llm == 0

    @pytest.mark.asyncio
    async def test_mensagem_normal_vai_ao_llm(self, monkeypatch) -> None:
        """Sem intenção → pipeline normal (LLM)."""
        orch = self._orch(monkeypatch)
        result = await orch.process("u1", "guardian", "me escreva um poema curto")
        assert result.route == "llm"
        assert result.message == "resposta-llm"
        assert orch.metrics.intents == 0

    @pytest.mark.asyncio
    async def test_sem_registry_cai_ao_llm(self, monkeypatch) -> None:
        """Sem ActionRegistry conectado → intenção vira pergunta normal."""
        orch = self._orch(monkeypatch, registry=False)
        result = await orch.process("u1", "guardian", "quantos processos estão rodando?")
        assert result.route == "llm"
        assert result.message == "resposta-llm"
        assert orch.metrics.intents == 0

    @pytest.mark.asyncio
    async def test_acao_degradada_cai_ao_llm(self, monkeypatch) -> None:
        """network_hosts sem /proc → format None → cai para o LLM."""
        orch = self._orch(monkeypatch)
        monkeypatch.setattr(
            "tools.actions.actions._read_proc", lambda name: ""
        )
        result = await orch.process("u1", "guardian", "quantas pessoas na rede?")
        assert result.route == "llm"
        assert result.message == "resposta-llm"
        assert orch.metrics.intents == 0