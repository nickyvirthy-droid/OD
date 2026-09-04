"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/capabilities.py
Descrição: Manifesto de capacidades do OmegaDrakon — inventário estruturado
           de TODAS as capacidades do sistema (core, memória, orquestração,
           execução, integrações, sensorial, observabilidade e runtime), com
           status de ativação no runtime (active/available/partial/dormant),
           origem legada, fase do roadmap e caminho do código.

           O manifesto é a resposta a "o que o sistema consegue fazer?" —
           consultável por:
             - CLI:    .venv/bin/python runtime/launcher.py capabilities
             - API:    GET /capabilities (X-API-Key)
             - Bot:    /capacidades (admin)
             - Código: from core.capabilities import capabilities_manifest

           Status:
             - active    → ligado no od-core em produção (launcher modo "all")
             - available → implementado + testado, utilizável, sem auto-start
             - partial   → parcialmente exposto (ex.: /codigo só leitura)
             - dormant   → implementado + testado, MAS sem trigger no runtime
                           (os componentes de auto-recuperação estão aqui)
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ROADMAP_ABSORCAO.md (37/37 capacidades, Fases 1–7)
  - docs/CAPACIDADES.md (visão humana)
  - docs/ACTIONS_CORRESPONDENCIA.md (catálogo de 56 actions NV → OD)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

__signature__ = "OD // CORE"

# Versão atual do sistema (usada pelo manifesto e pela API /info).
OD_VERSION = "0.27.3"

# Status válidos.
ACTIVE = "active"
AVAILABLE = "available"
PARTIAL = "partial"
DORMANT = "dormant"

# ---------------------------------------------------------------------------
# Inventário de capacidades
# ---------------------------------------------------------------------------

