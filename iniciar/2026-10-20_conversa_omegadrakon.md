# Conversa 2026-10-20 — OmegaDrakon

## §1 — Retomada de rotina ("leia iniciar", 20/10 ~01:38): sistema verde em v1.43.0+2079

Retomada pela regra 3 — li `iniciar/session.json`, `iniciar/RULES.md` e o
fim da transcrição anterior (`2026-10-17_conversa_omegadrakon.md` §16–§17).
Último ponto registrado: **19/10 16:29**, fecho da **v1.43.0+2079 — Calibre
Web interligada** (comits `2d0e550` + `d49ec06` + `aa3c5e5`, série "uma por
vez" FECHADA: FlatNotes → File Browser → Calibre).

Verificação feita com a fonte viva (não com o registro):

| Frente | Medição |
|---|---|
| Serviço | `od-core` active desde **19/10 16:23:09** (9h15), MainPID 3639833, **NRestarts=0**, journal **0 `[ERROR]`** desde o boot |
| Saúde | `/health` **status=up, 24 checks, nenhum fora** (críticos 0 fora) · `/dashboard/stats` `nomad_tools {9,9,[]}` · `notifier {ticks:553, checks_run:8848, problems:10, alerts_emitted:2, alerts_blocked:7, errors:0}` |
| Versão | `/app/version` **1.43.0 / 2079**, sha256 `9bc6ef18…` = APK publicado (55.700.429 B) |
| Git | árvore **limpa**, HEAD `aa3c5e5` == `origin/master` (0 à frente / 0 atrás) |
| Backup | `backup` up (estado `od-2026-10-19_0311.tar.gz`, 0,18 MB, 22,4 h) · `backup_capturas` up (semanal `od-capturas-2026-10-16_1434.tar.gz`, 301,62 MB, 83 h) · disco **66%** (78G livres) |
| Canais do dono | `txt.txt` **sem mensagem nova** (última escrita nossa 19/10 16:29 = entrega do Calibre) · `analise/` **inalterado** (2 capturas do Sistema Órion de 16/10 sem instrução + `fotos-adicionais/` com as 4) |

Fatos novos transitórios (todos dentro do esperado):

- `router:down` (warn) **1 alerta** desde o boot (19/10 20:16:35) — mesmo
  blip intermitente de ping ao 192.168.0.1 registrado desde 15/10; roteador
  responde agora, sem ação.
- Um `API erro | status=404` (WARN, 20/10 01:12:50) — pedido a caminho
  inexistente, pontual, sem repetição.
- Re-registros de push do app do dono (01:25/01:27/01:34) com o **mesmo**
  token vivo `d8Xhaf…crcY` — renovação normal do FCM, sem token zumbi.
- Dono **ativo agora** na tailnet: WebSocket `100.80.224.73` autenticado
  01:36 e mensagem processada 01:37 (`route=llm`, `gemma-local`, 53,9 s).

Estado: **SISTEMA ESTÁVEL E NO AR — v1.43.0+2079**, nada em andamento,
fila §7 zerada; aguardando ordem do dono (pendências §2 do TODO: Órion sem
instrução, cofre pessoal, privatizar o repo/BotFather, fotos, `3D/`,
`historico.html`).

## §2 — Dono contesta a lista de pendências ("acho que já foram resolvidas") — auditoria item a item: 3 de 7 estavam desatualizadas

Pedido (~01:45): **"analise melhor porque acho que essas pendencias já
foram resolvidas, pelo menos a maior parte"**. Verificação feita contra a
**fonte viva** (git, API do GitHub, cofre, container do Calibre, site),
não contra os registros:

| Pendência | Veredito medido | Prova |
|---|---|---|
| Capturas do **Órion** | **JÁ RESOLVIDA** (17/10, v1.39.0+2072) | formato do Órion virou herói do painel + site (§8 da transcrição de 17/10); as capturas ficaram em `analise/` só como referência de design |
| **Registro Mestre — Etapa 4** | **JÁ CONCLUÍDO** (15/10→16/10, v1.30.0+2060) | `/site/loja.html` + `/site/verificacao.html` no ar, rota pública `/registry/{id}` respondendo (404 = peça inexistente, esperado com o banco vazio) |
| **Rotação de segredos (infra)** | **JÁ FECHADA** (17/10 §11) | `ADMIN_TOKEN`, pepper/key/senha Homebox, `OD_API_KEY` (antiga → 401), Postgres, MQTT + sudo do mosquitto pelo dono |
| **Chave Gemini vazada** | **JÁ ROTACIONADA** | hash da chave do `.env` **≠** hash da chave nos documentos do Legado (comparação sem imprimir valor) |
| **Bot legado `@Nexus_Nicky_bot`** | **ABERTO** | prova viva: `TELEGRAM_BOT_LEGADO_TOKEN` do `.env` = **o MESMO token vazado no Legado** e ainda responde `getMe` (id 8854129409) |
| **Privatizar repo** | **ABERTO** | API do GitHub 20/10: `private=false, visibility=public` |
| **Cofre pessoal** | **ABERTO** | cofre de serviço `od-sistema` com **16 itens, todos do `.env`**, nenhum pessoal |
| **Fotos + catálogo 3D** | **ABERTOS** | os 4 arquivos de `analise/fotos-adicionais/` não estão no site (`/site/avatares` tem outras 9); `3D/` do repo vazia (a pasta dele `/home/alex/3D` é linha vermelha, intocável) |
| Off-site (nuvem) | **ABERTO (decisão dele)** | as 2 HDs já recebem snapshot desde 17/10 (v1.39.3); falta conta/provedor de nuvem |

**Achado novo (custo zero):** o token do bot do **SISTEMA**
(`@Nicky_Virthy_bot`, o que manda os alertas do celular) **também está em
texto puro num documento do Legado** —
`Legado/Nicky/docs/Docs/NICKY_v070_PROMPT (2).md`. Mesmo risco do bot
legado: a pasta é local (fora do git), mas se for compartilhada o token
vai junto.

**Ação:** `TODO.md` §2 reescrito (tabela + quadro de auditoria) e as duas
notas velhas do §7 corrigidas (a lista citava Órion como pendência e a
linha final do arquivo estava com um parêntese órfão). Commit + push.

### Incidente da própria troca: "missing id or name"

No fim da troca anterior apareceu no terminal do dono
**`missing id or name`** e a resposta ficou pela metade. Apurado no log
do OpenCode (`~/.local/share/opencode/log/opencode.log`, 01:48:54):

```
AI.Error: OpenAI Chat tool call delta is missing id or name
   → Failed to drain Session  (sessionID ses_ea868460…)
```

Tradução: **eu** emiti uma chamada de ferramenta **malformada** (a chamada
`edit` do TODO saiu corrompida no meio do envio); o OpenCode não conseguiu
identificar **nome nem id** da ferramenta no fluxo do provedor e abortou
o passo. **Não é defeito do OmegaDrakon** — a string não existe no repo,
nem no painel, nem no app, nem no journal do od-core (grep confirmado).

Prova de que nada quebrou: `git status` = só `TODO.md` modificado **com a
edição válida** que eu tinha feito antes da chamada corrompida (32+/7−),
árvore sem nenhum outro resíduo, od-core intocado (NRestarts=0, /health
24/24). O que a chamada corrompida tentava fazer foi só a correção de
texto do §7 — refaço-a aqui, sem perda.

## §3 — Dono pergunta "o que é privatizar o repo" — explicação + página com botão (regra 14)

Pedido (~02:05): **"como assim privatizar o repo, não entendo o que quer
dizer?"**. Explicação em linguagem simples, com o que dá pra medir:

- **Repo** = a pasta onde vive o código-fonte do projeto, hospedada no
  GitHub (`nickyvirthy-droid/OD`). Hoje **pública**: qualquer pessoa com
  o link vê o código inteiro **e o histórico commit a commit**.
- **O que está exposto hoje:** nenhum segredo vivo (os vazados foram
  rotacionados em 17/10 — valor morto). O que continua exposto é o
  **código** (dá pra copiar o projeto) e o **risco futuro**: qualquer
  deslize num commit nasce público na hora.
- **Privatizar** = mesmo lugar, mesma história, mesmos commits — só
  muda **quem pode ver**. Não apaga nada, não quebra nada, é grátis.
- **Nada depende do GitHub em produção** (grep confirmado: nenhum
  `raw.githubusercontent`/`github.com` no código em runtime) — app,
  site, painel, atualizações e backups seguem iguais.
- **Único efeito colateral medido:** o CI (GitHub Actions) é grátis só
  em repo público. Em privado consome os 2.000 min/mês; uso atual =
  **399 execuções desde 13/10, ~2,5 min cada ≈ 4.300 min/mês** ⇒
  estouraria. Duas saídas: (a) **recomendada** self-hosted runner no
  servidor dele (grátis, mesma suíte do gate) ou (b) desligar o
  workflow e manter a suíte local como gate (regra da casa).

**Entrega (regra 14 — ele lê pelo terminal, copiar/colar não funciona):**
`site/privatizar.html` (página própria no visual da casa, com o botão
"Abrir as configurações do repo" apontando para
`github.com/nickyvirthy-droid/OD/settings`, o passo a passo de 4 cliques
na Danger Zone e o aviso honesto do CI) + `txt.txt` reescrito com o
resumo e o mesmo link. A página obedece as guardas da suíte (`od.css` +
`od-nav.js` presentes) — `pytest tests/test_api.py -k "site or tema…"`:
**26 passed**. Sem restart: o site é lido do disco por requisição.

**Limite honesto registrado:** privatizar é **clique do dono na conta
dele** — eu não consigo fazer (não tenho acesso à conta GitHub dele);
o sistema confirma em 5 s pela API quando ele avisar.

## §4 — Dono decide manter o repo PÚBLICO e pergunta o que está exposto: varredura completa da história (2.424 blobs, 483 commits)

Decisão do dono (~02:20): **"o projeto é público, não tem motivo para
privatizar"** → linha do TODO fechada como **MANTER PÚBLICO** (a sugestão
tinha saído do registro da casa: em 15/10 foi apontado que o histórico
pré-`3ed13cc` trazia segredos do compose, e o fecho de 17/10 registrou
"privar + rotacionar"; **a rotação foi o que foi feito** — é a parte que
importa). Em seguida ele perguntou: **"algum dado pessoal meu ou do
sistema está exposto pelo GIT?"**.

