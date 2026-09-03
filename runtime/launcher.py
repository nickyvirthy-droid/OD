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
    OD_PRESENCE_ENABLED "0" desliga o Presence Monitor (default 1).
    OD_HA_CREDENTIALS   Caminho das credenciais do HA (default
                        config/iot_credentials.json).
    OD_PRESENCE_POLL_S  Intervalo do poll de presença (default 30).
    OD_VISION_ENABLED   "1" liga o Face Detector (webcam) no modo all
                        (default 0 — câmera só quando ativado).
    OD_VISION_DEVICE    Dispositivo da webcam (default /dev/video0).
    OD_VISION_POLL_S    Intervalo de captura (default 5).
    OD_VOICE_STT        "0" desliga a transcrição de voz recebida
                        (whisper.cpp) no bot (default 1).
    OD_VOICE_TTS        "0" desliga a resposta por voz (Piper) no bot
                        (default 1).
    OD_VOICE_PROFILE    Voz do TTS (default dii; "regulus" = faber).
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
    """TelegramBot real (HTTPTransport) sobre o Orchestrator.

    Voz (v0.21.0): se os binários reais da Fase 6 existirem, o bot
    transcreve áudios recebidos (whisper.cpp) e responde por voz (Piper)
    — controlado por OD_VOICE_STT / OD_VOICE_TTS.
    """
    from integrations.telegram import HTTPTransport, TelegramBot

    token = env("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN ausente — configure o .env (veja runtime/launcher.py)"
        )
    admins = _admin_ids()
    transport = HTTPTransport(token, timeout=30.0)
    offset_file = env("OD_TELEGRAM_OFFSET_FILE", "")

    stt = tts = None
    if env("OD_VOICE_STT", "1") != "0":
        from integrations.telegram.voice import TelegramVoiceSTT
        from tools.audio import WhisperSTT

        whisper = WhisperSTT()
        if whisper.available:
            stt = TelegramVoiceSTT(whisper)
            log.info("Voz STT habilitada (whisper.cpp)")
        else:
            log.warn("Voz STT indisponível — whisper.cpp ausente")
    if env("OD_VOICE_TTS", "1") != "0":
        from integrations.telegram.voice import TelegramVoiceTTS
        from tools.audio import PiperTTS

        piper = PiperTTS()
        if piper.available:
            profile = env("OD_VOICE_PROFILE", "default")
            tts = TelegramVoiceTTS(piper, profile=profile)
            log.info("Voz TTS habilitada (Piper)", voice=profile)
        else:
            log.warn("Voz TTS indisponível — Piper ausente")

    bot = TelegramBot(
        transport,
        orchestrator,
        admin_ids=admins,
        stt=stt,
        tts=tts,
        offset_file=(
            offset_file or str(DATA_DIR / "telegram_offset.json")
        ),
    )
    return bot


def build_presence_monitor() -> Any:
    """PresenceMonitor (Fase 6.2) sobre o Home Assistant real.

    Lê as credenciais de config/iot_credentials.json (token do HA),
    monitora person.*/device_tracker.* e notifica o admin no Telegram
    quando alguém chega ou sai de casa. Retorna None sem credenciais.
    """
    from integrations.homeassistant import (
        HACredentials,
        HAClient,
        PresenceConfig,
        PresenceMonitor,
    )

    creds_path = env("OD_HA_CREDENTIALS", "config/iot_credentials.json")
    path = REPO_ROOT / creds_path
    if not path.exists():
        log.warn("Presence desativado — sem credenciais HA", path=str(path))
        return None
    try:
        creds = HACredentials.from_file(path)
    except Exception as exc:  # pragma: no cover — arquivo corrompido
        log.warn("Presence desativado — credenciais HA inválidas", error=str(exc))
        return None
    client = HAClient(creds)
    monitor = PresenceMonitor(
        client,
        config=PresenceConfig(
            poll_interval_s=float(env("OD_PRESENCE_POLL_S", "30")),
            state_file=str(DATA_DIR / "presence_state.json"),
        ),
    )
    return monitor


def build_face_detector() -> Optional[Any]:
    """FaceDetector real (Fase 6.1) sobre a webcam do servidor.

    Retorna None se o OpenCV não estiver disponível ou a webcam não abrir.
    Notifica o admin no Telegram quando uma presença facial é confirmada
    (buffer 3 detecções consecutivas — sem alarme falso de sombra).
    """
    from tools.vision import CV2_AVAILABLE, FaceConfig, FaceDetector

    if not CV2_AVAILABLE:
        log.warn("Vision desativado — OpenCV ausente")
        return None
    detector = FaceDetector(
        config=FaceConfig(
            device=env("OD_VISION_DEVICE", "/dev/video0"),
            poll_interval_s=float(env("OD_VISION_POLL_S", "5.0")),
            captures_dir=str(DATA_DIR / "captures"),
        )
    )
    if detector._cascade is None:
        log.warn("Vision desativado — Haar Cascade indisponível")
        return None
    return detector


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


