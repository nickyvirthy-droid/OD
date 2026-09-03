"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: tools/vision/face_detector.py
Descrição: Face Detection (Fase 6, item 6.1) — detector facial com Haar
           Cascade + CLAHE (equalização adaptativa de contraste) + ROI guard
           (ignora bordas) e BUFFER DE CONFIRMAÇÃO multi-frame (3 detecções
           consecutivas = presença confirmada; 2 ausências = encerrada),
           espelhando o legado Nicky vision/face_detector.py. Captura de
           webcam plugável (device), Event Bus (face.presence), métricas,
           salvamento de frames com limite diário e introspecção.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky vision/face_detector.py (Haar + CLAHE + buffer de confirmação)
  - ROADMAP_ABSORCAO.md Fase 6, item 6.1

Decisões registradas (ver CHANGELOG):
  - OpenCV (opencv-python-headless) é a ÚNICA dependência externa desta
    entrega — autorizado pelo usuário (regra §10) e registrado no CHANGELOG
  - Detecção nunca é emitida em frame isolado: buffer de confirmação 3/2
    (como o legado) elimina sombras/reflexos
  - ROI guard de 10% nas bordas (janelas/reflexos) — mesmo critério legado
  - Capture plugável: `capture_fn` injetável para testes sem webcam
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.tools.vision.face")

try:
    import cv2
    import numpy as np

    CV2_AVAILABLE = True
except ImportError:  # pragma: no cover — sem OpenCV instalado
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    CV2_AVAILABLE = False

FACE_TOPIC = "face.presence"

DEFAULT_DEVICE = "/dev/video0"
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720


@dataclass(slots=True)
class FaceConfig:
    """Configuração do detector facial."""

    device: str = DEFAULT_DEVICE
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    scale_factor: float = 1.1
    min_neighbors: int = 8  # conservador (legado v0.3.9+)
    min_size: tuple[int, int] = (80, 80)
    max_size: tuple[int, int] = (400, 400)
    confirm_threshold: int = 3  # detecções consecutivas p/ confirmar
    reset_threshold: int = 2  # ausências consecutivas p/ encerrar
    captures_enabled: bool = True
    captures_dir: Optional[Union[str, Path]] = None  # default data/captures
    captures_max_per_day: int = 50
    cascade_path: Optional[Union[str, Path]] = None  # default do OpenCV
    poll_interval_s: float = 5.0


@dataclass(slots=True)
class FaceMetrics:
    """Métricas acumuladas do detector."""

    ticks: int = 0
    frames: int = 0
    captures_failed: int = 0
    detections: int = 0
    confirmations: int = 0
    resets: int = 0
    errors: int = 0
    frames_saved: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "ticks": self.ticks,
            "frames": self.frames,
            "captures_failed": self.captures_failed,
            "detections": self.detections,
            "confirmations": self.confirmations,
            "resets": self.resets,
            "errors": self.errors,
            "frames_saved": self.frames_saved,
        }


# Captura plugável: deve devolver (frame_bgr, ok) ou None se indisponível
CaptureFn = Callable[[], Optional[tuple[Any, bool]]]


