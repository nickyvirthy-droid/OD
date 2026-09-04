# NEXUS LEGACY — ANÁLISE COMPLETA DO SISTEMA

> **Status:** Documentação de Análise
> **Data:** 2026-09-02
> **Origem:** Leitura direta do código-fonte em `/home/alex/nexus`
> **Versão analisada:** v1.9.2 (Plêiade)
> **Assinatura:** `OD // CORE`

---

## 1. Resumo Executivo

O **Nexus** (A Sétima Entidade da Plêiade) é um sistema de IA autônomo eauto-reparável focado em:
- **Percepção holística** de hardware, serviços e rede (telemetria + nmap)
- **Roteamento cognitivo** com LLM local (llama-server porta 8081)
- **Integração IoT** via Home Assistant (MQTT + REST API)
- **Auto-extensão** — gera novas ferramentas em tempo de execução via Gemini
- **Auto-cura** — detecta falhas e gera scripts de correção automaticamente
- **Ciclo operacional** autônomo (a cada 5 minutos)
- **Vox Messenger** — notificações via Telegram
- **Auditoria** de integridade do sistema

O sistema roda como 3 serviços systemd: `nexus.service`, `nexus-router.service`, `nexus-pulse.service`.

---

## 2. Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                    NEXUS PLÊIADE v1.9.2                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Nexus Core   │  │ Cognitive    │  │ Perception       │  │
│  │ (Orchestrator│  │ Router       │  │ Syncer           │  │
│  │  + Auto-Ext) │  │ (FastAPI)    │  │ (Telemetry)      │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────────┘  │
│         │                 │                  │              │
│         └─────────────────┼──────────────────┘              │
│                           │                                 │
│  ┌────────────────────────┼────────────────────────────┐    │
│  │              CORE SUBSYSTEMS                         │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │    │
│  │  │Brain     │  │Context   │  │IoT       │          │    │
│  │  │(LLM)    │  │Manager   │  │Manager   │          │    │
│  │  └──────────┘  └──────────┘  └──────────┘          │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │    │
│  │  │Storage   │  │Vox       │  │Auditor   │          │    │
│  │  │(Cache)   │  │Messenger │  │          │          │    │
│  │  └──────────┘  └──────────┘  └──────────┘          │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │    │
│  │  │Self      │  │Auto      │  │Tool      │          │    │
│  │  │Repair    │  │Extension │  │Loader    │          │    │
│  │  └──────────┘  └──────────┘  └──────────┘          │    │
│  └─────────────────────────────────────────────────────┘    │
│                           │                                 │
│  ┌────────────────────────┼────────────────────────────┐    │
│  │              INFRAESTRUTURA                          │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │    │
│  │  │Mosquitto │  │Home      │  │Llama     │          │    │
│  │  │MQTT      │  │Assistant │  │Server    │          │    │
│  │  └──────────┘  └──────────┘  └──────────┘          │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Módulos Detalhados

### 3.1 Nexus Core (`src/nexus_core.py`)

Orquestrador principal com **auto-extensão**:
1. Recebe pergunta do usuário
2. Verifica ferramentas disponíveis no `ToolLoader`
3. Se existe ferramenta → executa (`EXECUTE:<nome>`)
4. Se não existe → **gera nova ferramenta via Gemini** (`NEED_EXTENSION:<descricao>`)
5. Hot-reload do registro → executa a nova ferramenta

**Gemini** é usado como "motor de programação" para criar código Python em tempo real.

### 3.2 Cognitive Router (`src/router.py`)

FastAPI server com:
- `/v1/chat/completions` — Proxy para llama-server (porta 8081) com **gestão de truncamento de contexto**
- `/v1/tools` — Lista ferramentas registradas
- `/v1/tools/execute` — Executa uma ferramenta
- `/v1/tools/reload` — Hot-reload das ferramentas

**Context Manager** detecta saturação de memória e trunca histórico automaticamente.

### 3.3 Perception Syncer (`src/perception.py`)

Telemetria holística do servidor:
- **Hardware:** CPU, RAM, temperatura (via `psutil`)
- **Docker:** Status de todos os containers
- **Serviços locais:** Portas críticas (1883 Mosquitto, 8080 Router, 8081 LLM, 3306 MariaDB, 8123 HA)
- **Rede:** Varredura Nmap na sub-rede local
- **Análise de estabilidade:** Contagem consecutiva de anomalias (CPU > 80%, RAM > 90%)

