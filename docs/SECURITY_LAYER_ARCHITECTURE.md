# Security Layer — referência do NV (v1.7.0) e o que o OD já implementa

> **Finalidade:** guardar no repositório a *intenção* da security layer do
> Nicky Virthy Runtime (o predecessor do OD) — não o código — e mostrar, peça
> por peça, onde cada camada vive hoje em `core/security/`. Serve para
> revisitar a arquitetura com a régua original à mão.
> **Fonte:** `SECURITY_LAYER_ARCHITECTURE.md` v1.7.0, extraído em 13/11 para
> `data/refs_todo/NV/NV v1.7.X/` (fora do git). O `analise/NV/` completo
> (1,2 GB) foi zipado para a HD do dono em 13/11.
> **Decisão:** **não portar código**. O OD já implementou o fluxo inteiro em
> `core/security/` (1.763 linhas em 8 arquivos); este doc é referência de
> intenção, não lista de tarefas.
> **Data:** 2026-11-26 · fila de prioridades item 6.
> **Assinatura:** `OD // CORE`

---

## 1. O que o documento original diz (v1.7.0, 24 linhas)

Reproduzido na íntegra, porque o valor está na concisão do contrato:

- **Componentes:** SecurityManager, PolicyEngine, PermissionEngine,
  ScopeEngine, ApprovalEngine, AuditEngine.
- **Fluxo:** `Action -> SecurityManager -> Policy -> Permission -> Scope ->
  Approval -> Execute -> Audit`.
- **Policies:** arquivo `config/security/policies.yaml`.
- **Roles:** `guest`, `operator`, `admin`.
- **Exceções:** `PermissionDenied`, `ScopeViolation`, `ApprovalRequired`,
  `PolicyViolation`.

Três coisas a notar nesse contrato:

1. a **ordem** das camadas é fixa e o `Audit` vem **depois** da execução —
   ou seja, toda decisão é registrada, permitida ou não;
2. **policies são dados** (YAML), não código — dá para mudar regra sem
   deploy;
3. as camadas **levantam exceção** (`PermissionDenied` etc.), o que obriga o
   chamador a tratar cada caso.

O OD manteve 1 e 3-de-outro-jeito; mudou 2 e 3 (ver §4).

---

## 2. O fluxo no OD (`core/security/manager.py`)

`SecurityManager` é a única porta de entrada. `PIPELINE_ORDER = ("policy",
"permission", "scope", "approval")` roda em ordem fixa dentro de
`validate()`; a auditoria é a quinta etapa (`audit_engine.record(decision)`),
executada **sempre**, inclusive quando negado.

Modos de enforcement (`EnforcementMode`):

| Modo | Comportamento |
|------|---------------|
| `compatibility` | só audita e loga; nunca bloqueia (padrão histórico) |
| `soft` | audita + `WARN`, mas permite |
| `strict` | **fail-closed**: qualquer camada que rejeitar bloqueia |

No runtime real o registry de actions é construído com
`SecurityManager(mode="strict")` (`runtime/launcher.py::build_action_registry`
e `build_auto_extension`). O gate acontece em `ActionRegistry.execute`, antes do
handler: a action declara `permission` (hoje `permission=spec["name"]` em
`tools/actions/__init__.py`) e o resultado vira
`ActionResult(status="denied")` quando a decisão nega — sem exceção no
caminho do chat.

---

## 3. Camada por camada — onde está no OD

### 3.1 Policy Engine — `core/security/policy.py` (224 linhas)

Regras globais da organização, avaliadas primeiro:

- **deny patterns** (`fnmatch` no nome da ação): `system.shutdown`,
  `system.reboot`, `system.halt`, `process.killall`, `database.drop_table`,
  `database.drop_database`, `database.truncate`, `filesystem.wipe`,
  `filesystem.format`, `security.disable`, `security.disable_layer`;
- **allowlist** opcional (`set_allowlist(True)` = deny-by-default para ação
  fora da lista);
- **tokens destrutivos** procurados na serialização dos parâmetros:
  `rm -rf`, `DROP TABLE`, `TRUNCATE TABLE`, `mkfs`, `dd if=/dev/zero`,
  `chmod -R 777`, fork bomb, `shutdown -h`, `reboot -f`,
  `git push --force`, entre outros.

### 3.2 Permission Engine — `core/security/permissions.py` (287 linhas)

Papéis → padrões de ação, com **menor privilégio por padrão** e
`UNKNOWN_ROLE_POLICY = "deny"` (papel desconhecido não herda nada):

| Papel | Escopo |
|-------|--------|
| `admin` | `*` (o dono) |
| `user` | leitura: sistema, arquivos, Docker, git, Google leitura, clima/câmbio, pesquisa web, saúde (referência), memória do próprio usuário, `role_list` |
| `familia` | herda `user` **por código** (`ROLE_HIERARQUIA`) + `ha_device_control` (única escrita do lar, com confirmação em 2 passos) |
| `agent` | leitura interna/memória/knowledge (nomenclatura da spec, com ponto) |
| `router` | `router.*` |

Detalhe importante já documentado no próprio arquivo: as listas do `agent`
usam a nomenclatura com ponto da spec, mas as actions reais do catálogo usam
underscore — por isso a lista de `user` é explícita e não um padrão amplo.