# Campos: id, name, category, description, source, phase, status, path
# category: core | memory | orchestration | execution | integrations |
#           sensorial | observability | runtime
CAPABILITIES: list[dict[str, str]] = [
    # --- CORE (Fase 1) ------------------------------------------------------
    {
        "id": "config-manager",
        "name": "Config Manager (YAML + env)",
        "category": "core",
        "description": "Configuração centralizada com defaults, YAML e vars OD_*.",
        "source": "Nicky",
        "phase": "Fase 1.1",
        "status": ACTIVE,
        "path": "configs/manager.py",
    },
    {
        "id": "security-layer",
        "name": "Security Layer (policy→permission→scope→approval→audit)",
        "category": "core",
        "description": "Gate de TODA execução/ação; modos compatibility/soft/strict.",
        "source": "NV",
        "phase": "Fase 1.2",
        "status": ACTIVE,
        "path": "core/security/",
    },
    {
        "id": "logger",
        "name": "Logger NICKY (logs estruturados)",
        "category": "core",
        "description": "Protocolo [NICKY][INFO|WARN|CRIT|ONLINE] chave=valor.",
        "source": "NV",
        "phase": "Fase 1.3",
        "status": ACTIVE,
        "path": "core/logger.py",
    },
    {
        "id": "event-bus",
        "name": "Event Bus (pub/sub async)",
        "category": "core",
        "description": "Barramento de eventos (mqtt.message, presence.changed, audit.record...).",
        "source": "Nicky",
        "phase": "Fase 1",
        "status": ACTIVE,
        "path": "core/event_bus.py",
    },
    {
        "id": "state-manager",
        "name": "State Manager",
        "category": "core",
        "description": "Estado tipado do núcleo.",
        "source": "Nicky",
        "phase": "Fase 1",
        "status": ACTIVE,
        "path": "core/state.py",
    },
    {
        "id": "message-router",
        "name": "Message Router",
        "category": "core",
        "description": "Roteamento de mensagens entre camadas.",
        "source": "Nicky",
        "phase": "Fase 1",
        "status": ACTIVE,
        "path": "core/router.py",
    },
    # --- MEMÓRIA (Fase 2) ---------------------------------------------------
    {
        "id": "history",
        "name": "Conversation History (ChatML)",
        "category": "memory",
        "description": "Histórico por usuário/perfil em JSON.",
        "source": "Nicky",
        "phase": "Fase 2.1",
        "status": ACTIVE,
        "path": "memory/history.py",
    },
    {
        "id": "cache",
        "name": "Cache LLM (SHA-256 + deduplicação)",
        "category": "memory",
        "description": "Cache de respostas por hash normalizado + perfil.",
        "source": "Nicky",
        "phase": "Fase 2.2",
        "status": ACTIVE,
        "path": "memory/cache.py",
    },
    {
        "id": "quick-responses",
        "name": "Quick Responses (AIML legado)",
        "category": "memory",
        "description": "Respostas instantâneas sem LLM (etapa 3 do pipeline).",
        "source": "Nicky",
        "phase": "Fase 2.3",
        "status": ACTIVE,
        "path": "memory/quick_responses.py",
    },
    {
        "id": "vector-rag",
        "name": "Vector Memory / RAG",
        "category": "memory",
        "description": "Memória vetorial com provider plugável (stdlib).",
        "source": "Nicky",
        "phase": "Fase 2.4",
        "status": ACTIVE,
        "path": "memory/vector.py",
    },
    {
        "id": "context",
        "name": "Context Manager (anti-estouro de tokens)",
        "category": "memory",
        "description": "Truncamento inteligente do histórico para o LLM.",
        "source": "Nexus",
        "phase": "Fase 2.5",
        "status": ACTIVE,
        "path": "memory/context.py",
    },
    # --- ORQUESTRAÇÃO (Fase 3) ----------------------------------------------
    {
        "id": "workflows",
        "name": "Workflow Engine (branching/nested/retries/timeouts)",
        "category": "orchestration",
        "description": "Pipeline orquestrado de steps; registrado via build_plugins.",
        "source": "NV",
        "phase": "Fase 3.1",
        "status": AVAILABLE,
        "path": "core/workflows.py",
    },
    {
        "id": "tool-loader",
        "name": "Tool Loader (plugins dinâmicos)",
        "category": "orchestration",
        "description": "Carregamento dinâmico de ferramentas/plugins.",
        "source": "Nexus",
        "phase": "Fase 3.2",
        "status": AVAILABLE,
        "path": "tools/loader.py",
    },
    {
        "id": "action-registry",
        "name": "Action Registry (56 actions, gate Security Layer)",
        "category": "orchestration",
        "description": "Registro tipado de actions com execução validada.",
        "source": "NV",
        "phase": "Fase 3.3",
        "status": ACTIVE,
        "path": "tools/registry.py",
    },
    {
        "id": "orchestrator",
        "name": "Orchestrator (pipeline 8 etapas + execute_action)",
        "category": "orchestration",
        "description": "rate limit → datetime → quick → cache → history → LLM → fallback → pós; executa ações via ActionRegistry com gate de role.",
        "source": "Nicky",
        "phase": "Fase 3.4 / Pós-Fase 7",
        "status": ACTIVE,
        "path": "core/orchestrator.py",
    },
    # --- EXECUÇÃO (Fase 4 + 6.6) --------------------------------------------
    {
        "id": "actions-catalog",
        "name": "Catálogo de 56 Actions (sistema/processo/docker/serviços/arquivos/git/db/introspecção)",
        "category": "execution",
        "description": "Ações operacionais executáveis via /executa e Orchestrator.execute_action.",
        "source": "NV",
        "phase": "Fase 4.4",
        "status": ACTIVE,
        "path": "tools/actions/",
    },
    {
        "id": "coder-engine",
        "name": "Coder Engine (sandbox→testes→backup→promoção)",
        "category": "execution",
        "description": "Modificação segura de código com rollback. Exposto no bot apenas como /codigo status/arvore (leitura).",
        "source": "NV",
        "phase": "Fase 4.1",
        "status": PARTIAL,
        "path": "core/coder.py",
    },
    {
        "id": "self-repair",
        "name": "Self Repair (detectar→gerar→reparar→verificar→rollback)",
        "category": "execution",
        "description": "Auto-correção mediada pelo Coder Engine. IMPLEMENTADO mas sem trigger no runtime (dormente).",
        "source": "Nexus",
        "phase": "Fase 4.2",
        "status": DORMANT,
        "path": "core/self_repair.py",
    },
    {
        "id": "perception",
        "name": "Perception Syncer (telemetria CPU/RAM/disco/rede/portas/docker/processos)",
        "category": "execution",
        "description": "Análise do ambiente via /proc. IMPLEMENTADO mas não coletado no runtime (dormente).",
        "source": "Nexus",
        "phase": "Fase 4.3",
        "status": DORMANT,
        "path": "tools/telemetry.py",
    },
    {
        "id": "auto-extension",
        "name": "Auto Extension (geração de ferramentas via LLM)",
        "category": "execution",
        "description": "Gera código de ferramentas, valida (compile + allowlist) e registra com permission mediada. IMPLEMENTADO mas sem trigger no runtime (dormente).",
        "source": "Nexus",
        "phase": "Fase 6.6",
        "status": DORMANT,
        "path": "tools/auto_extension/",
    },
    {
        "id": "plugin-system",
        "name": "Plugin System (hot-reload, 3 contratos)",
        "category": "execution",
        "description": "Carrega plugins de plugins/ (hoje 0 plugins reais).",
        "source": "NV",
        "phase": "Fase 7.4",
        "status": ACTIVE,
        "path": "plugins/",
    },
    # --- INTEGRAÇÕES (Fase 5 + runtime) --------------------------------------
    {
        "id": "telegram-bot",
        "name": "Telegram Bot (@Nicky_Virthy_bot)",
        "category": "integrations",
        "description": "13 comandos do legado + voz (STT/TTS) + /executa (actions) + /capacidades.",
        "source": "Nicky",
        "phase": "Fase 5.1",
        "status": ACTIVE,
        "path": "integrations/telegram/",
    },
    {
        "id": "api-rest",
        "name": "API REST (porta 8000, X-API-Key)",
        "category": "integrations",
        "description": "Endpoints /message, /health, /metrics, /llms, /capabilities, history, RAG... (WebSocket /ws/chat = 501 registrado).",
        "source": "Nicky",
        "phase": "Fase 5.2",
        "status": ACTIVE,
        "path": "integrations/api/",
    },
    {
        "id": "notifier",
        "name": "ProactiveNotifier (health + alertas anti-spam)",
        "category": "integrations",
        "description": "Sondas (LLM offline, disco, restart) com cooldown 1/hora. IMPLEMENTADO mas não iniciado no launcher (dormente).",
        "source": "Nicky",
        "phase": "Fase 5.3",
        "status": DORMANT,
        "path": "integrations/notifier.py",
    },
    {
        "id": "iot-manager",
        "name": "IoT Manager (Home Assistant)",
        "category": "integrations",
        "description": "Leitura/controle de entidades HA (taxonomia ambiental, gate de segurança). Cliente disponível; presença já usa o HA.",
        "source": "Nexus",
        "phase": "Fase 5.4",
        "status": AVAILABLE,
        "path": "integrations/homeassistant/",
    },
    {
        "id": "mqtt-bridge",
        "name": "MQTT Bridge (Mosquitto 127.0.0.1:1883)",
        "category": "integrations",
        "description": "Wire protocol MQTT 3.1.1 stdlib; assina od/in/# e roteia ao Event Bus.",
        "source": "Nexus",
        "phase": "Fase 5.5",
        "status": ACTIVE,
        "path": "integrations/mqtt/",
    },
    {
        "id": "control-bridge",
        "name": "Control Bridge (127.0.0.1:8765, usuário odrunner)",
        "category": "integrations",
        "description": "Ponte local de execução restrita (allowlist + escopo + auditoria). Serviço systemd ATIVO; sem cliente interno no OD ainda.",
        "source": "OD",
        "phase": "Runtime",
        "status": ACTIVE,
        "path": "runtime/control_bridge/",
    },
    # --- SENSORIAL (Fase 6) --------------------------------------------------
    {
        "id": "face-detection",
        "name": "Face Detection (webcam + OpenCV)",
        "category": "sensorial",
        "description": "Haar + CLAHE + buffer de confirmação. Off por default (OD_VISION_ENABLED=0).",
        "source": "Nicky",
        "phase": "Fase 6.1",
        "status": PARTIAL,
        "path": "tools/vision/face_detector.py",
    },
    {
        "id": "presence-monitor",
        "name": "Presence Monitor (HA person/device_tracker)",
        "category": "sensorial",
        "description": "Detecta chegada/saída e notifica o admin no Telegram.",
        "source": "Nicky",
        "phase": "Fase 6.2",
        "status": ACTIVE,
        "path": "integrations/homeassistant/presence.py",
    },
    {
        "id": "stt",
        "name": "STT (whisper.cpp)",
        "category": "sensorial",
        "description": "Transcrição de voz no bot; ativo quando os binários existem (auto-detectado).",
        "source": "Nicky",
        "phase": "Fase 6.3",
        "status": AVAILABLE,
        "path": "tools/audio/stt.py",
    },
    {
        "id": "tts",
        "name": "TTS (Piper, vozes por perfil)",
        "category": "sensorial",
        "description": "Respostas por voz no bot; ativo quando os binários existem.",
        "source": "Nicky",
        "phase": "Fase 6.4",
        "status": AVAILABLE,
        "path": "tools/audio/tts.py",
    },
    {
        "id": "profiles",
        "name": "Profile Manager (6 perfis + detecção automática)",
        "category": "sensorial",
        "description": "guardian/regulus/luma/vox/athenae/nyx com detecção por domínio.",
        "source": "Nicky",
        "phase": "Fase 6.5",
        "status": ACTIVE,
        "path": "agents/profiles.py",
    },
    {
        "id": "llm-provider",
        "name": "LLM local (gemma-4-E4B via llama-server 127.0.0.1:8081)",
        "category": "sensorial",
        "description": "OpenAICompatProvider (stdlib) com identidade Nicky Virthy.",
        "source": "Nexus",
        "phase": "v0.16.0",
        "status": ACTIVE,
        "path": "core/llm.py",
    },
    # --- OBSERVABILIDADE (Fase 7) ---------------------------------------------
    {
        "id": "audit",
        "name": "Audit System (JSONL persistente, rotação)",
        "category": "observability",
        "description": "Toda decisão de segurança registrada (allowed/denied).",
        "source": "Nexus",
        "phase": "Fase 7.1",
        "status": ACTIVE,
        "path": "observability/audit.py",
    },
    {
        "id": "metrics",
        "name": "Metrics Collector (Prometheus text format)",
        "category": "observability",
        "description": "Métricas od_* + fontes vivas (orchestrator/audit/uptime); GET /metrics.",
        "source": "Nicky",
        "phase": "Fase 7.2",
        "status": ACTIVE,
        "path": "observability/metrics.py",
    },
    {
        "id": "health",
        "name": "Health Check por componente (up/degraded/down)",
        "category": "observability",
        "description": "Checks críticos (orchestrator/llm) e não-críticos (audit/metrics/database).",
        "source": "NV",
        "phase": "Fase 7.3",
        "status": ACTIVE,
        "path": "observability/health.py",
    },
    {
        "id": "database-layer",
        "name": "Database Layer (SQLite stdlib, pool + transações + Repository)",
        "category": "observability",
        "description": "data/od.db com pool por fila, transações com afinidade e CRUD genérico.",
        "source": "NV",
        "phase": "Fase 7.5",
        "status": ACTIVE,
        "path": "storage/database.py",
    },
    # --- RUNTIME -------------------------------------------------------------
    {
        "id": "launcher",
        "name": "Launcher (modos api|telegram|mqtt|presence|vision|all|capabilities)",
        "category": "runtime",
        "description": "Sobe o od-core com Audit/Metrics/Health/DB/Plugins/ActionRegistry; systemd od-core + od-llm ativos.",
        "source": "OD",
        "phase": "Runtime",
        "status": ACTIVE,
        "path": "runtime/launcher.py",
    },
    {
        "id": "systemd",
        "name": "Serviços systemd (od-core, od-llm, od-control-bridge)",
        "category": "runtime",
        "description": "Auto-start no boot (units de usuário + unit de sistema da Bridge).",
        "source": "OD",
        "phase": "Runtime",
        "status": ACTIVE,
        "path": "runtime/systemd/",
    },
]

# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

VALID_STATUSES = frozenset({ACTIVE, AVAILABLE, PARTIAL, DORMANT})

_CATEGORY_LABELS: dict[str, str] = {
    "core": "Core",
    "memory": "Memória",
    "orchestration": "Orquestração",
    "execution": "Execução",
    "integrations": "Integrações",
    "sensorial": "Sensorial",
    "observability": "Observabilidade",
    "runtime": "Runtime",
}

_STATUS_LABELS: dict[str, str] = {
    ACTIVE: "🟢 ativa no runtime",
    AVAILABLE: "🟡 disponível (sem auto-start)",
    PARTIAL: "🟠 parcialmente exposta",
    DORMANT: "⚪ dormente (implementada, sem trigger)",
}


def _actions_summary() -> dict[str, Any]:
    """Resumo do catálogo de actions (56) com categorias — leitura lazily
    para evitar ciclos de import; degrada para contagem estática."""
    try:
        from tools.actions import ACTIONS_COUNT, CATEGORIES
        categories = dict(CATEGORIES)
    except Exception:  # pragma: no cover — ambiente sem catálogo
        return {"count": 56, "categories": {}, "note": "catálogo indisponível"}
    return {"count": int(ACTIONS_COUNT), "categories": categories}


def capabilities_manifest(now: Optional[datetime] = None) -> dict[str, Any]:
    """Manifesto completo das capacidades do sistema (JSON-serializável)."""
    if now is None:
        now = datetime.now(timezone.utc)
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for cap in CAPABILITIES:
        by_status[cap["status"]] = by_status.get(cap["status"], 0) + 1
        by_category[cap["category"]] = by_category.get(cap["category"], 0) + 1
    actions = _actions_summary()
    dormant = sorted(
        c["id"] for c in CAPABILITIES if c["status"] == DORMANT
    )
    return {
        "system": "Omega Drakon",
        "version": OD_VERSION,
        "generated_at": now.isoformat(),
        "roadmap": {
            "capacities": "37/37",
            "phases": "Fases 1–7 concluídas (2026-09-04)",
            "status_geral": "implementado; loop de auto-recuperação dormente",
        },
        "counts": {
            "capabilities": len(CAPABILITIES),
            "by_status": by_status,
            "by_category": by_category,
            "actions": actions["count"],
        },
        "actions": actions,
        "capabilities": [dict(c) for c in CAPABILITIES],
        "dormant": dormant,
        "integrations": {
            "api": "http://0.0.0.0:8000 (X-API-Key)",
            "telegram": "@Nicky_Virthy_bot",
            "llm": "127.0.0.1:8081 (gemma-4-E4B, OpenAI-compat)",
            "mqtt": "127.0.0.1:1883 (Mosquitto)",
            "home_assistant": "http://<host>:8123",
            "control_bridge": "http://127.0.0.1:8765",
        },
        "runtime": {
            "modes": ["api", "telegram", "mqtt", "presence", "vision", "all", "capabilities"],
            "services": ["od-core.service", "od-llm.service", "od-control-bridge.service"],
            "vision": "off por default (OD_VISION_ENABLED=0)",
            "plugins": "0 plugins reais (sistema pronto para receber)",
        },
        "auto_recovery": {
            "loop_fechado": False,
            "dormentes": dormant,
            "para_ativar": [
                "self-repair: iniciar SelfRepairEngine no launcher (ciclo periódico)",
                "auto-extension: expor action/trigger para gerar ferramenta via LLM",
                "perception: coletar Telemetry.collect() e alimentar health/self-repair",
                "notifier: iniciar ProactiveNotifier com sink Telegram no launcher",
            ],
        },
    }