### 3.4 Brain (`src/brain.py`)

Interface com o LLM local (llama-server porta 8081):
- System prompt definido em `config/system_prompt.md`
- Modelo: `qwen2.5-coder:7b`
- Análise de pulso do servidor → diagnóstico técnico

### 3.5 Main Cycle (`src/main_cycle.py`)

Motor de ciclo operacional autônomo (a cada 300s / 5 min):
1. Verifica integridade de contexto
2. Lê cache de estado IoT
3. Envia para LLM analisar anomalias
4. Se LLM detecta problema → gera código Python corretor
5. Salva em `sandbox/autocure_proposal.py`
6. Executa script de auto-cura
7. Notifica admin via Telegram

### 3.6 IoT Manager (`src/iot.py`)

Integração com Home Assistant:
- **Mapeamento ambiental** — taxonomia de entidades (atuadores, móveis, sensores, infra)
- **Leitura de estado** —查询 individual de entidades
- **Controle** — ligar/desligar dispositivos
- **Credenciais** em `config/iot_credentials.json`

### 3.7 Self Repair (`src/self_repair.py`)

Sensor de auto-reparo:
- Detecta **estouro de contexto** (memory overflow)
- Tenta **reset de memória curta**
- Se falhar → gera script de autocura via LLM

### 3.8 Context Manager (`src/context_manager.py`)

Gestão de contexto para o LLM:
- Análise de densidade de mensagens
- Truncamento inteligente de histórico
- Prevenção de estouro de janela de tokens

### 3.9 Vox Messenger (`src/vox_messenger.py`)

Notificações via Telegram:
- Envio de mensagens de status
- Alertas de auto-cura
- Relatórios de diagnóstico

### 3.10 Tool Loader (`src/tool_loader.py`)

Sistema de ferramentas dinâmicas:
- Carregamento automático de scripts Python de `src/tools/`
- Hot-reload em tempo de execução
- Registro centralizado de metadados

### 3.11 Auditor (`src/auditor.py`)

Auditoria de integridade:
- Verificação de arquivos do sistema
- Checagem de serviços
- Relatórios de conformidade

---

## 4. Serviços Systemd

| Serviço | Porta | Função |
|---|---|---|
| `nexus.service` | — | Motor de consciência (main_cycle.py, ciclo 5min) |
| `nexus-router.service` | 8080 | Router cognitivo + tool engine (FastAPI) |
| `nexus-pulse.service` | — | Perception syncer (telemetria) |

---

## 5. Dependências

- `fastapi` + `uvicorn`
- `httpx`
- `paho-mqtt` ≥ 2.0.0 (MQTT)
- `python-dotenv`
- `aiomysql`
- `psutil`
- `nmap` (python-nmap)
- `docker` (docker SDK)
- `google-genai` (Gemini API)

---

## 6. Configuração

| Arquivo | Conteúdo |
|---|---|
| `config/settings.json` | URL do llama-server, threshold de disco |
| `config/iot_credentials.json` | Token e URL do Home Assistant |
| `config/system_prompt.md` | System prompt do Nexus (identidade, regras, ferramentas) |
| `config/pleiade.yaml` | Configuração da plêiade |
| `config/mosquitto/` | Config do broker MQTT |

---

## 7. Pontos Fortes

1. **Auto-extensão** — Capacidade única de gerar novas ferramentas via Gemini em tempo real.
2. **Auto-cura** — Detecta falhas e gera scripts de correção automaticamente.
3. **Percepção holística** — Hardware, Docker, portas, rede (Nmap), IoT.
4. **Ciclo operacional autônomo** — Roda a cada 5 minutos sem intervenção humana.
5. **Integração IoT** — Home Assistant via REST + MQTT.
6. **Gestão de contexto** — Truncamento inteligente para evitar estouro de tokens.
7. **Vox Messenger** — Notificações proativas via Telegram.
8. **3 serviços systemd** — Isolamento de responsabilidades.
9. **Soberania local** — LLM local + HA local + MQTT local.

---

## 8. Problemas e Dívida Técnica

