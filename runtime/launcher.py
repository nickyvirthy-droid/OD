"""
OMEGA DRAKON • RUNTIME
Tecnologia que respira.
Módulo: runtime/launcher.py
Descrição: Launcher do sistema REAL — monta o Orchestrator com o provider
           LLM local (OpenAICompatProvider -> llama-server) e memórias em
           disco, e sobe os serviços: API REST (porta 8000) e Telegram Bot
           (polling com o token de .env).

Uso:
    .venv/bin/python -m runtime.launcher api       # sobe a API REST
    .venv/bin/python -m runtime.launcher telegram  # sobe o bot do Telegram
    .venv/bin/python -m runtime.launcher mqtt      # sobe a ponte MQTT
    .venv/bin/python -m runtime.launcher all       # api + bot + mqtt

Configuração (variáveis de ambiente / .env no raiz do repo):
    TELEGRAM_BOT_TOKEN  Token do bot (obrigatório p/ telegram).
    OD_TELEGRAM_ADMINS  IDs admin separados por vírgula (comandos admin).
    OD_LLM_URL          Endpoint OpenAI-compat (default 127.0.0.1:8081).
    OD_LLM_TIMEOUT_S    Timeout por chamada LLM (default 240).
    OD_API_PORT         Porta da API REST (default 8000).
    OD_API_HOST         Bind da API (default 0.0.0.0 — LAN/site; use
                        127.0.0.1 para só local).
    OD_API_KEY          Chave X-API-Key da API (endpoints protegidos).
    OD_API_AUTH_ALL     "0" libera os endpoints públicos sem chave
                        (default 1 — chave exigida em TODOS os endpoints).
    OD_MQTT_ENABLED     "0" desliga a ponte MQTT no modo all (default 1).
    OD_MQTT_HOST/PORT   Broker Mosquitto (default 127.0.0.1:1883).
    OD_MQTT_CLIENT_ID   Identificador no broker (default od-core).
    OD_MQTT_SUBSCRIBE   Filtros de entrada, vírgula (default "od/in/#").
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import threading
from typing import Any, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.runtime.launcher")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
DATA_DIR = REPO_ROOT / "data"


def load_env(path: pathlib.Path = ENV_PATH) -> dict[str, str]:
    """Carrega variáveis do .env (stdlib — sem python-dotenv)."""
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


_ENV_CACHE: Optional[dict[str, str]] = None


def env(name: str, default: str = "") -> str:
    """Valor de ambiente: os.environ primeiro, .env depois."""
    global _ENV_CACHE
    if _ENV_CACHE is None:
        _ENV_CACHE = dict(os.environ)
        _ENV_CACHE.update(load_env())
    return _ENV_CACHE.get(name, default)


def build_orchestrator() -> Any:
    """Orchestrator real: LLM local + memórias persistentes em data/."""
    from core.llm import OpenAICompatProvider
    from core.orchestrator import Orchestrator, OrchestratorConfig
    from memory.cache import LLMCache
    from memory.history import ConversationHistory

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    llm_timeout = float(env("OD_LLM_TIMEOUT_S", "240"))
    provider = OpenAICompatProvider(
        name="gemma-local",
        base_url=env("OD_LLM_URL", "http://127.0.0.1:8081"),
        timeout=llm_timeout,
        max_tokens=int(env("OD_LLM_MAX_TOKENS", "700")),
    )
    # Identidade da Interface Viva injetada por padrão (agents/personality)
    from agents.nicky_virthy.personality import (
        DEFAULT_PROFILE,
        get_system_prompt,
    )

    profile = env("OD_PROFILE", DEFAULT_PROFILE)
    orchestrator = Orchestrator(
        providers=[provider],
        history=ConversationHistory(base_dir=DATA_DIR / "conversations"),
        cache=LLMCache(
            cache_dir=DATA_DIR / "llm_cache",
            profile=profile,
            max_entries=int(env("OD_CACHE_ENTRIES", "2000")),
        ),
        config=OrchestratorConfig(
            llm_timeout_s=llm_timeout,
            default_system_prompt=get_system_prompt(profile),
        ),
    )
    log.info(
        "Orchestrator real montado",
        llm=provider.name,
        url=provider.base_url,
        history=str(DATA_DIR / "conversations"),
    )
    return orchestrator


def build_api_server(orchestrator: Any):
    """APIServer (integrations/api) sobre o Orchestrator real."""
    from integrations.api import APIConfig, APIServer

    api_key = env("OD_API_KEY", "")
    host = env("OD_API_HOST", "0.0.0.0")  # LAN (site 192.168.0.250:8000)
    port = int(env("OD_API_PORT", "8000"))
    # auth_all: bind exposto na LAN exige X-API-Key em TODOS os endpoints
    server = APIServer(
        orchestrator,
        config=APIConfig(
            host=host,
            port=port,
            api_key=api_key,
            auth_all=env("OD_API_AUTH_ALL", "1") != "0",
        ),
    )
    return server


def build_telegram_bot(orchestrator: Any):
    """TelegramBot real (HTTPTransport) sobre o Orchestrator."""
    from integrations.telegram import HTTPTransport, TelegramBot

    token = env("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN ausente — configure o .env (veja runtime/launcher.py)"
        )
    admins = {
        int(part)
        for part in env("OD_TELEGRAM_ADMINS", "").split(",")
        if part.strip().isdigit()
    }
    transport = HTTPTransport(token, timeout=30.0)
    offset_file = env("OD_TELEGRAM_OFFSET_FILE", "")
    bot = TelegramBot(
        transport,
        orchestrator,
        admin_ids=admins,
        offset_file=(
            offset_file or str(DATA_DIR / "telegram_offset.json")
        ),
    )
    return bot


def build_mqtt_bridge(event_bus: Any):
    """MQTTBridge real sobre o broker Mosquitto (env OD_MQTT_*)."""
    from integrations.mqtt import MQTTBridge, MQTTClient, MQTTConfig

    client = MQTTClient(
        env("OD_MQTT_HOST", "127.0.0.1"),
        int(env("OD_MQTT_PORT", "1883")),
        client_id=env("OD_MQTT_CLIENT_ID", "od-core"),
        keepalive=30,
    )
    bridge = MQTTBridge(
        client,
        event_bus=event_bus,
        config=MQTTConfig(poll_timeout_s=0.5, reconnect_delay_s=5.0),
    )
    # Tópicos de entrada (mensagens → Event Bus como mqtt.message)
    topics = [
        t.strip()
        for t in env("OD_MQTT_SUBSCRIBE", "od/in/#").split(",")
        if t.strip()
    ]
    bridge.subscribe(topics)
    return bridge


async def _run_api_forever(orchestrator: Any) -> None:
    server = build_api_server(orchestrator)
    server.serve_background()
    log.info("API REST no ar", port=server.bound_port)
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:  # pragma: no cover
        server.stop()


async def _run_telegram_forever(orchestrator: Any) -> None:
    bot = build_telegram_bot(orchestrator)
    log.info("Telegram bot iniciando polling...", admins=len(bot.admin_ids))
    await bot.run(interval=1.0)


async def _run_mqtt_forever(bridge: Any) -> None:
    """Loop da ponte MQTT (reconecta sozinha se o broker cair)."""
    log.info("Ponte MQTT iniciando loop...")
    await bridge.run()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    orchestrator = build_orchestrator()
    mqtt_enabled = env("OD_MQTT_ENABLED", "1") != "0"

    async def _all() -> None:
        # Event Bus único da entrega (bridge MQTT ↔ núcleo)
        from core.event_bus import EventBus

        tasks = [
            _run_api_forever(orchestrator),
            _run_telegram_forever(orchestrator),
        ]
        if mqtt_enabled:
            event_bus = EventBus()
            bridge = build_mqtt_bridge(event_bus)
            tasks.append(_run_mqtt_forever(bridge))
            log.info("Ponte MQTT habilitada (od-core)")
        await asyncio.gather(*tasks)

    if mode == "api":
        asyncio.run(_run_api_forever(orchestrator))
    elif mode == "telegram":
        asyncio.run(_run_telegram_forever(orchestrator))
    elif mode == "mqtt":
        from core.event_bus import EventBus

        bridge = build_mqtt_bridge(EventBus())
        asyncio.run(_run_mqtt_forever(bridge))
    elif mode == "all":
        asyncio.run(_all())
    else:
        print(f"modo desconhecido: {mode!r} (api|telegram|mqtt|all)")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())