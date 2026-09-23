# OmegaDrakon — conversa de 2026-09-23

> Transcrição da sessão (regra 4 do `iniciar/RULES.md`). Contexto completo em
> `iniciar/session.json` (§`historico_visual_2026_09_22`,
> §`historico_visual_app_2026_09_23`, §`chat_site_sair_e_ws_2026_09_23`,
> §`site_layout_fixo_2026_09_23`).

---

## 1. Deploy do Histórico Visual (13:23)

Restart autorizado — PID 235324, `NRestarts=0`. `GET /history/{user_id}` no ar
com prova viva: `/history/alex?limit=5` 200 em 0,05s (5 msgs cronológicas),
`/history/me` → alex, sem credencial 401, WS 426. Commits `b3d767d` (feature)
e `6419f29` (registro).

## 2. Conferência do APK 1.2.8+11 pela URL do Funnel

Download público sem credencial: HTTP 200, 52.410.843 B em 0,15s.
**sha256 idêntico ao local**
(`fa5f0db23f7cfecee036c671643b393d2d9495528ec32924666c2362b2174d9a`);
`aapt2 versionCode='11'`. Temporário removido. Commit `71541a9`.

## 3. Validação do protocolo do app (13:31) — celular ainda não conectou

- `POST /auth/login` alex/senha123 → 200, token de 36 chars.
- `GET /history/me?limit=50` com Bearer → 200: 50 msgs, ordem cronológica,
  roles user/assistant, conteúdo real da conta.
- Banco intacto: alex = 106 (as 6 novas são de 09-22 13:01 — teste pós-troca
  de senha); total 110 (só alex + 4 sintéticas deploy-check).
- **0 conexões WS e 0 "Message processed" desde o restart** — o app 1.2.8+11
  ainda não foi aberto/instalado no celular.
- Commit `c005ba3`.

## 4. Chat do site: Sair + bug do WebSocket (13:47)

Pedido do usuário: "vamos começar pelo básico — conectar pelo chat do site
(cadastro de usuário e senha) e colocar um logout, porque em computador não
seguro a conexão não pode ficar aberta".

**Bug real encontrado:** o frame `auth` do WS na página `/chat` só mandava
`api_key` — quem entrava por login/senha tinha o WS **sempre negado**
(close 4001) e caía no REST silenciosamente. O servidor já aceitava `token`
desde `d8374e2`; a página não mandava.

- Botão **Sair** no cabeçalho (só visível logado): `POST /auth/logout` (mata a
  sessão no servidor) + limpa credenciais do localStorage + fecha o WS + volta
  ao gate.
- **hist-note**: aviso visível quando o histórico não carrega (status HTTP ou
  falha de rede) ou quando a conta não tem mensagens.
- Suíte 1888 passed (+1: fluxo do site — registra → conversa → histórico →
  sair com sessão morta). Commit `df7027e`.
- **Regra nova do usuário:** restarts do od-core **não precisam mais de
  pedido** — "pode realizar o restart se ele é necessário".
- Prova viva 6/6 (PID 239235): página com botão e token no frame; conta
  `prova-site-923` criada (201), login 200, conversa (route=llm, 12,9s),
  histórico com a mensagem, logout 200 → token morto → 401. Conta removida
  com snapshot `backups/prova-site-923-20260923-134842.bak.json`.

## 5. Layout fixo + nome do usuário (13:5x)

Pedido: "(1) o cabeçalho some ao rolar; (2) a caixa de digitação idem;
(3) não aparece o nome do usuário logado".

- **Causa raiz:** o `#chat` crescia com o conteúdo e empurrava header/composer
  para fora da viewport. Correção: `flex: 1` + `min-height: 0` no `#chat` — o
  scroll fica DENTRO da lista; header e composer fixos por estrutura.
- **Badge 👤** com o username no cabeçalho (`user-badge`): preenchido no login,
  registro e auto-login; anônimo não mostra; limpo no Sair.
- Suíte 1888/16. Commits `2d4799f` + `9d2c856`. Deploy PID 241843, prova no ar.

## 6. Histórico agrupado por dia com hora discreta (~14:0x)

Pedido: "ajustar o estilo das bolhas do histórico carregado (agrupar por
horário ou mostrar timestamps discretos)".

- **Separador de dia** (`.day-sep`): pílula centralizada quando a data muda —
  `Hoje`, `Ontem` ou `dd MMM` (pt-BR) via `dayLabel()`.
- **Hora discreta** (`.hist-time`): HH:MM no canto da bolha (à direita nas do
  usuário, à esquerda nas do OD), só no histórico carregado — a conversa ao
  vivo continua igual.
- **Meta do OD** completa o selo: `llm_used · HH:MM` nas respostas.
- Função nova `addHistoryBubble(m)` + agrupamento dentro do `loadHistory()`.
- Suíte 1888/16. Commit `383217a`. Deploy PID 243498, 0 erros no journal,
  `GET /chat` 200 com `day-sep`/`hist-time`/`addHistoryBubble` presentes.

---

## 7. Histórico abre rolado até a mensagem mais recente (~14:2x)