def _admin_ids() -> set[int]:
    return {
        int(part)
        for part in env("OD_TELEGRAM_ADMINS", "").split(",")
        if part.strip().isdigit()
    }


def build_telegram_sink() -> Optional[Any]:
    """Sink de notificação: envia texto ao primeiro admin no Telegram."""
    from integrations.telegram import HTTPTransport

    token = env("TELEGRAM_BOT_TOKEN", "")
    admins = sorted(_admin_ids())
    if not token or not admins:
        return None
    transport = HTTPTransport(token, timeout=20.0)
    chat_id = admins[0]

    async def notify(text: str) -> None:
        await transport.send_message(chat_id, text)

    return notify


async def _send_presence_welcome(sink: Any) -> None:
    """Aviso único de ativação do presence (persistido — sem spam)."""
    flag = DATA_DIR / "presence_welcome_sent.flag"
    if flag.exists():
        return
    try:
        await sink(
            "🟢 Monitor de presença ativo — agora acompanho o Home "
            "Assistant e aviso quando você chegar ou sair de casa."
        )
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        flag.write_text("1", encoding="utf-8")
    except Exception as exc:  # pragma: no cover — rede falhou
        log.warn("Aviso de ativação não enviado", error=str(exc))


async def _run_vision_forever(detector: Any) -> None:
    """Loop do Face Detector (webcam) com notificação de presença."""
    sink = build_telegram_sink()
    notified = False

    async def on_change(data: Any) -> None:
        nonlocal notified
        if not data.get("confirmed"):
            return
        if sink is not None and not notified:
            await sink(
                "👤 Presença facial detectada na câmera do servidor "
                "(alguém está na frente)."
            )
            notified = True

    from core.event_bus import EventBus
    from tools.vision import FACE_TOPIC

    event_bus = EventBus()
    event_bus.subscribe_handler(FACE_TOPIC, on_change)
    detector.event_bus = event_bus
    log.info("Face Detector iniciando captura da webcam...")
    await detector.run()


async def _run_presence_forever(monitor: Any) -> None:
    """Loop do Presence Monitor (poll no HA + notificação Telegram)."""
    sink = build_telegram_sink()
    if sink is not None:
        from integrations.homeassistant import PresenceMonitor

        async def notify(change: Any) -> None:
            await sink(PresenceMonitor.format_change(change))

        monitor.add_sink(notify)
        await _send_presence_welcome(sink)
    log.info("Presence Monitor iniciando poll no HA...")
    await monitor.run()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    orchestrator = build_orchestrator()
    mqtt_enabled = env("OD_MQTT_ENABLED", "1") != "0"
    presence_enabled = env("OD_PRESENCE_ENABLED", "1") != "0"
    presence_monitor = build_presence_monitor() if presence_enabled else None
    vision_enabled = env("OD_VISION_ENABLED", "0") != "0"
    face_detector = build_face_detector() if vision_enabled else None

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
        if presence_monitor is not None:
            tasks.append(_run_presence_forever(presence_monitor))
            log.info("Presence Monitor habilitado (od-core)")
        if face_detector is not None:
            tasks.append(_run_vision_forever(face_detector))
            log.info("Face Detector habilitado (od-core)")
        await asyncio.gather(*tasks)

    if mode == "api":
        asyncio.run(_run_api_forever(orchestrator))
    elif mode == "telegram":
        asyncio.run(_run_telegram_forever(orchestrator))
    elif mode == "mqtt":
        from core.event_bus import EventBus

        bridge = build_mqtt_bridge(EventBus())
        asyncio.run(_run_mqtt_forever(bridge))
    elif mode == "presence":
        monitor = presence_monitor or build_presence_monitor()
        if monitor is None:
            print("presence indisponível — credenciais HA ausentes")
            return 2
        asyncio.run(_run_presence_forever(monitor))
    elif mode == "vision":
        detector = face_detector or build_face_detector()
        if detector is None:
            print("vision indisponível — OpenCV ou webcam ausente")
            return 2
        asyncio.run(_run_vision_forever(detector))
    elif mode == "all":
        asyncio.run(_all())
    else:
        print(f"modo desconhecido: {mode!r} (api|telegram|mqtt|presence|vision|all)")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())