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
| Actions no catálogo | **57** (sistema/processo/docker/serviços/arquivos/git/db/introspecção/rede) |
| Componentes inventariados | **40** |
| Loop de auto-recuperação | ✅ **FECHADO** (RecoveryLoop ativo — v0.27.4) |
| Runtime de produção | od-core + od-llm + od-control-bridge (systemd ativos) |

**Status de ativação:** 🟢 ativa no runtime (34) · 🟡 disponível, sem
auto-start (5) · 🟠 parcialmente exposta (1) · ⚪ dormente (0).

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
| Action Registry (57) + Orchestrator (`execute_action` + fast path) | `tools/registry.py` · `core/orchestrator.py` · `core/intents.py` |
| Catálogo de 57 Actions (incl. `network_hosts`) | `tools/actions/` |
| Coder Engine (auto-reparo via RecoveryLoop) | `core/coder.py` |
| Self Repair (ciclo periódico do RecoveryLoop) | `core/self_repair.py` |
| Perception Syncer (Telemetry periódica → health) | `tools/telemetry.py` |
| Auto Extension (trigger `/gerar` no bot) | `tools/auto_extension/` |
| RecoveryLoop (percepção + auto-reparo cíclico) | `core/recovery.py` |
| ProactiveNotifier (sink Telegram, estado persistido) | `integrations/notifier.py` |
| Plugin System (0 plugins reais) | `plugins/` |
| Telegram Bot (13 comandos + voz + /executa + /capacidades + /gerar) | `integrations/telegram/` |
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
| Face Detection | `tools/vision/face_detector.py` | off por default (`OD_VISION_ENABLED=0`) |
| API WebSocket `/ws/chat` | `integrations/api/` | 501 registrado (exige servidor async) |

> ⚪ **Nenhum componente dormente desde a v0.27.4** — o loop de
auto-recuperação está fechado (ver §4).

---

## 3. Inventário por Categoria

### Core (6) — Fase 1
config-manager · security-layer · logger · event-bus · state-manager ·
message-router

### Memória (5) — Fase 2
history · cache · quick-responses · vector-rag · context

### Orquestração (4) — Fase 3
workflows 🟡 · tool-loader 🟡 · action-registry · orchestrator

### Execução (7) — Fase 4 + 6.6 + 7.4 + v0.27.4
actions-catalog · coder-engine · self-repair · perception · auto-extension ·
recovery-loop · plugin-system

### Integrações (6) — Fase 5 + runtime
telegram-bot · api-rest · notifier · iot-manager 🟡 · mqtt-bridge ·
control-bridge

### Sensorial (6) — Fase 6
face-detection 🟠 · presence-monitor · stt 🟡 · tts 🟡 · profiles ·
llm-provider

### Observabilidade (4) — Fase 7
audit · metrics · health · database-layer

### Runtime (2)
launcher · systemd

---

## 4. Auto-recuperação — loop FECHADO (v0.27.4) ✅

O objetivo declarado do sistema é **se auto recriar e analisar o ambiente**.
Desde a v0.27.4 o ciclo roda no runtime via **RecoveryLoop**
(`core/recovery.py`), em thread daemon no launcher (modo `all`, intervalo
default 300s — `OD_RECOVERY_INTERVAL_S`):

```
Perceber (Telemetry.collect periódica) → Decidir (detecção determinística)
→ Agir (SelfRepair via Coder: sandbox→testes→backup→promoção)
→ Verificar (re-detecção pós-reparo + rollback automático)
        🟢 ativo                            🟢 ativo
```

O que **o loop faz a cada ciclo**:
1. **Percepção** — `Telemetry.collect()` (CPU/mem/disco/rede/portas/docker/
   processos) → check `perception` no Health Monitor (não-crítico: erro de
   sonda degrada, nunca derruba) + evento `perception.snapshot` no audit;
2. **Auto-reparo** — varre os `.py` do projeto (fora de `.venv`/`.git`/`data`/
   `logs`/backups), detecta falhas (compile determinístico) e repara via
   SelfRepairEngine mediado pelo Coder Engine — **conservador por
   construção**: só estratégias determinísticas (ex: AddMissingColon);
   correções LLM não entram sem o pipeline do Coder;
3. **Verificação** — relatório por ciclo (`files_scanned`, `detections`,
   `repairs_applied/failed`) + `recovery.tick` no Event Bus; falhas em
   qualquer etapa nunca derrubam o ciclo (métricas + isolamento).

**Fast path de respostas instantâneas (v0.27.5):** perguntas operacionais
em PT-BR respondem SEM LLM, em milissegundos — "quantas pessoas estão
conectadas na rede?" executa `network_hosts` (ARP), "quanta memória está
em uso?" executa `memory_usage`, "quanto é 2+2*3?" é avaliado com
matemática segura (ast). Detecção determinística em `core/intents.py`
(etapa 3.5 do pipeline), restrita a actions de LEITURA; sem
ActionRegistry ou com falha, a mensagem cai para o LLM normalmente.

Além do ciclo, o trigger de criação de ferramentas está exposto:
- **`/gerar <nome> <descrição>`** (admin) — Auto Extension gera via LLM,
  valida (compile + allowlist de imports) e registra com permission
  `auto_extension.generated` (gate do Security Layer); execute depois com
  `/executa auto.<nome>`;
- **ProactiveNotifier** ativo com sink Telegram (alertas de LLM offline /
  disco / restart, anti-spam 1/hora, estado em `data/notifier_state.json`).

Desligar (se necessário): `OD_SELF_REPAIR_ENABLED=0` e/ou
`OD_NOTIFIER_ENABLED=0` no `.env`.

> O manifesto (`core/capabilities.py`) reporta `auto_recovery.loop_fechado:
> true` e `dormant: []` — zero componentes dormentes.

---

## 5. Actions (56) — resumo por categoria

| Categoria | Qtd | Exemplos |
|---|---|---|
| sistema | 14 | system_info, uptime, disk_usage, system_env, network_hosts... |
| processo | 4 | process_list/info/kill + process_tree |
| docker | 4 | docker_list/status/logs/stats |
| serviço | 3 | service_list/status/logs |
| arquivos | 15 | filesystem_read/write/search/tree/archive... |
| git | 10 | git_status/commit/diff/push... |
| banco | 3 | database_tables/schema/query |
| introspecção | 4 | action_list/info/schema/validate |

Detalhe por action (NV → OD, excluídas e renomeadas): ver
`docs/ACTIONS_CORRESPONDENCIA.md`. `network_hosts` é complementar OD
(v0.27.5) e alimenta o **fast path de intenções** (§4).

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
- `docs/CHANGELOG.md` — [0.27.5] (fast path + network_hosts) · [0.27.4]
  (loop fechado) · [0.27.3] (manifesto)

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