Pedido: "fazer o histórico carregado abrir já rolado até a mensagem mais
recente".

- **Causa raiz:** a montagem rolava a cada bolha com o `scrollHeight` parcial —
  a lista abria no meio do histórico.
- **Correção:** as bolhas do histórico montam **sem rolar** (`noScroll` em
  `addBubble`) e um único `scrollToLatest()` roda ao final da montagem, dentro
  de **duplo `requestAnimationFrame`** — garante rolagem DEPOIS da pintura do
  último elemento.
- Suíte 1888/16. Commit `e61becb`. Deploy PID 245159, 0 erros no journal,
  `GET /chat` 200 com `scrollToLatest`/`noScroll` no HTML.

---

## 8. Paginação do histórico: carregar antigas ao rolar o topo (~15:1x)

Pedido: "carregar conversas mais antigas ao rolar até o topo do chat
(paginação por before/cursor)".

### Backend
- **`memory/history.py: get_messages_page(user_id, profile, limit, before_id)`**
  — devolve `{messages (cronológico), has_more, oldest_id}`. No **banco**, o
  cursor é a PK `id` (`WHERE id < before_id`, `limit+1` para detectar a próxima
  página). Em **memória/JSON** (sem id estável) o cursor é offset negativo:
  `before=-N` devolve a janela imediatamente anterior às N já carregadas.
- **`GET /history/{user_id}?before=`** — `before` inválido → **400
  `before_invalido`**; resposta agora sempre inclui `has_more` e `oldest_id`
  (o caminho antigo, sem `before`, segue idêntico mais os campos novos).

### Chat web
- Pill **"↑ Carregar conversas anteriores"** no topo da lista (`hist-top`):
  clicável E disparada ao rolar ao topo (folga 60px), com estado
  "Carregando…" e desaparece quando não há mais páginas.
- `loadOlder()` faz **prepend preservando a posição** da leitura (âncora no
  1º elemento + ajuste de `scrollTop`), re-agrupa separadores de dia e insere
  selo **"Início da conversa"** quando `has_more` fica False.

### Verificação (regra 12)
- Suíte **1895 passed, 16 skipped** (+7: `get_messages_page` no banco/memória,
  fluxo HTTP encadeando páginas, asserts do HTML).
- **Prova viva no ar** (PID 252797, 0 erros): p1 (10 recentes, oldest_id=103)
  → `?before=103` (10 anteriores, oldest_id=93, sem sobreposição) → p3
  (oldest_id=81); `before=abc` → 400; `hist-top` no HTML.
- Nota: o par user/assistant de um mesmo turno compartilha o `ts` — a partição
  entre páginas é por **id**, sem sobreposição; ts empatado é o par cortado.

- Commits: `54a3120` (feature) · deploy com restart (PID 252797).

---

## 9. Menu da conta: Limpar conversa + Sair dentro do nome (~15:4x)

Pedido: "consegue colocar o botão sair dentro do nome do usuário? Quando o
usuário clica no nome aparece a opção sair, também quero a opção limpar que
zera a conversa".

### Implementação
- O badge **👤 nome** virou **botão** (`#user-menu` + `#user-badge`): clicar
  abre dropdown com as opções da conta; fecha com clique fora ou **Esc**.
- **🧹 Limpar conversa** — `DELETE /history/me` com **dupla confirmação**
  (apaga TODA a conversa da conta no servidor), zera a tela (welcome de volta)
  e avisa quantas mensagens foram removidas. Paginação resetada (`hist-top`
  some). Anônimo recebe aviso específico (não tem conversa salva).
- **🚪 Sair** — como antes: `POST /auth/logout` (mata a sessão no servidor) +
  limpa credenciais do navegador + fecha o WS + volta ao gate.
- O botão solto "Sair" do cabeçalho foi removido (agora vive no menu).

### Verificação (regra 12)
- Suíte **1896 passed, 16 skipped** (+1: `test_limpar_conversa_zera_o_balde` —
  6 mensagens removidas, stats 0, 2ª limpeza 200/removed=0, conforme o
  contrato de 404 de `6af4d2f`: conta existe → 200).
- **Prova viva no ar** (PID 255429, 0 erros): HTML com dropdown/limpar/.dupla
  confirmação; conta descartável `menu-limpa`: conversou (2 msgs) → DELETE
  `/history/me` → 200 `removed=2` → stats 0. Conta removida depois.
- Commits: `d610ff9` (feature) · restart para o deploy.

---

## Estado da sessão

- **Site:** histórico visual completo (GET /history + carregamento + agrupamento
  por dia + hora + paginação por cursor), login/registro/anônimo, **menu da
  conta no nome (Limpar + Sair)**, streaming WS consertado, layout fixo.
- **App 1.2.8+11:** publicado e conferido; ainda sem conexão do celular.
- **Próximo passo:** confirmação visual do usuário no site; depois "partir para
  outro sistema" (não especificado ainda).
- **App 1.2.8+11:** publicado e conferido; ainda sem conexão do celular.
- **Próximo passo:** confirmação visual do usuário no site; depois "partir para
  outro sistema" (não especificado ainda).