### 8.1 Críticos

| Problema | Impacto |
|---|---|
| **Gemini API para auto-extensão** | Se a API cair, o Nexus perde a capacidade de gerar código |
| **Auto-cura com `subprocess`** | Scripts gerados por LLM são executados sem sandbox robusto |
| **Loop crashando** — `nexus.service` em `activating auto-restart` | Serviço em crash-loop (visível no status do servidor) |
| **Sem autenticação** | API aberta para qualquer um na rede |
| **Sem persistência de estado** | Estado em JSON files frágeis |

### 8.2 Arquiteturais

| Problema | Impacto |
|---|---|
| **Monólito com imports circulares** | Dificulta manutenção |
| **Mistura de concerns** | nexus_core.py faz orquestração + auto-extensão + execução |
| **Sem testes formais** | Apenas `tests/` com 10 testes (vs 100+ do NV) |
| **Logs mal formatados** | F-strings com escape quebrado no main_cycle.py |
| **Gemini 3.5-flash** | Modelo descontinuado/renomeado |

### 8.3 De Código

| Problema | Local |
|---|---|
| **F-strings com escape quebrado** — `\\(` em vez de `(` | `src/main_cycle.py` |
| **Imports hardcoded** — `from tool_loader import registry` (sem path relativo) | `src/nexus_core.py` |
| **Error handling fraco** — `except:` sem捕获exceção | Diversos |
| **Variáveis de ambiente misturadas** — `os.getenv()` + `config/settings.json` | Diversos |

---

## 9. Scripts de Suporte

| Script | Função |
|---|---|
| `nexus_pack.py` | Empacota o projeto para deploy |
| `nexus_unpack.py` | Desempacota o projeto |
| `antigravity_bridge.py` | Bridge para agente Gemini (diagnóstico) |
| `test_inference.sh` | Teste de inferência do LLM |

---

## 10. Mapeamento para OmegaDrakon

> **Status (atualizado em 2026-09-04):** todas as capacidades abaixo foram
> absorvidas e implementadas no OmegaDrakon — ver `docs/ROADMAP_ABSORCAO.md`
> (37/37 capacidades, 1382 testes).

| Capacidade Nexus | Destino OmegaDrakon | Status |
|---|---|---|
| Perception Syncer | `tools/telemetry.py` | ✅ Implementado (Fase 4.3) |
| IoT Manager | `integrations/homeassistant/` | ✅ Implementado (Fase 5.4) |
| Context Manager | `memory/context.py` | ✅ Implementado (Fase 2.5) |
| Self Repair | `core/self_repair.py` | ✅ Implementado (Fase 4.2) |
| Auto Extension | `tools/auto_extension/` | ✅ Implementado (Fase 6.6) |
| Vox Messenger | `integrations/telegram/` | ✅ Implementado (Fase 5.1) |
| Tool Loader | `tools/loader.py` | ✅ Implementado (Fase 3.2) |
| Auditor | `observability/audit.py` | ✅ Implementado — decisões de segurança (spec §7.3); integridade de arquivos = evolução futura |
| Brain (LLM) | `core/llm.py` | ✅ Implementado (v0.16.0) |
| MQTT Broker | `integrations/mqtt/` | ✅ Implementado (Fase 5.5) |

---

## 11. Recomendações para Absorção

1. **Prioridade 1:** Perception Syncer → extrair telemetria para `tools/telemetry/`.
2. **Prioridade 2:** IoT Manager → absorver para `integrations/homeassistant/`.
3. **Prioridade 3:** Context Manager → absorver para `memory/`.
4. **Prioridade 4:** Vox Messenger → absorver para `integrations/telegram/`.
5. **Prioridade 5:** Self Repair → absorver para `core/` com sandbox robusto.
6. **Prioridade 6:** Auto Extension → absorver com validação rigorosa (Gemini API como opção, não obrigação).

**Alerta:** A capacidade de auto-extensão e auto-cura do Nexus é poderosa pero perigosa. No OmegaDrakon, deve ser mediada pelo Security Layer (NV) e pelo Validation Bus (core).

---

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/NEXUS_LEGACY_ANALYSIS.md
Descrição: Análise completa do sistema legado Nexus v1.9.2 (Plêiade).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```
