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

## Estado da sessão

- **Site:** histórico visual completo (GET /history + carregamento + agrupamento
  por dia + hora), login/registro/anônimo, botão Sair, streaming WS consertado,
  layout fixo, badge do usuário. Pronto para o usuário testar e polir.
- **App 1.2.8+11:** publicado e conferido; ainda sem conexão do celular.
- **Próximo passo:** confirmação visual do usuário no site; depois "partir para
  outro sistema" (não especificado ainda).
