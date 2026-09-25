# Conversa OmegaDrakon — 2026-09-24

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
"leia iniciar" às 14:30. Ambiente canônico de testes: `.venv/bin/python`
SEM `OD_TEST_POSTGRES_DSN`.

---

## 1. Retomada (~14:30)

Checkpoint lido. Estado: chat web completo no ar (histórico visual,
paginação, menu da conta, bug do JS morto corrigido em 09-23), HEAD
`49a000c`, working tree com 1 arquivo não rastreado
(`backups/prova-site-923-20260923-134842.bak.json` — snapshot da conta de
prova de 09-23, mantido).

---

## 2. Bug: "usuário teste não salvou a conversa" (~15:0x)

Reporte: *"site funcionando normal. erro localizado, usuário teste não
salvou a conversa"*.

### Diagnóstico (evidência antes de inferir — regra 5)

Journal de 2026-09-23 15:23–15:35:

```
15:23:21 Interaction recorded | user=alex   →  Message processed | route=llm
15:28:17 Message processed | route=cache | user=teste   (SEM Interaction recorded)
15:28:47 Message processed | route=cache | user=teste   (SEM Interaction recorded)
... 5x route=cache, ZERO "Interaction recorded"
```

**Causa raiz** (`core/orchestrator.py`): as rotas TERMINAIS sem LLM —
`cache`, `datetime`, `quick_response`, `action_intent` — respondiam e
retornavam ANTES da etapa 8 (`_post_process`), que é quem grava histórico
e cache. Mensagem repetida = rota `cache` = turno nunca gravado = a
conversa "sumia". Vale para REST e WS (mesma lacuna nos 4 retornos
antecipados de cada caminho). O usuário teste tinha 5 interações
desaparecidas em 09-23.

### Correção

- **`_record_terminal(result, text, *, persist)`** (novo): grava o turno
  via `history.add_interaction(..., llm_used=result.llm_used)`, melhor
  esforço (falha vira `log.warn "Orchestrator history write failed"`,
  igual à etapa 8). Respeita `persist` — anônimo segue SEM rastro.
- **`PERSISTED_ROUTES`** passa a ser `{datetime, quick_response,
  action_intent, cache, llm, fallback}`; rate limit e `llm_unavailable`
  NÃO registram (não houve resposta da conta).
- Ganchos nos 4 retornos antecipados do `process()` e nos 4 do
  `process_stream()` (o stream não tem `persist`; só é chamado com conta
  autenticada).
- Nota de design que a prova confirmou: com `persist=False` a etapa 4
  pula o CACHE inteiro (anônimo não deve ser servido com resposta de
  outra conversa) — o anônimo em pergunta repetida segue `route=llm`.

### Verificação (regra 12)

- **+5 testes** em `tests/test_orchestrator.py`:
  `test_short_circuit_persiste_a_interacao_no_historico` (substitui o
  `test_short_circuit_does_not_persist_history`, que congelava o contrato
  antigo), `test_stream_grava_a_interacao_terminal_sem_llm`,
  `test_anonimo_nao_usa_cache_nem_grava`,
  `test_anonimo_rota_datetime_tambem_nao_grava` (e o desdobramento do
  bloco anonimo). **Suíte: 1899 passed, 16 skipped.**
- **Teste do teste — 4 mutações, todas detectadas e revertidas** (hash
  conferido após restore):
  1. gravação removida da rota cache do `process()` → 1 falha;
  2. `persist` ignorado no `_record_terminal` → 1 falha (só pegou depois
     do teste de datetime com anônimo);
  3. gravação datetime removida do `process_stream()` → 1 falha;
  4. `ROUTE_CACHE` fora do `PERSISTED_ROUTES` → 1 falha.
- Detour de ambiente: com `OD_TEST_POSTGRES_DSN` exportado, os 15 testes
  do Postgres tentam rodar no venv e TRAVAM (nunca rodaram de fato; a
  sessão anterior rodava sem DSN = "16 skipped" registrado). Ambiente
  canônico da suíte: `.venv` SEM o DSN. `test_mqtt.py::
  test_start_stop_thread` falhou 1x na suíte cheia e passou isolado —
  flaky de timing já documentado em 09-21.

### Deploy e prova viva (6/6)

- Commit **`2ee947b`** fix(core): interação servida do
  cache/datetime/quick/intent entra no histórico — pushed
  (`HEAD==origin/master`).
- **Restart autorizado** (regra de 09-23): 15:2x, **PID 367729,
  NRestarts=0**; `/health` 200 com chave; WS 426; 0
  Traceback/ERROR/CRIT.
- Prova com a própria conta do usuário teste (`teste`/`teste123` — a
  senha NÃO é `senha123`; `alex` continua `senha123`):

| Passo | Resultado |
|---|---|
| `POST /auth/login teste/teste123` | 200, token |
| "oi" | `route=cache`, `user=teste` |
| "prova cache historico 924" | `route=llm` |
| "oi" de novo | `route=cache` |
| `GET /history/me?limit=8` | 6 msgs — os 3 turnos completos, **incluindo os DOIS de cache** |
| journal | 3× `Interaction recorded \| user=teste`, um antes de cada `Message processed` (2 com `route=cache`) |

- Observação: a resposta do LLM na msg de prova veio
  `[NICKY][CRIT] Erro: Não foi possível carregar` (alucinação do
  gemma-local com prompt sintético) — conteúdo irrelevante para o bug;
  vigiar se repetir com o dono.
- A prova gravou 3 interações reais (6 msgs) no balde do `teste` —
  deixadas no banco de propósito.

### CHANGELOG

`docs/CHANGELOG.md`: nova seção **"Corrigido (2026-09-24) — interações de
rota terminal sem LLM sumiam do histórico 🧠"** no topo do [1.2.0]; título
da release ganhou 2026-09-24.

---

## 3. Estado da sessão

- **Código:** `2ee947b` no ar (PID 367729, NRestarts=0).
- **Contrato novo:** TODA resposta da conta registra o turno no
  histórico, venha de `llm`, `fallback`, `cache`, `datetime`, `quick`
  ou `action_intent` (REST e WS). Anônimo: zero rastro em qualquer rota.
- **Próximo passo:** ~~confirmação do usuário no chat do site~~ **CONFIRMADO PELO DONO em 2026-09-25 14:30** — as conversas do usuário teste aparecem no site; ponto FECHADO. Depois: o "outro sistema" (ainda não especificado).
- **Pendente opcional:** reset de senha do `teste` (não é `senha123`)
  se o dono quiser padronizar.

---

## 4. Encerramento do ponto (2026-09-25 14:30)

O dono confirmou no chat do site que as conversas do usuário `teste`
aparecem — a correção de `2ee947b` (rotas terminais gravam o turno) está
validada de ponta a ponta: servidor provado em 09-24 (6/6) + confirmação
visual do dono em 09-25. Ponto encerrado; nada mais pendente nele.
