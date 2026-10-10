# Conversa OmegaDrakon — 2026-10-10

## 1. Retomada — "leia iniciar" (~09:3x)

- Checkpoint de 09/10 lido: v1.24.0+2052 no ar (PID 1033717, desde 21:39:15),
  HEAD `244c7ae` == origin/master, Registro Mestre (banco/admin/sala/aba
  Verificar/desfazer venda) completo e no ar.
- **Pedido novo no `txt.txt` (regra 14):** "no site consigo apagar, limpar as
  minhas mensagens. quero fazer o mesmo pelo APP."

## 2. Diagnóstico — trabalho em andamento na árvore

- A árvore tinha **5 arquivos do app modificados e sem commit** de uma sessão
  anterior (`app/lib/models/message.dart`, `app/lib/screens/chat_screen.dart`,
  `app/lib/services/od_api.dart`, `app/lib/widgets/message_bubble.dart`,
  `app/test/od_api_test.dart`) — implementando exatamente o pedido:
  - `DELETE /history/me` (limpar TODA a conversa) + `DELETE /history/me/messages/{id}`
    (apagar UMA) — **rotas já existentes no servidor** (`history_delete`,
    `history_delete_message`, gate `_check_owner` com alias `me`);
  - no app: `OdMessage.serverId`, `deleteHistoryMessage()`, `clearHistory()`,
    long press na bolha do usuário, menu ⋮ "Limpar conversa", +8 testes.
- Nada foi apagado: investigado e concluído por cima.

## 3. Lacuna de falso-sucesso encontrada e fechada

- Mensagens **recém-escritas** não tinham `serverId` (nem os frames do
  streaming nem o `POST /message` devolvem ids) → o apagar só removia da tela
  e a mensagem voltava no próximo carregamento do histórico.
- **Correção (sem trocar protocolo):** `OdApi.resolveUserMessageId(content)`
  — no momento do apagar, o app consulta o histórico (100 msgs) e localiza a
  última mensagem do USUÁRIO com texto idêntico; com o id, o DELETE vale
  também para o que acabou de ser escrito. Sem candidata → remove só da tela,
  com aviso honesto ("removida da conversa local").
- `chat_screen._confirmDeleteMessage` usa a resolução antes de cair no
  caminho local; falha de rede no meio também cai no caminho local honesto.

## 4. Outro achado — teste acoplado à máquina (quebra a suíte)

- A suíte parou em `test_notifier.py::test_restart_alert_emitted_once` com
  `['restart', 'router:down']`: a sonda `_check_router` lê
  `<OD_LOG_DIR>/router_monitor.log` **escrito pela máquina**, e houve um blip
  real de rede durante a suíte (down 12:20:33 → up 12:21:32).
- **Correção (causa raiz):** fixture **autouse** em `tests/test_notifier.py`
  apontando `OD_LOG_DIR` para `tmp_path` — nenhum teste do módulo lê mais
  logs de produção (os testes de roteador já usavam tmp_path próprio).

## 5. Validação

- `flutter analyze` → **0 issues** · `flutter test` → **157 passed / 2 skipped**
  (+5 testes: 4 de `resolveUserMessageId` e 1 widget de long press →
  diálogo → DELETE).
- Suíte do servidor → **2393 passed / 16 skipped** (81s) · `test_notifier` 48
  pass · `test_version_policy` 9 pass · `test_capabilities` 11 pass.
- Bump **PATCH 1.24.1 + versionCode 2053** em todas as fontes vivas
  (`.env`, fallback de `capabilities`, `pubspec`, `_APP_VERSION_CODE`,
  site 3x, CHANGELOG `[1.24.1]`, README_VERSAO §1.24.1) — §5.3: todo APK
  publicado ganha versionCode novo.

## 6. Deploy 1.24.1 (regra 7.3 — validação verde)

- APKs pelo build canônico `./app/build_apk.sh`: **aapt2 `versionCode='2053'`
  `versionName='1.24.1'` EXATOS nos dois** (o bug do 4049 não repetiu) —
  full 55.246.176 B `a947d59a…` · arm64 19.977.978 B `34de9279…`.
- Commit **`1761474`** (push, HEAD == origin/master).
- **Restart 09:42:49, PID 1100479, NRestarts=0.** Provas vivas:
  - `/app/version` {1.24.1, 2053, sha256 `a947d59a…` == binário de site/}
    (local **e** Funnel) · `/health` up · `/capabilities` 1.24.1 ·
    `/supervision` restarts 0, degraded [].
  - `DELETE /history/me` e `DELETE /history/me/messages/{id}` → **401 sem
    credencial** (gates no ar).
  - **Prova ponta a ponta** (conta temporária `apagarteste6266`, criada e
    removida): 2 mensagens via `POST /message` → ids 805/807 em
    `/history/me` → `DELETE messages/805` some **só** ela (806/807/808
    seguem) → `DELETE /history/me` → `removed=3`, `messages: []`.
  - journal **0 erros** desde o restart · `/site` + `verificacao.html` +
    `historico.html` 200 · Funnel: APK **206** com magic bytes `PK` ·
    **0 🐉** nos 3 HTMLs.
- **Registro:** `txt.txt` reescrito com o resumo (regra 14) · Telegram msg
  2066 (regra 15) · `session.json` (`item_2f_app_apagar_mensagens_2026_10_10`)
  e esta transcrição.

**Para o dono:** abrir o app → banner "Nova versão 1.24.1" → Atualizar
(2052 → 2053). Depois: menu ⋮ → "Limpar conversa"; e long press na própria
bolha para apagar uma mensagem só.