def render_text() -> str:
    """Resumo legível (Telegram/CLI) das capacidades do sistema."""
    m = capabilities_manifest()
    counts = m["counts"]
    lines = [
        f"🐉 *OMEGA DRAKON — Capacidades* (v{m['version']})",
        "",
        f"Roadmap: {m['roadmap']['capacities']} capacidades · "
        f"{counts['actions']} actions · {counts['capabilities']} componentes",
        "",
        "*Por categoria:*",
    ]
    for cat in ("core", "memory", "orchestration", "execution",
                "integrations", "sensorial", "observability", "runtime"):
        n = counts["by_category"].get(cat, 0)
        lines.append(f"  • {_CATEGORY_LABELS.get(cat, cat)}: {n}")
    lines.append("")
    lines.append("*Por status:*")
    for status in (ACTIVE, AVAILABLE, PARTIAL, DORMANT):
        n = counts["by_status"].get(status, 0)
        lines.append(f"  {_STATUS_LABELS.get(status, status)}: {n}")
    if m["dormant"]:
        lines.append("")
        lines.append("*Dormentes (auto-recuperação sem trigger):* "
                     + ", ".join(m["dormant"]))
        lines.append("  → o loop de auto-recuperação NÃO está fechado no runtime")
    lines.append("")
    lines.append("Consulte: `GET /capabilities` (X-API-Key) · "
                 "`python runtime/launcher.py capabilities` · "
                 "`docs/CAPACIDADES.md`")
    return "\n".join(lines)


def render_json(indent: int = 2) -> str:
    """Manifesto em JSON (para CLI/consumo externo)."""
    return json.dumps(capabilities_manifest(), indent=indent, ensure_ascii=False)


__all__ = [
    "ACTIVE",
    "AVAILABLE",
    "PARTIAL",
    "DORMANT",
    "OD_VERSION",
    "CAPABILITIES",
    "capabilities_manifest",
    "render_text",
    "render_json",
]