"""
OMEGA DRAKON • TESTS
Módulo: tests/test_launcher_vision.py
Descrição: Testes do loop de visão do launcher (runtime/launcher.py,
           _run_vision_forever) — o handler que escuta `face.presence` no
           Event Bus único do núcleo.
           Cobre: entrega do Event ao handler (contrato do barramento:
           o payload vive em `event.data`), aviso ÚNICO de presença
           confirmada no sink do Telegram, silêncio em evento não
           confirmado e ausência de dead letter.
           Regressão (2026-09-14): o handler recebia `data` e chamava `.get()` no
           próprio `Event` → `AttributeError: 'Event' object has no
           attribute 'get'` a cada publicação, 3 tentativas esgotadas e
           dead letter no journal do od-core.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/event_bus.py (publish → handler(event) → event.data)
  - tools/vision/face_detector.py (FACE_TOPIC, payload confirmado)
  - tests/test_face_detector.py (mesmo contrato, do lado do detector)
"""

from __future__ import annotations

import pytest

from core.event_bus import Event, EventBus
from runtime.launcher import _run_vision_forever
from tools.vision import FACE_TOPIC


class _SinkColetor:
    """Sink fake do Telegram: guarda os textos enviados."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def __call__(self, text: str) -> None:
        self.sent.append(text)


class _FakeDetector:
    """Face Detector fake: publica eventos configurados e encerra o run()."""

    def __init__(self, events: list[dict]) -> None:
        self.event_bus = None
        self.ran = False
        self._events = events

    async def run(self) -> None:
        self.ran = True
        for data in self._events:
            await self.event_bus.publish(
                Event(topic=FACE_TOPIC, data=dict(data), source="face_detector")
            )


def _confirmado() -> dict:
    """Payload real do Face Detector ao confirmar presença."""
    return {"state": "detected", "confirmed": True, "faces": 1}


def _perdido() -> dict:
    return {"state": "lost", "confirmed": False, "faces": 0}


async def _run(detector: _FakeDetector) -> EventBus:
    bus = EventBus()
    await bus.start()
    try:
        await _run_vision_forever(bus, detector)
    finally:
        await bus.stop()
    return bus


# ---------------------------------------------------------------------------
# Contrato do Event Bus — evento não vira dead letter
# ---------------------------------------------------------------------------

class TestVisionHandlerNoBus:
    """O handler consome o `Event` (não o dict) e nunca falha."""

    @pytest.mark.asyncio
    async def test_presenca_confirmada_nao_vai_para_dead_letter(self) -> None:
        detector = _FakeDetector([_confirmado()])
        bus = await _run(detector)
        assert detector.ran is True
        assert bus.dead_letters == []
        assert bus.metrics.failed == 0

    @pytest.mark.asyncio
    async def test_evento_nao_confirmado_nao_gera_erro(self) -> None:
        detector = _FakeDetector([_perdido()])
        bus = await _run(detector)
        assert bus.dead_letters == []
        assert bus.metrics.failed == 0


# ---------------------------------------------------------------------------
# Aviso no sink — uma vez por presença confirmada
# ---------------------------------------------------------------------------

class TestAvisoDePresenca:
    """Aviso único no Telegram quando a presença facial é confirmada."""

    @pytest.mark.asyncio
    async def test_avisa_uma_vez_mesmo_com_varios_eventos(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = _SinkColetor()
        monkeypatch.setattr(
            "runtime.launcher.build_telegram_sink", lambda: sink
        )
        detector = _FakeDetector([_confirmado(), _confirmado()])
        bus = await _run(detector)
        assert len(sink.sent) == 1
        assert "Presença facial" in sink.sent[0]
        assert bus.dead_letters == []

    @pytest.mark.asyncio
    async def test_nao_avisa_quando_presenca_nao_confirmada(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = _SinkColetor()
        monkeypatch.setattr(
            "runtime.launcher.build_telegram_sink", lambda: sink
        )
        detector = _FakeDetector([_perdido()])
        bus = await _run(detector)
        assert sink.sent == []
        assert bus.dead_letters == []