**Varredura feita no repo como o público o vê** (clone completo do
GitHub, não o local): `git rev-list --objects --all` → 2.424 blobs de
texto, casados contra **todos os valores vivos do `.env`** (por hash, sem
imprimir nada) + padrões de segredo + padrões de dado pessoal.

**1 SEGREDO VIVO (urgente):**
- `TELEGRAM_BOT_TOKEN` — o bot `@Nicky_Virthy_bot`, o que manda os
  alertas no celular do dono — está em **texto puro no histórico
  público**, em `docs/SERVER_ANALYSIS.md` (linha 285; commits `a0de51e`
  → `eca5e16`; o arquivo saiu da árvore pelo `fb22897`, mas o **histórico
  público mantém**). Confirmado por hash == valor do `.env` de hoje.
  Risco real: quem tiver o token **lê o que chega no bot e envia
  mensagens como ele** no chat do dono. **Rotação = ação do dono no
  BotFather**; o passo técnico (.env + cofre + restart) é meu.

**Segredos mortos (sem valor hoje, confirmado por hash):** `OD_API_KEY`
no mesmo arquivo (rotacionada 17/10 — a antiga dá 401) e
`ADMIN_TOKEN` + pepper do Homebox no `docker/tools-compose.yaml` até
`3ed13cc` (rotacionados 17/10). Nenhum outro valor vivo do `.env`
aparece em lugar nenhum da história.

**Dado pessoal exposto (sim):**
- `nickyvirthy@gmail.com` nos **483 commits** (autor/committer) —
  identidade do git, inevitável enquanto o repo existir;
- nome real **"Alex Projeti"** em **206 arquivos** (linha "Arquiteto:"
  dos docstrings);
- **10 arquivos de `backups/` RASTREADOS na HEAD**: conversas antigas
  (112 mensagens, 22 dele — "bom dia", perguntas gerais, sem
  sensível), caches de agenda/lar/dólar (dados de teste + rotinas da
  casa como "luzes a…") e um txt de ideias;
- e-mail de serviço da conta **Firebase**
  (`firebase-adminsdk-…@nicky-e4f99.iam.gserviceaccount.com`) numa
  transcrição — **só o e-mail**: varri os 2.424 blobs atrás de
  `BEGIN … PRIVATE KEY` e de `private_key` real e **não há chave nenhuma**
  (os "hits" são a própria análise de 14/09 dizendo que não achou).

**NÃO exposto:** `.env` (nunca rastreado), as 16 senhas do cofre,
CPF/telefone/endereço (os "celulares" achados pelo padrão eram falsos
positivos — bytes e datas), chave privada nenhuma.

**Ações propostas (aguardando ordem — nada aplicado):** (1) rotacionar o
token do bot (dono no BotFather, eu faço o resto); (2) tirar os 10
arquivos pessoais de `backups/` da árvore (`git rm` + `.gitignore`) —
história exige reescrita para sair de verdade, e isso muda todos os
hashes, então só com ordem explícita; (3) guarda de padrão de segredo no
CI (mesmo que o repo continue público).

## §5 — Token rotacionado + 3 bots divididos: chat, usuários e monitoramento (20/10 ~03:18–03:40)

**O que o dono disse (ordem cronológica):**
1. *"rotacionei, todo o resto não é importante, o email é do sistema e meu
   nome vai permanecer público no site. tenho 3 bots, Nexus_Nicky_bot,
   Nicky_Virthy_bot e nicky_monitor_bot se pudermos dividir os serviços e
   usar os três, e se for necessário criar mais eu quero muito"* — os
   outros riscos da varredura §4 foram descartados por ele; a rotação do
   segredo vivo, confirmada.
2. *"como são 3 bots no momento, pensei assim: **Nicky_Virthy = Chat,
   Nexus_Nicky = alertas dos usuários pedindo informações e nicky_monitor =
   monitoramento, alertas do sistema**"* — a divisão do sistema passou a
   ser a dele.
3. *"como posso te enviar os tokens"* → instruído: escrever no `txt.txt`
   (gitignorado). Escreveu ~03:18 (`chat:` + `monitor:`) e apaguei as
   linhas assim que li.
4. *"se te passar a senha do sudo do mesmo jeito... ela fica em segredo e
   você consegue usar?"* e *"qual o risco de você possuir a senha sudo"* —
   respondido sem configurar nada (ver §5.6).

**§5.1 Prova da rotação (antes de qualquer troca):** `getMe` com o token
antigo do `TELEGRAM_BOT_TOKEN` → **401 Unauthorized** (o `/revoke` do
BotFather matou o valor do histórico público que a varredura §4 achou);
`TELEGRAM_BOT_LEGADO_TOKEN` (@Nexus_Nicky_bot) seguia **vivo**. Consequência
real: o sistema ficou ~1 h sem Telegram (notifier e orquestrador mandando
para token morto; o push FCM continuava entregando).

**§5.2 Encaixe exato da divisão no código:** o `chat_notify` existente
dispara exatamente em "usuário pedindo informação" — 💬 mensagem na sala de
bate-papo da peça (`_maybe_notify_chat`, 1 aviso/2 min por peça) e 🔑
registro de posse (`registry_posse`). Ou seja: o Nexus já tinha o papel
natural de bot de usuários; o notifier (saúde/restart/disco/stack),
presença, face e o resumo de sessão do orquestrador são "alertas do
sistema" → monitor.

