# NV RUNTIME — ANÁLISE COMPLETA DO SISTEMA

> **Status:** Documentação de Análise
> **Data:** 2026-09-02
> **Origem:** Leitura direta do código-fonte em `/home/alex/NV`
> **Versão analisada:** v1.11.0-operational-hardening
> **Assinatura:** `OD // CORE`

---

## 1. Resumo Executivo

O **NV Runtime** (Nicky Virthy Runtime Cognitivo Modular) é uma plataforma modular para execução local de agentes inteligentes. Diferente do Nicky (monólito orientado a conversação), o NV é um **runtime operacional** focado em:
- execução controlada de **56 actions** operacionais (sistema, arquivos, git, docker, db, processos)
- **Security Layer** com pipeline de validação (policy → permission → scope → approval → audit)
- **Workflow Engine** para orquestração de pipelines (linear + DAG + nested + scheduler)
- **Coder Engine** para modificação segura de código (sandbox → patch → validação → backup → promoção)
- **Plugin System** para extensibilidade dinâmica
- **API REST** (FastAPI) na porta 7001

O sistema está **operacional** com a API rodando via `nv-api.service`.

---

## 2. Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                     RUNTIME KERNEL                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │Config    │  │State     │  │Registry  │  │Service     │  │
│  │Runtime   │  │Runtime   │  │Services  │  │Container   │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │Event     │  │Action    │  │Memory    │  │Session     │  │
│  │System    │  │System    │  │Layer     │  │Layer       │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │Database  │  │Provider  │  │Plugin    │  │Workflow    │  │
│  │Layer     │  │Layer     │  │Layer     │  │Engine      │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────────┐  │
│  │Coder     │  │Security  │  │Tool Runtime (56 actions) │  │
│  │Engine    │  │Layer     │  │system,fs,git,docker,db   │  │
│  └──────────┘  └──────────┘  └──────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────┐   │
│  │              API Layer (FastAPI :7001)                 │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Módulos Detalhados

### 3.1 Runtime Kernel (`core/runtime/kernel.py`)

O_kernel_ é o orquestrador central. Inicializa todos os subsistemas e os registra no `ServiceContainer`.

**Componentes inicializados:**
- `RuntimeConfig` — configuração do runtime
- `ServiceContainer` — container de DI (dependency injection)
- `EventBus` — sistema de eventos interno
- `RuntimeState` — estado do runtime
- `PluginLoader` — carregamento dinâmico de plugins
- `ProviderManager` — gerenciamento de providers LLM
- `SessionManager` — gerenciamento de sessões
- `ActionManager` — executor central de actions (com SecurityManager integrado)
- `DatabaseManager` — camada de persistência
- `MemoryManager` — memória persistente e contextual
- `SessionHistory` — histórico de sessões
- `CoderEngine` — engine de modificação segura de código
- `WorkflowManager` — orquestração de workflows

### 3.2 Event System (`core/events/`)

- Pub/sub assíncrono
- Eventos tipados: `SYSTEM_BOOT`, `SYSTEM_SHUTDOWN`, `PLUGIN_DISCOVERED`, `WORKFLOW_STARTED`, `WORKFLOW_COMPLETED`, `ACTION_EXECUTED`, `ACTION_FAILED`
- Desacoplamento entre módulos

### 3.3 Action System (`core/actions/`)

- **56 actions operacionais** organizadas em categorias:
  - **Sistema:** `system_info`, `datetime`, `uptime`, `disk_usage`, `memory_usage`, `cpu_info`, `ip_address`, `system_which`, `system_hostname`, `system_env`, `system_ping`, `system_user`, `system_groups`
  - **Processos:** `process_list`, `process_info`, `process_kill`
  - **Docker:** `docker_list`, `docker_status`, `docker_logs`, `docker_stats`
  - **Serviços:** `service_list`, `service_status`, `service_logs`
  - **Arquivos:** `filesystem_search`, `filesystem_read`, `filesystem_write`, `filesystem_delete`, `filesystem_exists`, `filesystem_info`, `filesystem_list`, `filesystem_mkdir`, `filesystem_move`, `filesystem_copy`, `filesystem_touch`, `filesystem_tree`, `filesystem_hash`, `filesystem_archive`, `filesystem_extract`
  - **Git:** `git_branch`, `git_status`, `git_commit`, `git_add`, `git_log`, `git_diff`, `git_checkout`, `git_fetch`, `git_pull`, `git_push`
  - **Banco de Dados:** `database_tables`, `database_schema`, `database_query`
  - **Introspecção:** `action_info`, `action_schema`, `action_validate`

- **ActionManager** valida cada ação via SecurityManager antes de executar

### 3.4 Security Layer (`core/security/`)