**Pendências abertas (sem ordem ainda):** etapa 4 do item 2 (QR de posse +
registro do comprador + loja) · rotação dos segredos antigos (adiada) ·
itens 3 e 5 da pauta de divergências (unificação de ID e ordem das frentes).

---

## §2 — Canal de desenvolvimento: por que a sessão falhava aos 10 minutos (~10:15–10:35)

**Pedido do dono (chat):** "porque pelo Canal de Desenvolvimento a sessão
inicia e depois de 10 minutos falha? Para você desenvolver um pedido é
necessário 1 hora e às vezes mais..."

**Investigação com o código em mãos:**

1. `orquestrador.py:44` — `CLI_TIMEOUT_S: int = 600` (10 minutos fixos).
   Cada CLI da cascata (Freebuff → OpenCode → Kilo) recebia só 10 min.
2. `executar_cli` usava `subprocess.run(timeout=600)`: no timeout, o
   `TimeoutExpired` → retorna `None` → cascata tenta a próxima CLI →
   todas falham → status `todas_as_clis_falharam`.
3. Evidência do caso real (09/10): sessão ativada 10:31:14, falhou
   10:41:26 — exatamente ~600 s. OpenCode "estourou 600s".
4. **Pior:** `subprocess.run(timeout=)` mata só o processo DIRETO. Os
   FILHOS da CLI (runtime do OpenCode/Kilo) sobrevivem e continuam
   mexendo no repo SEM validação — foi o que publicou o APK com
   versionCode 4049 em 09/10 (split por ABI sem a flag canônica).

**Correções (commit `aabea5b`):**

- `CLI_TIMEOUT_S` agora vem do `.env` (`OD_DEV_CLI_TIMEOUT_S`),
  padrão **7200 s (2 h)** — tempo real de pedido de desenvolvimento.
- `executar_cli` usa `Popen` com `start_new_session=True` (grupo de
  processo próprio). No timeout, `_matar_grupo()` mata o grupo inteiro
  (SIGTERM → espera 10 s → SIGKILL) — **sem CLI órfã**.
- **Batimento** `SESSAO_HEARTBEAT_S = 15 s`: thread daemon re-grava o
  estado com `decorrido_s` enquanto a CLI roda (gravação atômica). O
  painel mostra "executando há: Xmin Ys" — sessão longa deixa de
  parecer travada.

**Validação:** 61 testes do orquestrador (+3: timeout mata o grupo, teto
configurável, CLI lenta grava decorrido) · suíte completa 2396 pass /
16 skip.

**Deploy:** 10:29:32 — PID 1106906, NRestarts=0. Provas: `/health` up ·
`/app/version` 1.24.1/2053 · `/admin/dev/sessao` ok · JS do painel
servido com `decorrido_s` · constantes no processo (`CLI_TIMEOUT_S=7200`,
`SESSAO_HEARTBEAT_S=15.0`) · journal 0 erros.

**Sem bump de versão:** backend only — nenhuma mudança no app nem no
site publicado; `/app/version` segue 1.24.1/2053 coerente com o APK.

## §3 — Continuação pós-timeout + anti-duplicata no canal (~10:40–10:55)

**Pedidos do dono (chat):**
1. "se estourar esse tempo o sistema consegue continuar de onde parou"
2. "se fizer um pedido sobre algo que já foi implementado o sistema avisa
   ou tenta recriar só porque o txt é diferente. por exemplo qual a
   temperatura em são paulo, alguns dias depois peço para implementar
   qual a temperatura no rio de janeiro"

**Respostas (com o código na mão):**

1. **Continuação pós-timeout: não automática.** O `_matar_grupo()` mata
   o processo inteiro; não existe mecanismo de resume. PORÉM as
   alterações de arquivos que a CLI já fez continuam na árvore (sem
   commit) — o risco é a próxima sessão não saber disso.

2. **Anti-duplicata: a guarda `ideia_ja_implementada` é por hash do
   texto** — pega só repetição EXATA. "temperatura em SP" ≠
   "temperatura no RJ" → passa batido. A CLI é instruída a analisar o
   que já existe, mas modelos grátis podem não reconhecer a variante
   semântica.

**Três melhorias implementadas (commit `164c5c1`):**

| # | Melhoria | Como funciona |
|---|---|---|
| 1 | **Árvore suja detectada** | `git status --porcelain` no início da sessão; se houver trabalho parcial de sessão anterior que falhou, o prompt avisa a CLI para avaliar/retomar |
| 2 | **Prompt anti-duplicata** | Instrução explícita: "verificar se a funcionalidade já existe em OUTRA FORMA (ex: ação genérica que aceita qualquer cidade) antes de criar" |
| 3 | **Busca por palavras-chave** | `_extrair_palavras_chave` (stopwords PT) + `_buscar_no_codigo` (core/tools/integrations/memory/runtime, máx. 3 arquivos/palavra) — achados injetados como contexto no prompt |

**Prova real no repositório:** "implementar qual a temperatura no rio de
janeiro" → palavras-chave `[temperatura, janeiro]` → achados em
`core/intents.py`, `core/orchestrator.py`, `tools/actions/actions.py` —
a CLI vê onde a funcionalidade já existe antes de decidir criar.

**Validação:** 72 testes do orquestrador (+11) · suíte completa 2407
pass / 16 skip. Backend only — sem bump, sem restart (`orquestrador.py`
é spawned fresh por sessão).