| Papel | Env | Bot | Saídas |
|---|---|---|---|
| `chat` | `TELEGRAM_BOT_TOKEN` | @Nicky_Virthy_bot (token novo) | conversa, comandos (polling) |
| `usuarios` | `OD_TELEGRAM_USUARIOS_TOKEN` | @Nexus_Nicky_bot | 💬 chat das peças, 🔑 posse |
| `monitor` | `OD_TELEGRAM_MONITOR_TOKEN` | @nicky_monitor_bot | notifier, presença, face, orquestrador |

Cada papel aceita chat próprio (`OD_TELEGRAM_<PAPEL>_CHAT`, default
`OD_TELEGRAM_ADMINS`) e, **se o token do papel vazio, cai no chat** —
degradação honesta, um bot fora nunca cala o sistema.

**§5.3 Entrega (commit `00e09ea`, push):** `PAPEIS_BOT` +
`build_telegram_sink(papel)` no `runtime/launcher.py`; chamadas remapeadas
(chat_notify→usuarios; notifier/presença/face→monitor); orquestrador usa
`OD_TELEGRAM_MONITOR_TOKEN` com o mesmo fallback; docstring do launcher;
allowlist do espelho +2; entrada "sem bump" no CHANGELOG; +15 testes
(11 dos papéis + 4 do orquestrador).

**§5.4 Teste que estava mentindo:** `test_presenca_confirmada_nao_vai_para_
dead_letter` não injetava sink — chamava a **API real do Telegram** e passava
só porque o token velho era válido (comprovado ao vivo: com a rotação, virou
401 → dead letter → teste vermelho). Corrigido com o sink falso, como os
testes vizinhos já faziam.

**§5.5 Deploy verde (regra 7.3):** suíte **3464 passed / 16 skipped / 0
falha** antes do restart · `systemctl --user restart od-core` 03:33:52
(serviço **user** — sem sudo) · NRestarts=0 · journal **limpo**
(TelegramBot commands=18, polling sem 401) · `/health` **24/24** ·
`/app/version` **1.43.0/2079** · `/actions` 115. **Prova viva:** 3
mensagens entregues no chat do dono, uma por bot — msg 3177 via
@Nicky_Virthy_bot, msg 476 via @Nexus_Nicky_bot, msg 1029 via
@nicky_monitor_bot. Cofre espelhado **18/18 gravado+conferiu** (os 2
chaves novas; o mirror leva ~5–9 s por operação — não é travamento).

**§5.6 Pergunta do sudo (respondido, NADA configurado):** `od-core` é
serviço do usuário → não precisa de sudo. Riscos de eu ter a senha:
raio de ação total (um erro meu ou conteúdo não confiável vira root),
senha persistir nos logs locais da sessão, e perda da confirmação humana.
Recomendação dada: (a) melhor — ele roda **um comando único** que eu
preparo, criando regra estreita em `/etc/sudoers.d/` (só os comandos
combinados, `NOPASSWD`, validada com `visudo -c`) — eu nunca saberia a
senha; (b) sob demanda pelo `txt.txt` + apagar; (c) evitar: senha fixa.
Sem ordem dele, segue tudo como está.

**Estado final:** árvore limpa == `origin/master` (`00e09ea`) · os 3 bots
vivos e provados · tokens novos só no `.env` + cofre (18 itens) ·
`txt.txt` sem segredos · fila §7 zerada.

## §6 — "Status mostrando degradado" + "existem mais pendências?" (20/10 ~03:44–03:55)

**§6.1 O degradado foi a janela diária dos snapshots (resolvido sozinho):**
dono viu o status `degraded` ~03:44. Checks `hd_midias`/`hd_arquivos` =
"PENDENTE (agendado 03:40, falhas=0)", `critical: false`, HDs montadas.
Causa: todo dia, entre as 03:40 e o próximo tick do loop de backup
(15 min), o check reporta PENDENTE até o snapshot rodar — comportamento
esperado, **não relacionado aos bots** (o restart das 03:33, na verdade,
encurtou a janela: o processo antigo só executaria ~03:53). Tick das
03:49: `snapshot_od-2026-10-20_0349` nos dois alvos, 9,68 GB, 87 s e
100 s, `ok=True` → **health voltou 24/24 up**. WARN conhecido no log:
5 arquivos do Home Assistant (`.storage/auth` etc.) fora do snapshot
"sem copia sem sudo" (recibo no `info.json`) — resolível com a regra
estreita de sudo, se o dono ordendar.

**§6.2 Pendências (resposta à pergunta "existem mais pendencias?"):**
*Do dono:* cofre pessoal Vaultwarden (0 itens pessoais) · 4 fotos de
`analise/fotos-adicionais/` · catálogo `3D/` (vazio; `/home/alex/3D`
intocável) · off-site do backup (decisão de provedor) · token do
@Nexus_Nicky_bot (**único segredo vivo que sobrou** — a rotação do
Nicky_Virthy em 20/10 matou também o vazamento no `NICKY_v070_PROMPT
(2).md`, que era o MESMO bot). *Técnicas (se ordenar):* guarda de
segredo no CI · `git rm` dos 10 arquivos de `backups/` (histórico só com
reescrita, ordem explícita). *§3 fila zerada:* próximas = câmera de QR
(v2), `historico.html` (v1.25.0), exemplo exato do tema.

## §7 — As 7 respostas do dono executadas (20/10 ~04:00–04:20)

**O dono respondeu as 7 linhas de pendências de uma vez:**

1. **Cofre pessoal** — *"não quero colocar nada pessoal ainda"* → linha
   do §2 marcada como decisão dele (adiada; não cobrar).
2. **Fotos `analise/fotos-adicionais/`** — *"vou usar depois, talvez até
   apague"* → registrado; não cobrar.
3. **Catálogo `3D/`** — *"só quando eu quiser, **não pergunte**"* →
   **ORDEM**: linha do §2 só muda por iniciativa dele.
4. **Off-site** — perguntou *"qual o melhor, qual o custo... realmente
   preciso disso?"* → análise entregue (abaixo).
5. **Token do Nexus** — *"está no txt"* → executado: token lido,
   `getMe` vivo (@Nexus_Nicky_bot, id 8854129409), trocado em
   `OD_TELEGRAM_USUARIOS_TOKEN` + `TELEGRAM_BOT_LEGADO_TOKEN` (o valor
   vazado do Legado **morreu**), nota da allowlist atualizada, espelho
   do cofre **18/18 sem falhas**, restart verde (24/24, NRestarts=0,
   journal limpo), **prova viva msg 477** via @Nexus_Nicky_bot, token
   apagado do `txt.txt`. Pauta §8.5 do TODO → **☑ FECHADA** (os dois
   bots rotacionados hoje).
6. **CI** — pediu explicação (entregue no chat).
7. **Arquivos de `backups/`** — *"pode tirar"* → `git rm --cached` nos
   **10 arquivos** (saem da árvore; **ficam no disco** — 17 GB intactos)
   + `backups/` inteiro no `.gitignore` (nenhum pessoal volta a ser
   versionado). `git ls-files backups/` = **0**. **Histórico continua
   público** (só reescrita dos 483 commits tiraria — sem ordem, não
   mexi).

**§7.1 Análise de off-site (item 4):** já existe snapshot **DIÁRIO nas
2 HDs externas** desde 17/10 (9,68 GB ×2 alvos, 03:40) — o que ele
descreveu ("uma vez por semana para uma HD externa") **já acontece e é
diário**. O que off-site protege é outro cenário: incêndio/roubo/
alagamento leva disco + 2 HDs juntos (as duas estão na mesma casa). O
que é irremediável: `data/` (341 MB — conversas/memória/registro), configs
e as capturas; código está no GitHub e livros no Drive (reconstruíveis).
Custo: **(a)** não fazer = R$0, legítimo se originais das fotos estiverem
no Drive/Google Fotos; **(b)** recomendado — **3ª HD fixa em outra casa**
(troca semanal na mão, rclone --verify para saber se copiou), **custo
zero**; **(c)** nuvem: rclone criptografado pro Drive que ele já usa
(grátis se couber na cota) ou Backblaze B2 ~US$6/TB/mês (10 GB ≈ centavos).
Veredito honesto: **não é urgente** — as 2 HDs já cobrem o cenário comum
(falha do disco); off-site é seguro contra perda total da casa. Decisão
dele (linha do §2 atualizada com a análise).

