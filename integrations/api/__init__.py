"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Pacote: integrations/api/
Descrição: API REST sobre o Orchestrator (Fase 5, item 5.2) — os 17
           endpoints do legado Nicky em http.server stdlib (sem FastAPI):
           /health, /profiles, /presence/today, /dashboard, /chat, /metrics,
           /dashboard/stats, /llms, POST /message, /transcribe, /tts,
           /history/{user_id}, /history/{user_id}/stats,
           /memory/{user_id}/search e /ws/chat (501 — decisão registrada).
           API key via X-API-Key + rate limit por IP + CORS.

Módulos:
  - server.py  → APIConfig, APIServer, APIHandler, APIError, ROUTES
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/api.py (17 endpoints, porta 8000)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.2
"""

from integrations.api.server import (
    APIError,
    APIConfig,
    APIServer,
    APIHandler,
    DEFAULT_PROFILE,
    DEFAULT_PROFILES,
    ROUTES,
)

__signature__ = "OD // CORE"
__all__ = [
    "APIConfig",
    "APIServer",
    "APIHandler",
    "APIError",
    "DEFAULT_PROFILE",
    "DEFAULT_PROFILES",
    "ROUTES",
]
