# OMEGA DRAKON — CAPACIDADES DO SISTEMA

> **Status:** Documento de Referência (vigente)
> **Data:** 2026-09-04
> **Fonte de verdade:** `core/capabilities.py` (manifesto) — este documento
> é a visão humana; o estado **atual** é consultável em runtime por:
> - **CLI:** `.venv/bin/python -m runtime.launcher capabilities` (JSON)
> - **API:** `GET /capabilities` com header `X-API-Key`
> - **Bot:** `/capacidades` (admin) no @Nicky_Virthy_bot
> - **Código:** `from core.capabilities import capabilities_manifest`
> **Assinatura:** `OD // CORE`

---

## 1. Resumo Executivo

| Métrica | Valor |
|---|---|
| Capacidades do roadmap | **37/37** (Fases 1–7 concluídas) |
| Actions no catálogo | **56** (sistema/processo/docker/serviços/arquivos/git/db/introspecção) |
| Componentes inventariados | **39** |
| Loop de auto-recuperação | ❌ **NÃO fechado** (componentes dormentes, sem trigger) |
| Runtime de produção | od-core + od-llm + od-control-bridge (systemd ativos) |

**Status de ativação:** 🟢 ativa no runtime (28) · 🟡 disponível, sem
auto-start (5) · 🟠 parcialmente exposta (2) · ⚪ dormente, implementada sem
trigger (4).

---

## 2. Por Status de Ativação

### 🟢 ATIVAS no od-core (produção, launcher modo `all`)

| Capacidade | Caminho |
|---|---|
| Config Manager | `configs/manager.py` |
| Security Layer | `core/security/` |
| Logger NICKY | `core/logger.py` |
| Event Bus / State Manager / Message Router | `core/` |
| Memória (history, cache, quick, RAG, context) | `memory/` |
| Action Registry (56) + Orchestrator (`execute_action`) | `tools/registry.py` · `core/orchestrator.py` |
| Catálogo de 56 Actions | `tools/actions/` |
| Plugin System (0 plugins reais) | `plugins/` |
| Telegram Bot (13 comandos + voz + /executa + /capacidades) | `integrations/telegram/` |
| API REST (8000, X-API-Key, 18 rotas) | `integrations/api/` |
| MQTT Bridge (Mosquitto) | `integrations/mqtt/` |
| Control Bridge (127.0.0.1:8765, odrunner) | `runtime/control_bridge/` |
| Presence Monitor (HA) | `integrations/homeassistant/presence.py` |
| Profile Manager (6 perfis) | `agents/profiles.py` |
| LLM local (gemma-4-E4B, 127.0.0.1:8081) | `core/llm.py` |
| Audit / Metrics / Health / Database | `observability/` · `storage/database.py` |
| Launcher + systemd | `runtime/launcher.py` · `runtime/systemd/` |

### 🟡 DISPONÍVEIS (implementadas + testadas, sem auto-start)

| Capacidade | Caminho | Como ativar |
|---|---|---|
| Workflow Engine | `core/workflows.py` | registrar workflows (plugins/contractos) |
| Tool Loader | `tools/loader.py` | usado por plugins/registry |
| IoT Manager (HA) | `integrations/homeassistant/` | cliente pronto; controle via código |
| STT (whisper.cpp) | `tools/audio/stt.py` | auto-detectado no bot se binários existirem |
| TTS (Piper) | `tools/audio/tts.py` | idem |

### 🟠 PARCIAIS

| Capacidade | Caminho | Limitação |
|---|---|---|
| Coder Engine | `core/coder.py` | `/codigo` só `status`/`arvore` (leitura); patch completo via lib |
| Face Detection | `tools/vision/face_detector.py` | off por default (`OD_VISION_ENABLED=0`) |
| API WebSocket `/ws/chat` | `integrations/api/` | 501 registrado (exige servidor async) |

### ⚪ DORMENTES (implementadas + testadas, SEM trigger no runtime)

| Capacidade | Caminho | O que falta |
|---|---|---|
| Self Repair | `core/self_repair.py` | iniciar `SelfRepairEngine` no launcher (ciclo/trigger) |
| Auto Extension | `tools/auto_extension/` | expor action/comando para gerar ferramenta via LLM |
| Perception Syncer | `tools/telemetry.py` | coletar `Telemetry.collect()` e alimentar health/self-repair |
| ProactiveNotifier | `integrations/notifier.py` | iniciar com sink Telegram no launcher |

---