Pipeline de validação em 5 camadas:

```
Action Request
      │
      ▼
┌─────────────┐
│Policy Engine│ → Regras globais (allowed/denied patterns)
└──────┬──────┘
       │
       ▼
┌────────────────┐
│Permission Engine│ → Roles e permissões por action
└──────┬─────────┘
       │
       ▼
┌─────────────┐
│ Scope Engine │ → Escopo filesystem e operacional
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│Approval Engine  │ → Aprovação humana (desativado por padrão)
└──────┬──────────┘
       │
       ▼
┌─────────────┐
│ Audit Engine │ → Registro de todas as decisões
└─────────────┘
```

**Modos de enforcement:**
- `compatibility` — apenas audit (padrão)
- `soft` — audit + warn mas permite
- `strict` — fail-closed (bloqueia se qualquer camada rejeitar)

**Configuração via YAML:**
- `config/security/enforcement.yaml`
- `config/security/permissions.yaml`
- `config/security/scopes.yaml`
- `config/security/approval.yaml`

### 3.5 Workflow Engine (`core/workflows/`)

- Execução linear de workflows com steps
- Suporte a **branching** condicional (`if_true_next` / `if_false_next`)
- **Sub-workflows** (nested)
- **Retries** automáticos com delay configurável
- **Timeouts** por step
- **Persistência** de execuções via `WorkflowExecutionsRepository`
- **Contexto isolado** por execução (`WorkflowContext`)

### 3.6 Coder Engine (`core/coder.py`)

Pipeline de modificação segura de código:

```
Arquivo Original
      │
      ▼
┌──────────┐
│ Sandbox  │ → Cópia isolada para modificação
└────┬─────┘
     │
     ▼
┌──────────┐
│ Patch    │ → Aplicação da modificação
└────┬─────┘
     │
     ▼
┌──────────────┐
│ Validação    │ → Análise sintática + testes
└────┬─────────┘
     │
     ▼
┌──────────┐
│ Backup   │ → Snapshot do estado anterior
└────┬─────┘
     │
     ▼
┌──────────┐
│ Promoção │ → Aplicação ao código real
└──────────┘

Em caso de erro:
Sandbox → Erro → Rollback → Arquivo Original Preservado
```

### 3.7 Database Layer (`core/database/`)

- `DatabaseManager` — gerenciamento de conexões
- `DatabaseConnection` — pool de conexões
- **Repositórios:**
  - `KeyValueRepository` — armazenamento chave-valor
  - `MessagesRepository` — mensagens de sessão
  - `WorkflowExecutionsRepository` — execuções de workflows
- **Migrations** — schema management
- Backend: MariaDB (via `mysql-connector-python`)

### 3.8 Memory Layer (`core/memory/`)

- `MemoryManager` — gerenciamento central de memória
- `ProfileMemory` — memória por perfil de agente
- `RuntimeMemory` — memória de runtime
- **Fact Extraction** — extração de fatos
- **Resolver** — resolução de informações

### 3.9 Provider Layer (`llm/`)

- `ProviderManager` — gerenciamento de providers
- `LlamaCppProvider` — integração com llama-server (porta 8081)
- `ProviderRequest` / `Message` — modelos de request
- `build_system_prompt()` — construction de system prompts

### 3.10 Plugin Layer (`plugins/`)

- `PluginLoader` — carregamento dinâmico de plugins
- Subdiretórios: `actions/`, `providers/`, `workflows/`, `integrations/`
- `register_actions()` — registro de actions de plugins
- `register_workflows()` — registro de workflows de plugins

### 3.11 API Layer (`interfaces/api/`)

- FastAPI na porta **7001**
- CORS configurável
- Rate limiting
- Endpoints operacionais

### 3.12 Observability (`observability/`)

- `logging/` — sistema de logging
- `audit/` — trilhas de auditoria
- `health/` — health checks
- `tracing/` — distributed tracing
- `metrics/` — métricas operacionais

---

## 4. Dependências

### 4.1 Core
- `fastapi` + `uvicorn`
- `pydantic` 2.13.4
- `sqlalchemy` 2.0.50 + `aiosqlite` 0.22.1
- `httpx` 0.28.1
- `python-dotenv` 1.2.2
- `psutil` 7.2.2
- `mysql-connector-python` 9.7.0
- `PyYAML` ≥ 6.0

---

## 5. Pontos Fortes

