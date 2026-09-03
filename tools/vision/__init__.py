"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Pacote: tools/vision/
Descrição: Sensorial visual (Fase 6) — Face Detection (6.1) com Haar
           Cascade + CLAHE + buffer de confirmação, espelhando o legado
           Nicky vision/.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Módulos:
  - face_detector.py → FaceDetector (detecção + presença facial estável)
"""

from tools.vision.face_detector import (
    CV2_AVAILABLE,
    FACE_TOPIC,
    FaceConfig,
    FaceDetector,
    FaceMetrics,
)

__signature__ = "OD // CORE"
__all__ = [
    "FaceDetector",
    "FaceConfig",
    "FaceMetrics",
    "FACE_TOPIC",
    "CV2_AVAILABLE",
]