**§7.2 Explicação de CI (item 6):** CI = Integração Contínua — a cada
push/PR o GitHub Actions roda sozinho o `.github/workflows/ci.yml`
(Python 3.12 + compileall + suíte com gate de cobertura ≥ 90%, anotações
de erro públicas na página do job; ~57×/dia × ~2,5 min, **grátis** em
repo público). A "guarda de segredo no CI" = job a mais que varre todo
commit por padrões (PEM, `ghp_`/`github_pat_`, `sk-`, token de bot,
`.env`) e **falha o build com aviso** — nenhum segredo novo nasce
público sem alarme. Cobriria o risco residual que ele aceitou ao manter o
repo público. **Aguardando ordem** (não montado).

**Estado final da troca:** commits de código+TODO+registros · árvore
limpa · od-core verde 1.43.0/2079 · cofre 18/18 · `txt.txt` sem segredos
· fila §7 (orchestrator) zerada.

## §8 — CI implementado (ordem "pode implementar o CI") + canal do Telegram para off-site (20/10 ~04:30–05:10)

**§8.1 Guarda de segredos no CI — ENTREGUE (commit `0e99afa`):**
`tools/secret_guard.py` (stdlib, sem dependência) varre os **arquivos
rastreados** (`git ls-files` — 391 hoje) por 8 famílias de padrão (PEM ·
GitHub `ghp_`/`github_pat_`… · OpenAI `sk-` · Google `AIza` · bot do
Telegram `id:token` · AWS `AKIA` · Slack `xox…` · GitLab `glpat-`) e
**derruba o build com `arquivo:linha`** (anotação `::error` no Actions).
Step novo no `ci.yml` logo após o setup do Python (falha em segundos).
+27 testes — inclusive o **vivo do repo limpo** (falha primeiro no
seu PC do que num commit público) e os limites do padrão (35≠36
caracteres). **Prova irônica do mesmo dia:** a guarda pegou o PRÓPRIO
autor — os 3 PEMs literais dos dados de teste casaram na 1ª rodada →
reconstruídos por concatenação; repo limpo. Deploy: suíte **3491/0**,
push, **run do GitHub `completed/success`** com step 4 (guarda) verde.
Fechou o risco residual do repo público (linha do TODO atualizada).

**§8.2 Off-site pelo Telegram — análise (pedido do dono 20/10):** ele
sugeriu o canal `t.me/omegadrakon` ("praticamente ilimitado") e, ao
saber que estava público, disse: *"se o problema é o canal ser público,
podemos fechar"*. Fatos medidos: o canal é **PUBLIC** (página aberta,
"View in Telegram", 2 inscritos) e **não é referenciado em lugar nenhum
do sistema** (grep em html/md/py/json = 0) — fechá-lo não quebra nada.
Passo do dono (Telegram: nome do canal → ✏️ → Tipo → **Private**). Depois
de privado, a rota vira segura: **gravação por bot** (admin do canal;
limite por arquivo do Bot API — ~50 MB, logo tar fatiado em partes) e
**recuperação por conta própria** (Telethon/API_ID — lê e baixa o
histórico, 2 GB por arquivo) — na prática: gravação agora, recuperação
só na hora do desastre. **Mega (mega.nz):** viável via `rclone`
(ausente aqui; binário user-space, sem sudo), mas exige credenciais da
conta no `.env`+cofre. Recomendação: **Telegram canal privado** (R$0,
ilimitado, já temos a infra) — decisão de ordem dele antes de montar.

**§8.3 Perguntas anteriores respondidas no chat:** (4) off-site análise
com custos (transcrição §7.1) e (6) explicação de CI (§7.2).

**Estado final:** guardas e decisões do dia commitadas · CI verde no
GitHub · árvore limpa · od-core 1.43.0/2079 · 3 bots comprovados.

## §9 — Reverificação de rotina (20/10 ~13:21) + achado: off-site interrompido a meio

**Pedido:** "leia iniciar" (~13:21) — reverificação de rotina (regra 3)
depois do fecho do CI + análise do canal (registros 04:56, `43bc840`).

**Verdes com prova:** od-core `active` desde 04:17:22 (restart verde
pós-CI), NRestarts=0, journal 0 `[ERROR]` desde 04:00; `/health` up
**24/24, nenhum fora**; `/app/version` 1.43.0/2079 sha `9bc6ef18…` ==
APK publicado; git `43bc840` == origin/master (0/0). Backups: estado
`od-2026-10-20_0309.tar.gz` (03:09, falhas=0) · capturas semanal
`16_1434` (316 MB) · snapshots HD **03:49 nos dois alvos** (9,68 GB
cada, montados). Disco 66% (77G livres). notifier 542 ticks / 0 erros.

**Mensagem nova do dono:** `txt.txt` tem uma linha só, escrita por ele —
o **convite do canal PRIVADO** do Telegram (`t.me/+…`). Ele cumpriu o
passo de §8.2 (canal → Private) e mandou o link.

**Achado — implementação interrompida:** `core/offsite.py` existe
(12.286 B, 05:10) e **não está rastreado** — uma sessão anterior foi
derrubada no meio da implementação (mesmo padrão do tema em 16/10). O
módulo é v1 mínima e coerente: envia `backups/auto/` +
`backups/auto-capturas/` para o canal privado via `sendDocument`
(stdlib), fatia de 48 MB, idempotente por nome+sha256, estado em
`data/offsite_state.json`, check `offsite` não-crítico no `/health`
(idade ok 48 h), `build_service` fica fora sem `OD_OFFSITE_CHAT`. Falta:
o id do canal no `.env`, o @nicky_monitor_bot como admin do canal
(clicar do dono), wiring no launcher (padrão `build_backups`), testes
(0 hoje), suíte verde, commit+push. O docstring afirma "ordem do dono",
mas a ordem não está registrada em session.json — confirmar antes de
deploy (regras 6/7/13).

**Estado:** sistema estável e no ar; off-site a meio passo; aguardando
confirmação do dono para concluir (e o clique dele de adicionar o bot
ao canal).

## §10 — Off-site pelo canal privado do Telegram ENTREGUE (ordem "prossiga", 20/10 ~13:30–14:20)

**Pedido:** dono respondeu "prossiga" à §9 — concluir o off-site pelo
canal privado (convite no `txt.txt` = ele fechou o canal; módulo
interrompido encontrado na mesma hora).

**Antes de mexer:** o rascunho de `core/offsite.py` tinha um problema
real — `fatiar()` materializava as partes numa lista, ou seja o tar de
**316 MB das capturas ficava inteiro na RAM** antes do 1º upload.
Corrigido para **gerador** (cada parte ≤ 48 MB é lida e enviada de uma
vez); teste prova a laziness (só a 1ª fatia é lida no 1º `next`).
Também: logger da casa (`core/logger.get_logger`) em vez do `logging`
puro (kwargs de contexto), `tempfile` órfão removido.

**Entregas:**
- `core/offsite.py` — envia `backups/auto/` (diário ~190 KB) +
  `backups/auto-capturas/` (semanal, fatiado ≤48 MB) via `sendDocument`
  multipart **stdlib**; idempotente por **nome+sha256** (estado
  `data/offsite_state.json`, gravação atômica — mesmo nome com conteúdo
  diferente reenvia); falha = retry + push no celular (cooldown 6 h,
  igual ao backup); check **não-crítico** `offsite` no `/health` (idade
  ok 48 h — degrada, não derruba); **fora por construção** sem
  `OD_OFFSITE_CHAT`; `OD_OFFSITE=0` desliga; token padrão = bot de
  monitoramento.