## 3. Inventário por Categoria

### Core (6) — Fase 1
config-manager · security-layer · logger · event-bus · state-manager ·
message-router

### Memória (5) — Fase 2
history · cache · quick-responses · vector-rag · context

### Orquestração (4) — Fase 3
workflows 🟡 · tool-loader 🟡 · action-registry · orchestrator

### Execução (6) — Fase 4 + 6.6 + 7.4
actions-catalog · coder-engine 🟠 · self-repair ⚪ · perception ⚪ ·
auto-extension ⚪ · plugin-system

### Integrações (6) — Fase 5 + runtime
telegram-bot · api-rest · notifier ⚪ · iot-manager 🟡 · mqtt-bridge ·
control-bridge

### Sensorial (6) — Fase 6
face-detection 🟠 · presence-monitor · stt 🟡 · tts 🟡 · profiles ·
llm-provider

### Observabilidade (4) — Fase 7
audit · metrics · health · database-layer

### Runtime (2)
launcher · systemd

---

## 4. Auto-recuperação — o loop NÃO está fechado

O objetivo declarado do sistema é **se auto recriar e analisar o ambiente**.
Os blocos existem e estão testados, mas **nada os dispara no runtime**:

```
Perceber (telemetry) → Decidir (LLM) → Agir (auto-extension/coder) → Verificar (self-repair)
        ⚪ dormente         🟢 ativo            ⚪ dormente                  ⚪ dormente
```

O que **já funciona hoje**:
- Análise do ambiente **sob pedido**: `/executa system_info|process_list|disk_usage|...`
  (56 actions, leitura/controle com classificação de risco e gate de admin).
- Execução de ações via `Orchestrator.execute_action()` e pelo bot.
- Presença/MQTT/health/audit alimentando observabilidade em tempo real.

O que **falta** (caminho para fechar o loop):
1. **Perception**: coletar `Telemetry.collect()` periodicamente (ou sob pedido)
   e alimentar o Health Monitor e os oracles do Self Repair.
2. **Self Repair**: iniciar o `SelfRepairEngine` com um ciclo (ex.: a cada N
   minutos, como o `main_cycle` do Nexus) ou expor como action `/executa`.
3. **Auto Extension**: expor um trigger para gerar uma nova ferramenta via LLM
   (validação compile + allowlist + Security Layer já prontas).
4. **Notifier**: iniciar o `ProactiveNotifier` com sink Telegram (alertas de
   LLM offline/disco/restart já prontos).

> O manifesto (`core/capabilities.py`) reporta `auto_recovery.loop_fechado:
> false` e lista exatamente esses 4 itens — é o contrato do próximo trabalho.

---

## 5. Actions (56) — resumo por categoria

| Categoria | Qtd | Exemplos |
|---|---|---|
| sistema | 13 | system_info, uptime, disk_usage, system_env... |
| processo | 4 | process_list/info/kill + process_tree |
| docker | 4 | docker_list/status/logs/stats |
| serviço | 3 | service_list/status/logs |
| arquivos | 15 | filesystem_read/write/search/tree/archive... |
| git | 10 | git_status/commit/diff/push... |
| banco | 3 | database_tables/schema/query |
| introspecção | 4 | action_list/info/schema/validate |

Detalhe por action (NV → OD, excluídas e renomeadas): ver
`docs/ACTIONS_CORRESPONDENCIA.md`.

---

## 6. Como Consultar as Capacidades

```bash
# CLI — manifesto completo em JSON (rodar do raiz do repo)
.venv/bin/python -m runtime.launcher capabilities

# API — com chave
curl -H "X-API-Key: $OD_API_KEY" http://127.0.0.1:8000/capabilities

# Bot — /capacidades (admin) no @Nicky_Virthy_bot

# Código
python - <<'PY'
from core.capabilities import capabilities_manifest, render_text
print(render_text())
print(capabilities_manifest()["counts"])
PY
```

---

## 7. Referências

- `core/capabilities.py` — fonte de verdade do manifesto
- `docs/ROADMAP_ABSORCAO.md` — 37/37 capacidades, Fases 1–7
- `docs/ACTIONS_CORRESPONDENCIA.md` — catálogo de 56 actions (NV → OD)
- `docs/CHANGELOG.md` — [0.27.3] (esta entrega)

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/CAPACIDADES.md
Descrição: Inventário humano das capacidades do OmegaDrakon com status de
           ativação no runtime (active/available/partial/dormant).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```