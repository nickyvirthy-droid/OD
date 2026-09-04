# OMEGA DRAKON — CORRESPONDÊNCIA DE ACTIONS (NV → OD)

> **Status:** Documento de Referência (vigente)
> **Data:** 2026-09-04
> **Origem:** Leitura direta de `~/NV/plugins/actions/` (legado NV v1.11.0) e
> `tools/actions/actions.py` (catálogo OD v0.27.x)
> **Assinatura:** `OD // CORE`

---

## 1. Resumo

O legado **NV** expõe **58 módulos de action** em `plugins/actions/` (59
entradas, incluindo o helper `loader.py`). Destes:

| Conta | Valor |
|---|---|
| Módulos de action no NV (`plugins/actions/`) | **58** |
| — implementados de verdade | 56 |
| — **stubs vazios (0 bytes)** | 2 (`database_backup`, `database_stats`) |
| Actions no catálogo OD (`tools/actions/`) | **56** |
| — portadas com o **mesmo nome** | 54 |
| — portadas com **nome alterado** | 1 (`list_actions` → `action_list`) |
| — **excluídas** | 3 (`system_exec`, `database_backup`, `database_stats`) |
| — **complementares** (não existiam no NV) | 1 (`process_tree`) |

**Conferência da conta:** 58 NV − 3 excluídas + 1 complementar = **56 OD** ✅

> **Correção histórica:** o CHANGELOG v0.11.0 registrou "54 ações enumeradas
> na análise legada + 2 complementares (process_tree, action_list)". A
> verificação direta do legado mostra que **action_list é renomeação** de
> `list_actions` (que existia no NV) — o único complementar real é
> `process_tree`. A conta final (56) está correta; a origem declarada não.

---

## 2. Tabela de Correspondência

### 2.1 Sistema (NV 14 → OD 13)

| NV (`plugins/actions/`) | OD (`tools/actions/`) | Status |
|---|---|---|
| `system_info` | `system_info` | ✅ Portada |
| `datetime` | `datetime` | ✅ Portada |
| `uptime` | `uptime` | ✅ Portada |
| `disk_usage` | `disk_usage` | ✅ Portada |
| `memory_usage` | `memory_usage` | ✅ Portada |
| `cpu_info` | `cpu_info` | ✅ Portada |
| `ip_address` | `ip_address` | ✅ Portada |
| `system_which` | `system_which` | ✅ Portada |
| `system_hostname` | `system_hostname` | ✅ Portada |
| `system_env` | `system_env` | ✅ Portada |
| `system_ping` | `system_ping` | ✅ Portada |
| `system_user` | `system_user` | ✅ Portada |
| `system_groups` | `system_groups` | ✅ Portada |
| `system_exec` | — | ❌ **Excluída** (§3.1) |

### 2.2 Processos (NV 3 → OD 4)

| NV | OD | Status |
|---|---|---|
| `process_list` | `process_list` | ✅ Portada |
| `process_info` | `process_info` | ✅ Portada |
| `process_kill` | `process_kill` | ✅ Portada |
| — | `process_tree` | ➕ Complementar (§4.2) |

### 2.3 Docker (NV 4 → OD 4)

| NV | OD | Status |
|---|---|---|
| `docker_list` | `docker_list` | ✅ Portada |
| `docker_status` | `docker_status` | ✅ Portada |
| `docker_logs` | `docker_logs` | ✅ Portada |
| `docker_stats` | `docker_stats` | ✅ Portada |

### 2.4 Serviços (NV 3 → OD 3)

| NV | OD | Status |
|---|---|---|
| `service_list` | `service_list` | ✅ Portada |
| `service_status` | `service_status` | ✅ Portada |
| `service_logs` | `service_logs` | ✅ Portada |

### 2.5 Arquivos (NV 15 → OD 15)

| NV | OD | Status |
|---|---|---|
| `filesystem_search` | `filesystem_search` | ✅ Portada |
| `filesystem_read` | `filesystem_read` | ✅ Portada |
| `filesystem_write` | `filesystem_write` | ✅ Portada |
| `filesystem_delete` | `filesystem_delete` | ✅ Portada |
| `filesystem_exists` | `filesystem_exists` | ✅ Portada |
| `filesystem_info` | `filesystem_info` | ✅ Portada |
| `filesystem_list` | `filesystem_list` | ✅ Portada |
| `filesystem_mkdir` | `filesystem_mkdir` | ✅ Portada |
| `filesystem_move` | `filesystem_move` | ✅ Portada |
| `filesystem_copy` | `filesystem_copy` | ✅ Portada |
| `filesystem_touch` | `filesystem_touch` | ✅ Portada |
| `filesystem_tree` | `filesystem_tree` | ✅ Portada |
| `filesystem_hash` | `filesystem_hash` | ✅ Portada |
| `filesystem_archive` | `filesystem_archive` | ✅ Portada |
| `filesystem_extract` | `filesystem_extract` | ✅ Portada |

### 2.6 Git (NV 10 → OD 10)