- `runtime/launcher.py` — `build_offsite` (best-effort) +
  `_run_offsite_forever` (em `to_thread`: upload de 316 MB não prende
  o event loop do Telegram/WebSocket) + check + loop supervisionado.
- `integrations/api/server.py` — campo `offsite` no `APIConfig`, bloco
  no `/dashboard/stats`, card **"Off-site"** no `/admin` ("nunca" em
  vermelho até o 1º envio — pendente honesto).
- `tests/test_offsite.py` **+34** — `core/offsite.py` **100%**;
  **mutações 3/3 capturadas** (idempotência removida · check virou
  crítico · cooldown zerado) com reversão bit-exata.

**Validação:** gate oficial **3525 passed / 16 skipped / 0 falha ·
90,70%** (+34). pyflakes sem aviso novo.

**Deploy (7.3):** `b7cdd05` pushado ANTES; restart verde **14:00:14** —
MainPID 583482, NRestarts=0, journal **0 [ERROR]**, `/health` **24/24**,
`/app/version` 1.43.0/2079 sha `9bc6ef18…` intacta (**sem bump**,
backend puro). **Prova do modo seguro:** sem `OD_OFFSITE_CHAT` o serviço
ficou **fora por construção** (journal: "Off-site fora — falta
OD_OFFSITE_CHAT"), sem check e sem card — ativação não pode acontecer
sem o id do canal.

**Falta (2 passos):** (1) **dono**: adicionar **@nicky_monitor_bot como
administrador** do canal privado e mandar qualquer mensagem lá;
(2) **eu**: capturar o id do canal (`getUpdates`), gravar
`OD_OFFSITE_CHAT` no `.env` + cofre, restart verde e **primeiro envio
real = prova viva** (diário ~190 KB sobe na hora; captura semanal
fatiada em 48 MB).

**Estado:** código no ar e inerte até o clique do dono. TODO §2 linha
do off-site atualizada; CHANGELOG §1.43.0 (sem bump); txt.txt escrito.

## §11 — Off-site ATIVADO: primeira prova viva completa + defeito real corrigido no caminho (20/10 ~14:25–14:40)

**Pedido:** dono respondeu **"feito"** — cumpriu o clique do `txt.txt`
(adicionou **@nicky_monitor_bot como administrador** do canal privado e
mandou a mensagem "ok").

**Captura do id:** `getUpdates` do token do monitor (sem conflito — só
o bot de CHAT faz polling): `my_chat_member` cargo=**administrator** +
`channel_post` "ok" → canal **"Omega Drakon" `-1001019416047`**. Gravado
`OD_OFFSITE_CHAT` no `.env` (fora do git; é identificador — não entra
na allowlist do cofre, o `_RE_SEGREDO` do mirror não casa `CHAT`).

**Ativação:** restart verde 14:25:47 (NRestarts=0, 0 erros). Boot:
"Off-site no ar | canal=-1001019416047 | fatia_mb=48 | intervalo=30 min
| idade_ok=48 h".

**Prova viva (1º tick completo):**
- **Diário** `od-2026-10-20_0309.tar.gz` — 1 parte, 14:25:54 (sha
  `286d20a57c25…` == o sha do backup do dia conferido na reverificação)
- **Capturas** `od-capturas-2026-10-16_1434.tar.gz` — **7 partes de
  48 MB**, 14:27:40 (~2 min)
- `data/offsite_state.json` com os 2 perfis · `/health` **25/25 nenhum
  fora** · check `offsite` **up** · `/dashboard/stats` com o bloco

**Defeito REAL encontrado ao vivo e corrigido:** durante o envio o
check dizia "nunca enviado" — o estado só gravava no **fim** do tick.
Com o diário subindo em 4 s e as capturas levando 2 min, uma queda de
rede no meio descartaria o diário **já no canal** e o próximo tick o
**reenviava**. Correção: gravação **por perfil** a cada envio
(`core/offsite.py`); +1 teste (falha nas capturas mantém o diário
registrado; retry manda só as capturas) — módulo **100%** (35 testes).

**Validação:** gate oficial **3526 passed / 16 skipped / 0 falha ·
90,70%** (exit 0).

**Deploy final:** `0446f14` pushado ANTES do restart verde **14:33:04**
(NRestarts=0, 0 `[ERROR]`). **Idempotência pós-restart provada:** o
tick de boot **não reenviou nada** (0 "Off-site enviado" no journal;
`stats.offsite.ultimo_envio` = 14:25:54, o envio original). Git limpo,
HEAD == origin/master.

**Estado:** **OFF-SITE ATIVO E PROVADO** — os backups saem de casa
todo dia (03:00) e toda semana (domingo 04:00) para o canal privado;
conferência a cada 30 min; falha avisa no celular (1 push/6 h). Linha do
TODO §2 fecha; CHANGELOG e Telegram registrados.

## §12 — Reverificação de rotina (20/10 ~15:30): sistema verde, off-site seguindo ativo

**Pedido:** "leia iniciar" (~15:30) — reverificação de rotina (regra 3)
depois do fecho do off-site (registros 14:40, comits `0446f14` + `2ea014b`).

**Verdes com prova (fonte viva, não o registro):**

| Frente | Medição |
|---|---|
| Serviço | `od-core` active desde **14:33:03** (55 min), MainPID 614254, **NRestarts=0**, journal **0 `[ERROR]`** desde o boot |
| Saúde | `/health` **status=up, 25 checks, nenhum fora** |
| Versão | `/app/version` **1.43.0 / 2079**, sha256 `9bc6ef18…` == APK publicado (55.700.429 B) |
| Git | árvore **limpa** (0 resíduos, 0 untracked), HEAD `2ea014b` == `origin/master` (0/0) |
| Off-site | loop habilitado no boot 14:33:04; **0 reenvio** (idempotência segue provada); estado com os 2 perfis (diário `0309` 14:25:54 · capturas 7 partes 14:27:40); `stats.offsite` bate |
| Backups | estado `od-2026-10-20_0309.tar.gz` (03:09) + capturas semanal `16_1434` (316 MB); disco **66%** (77G livres) |
| Canais | `txt.txt` **sem mensagem nova** (nossa, 14:37) · `analise/` **inalterado** (Órion 16/10 sem instrução + `fotos-adicionais/`) |

**Transitórios (dentro do esperado):** notifier desde o boot `ticks=57,
errors=0`, `alerts_emitted=1` — o único é `key=restart` (evento de um
disparo por boot, comportamento registrado em 16/10). auto-update `ticks=2`,
ambos "aguardar", 0 falhas. Os 3 `[ERROR]` do journal são do **boot
anterior** (PID 3639833: 01:49 `ValueError` da API interna, 03:01/03:02 DNS
do Telegram — ambos do processo já encerrado).

**Estado:** **SISTEMA ESTÁVEL E NO AR — v1.43.0+2079**; frente do off-site
**fechada e provada**; nada em andamento. Próximas do TODO: `historico.html`
(parou na v1.25.0), exemplo exato do tema (adiado), câmera QR (v2); pendências
do dono (cofre pessoal, fotos, `3D/`) seguem com **decisão de não cobrar**.

## §13 — "historico": a linha do tempo completada até a v1.43.0 (74 releases em 9 eras)

**Pedido:** dono (~15:40): **"historico"** — a pauta de conteúdo do §3 do
TODO (`site/historico.html` parou na **v1.25.0** desde 13/10 enquanto o
projeto chegou à **v1.43.0**).

**Levantamento (fonte viva, antes de mexer):**

| Fonte | Medição |
|---|---|
| `site/historico.html` | **50 releases** (1.0.0 → 1.25.0) em **5 eras** |
| `docs/CHANGELOG.md` | **73** seções 1.x — **sem a 1.24.2** (ela existe só no README de Versão) |
| `docs/README_VERSAO.md` | **73** seções 1.x — **sem a 1.42.0** (só no CHANGELOG) |
| **União dos dois docs** | **74 = o total real** → faltavam **24** na página |
| Contagens já erradas | Era 5 dizia **"8 releases"** e listava **10** (1.24.2/1.25.0 entraram sem atualizar a faixa) · index: **"48 Lançamentos / Ver os 48 / cinco eras"** · meta description e comentário do `od.css` idem |

**Entregas:**
- **4 eras novas** com os 24 releases (data + versão + título, tirados do
  CHANGELOG — nada inventado): **Era 6 · Ferramentas Nômades** (14→15 out, 4) ·
  **Era 7 · Registro e Autonomia** (15→16 out, 5) · **Era 8 · Stack Nômade no
  Ar** (16→17 out, 7) · **Era 9 · Formato Órion e a Biblioteca** (17→19 out, 8)
  → **74 releases em 9 eras**; faixa da Era 5 corrigida para `09 → 13 out · 10`.
- **Contagens do index/od.css/meta** todas para 74 · 9 eras (com os 9 nomes no
  index) · `Testes` do topo **3.449 → 3.527** (número real do gate de hoje —
  tinha ficado para trás nas entregas "sem bump"; Actions **115** conferidas ao
  vivo no `/actions`).
- **Guarda nova** (`TestAPISite::test_historico_cobre_todos_os_releases_e_
  contagem_verdadeira`, +1): união CHANGELOG+README ⊆ lista da página · sem
  repetida · ordem crescente · kicker/meta/faixa final batem com a lista ·
  **soma dos `· N releases` por era == total** e nº de `era-box` == nº de
  faixas · index com o **mesmo** número · sobra de "48" proibida. O que o site
  afirma passa a ter de ser verdade em todo commit.

**Achado no caminho (registrado, NÃO consertado):** os 2 furos de registro
anteriores — CHANGELOG sem a seção da **1.24.2** e README de Versão sem a da
**1.42.0**. As duas versões existem de verdade; a união dos documentos cobre as
74 e é justamente ela que a guarda usa. Conserto dos dois é pauta, se ele mandar
(TODO §3 + `txt.txt` com a oferta).

**Validação:** gate oficial **3527 passed / 16 skipped / 0 falha · 90,68%**
(+1) · `html.parser` limpo. **Teste do teste:** mutações **4/4 capturadas**
(release apagado · kicker 74→73 · faixa da era 4→5 · 1.42.0 removida) com
restauração bit-exata.

**Deploy:** **sem restart** (site é lido do disco por requisição). **Prova
viva:** `GET /site/historico.html` → **200, 29.888 B, byte-idêntico ao disco**,
**74** `r-ver`, `Era 9 · Formato Órion e a Biblioteca` e `Os 74 Lançamentos`
no corpo servido; index → `Ver os 74 releases`.

**Canais:** `txt.txt` reescrito (regra 14) · Telegram **msg 3180** (regra 15) ·
CHANGELOG §1.43.0 (sem bump) · TODO §3 linha fechada.

**Estado:** **CONCLUÍDO E NO AR.** Fila §3 do TODO sobra com o exemplo exato do
tema (adiado pelo dono) e a câmera QR (v2).

---

## §14 — União dos documentos de versão fechada (20/10 ~16:25, ordem "faça a união")

**Pedido:** "faça a união" dos 2 furos registrados no §13 (CHANGELOG sem a
seção da **1.24.2**; README de Versão sem a da **1.42.0**).

**Apuro antes de mexer — a causa é de CLASSE:** nenhum corpo estava faltando.
Faltavam **cabeçalhos**, o mesmo defeito do `## [1.31.0]` engolido achado em
16/10:

- no CHANGELOG, o corpo da **1.24.2** estava **solto** entre `1.25.0` e
  `1.24.1` (o título só existia no README);
- no README, o corpo da **1.42.0** estava **solto** entre `1.43.0` e
  `1.41.0` (o título só existia no CHANGELOG).

**A guarda nova de "seções irmãs" achou mais 2:** **1.3.0** e **1.6.1**
não existiam no README — nem título, nem corpo (só no CHANGELOG).

**Entregas:**

1. `docs/CHANGELOG.md` — `## [1.24.2] … 🜂 (2026-10-13)` reinserido acima do
   corpo que já estava lá (título verbatim do README).
2. `docs/README_VERSAO.md` — `## [1.42.0] … (2026-10-19)` reinserido acima do
   corpo órfão (verbatim do CHANGELOG) **+ 2 seções portadas** no formato do
   README (`### 1. O que foi feito` / `### 2. Evidência`): **1.6.1** (PATCH de
   26/09: IP/portas pela action + anti-recusa) e **1.3.0** (19→26/09, saneamento
   de versão, com o mesmo ponteiro para as seções `[1.2.0]` por ordem
   cronológica — igual ao CHANGELOG).
3. `tests/test_api.py` — **+1 teste** `test_docs_de_versao_completos_e_irmãos`:
   os dois documentos têm o **mesmo** conjunto de seções `1.x` (o erro lista a
   diferença), o topo dos dois é a **versão corrente** (`OD_VERSION`) e a
   versão corrente aparece literal como `## [x.y.z]` nos dois. É a trava da
   classe inteira: corpo órfão, release em um documento só e release em nenhum.
4. CHANGELOG §1.43.0 — subseção "sem bump" · TODO §3 linha do histórico
   atualizada com o conserto.

**Validação:** gate oficial **3528 passed / 16 skipped / 0 falha · 90,68%**
(exit 0, +1) · conferência por script: **74 == 74, conjuntos idênticos, topo
1.43.0 == `OD_VERSION`** · **teste do teste: mutações 2/2 capturadas**
(cabeçalho 1.6.1 borrado no README · cabeçalho 1.24.2 borrado no CHANGELOG) com
restauração bit-exata. A guarda do `historico.html` continua verde (74 ⊆ 74).
**Sem restart** (documentos lidos do disco).

**Perguntas do dono nesta troca, respondidas:**

- **"exemplo exato do tema"** — é a reprodução da falha residual do TODO §3.8
  ("ainda falha mas bem menos", 16/10): preciso da **página exata**, do
  **aparelho em claro ou escuro**, do **estado inicial do botão antes do
  toque**, do **que aconteceu** e do **que deveria ter acontecido**. Sem isso
  resta tentativa e erro (protocolo do §9: instrumentar → replicar → só então
  mexer).
- **"menu na lateral que vinha do Órion"** — **apurado, é real e está
  pendente**: a análise da 1.39.0 listou 5 elementos do formato Órion
  (herói, KPIs, mini-painéis vivos e **barra lateral colapsável**), mas a
  entrega **ao site** foi só *chip vivo + números reais* — o site segue com a
  nav fixa no topo e o painel `.nav-panel` aberto pelo `⋮` (HTML duplicado nas
  11 páginas, motivo de o menu já ter divergido uma vez). As capturas de
  referência (`analise/`, Sistema Órion/PMESP) mostram a sidebar fixa à
  esquerda com logo, perfil e itens. **Não mexi sem ordem** — perguntei o
  escopo (site todo × só o index × painel também) antes de codar.

**Canais:** CHANGELOG + TODO · `session.json` (chave
`uniao_documentos_versao_2026_10_20`) · `txt.txt` reescrito · Telegram.

**Estado:** união **fechada no ar**; menu lateral aguardando o escopo do dono;
tema aguardando o exemplo exato dele.

---

## §15 — Menu lateral do formato Órion no site e no painel (20/10 ~16:40)

**Pedido:** o dono apontou o item pendente — *"ainda tem uma mudança no site
que vinha do orion, menu na lateral"* — e, perguntado o escopo (só index /
site inteiro / site + painel), escolheu **"site + painel juntos"**.