### 3.3 Scope Engine — `core/security/scope.py` (297 linhas)

Limita **onde** a ação pode tocar:

- `classify_operation(request)` (read/write/delete/execute…) e
  `extract_paths(request)` (inclusive `caminho`/`origem` e `/tmp` quando as
  raízes são o padrão);
- raízes permitidas (`add_root`/`remove_root`), caminhos protegidos
  (`add_protected_path`), `allow_root` e `allow_destructive`;
- `is_within_roots` / `is_protected` resolvem o caminho antes de comparar
  (symlink/`..` não passam).

### 3.4 Approval Engine — `core/security/approval.py` (257 linhas)

Confirmação humana para ações marcadas (`require_approval("pattern")`):
`PendingApproval` com token, TTL e `approve`/`reject`; `is_approved` valida o
token do `ActionRequest`. Desligado por padrão (`enabled`), ligável em
runtime. No `strict`, exigência pendente bloqueia; nos outros modos apenas
marca `approval_required`.

### 3.5 Audit Engine — `core/security/audit.py` (162 linhas)

`AuditEngine.record(decision)` grava `AuditRecord` para toda decisão
(inclusive permitida), com sinks plugáveis (`add_sink`) e métricas
(`AuditMetrics`). Em produção o sink persistente é o `AuditSystem`
(`observability/audit.py`, JSONL em `logs/audit.jsonl`, `OD_AUDIT_FILE`).

### 3.6 Modelos — `core/security/models.py` (196 linhas)

`ActionRequest` (action, params, role, source, session_id, paths, destructive,
requires_root, approval_token, metadata), `CheckResult` (layer, allowed,
reason), `SecurityDecision` (allowed, denied_by, reasons, approval_*,
`to_dict`), `AuditRecord` (`from_decision`), `EnforcementMode`.

---

## 4. Diferenças em relação ao NV (e por quê)

| NV v1.7.0 | OD | Motivo |
|-----------|----|--------|
| roles `guest`/`operator`/`admin` | `admin`/`user`/`familia`/`agent`/`router` | o OD tem contas reais (painel, app, famílias) e papéis internos; `guest` virou o anônimo sem conta, tratado antes do gate |
| policies em `config/security/policies.yaml` | defaults **em código** (`DEFAULT_DENY_PATTERNS`, `DEFAULT_DESTRUCTIVE_TOKENS`) + API de mutação | não existe `config/security/` no repo; manter uma fonte só evita YAML divergente do código (e o dono não edita YAML hoje) |
| camadas **levantam exceção** | devolvem `CheckResult`/`SecurityDecision` | o caminho de chat/API precisa de decisão auditável, não de `try/except` em cada chamador |
| Auditoria depois do `Execute` | decisão auditada **antes** do handler; a execução é do `ActionRegistry` | o gate é pré-execução por construção; a trilha da decisão já contém o que seria executado |
| — | `EnforcementMode` (`compatibility`/`soft`/`strict`) | permitiu ligar o gate em produção sem quebrar o legado na transição |

O que **não** foi portado: o YAML de políticas, a semântica de `guest`/
`operator` como papéis de conta e as exceções nomeadas. Nada disso é
necessário para o fluxo atual — está registrado aqui para não ser
"redescoberto" como lacuna.

---

## 5. Lacunas reais (honestas) e próximos passos

1. **Policies só por código**: mudar uma regra exige alterar/instanciar o
   `PolicyEngine` no boot. Se o dono quiser editar regra sem deploy, o
   caminho é um YAML carregado no `build_action_registry` — a API de
   mutação (`add_deny`, `add_allow`, `add_destructive_token`) já existe.
2. **Papéis × actions com nomes diferentes** (ponto vs underscore) é a
   armadilha histórica — já causou `permission denied` silencioso em
   `weather_city`/`exchange_rate` (13/10) e `role_list` (14/11). Action nova
   precisa entrar na lista do papel `user`, não só no catálogo.
3. **Visibilidade do dump**: `SecurityManager.dump()` (modo, métricas,
   políticas, permissões, escopo, aprovação, auditoria) não está exposto no
   painel nem no `/health`; hoje só via código/teste. Expor é barato se
   houver demanda.
4. **Aprovação humana** está pronta e desligada; ligar é decisão do dono
   (muda o fluxo de ações destrutivas do admin).

---

## 6. Referências

- `data/refs_todo/NV/NV v1.7.X/SECURITY_LAYER_ARCHITECTURE.md` — original
  (24 linhas, fora do git).
- `docs/NV_DAG_SCHEDULER_REFERENCE.md` — a outra metade do item 6: DAG
  (`dag_engine.py`, 347 linhas) e scheduler (`scheduler_engine.py`, 413
  linhas) do NV v1.9.2, com o mapa de como o OD já cobre retry/paralelismo e
  o que falta (workflow como entidade de domínio).
- `docs/ARCHITECTURE_v2.md` — visão geral do sistema.
- Código vivo: `core/security/*.py`, `tools/registry.py` (gate em
  `execute`), `runtime/launcher.py::build_action_registry`,
  `observability/audit.py`.
