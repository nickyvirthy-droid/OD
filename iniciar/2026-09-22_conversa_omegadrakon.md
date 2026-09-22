# OmegaDrakon — conversa de 2026-09-22

> Transcrição da sessão (regra 4 do `iniciar/RULES.md`). Contexto completo em
> `iniciar/session.json` (§`reboot_prova_2026_09_22`, §`alias_transporte_2026_09_22`).

---

## 1. Retomada: "leia iniciar"

Pedido: "leia iniciar".

Lidos `iniciar/README.md`, `iniciar/RULES.md`, `iniciar/session.json` e a
transcrição de 09-21. Estado vivo conferido antes de assumir contexto (regra 3).

**Achado principal:** o reboot que a sessão anterior deixara pendente **já
aconteceu** — e o Funnel sobreviveu sozinho — **mas o provador nunca foi
instalado**.

| Verificação | Resultado |
|---|---|
| `boot_id` | `3f33b3fe…` → **`64896b18…`** (diferente = reboot confirmado) |
| Journal | od-core parou 11:00:51 → `-- Boot 64896b18…` → subiu **11:01:36** (PID 1130, `NRestarts=0`) |
| Autonomia | `Linger=yes`, `tailscaled` e `od-core` **enabled+active** |
| Funnel pós-boot | **`# Funnel on`** com `/`→8000 e `/ws`→8001 |
| Probe da URL pública | `/health` → **401** (nossa API) · `/ws` → **426** (nosso WS), 0,03 s |
| `od-boot-prover` | `not-found`, sem `last.txt` (instalação nunca ocorreu) |

O usuário escolheu **aceitar a evidência retroativa** do boot (o Funnel
sobrevive ao reboot; o critério formal do `last.txt` fica dispensado) e seguir
para **migrar o histórico app + Telegram**.

## 2. Alias de transporte legado → conta

Decisão: **"Migrar + rotear Telegram e app por código"**, estendida (com
autorização) ao balde `web` do chat em modo avançado.

O motivo de os baldes terem ficado de fora antes era real: o **app** manda
`user_id: "app"` fixo (via `OD_API_KEY`), o **bot** usa o id numérico do chat e
o **chat web em modo avançado** usa `web` — cada um renasceria na mensagem
seguinte. A solução é um mapa de operador: `OD_ACCOUNT_ALIASES`.

### Implementação

- **`core/identity.py` (novo)** — `parse_aliases("app=alex,…")` e
  `resolve_account(id, mapa)`: casamento sem diferenciar maiúsculas, entradas
  malformadas ignoradas, mapa vazio = comportamento antigo.
- **REST** (`integrations/api/server.py`) — `APIConfig.account_aliases` +
  `resolve_account` no caminho **sem usuário** do `POST /message`.
- **WebSocket** (`integrations/api/ws_server.py`) —
  `WebSocketServer(account_aliases=...)` aplicado quando o frame `auth` não traz
  identidade de usuário.
- **Telegram** (`integrations/telegram/bot.py`) —
  `TelegramBot(account_aliases=...)` + `_account_for(chat)` em `process()`,
  `history_lines()` e `clear_chat()`.
- **`runtime/launcher.py`** — monta o mapa em um único lugar e injeta no REST,
  no WS e no bot. `.env`: `OD_ACCOUNT_ALIASES=app=alex,660518870=alex,web=alex`
  (backup em `backups/env-20260922-pre-alias.bak`).

Regra mantida: **credencial de usuário manda** — sessão `Bearer` ou API key
`od_...` ainda define a identidade e o alias é ignorado.

### Verificação (regra 12)

| Prova | Resultado |
|---|---|
| `tests/test_identity.py` (novo) + alias no REST/WS/bot | **1870 passed, 16 skipped** |
| Teste do teste (4 mutações, revertidas) | resolve bruto → 6 falhas · REST sem alias → 1 · WS → 1 · bot → 1 |
| Sandbox `sandbox_agent/auth_sandbox.py` (5º cenário: REST+WS+Telegram) | **44/44 OK** (era 36) |

### Migração no banco real

```
.venv/bin/python -m runtime.migrate_history_owner \
    --de app,660518870,web --para alex --apply
```

- `660518870`/guardian **20** + `app`/guardian **44** + `web`/guardian **6** =
  **70 msgs** → `alex` (**28 → 98**).
- Total da tabela **intacto** (102 antes e depois); resíduo na origem: nenhum.
- Snapshot de rollback: `backups/history-owner-20260922-020027.bak`.
- Fora da migração, de propósito: `deploy-check(-2)` (4 msgs sintéticas).

## 3. Deploy

Restart do `od-core` autorizado pelo usuário — registrado com a prova viva no
§`alias_transporte_2026_09_22` do `iniciar/session.json` após o deploy.