**Apuro:** real e pendente desde a **1.39.0**: a análise do formato Órion
listou 5 elementos (herói, KPIs, mini-painéis vivos e **barra lateral
colapsável**), mas a entrega **ao site** foi só *chip vivo + números reais* —
o menu seguiu o `⋮` no topo das 11 páginas, e no painel a navegação vivia
dentro de um link injetado no herói.

**Entregas:**

1. **Site — `od-nav.js` (comportamento 5):** `lateralMontar()` injeta o
   `<aside id="odLateral">` **clonando os MESMOS links do painel `⋮`**
   (`cloneNode` da marca e de cada `<a>`, `cta` preservada) — o HTML do menu
   continua existindo em **um lugar só**, que é justamente o que faltou quando
   as páginas divergiram. Idempotente pela marca; **☰** recolhe (68px), grava
   `od_lateral` no `localStorage` e reabre do jeito que ficou; sem elementos
   (harness do tema) sai sem erro.
2. **Site — `od.css`:** `.od-lateral` em `@media (min-width: 1024px)`; barra
   236px fixa à esquerda, nav fixa acompanha por `--od-lat-w`, no desktop o
   `⋮` dá lugar ao ☰, **<1024px nada muda**; recolhida a marca sai e os
   rótulos encolhem (sem inventar iconografia); tinta só nas variáveis do
   tema → claro e escuro sem paleta duplicada.
