"""Três bots do dono — um por papel (divisão dele, 20/10).

@Nicky_Virthy_bot = chat (conversa, comandos).
@Nexus_Nicky_bot  = alertas de usuários pedindo informação (💬 chat das
peças, 🔑 registro de posse).
@nicky_monitor_bot = monitoramento e alertas do sistema (notifier,
presença, face, resumo do orquestrador).

Regra coberta aqui: cada papel fala pelo SEU token e, quando o token do
papel falta, CAI NO CHAT (a Nicky) — um bot fora degrada, nunca silencia.
Hermético: o transporte é substituído, nenhum teste faz rede.
"""
from __future__ import annotations

import asyncio

import pytest

from runtime import launcher


class _Env:
    """Cache de ambiente isolado do launcher (sem vazar o .env real).

    `launcher.env()` lê primeiro os.environ e depois o .env do disco —
    por isso o cache é substituído por um dicionário nosso e os valores
    entram nele, não no processo.
    """

    def __init__(self, monkeypatch) -> None:
        self.cache: dict[str, str] = {}
        monkeypatch.setattr(launcher, "_ENV_CACHE", self.cache)

    def set(self, chave: str, valor: str) -> None:
        self.cache[chave] = valor

    def limpar(self, chave: str) -> None:
        self.cache.pop(chave, None)


@pytest.fixture
def env(monkeypatch):
    return _Env(monkeypatch)


class _TransporteFalso:
    """Transporte que grava o token recebido e o que foi enviado."""

    def __init__(self) -> None:
        self.token: str | None = None
        self.chats: list[int] = []
        self.textos: list[str] = []

    def __call__(self, token: str, timeout: float = 0.0):
        self.token = token
        return self

    async def send_message(self, chat_id: int, text: str) -> None:
        self.chats.append(chat_id)
        self.textos.append(text)


@pytest.fixture
def transporte(monkeypatch):
    import integrations.telegram as telegram

    falso = _TransporteFalso()
    monkeypatch.setattr(telegram, "HTTPTransport", falso)
    return falso


class TestPapeisDeBot:
    def test_mapa_de_papeis_completo(self) -> None:
        """Os 3 papéis existem com token/chat próprios."""
        assert launcher.PAPEIS_BOT == {
            "chat": ("TELEGRAM_BOT_TOKEN", "OD_TELEGRAM_ADMINS"),
            "usuarios": ("OD_TELEGRAM_USUARIOS_TOKEN", "OD_TELEGRAM_USUARIOS_CHAT"),
            "monitor": ("OD_TELEGRAM_MONITOR_TOKEN",
                        "OD_TELEGRAM_MONITOR_CHAT"),
        }

    def test_chat_fala_pelo_token_principal(self, env, transporte) -> None:
        env.set("TELEGRAM_BOT_TOKEN", "tok-a")
        env.set("OD_TELEGRAM_ADMINS", "111")

        sink = launcher.build_telegram_sink("chat")
        assert sink is not None
        asyncio.run(sink("oi"))

        assert transporte.token == "tok-a"
        assert transporte.chats == [111]

    def test_usuarios_falam_pelo_nexus(self, env, transporte) -> None:
        """💬 chat das peças / 🔑 posse saem pelo @Nexus_Nicky_bot."""
        env.set("TELEGRAM_BOT_TOKEN", "tok-a")
        env.set("OD_TELEGRAM_USUARIOS_TOKEN", "tok-b")
        env.set("OD_TELEGRAM_ADMINS", "111")

        sink = launcher.build_telegram_sink("usuarios")
        assert sink is not None
        asyncio.run(sink("💬 Peça P1 — fulano: tem ainda?"))

        assert transporte.token == "tok-b"
        assert transporte.chats == [111]
        assert transporte.textos == ["💬 Peça P1 — fulano: tem ainda?"]

    def test_monitor_fala_pelo_monitor(self, env, transporte) -> None:
        env.set("TELEGRAM_BOT_TOKEN", "tok-a")
        env.set("OD_TELEGRAM_MONITOR_TOKEN", "tok-c")
        env.set("OD_TELEGRAM_ADMINS", "111")

        sink = launcher.build_telegram_sink("monitor")
        assert sink is not None
        asyncio.run(sink("🚨 disco em 91%"))

        assert transporte.token == "tok-c"

    def test_papel_sem_token_cai_no_chat(self, env, transporte) -> None:
        """Token do papel vazio = degrada para o chat, não some."""
        env.set("TELEGRAM_BOT_TOKEN", "tok-a")
        env.set("OD_TELEGRAM_ADMINS", "111")

        sink = launcher.build_telegram_sink("monitor")
        assert sink is not None
        asyncio.run(sink("aviso"))

        assert transporte.token == "tok-a"

    def test_papel_com_chat_proprio_usa_ele(self, env, transporte) -> None:
        """Chat por papel prevalece; sem ele, o do dono."""
        env.set("TELEGRAM_BOT_TOKEN", "tok-a")
        env.set("OD_TELEGRAM_USUARIOS_TOKEN", "tok-b")
        env.set("OD_TELEGRAM_ADMINS", "111")
        env.set("OD_TELEGRAM_USUARIOS_CHAT", "222, 333")

        asyncio.run(launcher.build_telegram_sink("usuarios")("x"))
        assert transporte.chats == [222]

    def test_papel_desconhecido_cai_no_chat(self, env, transporte) -> None:
        env.set("TELEGRAM_BOT_TOKEN", "tok-a")
        env.set("OD_TELEGRAM_ADMINS", "111")

        sink = launcher.build_telegram_sink("qualquer-coisa")
        assert sink is not None
        asyncio.run(sink("x"))
        assert transporte.token == "tok-a"

    def test_padrao_e_o_chat(self, env, transporte) -> None:
        """Sem argumento, o sink é o do chat (a Nicky)."""
        env.set("TELEGRAM_BOT_TOKEN", "tok-a")
        env.set("OD_TELEGRAM_ADMINS", "111")

        asyncio.run(launcher.build_telegram_sink()("x"))
        assert transporte.token == "tok-a"

    def test_sem_token_nenhum_retorna_none(self, env) -> None:
        env.set("OD_TELEGRAM_ADMINS", "111")
        assert launcher.build_telegram_sink("monitor") is None

    def test_sem_chat_retorna_none(self, env) -> None:
        env.set("OD_TELEGRAM_MONITOR_TOKEN", "tok-c")
        assert launcher.build_telegram_sink("monitor") is None

    def test_chat_invalido_nao_vira_sink(self, env) -> None:
        env.set("TELEGRAM_BOT_TOKEN", "tok-a")
        env.set("OD_TELEGRAM_ADMINS", "invalido,abc")
        assert launcher.build_telegram_sink("chat") is None
