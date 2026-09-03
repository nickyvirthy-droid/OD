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
    .venv/bin/python -m runtime.launcher all       # ambos (threads)

Configuração (variáveis de ambiente / .env no raiz do repo):
    TELEGRAM_BOT_TOKEN  Token do bot (obrigatório p/ telegram).
    OD_TELEGRAM_ADMINS  IDs admin separados por vírgula (comandos admin).
    OD_LLM_URL          Endpoint OpenAI-compat (default 127.0.0.1:8081).
    OD_LLM_TIMEOUT_S    Timeout por chamada LLM (default 240).
    OD_API_PORT         Porta da API REST (default 8000).
    OD_API_KEY          Chave X-API-Key opcional da API (default vazia).
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
    port = int(env("OD_API_PORT", "8000"))
    server = APIServer(
        orchestrator,
        config=APIConfig(
            host="127.0.0.1",
            port=port,
            api_key=api_key,
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
    bot = TelegramBot(transport, orchestrator, admin_ids=admins)
    return bot


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


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    orchestrator = build_orchestrator()

    async def _all() -> None:
        await asyncio.gather(
            _run_api_forever(orchestrator),
            _run_telegram_forever(orchestrator),
        )

    if mode == "api":
        asyncio.run(_run_api_forever(orchestrator))
    elif mode == "telegram":
        asyncio.run(_run_telegram_forever(orchestrator))
    elif mode == "all":
        asyncio.run(_all())
    else:
        print(f"modo desconhecido: {mode!r} (api|telegram|all)")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())