1. **Arquitetura modular extrema** — Cada subsystem é um módulo independente com responsabilidade única.
2. **Security Layer robusto** — Pipeline de 5 camadas com enforcement configurável (compatibility/soft/strict).
3. **56 actions operacionais** — Cobertura ampla de operações de sistema, arquivos, git, docker, db.
4. **Workflow Engine completo** — Branching, nested workflows, retries, timeouts, persistência.
5. **Coder Engine** — Modificação segura de código com sandbox, validação, backup e rollback.
6. **Service Container** — DI container para desacoplamento.
7. **Plugin System** — Extensibilidade dinâmica via carregamento de plugins.
8. **Testes extensivos** — 100+ testes unitários cobrindo actions, security, workflows, etc.
9. **Observabilidade** — Logging, audit, health, tracing, metrics.
10. **API REST documentada** — FastAPI com OpenAPI spec.

---

## 6. Problemas e Dívida Técnica

### 6.1 Arquiteturais

| Problema | Impacto |
|---|---|
| **Acoplamento ao Nicky** — Imports de `config.settings` do Nicky | Impossível rodar independentemente |
| **MariaDB via mysql-connector** — Diferente do aiomysql do Nicky | Pool de conexão separado |
| **Sem Event Bus compartilhado** — EventBus próprio do NV | Não se comunica com o Nicky |
| **Singletons implícitos** — ServiceContainer global | Testes difíceis |

### 6.2 De Código

| Problema | Local |
|---|---|
| **Código duplicado** — `_execute_step` tem return duplicado no final | `core/workflows/engine.py` |
| **Imports circulares potenciais** — Muitos imports locais dentro de funções | Diversos |
| **Error handling genérico** — `except Exception` em vários locais | Diversos |
| **Documentação inconsistente** — Algumas seções com formatação quebrada | `docs/README.md` |

### 6.3 De Segurança

| Problema | Risco |
|---|---|
| **Approval desativado** — `approval: False` por padrão | Ações executam sem aprovação humana |
| **Scope não validado** — Scope engine existe mas pode não ter regras | Acessos fora do escopo |
| **API sem auth** — `/v1/tools/execute` sem autenticação | Execução remota de qualquer action |

---

## 7. Endpoints da API (Porta 7001)

| Método | Path | Descrição |
|---|---|---|
| POST | `/v1/chat/completions` | Proxy para llama-server |
| GET | `/v1/tools` | Lista ferramentas registradas |
| POST | `/v1/tools/execute` | Executa uma ferramenta |
| GET | `/v1/tools/reload` | Hot-reload das ferramentas |

---

## 8. Testes

- **100+ testes** em `tests/`
- `test_action_*.py` — actions individuais (30+ arquivos)
- `test_security_*.py` — security layer
- `test_workflow_*.py` — workflow engine
- `test_runtime_*.py` — runtime components
- `test_database_*.py` — database layer
- `test_memory_*.py` — memory layer

---

## 9. Mapeamento para OmegaDrakon

> **Status (atualizado em 2026-09-04):** todas as capacidades abaixo foram
> absorvidas e implementadas no OmegaDrakon — ver `docs/ROADMAP_ABSORCAO.md`
> (37/37 capacidades, 1382 testes).

| Capacidade NV | Destino OmegaDrakon | Status |
|---|---|---|
| Event System | `core/event_bus.py` | ✅ Reescrito |
| Security Layer | `core/security/` | ✅ Implementado (Fase 1.2) |
| Action System (56 actions) | `tools/actions/` + `tools/registry.py` | ✅ Implementado (Fase 4.4) |
| Workflow Engine | `core/workflows.py` | ✅ Implementado (Fase 3.1) |
| Coder Engine | `core/coder.py` | ✅ Implementado (Fase 4.1) |
| Memory Layer | `memory/` | ✅ Implementado (Fase 2) |
| Database Layer | `storage/database.py` | ✅ Implementado (Fase 7.5) |
| Plugin System | `plugins/` | ✅ Implementado (Fase 7.4) |
| API Layer | `integrations/api/` | ✅ Implementado (Fase 5.2) |
| Observability | `observability/` | ✅ Implementado (Fase 7) |

---

## 10. Recomendações para Absorção

1. **Prioridade 1:** Security Layer → extrair pipeline de validação para `core/security/`.
2. **Prioridade 2:** Action System → absorver as 56 actions para `tools/`.
3. **Prioridade 3:** Workflow Engine → absorver para `core/workflows.py`.
4. **Prioridade 4:** Coder Engine → absorver para `core/coder.py`.
5. **Prioridade 5:** Memory Layer → absorver para `memory/`.
6. **Prioridade 6:** Database Layer → absorver para `storage/`.

**Diferença-chave:** O NV é o sistema mais "engenheiro" do ecossistema — sua.forceza está na execução controlada de ações e na security layer. O Nicky é o "conversacional". O OmegaDrakon deve unir ambos.

---

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/NV_LEGACY_ANALYSIS.md
Descrição: Análise completa do sistema legado NV Runtime v1.11.0.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```