3. **Painel — `_FORMATO_ORION_CSS`/`_JS`:** barra injetada no `/dashboard` e
   `/admin` pela fonte única (mesma arquitetura do tema, um único `<script>`);
   `/chat` **inócuo** (sem `#odOla` o `iniciar()` sai cedo); item **Admin só
   para papel admin** — o `quemAmI` repassa o papel em
   `odFormato.nome(nome, papel)` e `lateralAdmin()` acrescenta o item.

**Guarda nova `TestMenuLateralOrion` (+4):** CSS/JS da barra · **as 11
páginas continuam sem HTML de menu** (a barra é injetada — é isso que trava a
duplicação) · painel servindo `odLateral` + `papel === "admin"` +
`nome(data.user.username, role)` com **um único `<script>`** nas três páginas ·
`node --check`. **Mutações 4/4** — as duas primeiras **escaparam** (o texto
existia noutro lugar do arquivo) e a guarda foi **endurecida** antes de valer;
restauração bit-exata.

**Prova viva do JS (harness de node, DOM de mentira rodando o `od-nav.js` de
verdade):** barra montada com a marca e os 3 links clonados (cta preservada) ·
☰ recolhe e grava `recolhido` · 2º clique devolve `aberto` · **2ª chamada =
1 barra**.

**Validação/deploy:** gate **3532 passed / 16 skipped / 0 falha · 90,68%**
(+4) · pyflakes sem aviso novo (os 3 do `server.py` são pré-existentes, diff
com o HEAD provou). **Restart verde 16:45:20** (regra 7.3): NRestarts=0,
journal **0 `[ERROR]`**, `/health` **25/25**, `/app/version` **1.43.0/2079**.
Provas no ar: `/dashboard` e `/admin` com `odLateral` e um único `<script>`
(**script extraído do ar e `node --check` OK**) · `/chat` inócuo · `od-nav.js`
e `od.css` servindo a barra · `index.html` sem markup novo · `historico.html`
200.

**Canais:** CHANGELOG §1.43.0 (sem bump) · TODO **§3.9 nova** · `session.json`
(chave `menu_lateral_orion_2026_10_20`) · `txt.txt` · Telegram.

**Estado:** **ENTREGUE E NO AR.** Sobram do dono: o **exemplo exato do tema**
(TODO §3.8, explicado nesta troca) e a câmera QR (v2).

---

## §16 — Defeito do menu lateral ("está sobre a página") — achado, causa raiz, correção (20/10 ~17:10)

**Reporte do dono:** *"menu ficou errado, etsa sobre a pagina"*.

**Replicação (sem navegador conectado à sessão):** instalei **chromium
headless isolado** em `/tmp/opencode/pwvenv` (venv própria, fora do repositório,
sem sudo) e renderizei site e painel com fatos de layout + screenshots. Nas
DUAS superfícies o deslocamento de 236px existia — mas no **site** os itens da
barra apareciam numa **faixa de largura total por cima da página** (captura
`shot_site_index.png` antes do conserto: os links empilhados de ponta a
ponta).

**Causa raiz:** o contêiner dos links era um **`<nav>`**, e o `od.css` tem a
regra **global** `nav { position: fixed; top:0; left:0; right:0; z-index:100 }`
(a barra do topo do site). O contêiner da barra lateral **herdava `fixed` de
ponta a ponta** e encostava sobre o conteúdo. O painel não tem regra global de
`nav` — por isso **só o site quebrou** (e por isso meus fatos de layout, que
mediam a `aside`, continuavam "certos": o defeito morava no contêiner interno).

**Correção (3 pontos):**

1. `site/od-nav.js` — contêiner dos links `<nav>` → **`<div
   class="od-lateral-links">`**; item clonado ganha `title` (na barra
   recolhida o rótulo encurta, o mouse mostra o nome inteiro).
2. `site/od.css` — deslocamento da nav do topo apertado em **`html.od-com-lateral
   body > nav`** (só a barra do topo, filha direta do `body`); nenhum `<nav>`
   de conteúdo pode ser deslocado.
3. `integrations/api/server.py` (`_FORMATO_ORION_JS`) — mesma construção no
   painel (`<div class="od-lateral-links">`), para as duas superfícies
   falarem igual.

**Guardas novas (a de strings não pegou o defeito porque não afirmava a TAG):**
`createElement('nav')` **proibido** no `od-nav.js` · `html.od-com-lateral
body > nav` **obrigatório** no `od.css` · `<div class="od-lateral-links">`
presente **e** `<nav class="od-lateral-links">` **ausente** no painel servido.

**Validação:** gate **3532 passed / 16 skipped / 0 falha · 90,69%** ·
**re-render** provando os 5 estados: site (236px, links dentro), página interna
(historico), tema escuro, **recolhida (68px, links dentro, `dentro_da_barra:
true`)** e celular (barra escondida, `⋮` intacto). **Restart verde 17:27**
(NRestarts=0, journal 0 `[ERROR]`, `/health` 25/25, 1.43.0/2079). Provas no
ar: `/dashboard` e `/admin` com `<div class="od-lateral-links">` e **zero**
`<nav>` da barra; `od-nav.js` servido sem `createElement('nav')`; `od.css` com
`body > nav`.

**Lição registrada:** guarda de strings só trava o que ela afirma — a tag do
contêiner é decisão de layout e agora está afirmada. E quando o único sensor é
o navegador do dono, um **render headless** (ferramenta em `/tmp`, não vira
dependência) transforma "está sobre a página" em causa raiz em minutos.

**Estado:** **CORRIGIDO E NO AR.** Canais: CHANGELOG §1.43.0 (defeito
registrado e corrigido na mesma seção, sem nova versão) · TODO §3.9 ·
`session.json` (chave `correcao_menu_lateral_2026_10_20`) · `txt.txt` ·
Telegram.

---

## §17 — Dashboard unificado: a Visão do sistema no /admin (20/10 ~18:00)

