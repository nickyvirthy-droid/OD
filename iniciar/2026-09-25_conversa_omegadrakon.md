# Conversa OmegaDrakon — 2026-09-25

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
"leia inicir" (~14:2x). Ambiente canônico de testes: `.venv/bin/python`
SEM `OD_TEST_POSTGRES_DSN`.

---

## 1. Retomada (~14:2x)

Checkpoint lido. Estado confirmado: od-core active (PID 367729, mesmo do
deploy de 09-24), NRestarts=0, HEAD `b7fd767` == origin/master.

## 2. Fechamento do ponto do histórico do usuário teste (14:30)

O dono confirmou no site que as conversas do usuário `teste` aparecem.
Correção `2ee947b` validada de ponta a ponta (prova servidor 6/6 em
09-24 + confirmação visual do dono). Ponto FECHADO — ver §4 da
transcrição de 09-24 e `cache_historico_2026_09_24_fechamento` no
session.json.

## 3. Bug: "quando troco usuário ou entro pela primeira vez as conversas não atualizam" (~15:1x)

### Evidência antes de inferir (regra 5)

- **Servidor íntegro via curl**: login `teste` → `/history/teste` 200
  (total 0 — balde tinha sido limpo; em 09-24 eram 6 msgs, o dono usou o
  🧹 Limpar nos testes); login `alex` → `/history/alex` 200 com 5 msgs;
  `/history/me` com Bearer → `user_id` resolvido CERTO em ambos.
- **JS servido == repo** (md5 do `<script>` igual ao do arquivo) e
  processo (367729) mais novo que server.py — não era deploy velho.
- **Journal**: 5 logins hoje (teste→alex, 3× alex, teste→alex) e ZERO
  `Message processed`/`WebSocket authenticated` (o "Transporte
  indisponível" do journal é o bot Telegram sem rede — pré-existente e
  sem relação).
- **Cabeçalhos**: `GET /chat` NÃO mandava `Cache-Control` (só `_json`
  mandava `no-store`).

### Causa raiz — 3 defeitos no CLIENTE (página /chat)

1. **Página sem `Cache-Control: no-store`** (`_html()`): o navegador
   pode rodar JS ANTIGO do cache — classe clássica de "nada muda".
2. **`loadHistory()`/`loadOlder()`/Limpar usavam o `user_id` DO
   NAVEGADOR** (`/history/<user_id>`): defasado na troca de conta ou no
   modo API key (ficava `web`) → balde errado/403 → histórico não
   aparece. O servidor já é a fonte da verdade (`/history/me` resolve
   pela credencial desde 7ca6eec).
3. **Filtro de perfil (dropdown) persistia entre usuários**: perfil com
   0 msgs para o próximo usuário (nyx=6, regulus/luma/nexus=0) →
   "histórico vazio".

### Correção (integrations/api/server.py)

- `_html()`: `Cache-Control: no-store` (páginas embutidas evoluem com o
  servidor; JS do /chat é parte do contrato da API).
- Chat: `loadHistory`/`loadOlder`/`btn-limpar` usam `/history/me`
  (identidade da credencial, nunca do navegador); badge do cabeçalho é
  corrigido com `data.user_id` DA RESPOSTA (servidor manda o dono real).
- `resetProfileFilter()`: dropdown volta para `auto` nos 3 pontos de
  entrada (login, auto-login do registro, API key) — filtro é da SESSÃO,
  não do navegador.

### Verificação (regra 12)

- Contrato atualizado: `tests/test_api.py` (no-store + `/history/me` +
  resetProfileFilter) e `tests/test_auth.py::test_chat_page_…`
  (fetch por "me" + `resetProfileFilter();` ×3, count==3).
- **A guarda node --check de 09-23 pegou NOVO bug meu no ato**: a edição
  tinha engolido a quebra de linha do comentário `// --- Login ---`
  (`// --- Login ---function resetProfileFilter()`), o que mataria todos
  os handlers em produção. Corrigido antes do deploy — a guarda cumpriu
  o papel dela de novo.
- **Suíte: 1899 passed, 16 skipped** (nenhum perdido; +0 líquido —
  asserts novos dentro dos testes existentes).
- **Teste do teste — 3 mutações, TODAS detectadas e revertidas**:
  1. `no-store` removido do `_html()` → 1 falha;
  2. `loadHistory` voltando a usar o `user_id` do cliente → 1 falha;
  3. `resetProfileFilter()` removido do 1º ponto de entrada → 1 falha
     (após endurecer o teste para count==3; com assert de presença a
     mutação SOBREVIVEU — 2ª lição do dia: presença de string não cobre
     multiplicidade).

### Deploy e prova viva (5/5)

- Restart autorizado (regra de 09-23): **PID 479051, NRestarts=0**.
- `GET /chat` → `Cache-Control: no-store` no ar.
- JS no ar compila (`node --check` OK); 0 Traceback/ERROR/CRIT.
- `/history/me?limit=50&profile=auto` com Bearer → `user_id=alex`,
  total 50, `has_more=True` (paginação intacta).
- `/health` 200 com chave; WS :8001 → 426 (no ar).

Observação para o dono: como a página antiga pode ter ficado em cache no
seu navegador, force um reload (Ctrl+Shift+R) UMA vez — depois o
no-store impede recursão do problema.

## 4. Estado da sessão

- **Código:** no ar (PID 479051), commit pendente → foi commitado junto
  com este registro (ver git log do dia).
- **Banco:** alex 110 msgs (104 guardian + 6 nyx); balde `teste` ZERADO
  pelo botão Limpar do dono (não é bug).
- **Pendente:** confirmação visual do dono (trocar de usuário no site e
  ver o histórico trocar junto, com a página recarregada); depois o
  "outro sistema".