class FaceDetector:
    """Detector facial com buffer de confirmação (presença estável).

    Uso típico:
        detector = FaceDetector()
        ok = detector.tick()          # captura + detecta + atualiza presença
        if detector.presence_confirmed:
            ...
        detector.run(...)             # ou start()/stop() em thread
    """

    def __init__(
        self,
        *,
        config: Optional[FaceConfig] = None,
        event_bus: Any = None,
        capture: Optional[CaptureFn] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.config = config or FaceConfig()
        self.event_bus = event_bus
        self._capture = capture or self._default_capture
        self._clock = clock or time.time
        self.metrics = FaceMetrics()
        self._closed = False
        self._thread: Optional[Any] = None
        self._lock = None  # threading desnecessário: tick único por loop
        self._cascade = self._load_cascade()
        self._consecutive_detections = 0
        self._consecutive_absences = 0
        self._presence_confirmed = False
        self._last_frame_time: float = 0.0
        self._last_faces: list[tuple[int, int, int, int]] = []

    # -- Inicialização -------------------------------------------------------

    def _load_cascade(self) -> Any:
        """Carrega o Haar Cascade frontal (path custom ou default OpenCV)."""
        if not CV2_AVAILABLE:
            log.warn("OpenCV ausente — detector desativado")
            return None
        path = self.config.cascade_path or (
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        cascade = cv2.CascadeClassifier(str(path))
        if cascade.empty():
            log.error("Haar Cascade não carregado", path=str(path))
            return None
        log.info("Haar Cascade carregado", path=str(path))
        return cascade

    # -- Pré-processamento ---------------------------------------------------

    def _preprocess(self, frame: Any) -> Any:
        """CLAHE em escala de cinza (contraste adaptativo)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(gray)

    # -- Detecção ------------------------------------------------------------

    def detect_faces(self, frame: Any) -> list[tuple[int, int, int, int]]:
        """Detecta rostos no frame → lista de (x, y, w, h) (ROI guard)."""
        if self._cascade is None:
            return []
        processed = self._preprocess(frame)
        h_frame, w_frame = processed.shape[:2]
        faces_raw = self._cascade.detectMultiScale(
            processed,
            scaleFactor=self.config.scale_factor,
            minNeighbors=self.config.min_neighbors,
            minSize=self.config.min_size,
            maxSize=self.config.max_size,
        )
        if len(faces_raw) == 0:
            return []
        # ROI guard: ignora detecções nos 10% das bordas (janelas/reflexos)
        margin_x = int(w_frame * 0.10)
        margin_y = int(h_frame * 0.10)
        faces: list[tuple[int, int, int, int]] = []
        for x, y, w, h in faces_raw:
            if x < margin_x or y < margin_y:
                continue
            if (x + w) > (w_frame - margin_x):
                continue
            if (y + h) > (h_frame - margin_y):
                continue
            faces.append((int(x), int(y), int(w), int(h)))
        return faces

    # -- Buffer de confirmação -----------------------------------------------

    def update_presence(self, face_count: int) -> tuple[bool, bool]:
        """Atualiza o buffer → (presença_confirmada, mudou_estado)."""
        previous = self._presence_confirmed
        if face_count > 0:
            self._consecutive_detections += 1
            self._consecutive_absences = 0
            if (
                not self._presence_confirmed
                and self._consecutive_detections >= self.config.confirm_threshold
            ):
                self._presence_confirmed = True
                self.metrics.confirmations += 1
                log.info(
                    "Presença facial confirmada",
                    detections=self._consecutive_detections,
                )
        else:
            self._consecutive_absences += 1
            self._consecutive_detections = 0
            if (
                self._presence_confirmed
                and self._consecutive_absences >= self.config.reset_threshold
            ):
                self._presence_confirmed = False
                self.metrics.resets += 1
                log.info(
                    "Presença facial encerrada",
                    absences=self._consecutive_absences,
                )
        changed = previous != self._presence_confirmed
        return self._presence_confirmed, changed

    @property
    def presence_confirmed(self) -> bool:
        return self._presence_confirmed

    @property
    def last_faces(self) -> list[tuple[int, int, int, int]]:
        return list(self._last_faces)

    # -- Captura -------------------------------------------------------------

    def _default_capture(self) -> Optional[tuple[Any, bool]]:
        """Captura da webcam (device configurável). Sync — roda em thread."""
        if not CV2_AVAILABLE:
            return None
        try:
            cap = cv2.VideoCapture(self.config.device)
            if not cap.isOpened():
                self.metrics.captures_failed += 1
                log.warn("Webcam indisponível", device=self.config.device)
                return None
            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
                # descarta frames antigos do buffer
                for _ in range(3):
                    cap.grab()
                ok, frame = cap.read()
            finally:
                cap.release()
            if not ok or frame is None or frame.size == 0:
                self.metrics.captures_failed += 1
                log.warn("Frame inválido da webcam")
                return None
            self._last_frame_time = self._clock()
            return frame, ok
        except Exception as exc:  # pragma: no cover — falha de driver
            self.metrics.errors += 1
            self.metrics.captures_failed += 1
            log.error("Falha na captura", error=str(exc))
            return None

    async def capture_and_detect(
        self,
    ) -> tuple[int, list[tuple[int, int, int, int]]]:
        """Captura em executor e detecta → (face_count, faces)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover — uso síncrono atípico
            loop = asyncio.get_event_loop()
        captured = await loop.run_in_executor(None, self._capture)
        if captured is None:
            self.metrics.captures_failed += 1
            return 0, []
        frame, ok = captured
        if not ok:
            self.metrics.captures_failed += 1
            return 0, []
        self.__last_frame = frame
        faces = self.detect_faces(frame)
        self._last_faces = faces
        return len(faces), faces

    # -- Tick ------------------------------------------------------------------

    async def tick(self) -> bool:
        """Ciclo: captura → detecta → buffer → evento. True se presença confirmada."""
        self.metrics.ticks += 1
        faces = await self.capture_and_detect()
        count = faces[0]
        if count > 0:
            self.metrics.detections += count
            self.metrics.frames += 1
        confirmed, changed = self.update_presence(count)
        if changed:
            await self._publish_event(count, confirmed)
            if confirmed and count > 0:
                self._save_last_capture(count)
        return confirmed

    async def _publish_event(self, count: int, confirmed: bool) -> None:
        if self.event_bus is None:
            return
        from core.event_bus import Event

        await self.event_bus.publish(
            Event(
                topic=FACE_TOPIC,
                data={
                    "state": "detected" if confirmed else "lost",
                    "confirmed": confirmed,
                    "faces": count,
                    "ts": self._clock(),
                },
                source="vision",
            )
        )

    def _save_last_capture(self, count: int) -> Optional[Path]:
        """Salva o frame da confirmação (limite diário)."""
        if not self.config.captures_enabled:
            return None
        try:
            frame = getattr(self, "_FaceDetector__last_frame", None)
            if frame is None:
                return None
            now = datetime.now(timezone.utc)
            base = (
                Path(self.config.captures_dir)
                if self.config.captures_dir
                else Path("data") / "captures"
            )
            date_dir = base / now.strftime("%Y-%m-%d")
            date_dir.mkdir(parents=True, exist_ok=True)
            existing = list(date_dir.glob("*.jpg"))
            if len(existing) >= self.config.captures_max_per_day:
                return None
            path = date_dir / (now.strftime("%H-%M-%S") + f"_{count}f.jpg")
            ok = cv2.imwrite(str(path), frame)
            if ok:
                self.metrics.frames_saved += 1
                return path
        except Exception as exc:  # pragma: no cover
            self.metrics.errors += 1
            log.error("Falha ao salvar frame", error=str(exc))
        return None

    # -- Loop ------------------------------------------------------------------

    async def run(
        self,
        interval: Optional[float] = None,
        max_ticks: Optional[int] = None,
    ) -> int:
        pause = interval if interval is not None else self.config.poll_interval_s
        ticks = 0
        while not self._closed:
            await self.tick()
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            await asyncio.sleep(pause)
        return ticks

    def start(self) -> Any:
        """Sobe o loop em thread daemon (runtime)."""
        import threading

        if self._thread is not None and self._thread.is_alive():
            return self._thread
        self._closed = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return self._thread

    def _run_loop(self) -> None:
        try:
            asyncio.run(self.run())
        except Exception as exc:  # pragma: no cover
            self.metrics.errors += 1
            log.error("Loop do face detector encerrado", error=type(exc).__name__)

    def stop(self) -> None:
        self._closed = True

    def close(self) -> None:
        self.stop()

    # -- Introspecção ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "device": self.config.device,
            "presence_confirmed": self._presence_confirmed,
            "consecutive_detections": self._consecutive_detections,
            "consecutive_absences": self._consecutive_absences,
            "metrics": self.metrics.snapshot(),
            "last_faces": self._last_faces,
        }

    def dump(self) -> dict[str, Any]:
        return self.snapshot()

    def health(self) -> dict[str, Any]:
        return {
            "ok": self._cascade is not None,
            "cascade": self._cascade is not None,
            "cv2": CV2_AVAILABLE,
            "device": self.config.device,
            "presence_confirmed": self._presence_confirmed,
            "ts": self._clock(),
        }