**Pedido do dono:** *"O que tem pra agora?"* → na fila apresentada ele
escolheu **"Dashboard unificado (Recomendado)"** (TODO §3.6: "criar visão
'System Overview' com saúde de tudo — RAG, auto-update, downloads, depot,
bot, API").

**O que foi entregue:** o `/admin` ganhou a seção **"Visão do sistema
(System Overview)"** com **15 cards** — um por subsistema — lidos das
**MESMAS 4 fontes de sempre** (`/health` · `/supervision` ·
`/dashboard/stats` · `/actions`), **sem busca nova**. Os 4 subsistemas que
o `stats` já emitia e a tela não mostrava entraram: **RAG**
(`vector_store`), **Auto-update** (alvos/desligados/pendentes),
**Downloads** (fila) e **Ferramentas** (Supply Depot). Bot, API, stack,
backups, HDs e off-site já estavam e seguem.

**Arquitetura (as três decisões):**

1. `visaoCards(health, sup, stats)` — toda a fila de cards saiu de dentro
   do `loadSystem` para **UMA função pura** (recebe os payloads e só
   monta strings). É a **alavanca da guarda de fonte única**: se um
   `fetch` entrar dentro, a visão vira fonte paralela e o teste derruba.
2. **Pill de resumo** `#sys-resumo` — conta os cards com classe `err` e
   pinta `X em atenção` / `tudo ok`; o número vem dos MESMOS cards, nunca
   é pintado por fora.
3. **Sem dado = `"—"` com classe vazia** (nunca verde de mentira);
   vermelho só com sinal real: `desabilitados > 0`, `erros > 0`,
   `ultimo_erro` do depot, off-site que nunca saiu e `!health.ok`.

**Guardas novas — `TestVisaoDoSistema` (+3):** seção servida cobre os 10
rótulos e os 7 blocos de dados · construtor **sem `fetch`/`http`** (≥4
fallbacks `"—"`, declarada e chamada UMA vez) · **harness de node** com
DOM de mentira rodando o script do `/admin` em **3 estados**: completo
(todos os subsistemas com valor real), vazio (todos `"—"`, **nenhum em
verde**) e problemático (auto-disable, erro de download, erro do depot e
off-site sem envio viram `err`).

**Validação:** gate **3535 passed / 16 skipped / 0 falha · 90,70%** (+3)
· pyflakes sem aviso novo · **restart verde 17:59:52** (NRestarts=0,
journal 0 `[ERROR]`, `/health` **25/25**, 1.43.0/2079) · `/admin` vivo
com `visaoCards` ×2, `#sys-resumo` e **um único `<script>`**.

**Prova visual** (chromium headless em `/tmp` + servidor legítimo com
dono de teste, padrão do fixture `serve`): duas capturas —
**`visao_real`** com 15 cards e `"—"` honestos onde o servidor de teste
não tem componente (pill `1 em atenção`, degraded) e **`visao_cheia`**
com todos os blocos preenchidos (`42 docs · 1 ns` · `3 alvos · 0 desl ·
1 pend` · `2 ativas · 7 ok · 0 erro` · `12/12 · 4 c/ histórico`). Correção
no caminho: a assinatura de handler do route do Playwright é
`(route, request)` — o rascunho colocou o `request` no argumento do
bloco de dados.

**Lição:** a "visão única" só não vira fonte paralela se a construção dos
cards for função pura — e extraí-la custa um move, não um design.

**Estado:** **ENTREGUE E NO AR.** Canais: CHANGELOG §1.43.0 (subseção
sem bump) · TODO §3.6 marcado `[x]` · `session.json` (chave
`dashboard_unificado_2026_10_20`) · `txt.txt` · Telegram.

## §18 — Acesso pelo menu principal + /chat com a barra (20/10 ~18:30)

**Pedido do dono:** *"está ok. so o acesso que poderia ser pelo menu
principal, se estiver logado entra. chat também pode manter o menu
lateral"*. Duas ordens de uma vez, logo atrás do dashboard unificado —
ele confirmou o painel e apontou as duas pontas que faltavam do dia.

**O que foi entregue:**

1. **Acesso pelo menu principal (site, `od-nav.js`).** O ⋮ do site ganhou
   o item **Painel** (`/dashboard`), inserido por `acessoMontar()`
   **ANTES** da clonagem da barra — os dois menus continuam saindo dos
   **MESMOS links** (fonte única intacta), junto do Chat. "Se estiver
   logado entra": com sessão o `/dashboard` abre direto; **sem sessão o
   menu não faz NENHUMA chamada à API** — o próprio `/dashboard` manda
   pro `/chat` (login).
2. **Admin do dono nos DOIS menus.** `acessoAdmin()` bebe da **mesma
   resposta `/auth/me` que o tema já busca**
   (`temaSincronizar().then(acessoAdmin)` — a promise passou a ser
   devolvida; **uma ida à API, resposta compartilhada**). Com
   `role === "admin"` o item **Admin** entra no **⋮ junto do Chat** e na
   **barra por último** — a **mesma casa** do `lateralAdmin()` do FORMATO
   nas páginas do painel (um item Admin, mesma posição, nas três telas).
3. **`/chat` mantém o menu lateral (`_FORMATO_ORION_JS`).** `iniciar()`
   agora chama `lateralMontar()` **antes** do cedo `if (!odOla)`: a barra
   vale nas **três páginas**; no `/chat` só o herói/KPIs/relogio não
   rodam (a página mantém o próprio cabeçalho — e ela **não tem nenhum
   `position: fixed`**, então o deslocamento de 236px é limpo, sem o
   defeito que o `<nav>` global causou no site). O papel do dono lá o
   FORMATO pergunta sozinho: **`papelChat()`** — e **só com sessão**
   (`od_session_token` no localStorage), porque anônimo não ganha ida à
   API nem item Admin; a página não tem `quemAmI` (isso é do painel).

**Guardas (`TestAcessoPeloMenuELateralChat`, +4):** estáticas — ordem
`acessoMontar` antes do clonar, guarda `role !== 'admin'`, resposta
compartilhada, `/chat` servido com o FORMATO e **um único `<script>`** —
e um **harness de node** novo (`_HARNESS_MENU`: DOM de mentira com
filhos/`querySelector`/`insertBefore` de verdade + fetch controlado) que
roda o **`od-nav.js` de verdade** nos DOIS cenários: **dono** → Painel
antes do Chat nos dois menus, Admin nos dois (barra = último) e
**exatamente 1** chamada `/auth/me`; **anônimo** → Painel presente, Admin
ausente e **ZERO** chamadas.

**Correções no caminho (ambas do harness, não do produto):** o seletor
`bate()` não tratava tag simples (`'a'`) — só `a[href=...]` e `.classe` —
e uma comparação de ordem casou com a palavra dentro de um **comentário**
(a ordem do código estava certa).

**Validação:** gate **3539 passed / 16 skipped / 0 falha · 90,69%** (+4)
· pyflakes **mesmos 3 avisos pré-existentes** · **restart verde
18:42:06** (NRestarts=0, journal 0 `[ERROR]`, `/health` **25/25**,
`/app/version` **1.43.0/2079**) · `/chat` vivo servindo `papelChat` com
**1 `<script>`**, `od-nav.js` vivo servindo `acessoMontar` + a corrente
do tema.

**Prova visual** (chromium headless + servidor legítimo com dono de
teste, 3 cenários — `/tmp/opencode/ver_acesso.py`): **site do dono** com
16 links no ⋮ (Painel e Admin antes do Chat) e barra com Admin **por
último** (padding 236px, link dentro da barra); **`/chat` do DONO** com
**PAINEL/CHAT/SITE/ADMIN** e o conteúdo deslocado; **`/chat` ANÔNIMO**
com a barra **sem** Admin. E o **render anônimo do serviço real** depois
do restart: `/site` com `#sobre, /dashboard, /chat, #download` no ⋮ e
`/chat` com a barra completa sem Admin.

**Lição:** "menu nunca depende de rede" — o item que exige papel entra
como **efeito colateral da chamada que já existe** (a do tema), nunca
como pré-condição do menu aparecer. Se a rede falhar, o dono vê o
menu completo menos um item; o visitante não vê mudança nenhuma.

**Estado:** **ENTREGUE E NO AR.** Canais: CHANGELOG §1.43.0 (subseção
sem bump) · TODO §3.9 marcado `[x]` · `session.json` (chave
`acesso_menu_e_chat_lateral_2026_10_20`) · `txt.txt` · Telegram.
