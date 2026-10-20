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