| NV | OD | Status |
|---|---|---|
| `git_branch` | `git_branch` | ✅ Portada |
| `git_status` | `git_status` | ✅ Portada |
| `git_commit` | `git_commit` | ✅ Portada |
| `git_add` | `git_add` | ✅ Portada |
| `git_log` | `git_log` | ✅ Portada |
| `git_diff` | `git_diff` | ✅ Portada |
| `git_checkout` | `git_checkout` | ✅ Portada |
| `git_fetch` | `git_fetch` | ✅ Portada |
| `git_pull` | `git_pull` | ✅ Portada |
| `git_push` | `git_push` | ✅ Portada |

### 2.7 Banco de Dados (NV 5 → OD 3)

| NV | OD | Status |
|---|---|---|
| `database_tables` | `database_tables` | ✅ Portada |
| `database_schema` | `database_schema` | ✅ Portada |
| `database_query` | `database_query` | ✅ Portada |
| `database_backup` | — | ❌ **Excluída** (§3.2 — stub vazio) |
| `database_stats` | — | ❌ **Excluída** (§3.3 — stub vazio) |

### 2.8 Introspecção (NV 4 → OD 4)

| NV | OD | Status |
|---|---|---|
| `action_info` | `action_info` | ✅ Portada |
| `action_schema` | `action_schema` | ✅ Portada |
| `action_validate` | `action_validate` | ✅ Portada |
| `list_actions` | `action_list` | 🔁 Renomeada (§4.1) |

---

## 3. Excluídas — Justificativas

### 3.1 `system_exec` (NV) — excluída

- **O que era:** executa comandos arbitrários do sistema via `subprocess`
  (`~/NV/plugins/actions/system_exec/action.py`), marcada **`dangerous = True`**
  no próprio legado.
- **Por que não foi portada:** execução arbitrária de comandos sem gate
  específico não é exposta como action do catálogo no OmegaDrakon. No OD,
  esse papel é coberto por caminhos **mediados**:
  - **Control Bridge** (`runtime/control_bridge/bridge.py`) — execução local
    restrita com allowlist de comandos, tokens bloqueados, escopo de
    filesystem, timeout e auditoria JSONL;
  - **Coder Engine** (`core/coder.py`) — modificação de código via pipeline
    sandbox → testes → backup → promoção;
  - **Auto Extension** (`tools/auto_extension/`) — geração de ferramentas com
    compile + allowlist de imports, mediada pelo Security Layer.
- **Decisão:** manter fora do catálogo. Se um dia houver necessidade
  arquitetural real, deve entrar como action com `permission` própria e gate
  do Security Layer — registrada no CHANGELOG antes de ser incorporada.

### 3.2 `database_backup` (NV) — excluída (stub)

- `~/NV/plugins/actions/database_backup/__init__.py` tem **0 bytes** — nunca
  foi implementada no legado (apenas placeholder de diretório).
- O OD não porta placeholders; backup do banco é coberto pela camada de
  persistência (`storage/database.py`) quando houver requisito real.

### 3.3 `database_stats` (NV) — excluída (stub)

- `~/NV/plugins/actions/database_stats/__init__.py` tem **0 bytes** — idem
  §3.2, nunca implementada.
- Métricas do banco já são cobertas pelo `Database` do OD
  (`queries/writes/transactions/errors/avg_latency_ms` em
  `storage/database.py`) e pelo Metrics Collector (`observability/metrics.py`).

---

## 4. Renomeada e Complementar

### 4.1 `list_actions` (NV) → `action_list` (OD) 🔁

Mesma função ("lista actions registradas"), renomeada para seguir a
convenção de nomenclatura do catálogo OD (`<domínio>_<verbo>`).

### 4.2 `process_tree` (OD) ➕ Complementar

Não existia no NV. Adicionada ao catálogo OD como ação complementar de
introspecção de processos (árvore a partir de um PID, default 1).

---

## 5. Modelo de Segurança no OD

- **Permissão:** cada action registra `permission = <nome da action>` — o
  gate do Security Layer (`core/security/`) decide na execução
  (roles admin/agent, escopo estrito §7.1, deny patterns).
- **Degradação graciosa:** docker/systemd/journald sem binário/daemon e
  banco sem camada configurada retornam `{ok: False, error}` em vez de
  exceção — o catálogo é executável em qualquer ambiente.
- **Sem caminhos padrão:** handlers de arquivo/git exigem parâmetros
  explícitos; `process_kill` protege `pid < 2`; `system_env` sem `keys`
  retorna apenas nomes (anti-vazamento de segredos); `system_ping` é sonda
  TCP (ICMP exigiria root).

---

## 6. Referências

- CHANGELOG: `docs/CHANGELOG.md` [0.11.0] (criação do catálogo) e [0.27.2]
  (esta tabela)
- ROADMAP: `docs/ROADMAP_ABSORCAO.md` — Fase 4, item 4.4 (56 Actions)
- Legado: `~/NV/plugins/actions/` (58 módulos) e `~/NV/core/actions/`
  (registry/executor)
- Código: `tools/actions/actions.py` (CATALOG) e `tools/actions/__init__.py`
  (`register_all`/`build_registry`)

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/ACTIONS_CORRESPONDENCIA.md
Descrição: Tabela de correspondência das 56 actions (NV → OD) com
           justificativas das excluídas, renomeadas e complementares.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```