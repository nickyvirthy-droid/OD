# Conversa 2026-10-12 — OmegaDrakon

## §1 — Retomada "leia iniciar" (~10:0x)

**Pedido:** usuário: "leia iniciar".

### O que a leitura mostrou

- `session.json` (última atualização 11/10 15:30) terminava na §5 de
  `iniciar/2026-10-11_conversa_omegadrakon.md`: fotos da Plêiade em SVG
  entregues, campos do banco respondidos (básico primeiro), segredos do
  Legado = mesmos do `.env` (rotação pode ser fechada; sobra higiene).
- **`txt.txt` com 2 mensagens novas do dono (11/10 à noite):**
  1. "quando mando atualizar pelo canal de desenvolvimento não recebo
     o resumo pelo telegram."
  2. "quando a sessão falha também seria bom receber um aviso."

### Achado: sessão órfã do canal de desenvolvimento (11/10 19:14–19:26)

O dono ativou o canal com exatamente essas 2 mensagens; a sessão
**concluiu e commitou `0e8e4c2`** ("feat(dev): … não recebo o resumo"),
testes 2419 passed / 16 skipped, `motivo: implantado` — mas:

- o commit **não foi para o `origin`** (HEAD `0e8e4c2` ≠ origin/master
  `421b889`);
- nada foi registrado em `iniciar/` — a sessão morreu no fim.

### Auditoria do diff (com o código em mãos)

`orquestrador.py` +96 (função `_notificar_telegram(estado)` lendo
`TELEGRAM_BOT_TOKEN`/`OD_TELEGRAM_ADMINS` do ambiente, formatando
resumo com status/ideia/CLI/motivo/commit/testes/diff/duração, envio
best-effort via urllib) chamada em `_encerrar()`. Verificado:

- **Todos os 6 caminhos de fim** passam por `_encerrar` → sucesso
  (`implantado`, `nada_mudou`) E falhas (`todas_as_clis_falharam`,
  `limite_de_autorizacoes_excedido`, `autorizacao_nao_respondida`,
  `testes_vermelhos`) → pedido 2 do dono coberto.
- **Sem restart:** o od-core spawna `orquestrador.py --sessao`
  desanexado do disco por sessão (`server.py:_sessao_ativar`, Popen
  cwd=REPO_ROOT) e o `main()` roda `load_dotenv()` na raiz → token/chat
  chegam. Backend only, sem bump (precedente 10/10 §3).

### 2 bugs reais corrigidos por cima (commit `f72d017`)

1. **Escape HTML:** a mensagem usa `parse_mode=HTML`, mas a ideia do
   dono (texto livre) entrava crua — um `<` ou `&` faria o Telegram
   rejeitar com 400 "can't parse entities" e o aviso **nunca chegaria**
   (o próprio problema reportado, de outra forma). Todos os campos
   dinâmicos passam por `html.escape`.
2. **Testes com rede real:** os 2 testes de formatação chamavam
   `urlopen` de verdade (api.telegram.org) a cada rodada — lento e
   frágil em CI sem rede — e não afirmavam nada. Fixture `capturas`
   substitui `urlopen`, inspeciona o payload (chat_id, CONCLUÍDA/
   FALHOU, duração) e +1 teste cobre o escape.

### Validação e publicação

- `tests/test_orquestrador.py`: **81 passed** (0,91s — sem rede).
- Suíte completa no `.venv`: **2420 passed / 16 skipped (84s)**.
- **Commits publicados** (regra 7.1): `0e8e4c2` (do canal) +
  `f72d017` (correções) — HEAD == origin/master.
- **Sem restart** (orquestrador lido do disco por sessão); od-core
  segue PID 1142795, NRestarts=0, journal 0 erros, `/app/version`
  1.24.1/2053.

### Prova viva (regra 15)

- `_notificar_telegram` real com `.env` real → enviou sem exceção
  (mensagem de PROVA VIVA ao dono).
- Resumo de conclusão via API direta → **`ok: True`, message_id 2168**.
- `txt.txt` reescrito (regra 14).

### Pendências conhecidas (inalteradas)

- Fotos da Plêiade: SVG entregue 11/10 — aguarda o dono.
- Etapa 4 do item 2: registro do comprador no app + QR de posse + loja.
- Itens 3 e 5 da pauta de divergências (unificação de ID, ordem das
  frentes).
- Higiene de segredos: chaves vivas em texto puro nos docs antigos do
  Legado — nunca publicar/nuvem (regra 16). Rotação: fechada (não há
  segredo antigo fora do `.env`).

## §2 — Orquestrador dentro das regras da casa (fecho, retentativa, pendências)

### Pedidos do dono (2 mensagens conectadas)

1. "faça o orquestrador trabalhar dentro das diretrizes e regras já
   conhecidas. se a sessão concluir ok ela deve fechar tudo e limpar
   qualquer sujeira, também termina o serviço já que o serviço foi
   concluído. se der falha poderia tentar reiniciar mais uma vez."
2. "quando inicia ou retorna, verifica pendências e conserta os erros
   assim como acabou de fazer agora descobrindo que a sessão morreu sem
   publicar" (referência ao conserto manual do lote órfão `0e8e4c2` na
   retomada da manhã).

### O que mudou em `orquestrador.py`

- **Início**: `recuperar_pendencias()` — commit órfão local
  (`origin/master..HEAD > 0`) → `git push` automático (regra 7.1);
  estado anterior `ativo` (runner morto sem fechar) → anotação honesta;
  push falho vira anotação com o erro, nunca exceção. As anotações vão
  para o estado, a caixa do painel e o contexto da CLI.
- **Fecho de sucesso**: `_fechar_sessao()` só com commit ok —
  `git push origin master` → `estado.publicado`; `_limpar_residuos()` →
  `estado.limpeza`; conferência final → `estado.arvore_limpa` (mesmo
  critério do aviso de árvore suja).
- **Limpeza segura por desenho**: só `??` (untracked) descartável —
  sufixos `.pyc/.pyo/.tmp/.orig/.rej` e dirs
  `__pycache__/.pytest_cache/.od_sandbox`. `backups/`, `data/`, `logs/`
  intocáveis (regra 9); trabalho rastreado **nunca** é apagado.
- **Serviço da CLI termina em qualquer desfecho** (sucesso, falha,
  timeout): pgid = pid do filho capturado no nascimento e
  `_matar_grupo(processo, pgid)` após a `communicate`.
- **Retentativa**: `main_sessao` ganhou loop de `SESSAO_RETENTATIVA`
  (env `OD_DEV_SESSAO_RETENTATIVA`, default 1). Motivo determinístico
  (`limite_de_autorizacoes_excedido`) não retenta — repetir é o mesmo
  desfecho. Caixa avisa "tentativa N de M".
- **Prompt**: contrato de fechamento em `INSTRUCAO_SESSAO` (árvore
  limpa, orquestrador quem commita/publica/limpa, corrigir causa raiz).
- **Telegram**: linhas 🔁 Tentativa, 🩹 Pendências, 🌐 Publicado,
  🧹 Limpeza — todas com `html.escape`.

### Corrida de processo paga durante o próprio trabalho

A 1ª versão capturava o pgid com `os.getpgid(processo.pid)` logo após o
`Popen`. O `setsid()` do filho é **concorrente**: se o `getpgid`
ganhasse a corrida, o pgid capturado seria o do **nosso** grupo — e o
`killpg` do fecho mataria o próprio orquestrador. Corrigido para
`pgid = pid` (invariante do `start_new_session`). Prova com subprocesso
real: 2ª `communicate` não quebra, `wait` retorna na hora e
`killpg(pid)` alcança o órfão **depois** do líder sair — exatamente o
cenário do runtime sobrevivente do incidente 09/10 (APK 4049).

### Testes e validação

- `tests/test_orquestrador.py`: **81 → 108 passed** (+27: recuperação,
  limpeza, fecho, retentativa, serviço, notificação, prompt).
- **3 mutações aplicadas e todas capturadas** (6 falhas): retentativa
  desligada, fecho removido, push da recuperação removido. Reversão
  bit-exata → 108 verdes.
- Suíte completa no `.venv`: **2447 passed / 16 skipped (87s)**.
- 1 warning pré-existente em `tests/test_orchestrator.py` (marca
  asyncio em teste síncrono) — fora do escopo, não touchado.
- **Commit publicado** (regra 7.1): `6339383` — HEAD == origin/master,
  árvore limpa.

### Sem deploy

Runner é spawna do disco por sessão (`server.py:_sessao_ativar`,
`Popen cwd=REPO_ROOT, start_new_session=True`) — **sem restart**, od-core
intacto (PID 1142795, NRestarts=0).

### Pendências do dono (inalteradas)

Fotos da Plêiade (SVG pronto) · etapa 4 do item 2 (comprador+QR+loja) ·
itens 3/5 da pauta de divergências · higiene de segredos no Legado
(rotação fechada).

## §3 — Project NOMAD: leitura integral e mapa de absorção

### Pedido do dono (chegou no `txt.txt` durante o trabalho do §2)

> "você conhece o projeto-nômade.
> https://github.com/Crosstalk-Solutions/project-nomad
> ele tem muitas da coisas que já temos e outras que ainda quero.
> voce consegue ler todo o sistema, pode baixar se for necessário, e
> absorver para dentro do nosso projeto."

### Leitura integral

Repositório clonado (`/tmp/opencode/project-nomad` — 693 arquivos,
29 MB) e lido por inteiro (agente de exploração a fundo + leitura
direta). Análise entregue em **`docs/ANALISE_PROJECT_NOMAD.md`**.

### O que é

Servidor offline de conhecimento/educação — "Command Center" (AdonisJS +
TypeScript + Inertia/React + MySQL + Redis) que orquestra ferramentas
containerizadas via Docker: Wikipédia ZIM (Kiwix), chat IA + RAG
(Qdrant), educação (Kolibri), mapas, CyberChef, notas, benchmark de
hardware, catálogo de apps e auto-update em 3 camadas. ~55–70k linhas.

**Stack diferente da nossa** → absorção é de **ideias e padrões**, não
de código (Apache-2.0 permite trechos com atribuição; mas a tradução é
para o nosso Python/Flutter, no estilo do que já fizemos com o Legado).

### Já temos (não duplicar)

Chat com streaming, sessões, histórico, persona/system-prompt (o
`NOMAD.md` deles é um system prompt editável — já temos personas),
API, painel admin, telemetria zero. **Nossa auth é mais forte que a deles**
— eles NÃO têm nenhuma (session middleware comentado, CSRF/CSP com
"TODO"; postura deles: "proteção é via rede").

### Ele tem e nós não temos (ordem de valor)

1. **Pipeline RAG completo** — reescrita de query com histórico,
   relevance floor + reranker, orçamento de contexto com métrica do que
   foi descartado, calibração por modelo.
2. **Eval harness** — goldens JSONL, modos oracle/e2e/noretrieval,
   baseline commitada como gate de CI.
3. **Referência médica** — openFDA + condições→o que usar + interações +
   banners de segurança; dados curados reaproveitáveis; encaixa no
   fastpath de intents.
4. **Auto-update em camadas** — janela, cool-off, cap de bytes,
   auto-disable em 3 falhas, dry-run determinístico.
5. **Fila de downloads resumable** — retry, progresso SSE, dedup.
6. **Wizard de setup** por capabilities com projeção de disco.
7. **Catálogo estilo Supply Depot** → registro de skills/tools do
   orquestrador.
8. **Tradução offline** (`nomad-translate` — já é Python).

### Descartado (com motivo)

Kolibri/CyberChef/FlatNotes/ProtoMaps/Kiwix-ZIM completo,
benchmark+leaderboard, sidecar Docker de update, Supply Depot como
Docker — ferramenta de terceiro ou específico de instalação offline
multi-container.

### Padrões de ouro levados

Pipeline de decisão puro + **dry-run determinístico** (o `evaluate()`
com overrides de relógio/releases/preflight roda o MESMO caminho em prod
e CI) · funções decision puras com spec própria (58 specs) · cool-off
ancorado em "first seen" com severidade skip vs failure · guardrails de
disco antes de ingestão pesada · eval como gate de CI.

### Próximo passo

Dono escolhe a ordem das **partes A–F** do `docs/ANALISE_PROJECT_NOMAD.md`
(sugestão: A = eval primeiro — dá métrica para julgar as demais; depois
C = referência médica, quick win visível no chat). Cada parte em sessão
própria do canal de desenvolvimento, com teste + commit + publicação
(regras 7.1/7.3).

## §4 — Retomada "leia iniciar" (~20:15): 3 constatações + 2 consertos no ar

### Achados

1. **Fix do TXT commitado mas não no ar.** A sessão das 14:29–14:49
   (commit `38eff9b`, isenção de rate limit em `/admin*`) publicou o
   código, mas o od-core rodava desde **10/10** — processo velho, sem o
   fix. Prova: 35 requests a `/admin/registry` → 401×28 e depois 429
   (rate limit ainda ativo em `/admin`). A reclamação do dono ("não
   consigo escrever texto longo no TXT… rate_limited") estava tratada no
   disco e **viva no ar**.
2. **od-stirling-pdf em crash loop — 1917 restarts.** Causa raiz nos
   logs: `java.lang.OutOfMemoryError: Metaspace` — o
   `MaxMetaspaceSize=128m` embutido no entrypoint da s-pdf 2.13.1 não
   segura as classes do Spring. Healthcheck falhava (curl rc=7 no
   `/api/v1/info/status`) e o `restart: unless-stopped` reiniciava em
   loop por ~13 h.
3. **od-kiwix em crash loop — 763 restarts.** `/data/wikipedia.zim`
   com **0 bytes** (o download anterior falhou no meio; a URL estável do
   compose dá 404 porque o mirror do Kiwix só serve **nomes datados**).

### Ações

- **Restart verde do od-core (regra 7.3)** — suíte `2488 passed / 16
  skipped` verdes, HEAD == origin/master, árvore limpa. Novo PID
  3299638, NRestarts=0, `/health` 9/9, journal 0 erros, `/app/version`
  1.24.1/2053. Prova pós-restart: 35×`/admin/registry` → **401×35**
  (isento de 429) — o fix do dono está **no ar**.
- **Stirling curado** (`docker/tools-compose.yaml`, commit `699ef6c`):
  `JAVA_TOOL_OPTIONS` com `-XX:MaxMetaspaceSize=256m` (mesma lista do
  entrypoint, metaspace dobado) + `mem_limit` 1g→1500m. Container
  recriado → **healthy, restarts=0**.
- **Kiwix**: zim de 0 bytes removido, container parado (sem loop
  inútil). Download em background de
  `wikipedia_en_all_mini_2026-09.zim` (**14,4 GB** — o nome estável
  antigo dá 404; o mirror usa nomes datados) com `wget -c` em
  `.wikipedia_en_all_mini.part`; um script em background renomeia e dá
  `docker start od-kiwix` sozinho ao terminar. Log:
  `logs/zim_download.log`.

### Estado

od-core verde e no ar (fix do TXT vivo) · Stirling healthy · Kiwix
aguardando o download do ZIM (sobe sozinho) · Vaultwarden + 6 outros
containers up · HEAD `699ef6c` == origin/master.

### Pendências do dono (inalteradas + 1 nova)

- **NOVA:** ao terminar o ZIM (~14,4 GB), o Kiwix sobe sozinho — aí
  falta `tailscale serve --bg http://127.0.0.1:8090` para acessar de
  fora (mesmo padrão das outras ferramentas).
- Vaultwarden: HTTPS (Tailscale Serve) + criar conta + fechar signups
  (`SIGNUPS_ALLOWED=false`).
- Fotos da Plêiade (SVG pronto) · etapa 4 do item 2 (comprador+QR+loja)
  · itens 3/5 da pauta de divergências · higiene de segredos no Legado.

## §5 — Limpeza do computador + zip para o HD externo (~20:45–21:50)

Dono retomou pela última coisa que lembrava: "limpando o computador,
retirando tudo o que o sistema não usa e compacta dentro de backup.
depois vou colocar esse arquivo dentro de uma hd externa". Regra 9 em
vigor: zip **primeiro**, verificado, e só então remoção.

### Levantamento (prova por grep/du/systemd)

- Disco principal 81 GB usados / 232 GB. `~/dados` (69 GB, Filmes) está
  em **disco separado** `/dev/sdb1` — não pesa no sistema.
- Serviço legado **omega-drakon.service ativo** desde 01/10 rodando
  `/home/alex/OD/od.py --daemon` (bot @Nexus_Nicky_bot, 44 MB RSS,
  idle). grep: o od-core não referencia nada de `OD/` (0 hits).
- `od-orchestrator.service`: unit já **inactive+disabled** (descreve a
  fila antiga `pedido.txt → codigo_gerado.py`; o canal atual executa
  `orquestrador.py` por sessão via `server.py`).
- `nicky.service` (system): disabled, aponta para `/home/alex/nicky`
  inexistente — pendência (remoção exige sudo).
- APKs publicados em `site/` = byte a byte os de `app/build` (sha256
  igual em fat e arm64); `app/build` guarda ainda armeabi-v7a e x86_64
  não publicados + mapping R8 e symbols.

### Decisões do dono (4 perguntas, nesta ordem)

1. OD antigo → **"Parar, analisar o que pode ser absorvido, compacto
   no ZIP, limpa tudo"**.
2. Modelos LLM não usados (gemma-4 4,6 GB, coder-7b 4,4 GB, qwen2.5-3b
   2 GB, 0,5B 0,5 GB) → **"deixa fora da limpeza"** (ficaram).
3. `~/.gradle` (7,9 GB) + `~/.npm` (1,1 GB) → **"Apagar direto"**.
4. `3D/` (1,2 GB) → **"fora da limpeza, serão catalogados posteriormente"**.

### Absorção do OD antigo (análise pedida por ele)

754 linhas de código no total. Veredito: **nada essencial a absorver** —
o sistema atual já cobre cada função: `evolution.py` (aider auto) →
canal de desenvolvimento; `guardian.py` (temp/disco/mem + alertas) →
`/health` perception + alertas proativos; `router.py` +
`skills_registry.py` → `core/intents` + catálogo de ações;
`sandbox/runner.py` → `.od_sandbox`; `telegram_bridge.py` →
`integrations/telegram`. Duas ideias registradas (não implementadas):
(a) limiares de alerta proativo do guardian (disco ≥80%, temp ≥80 °C);
(b) rate-limit "máx. N arquivos promovidos/hora" do evolution no canal.

### Zip (prova da regra 9)

`/home/alex/OD_limpeza_2026-10-12.zip` — **523,4 MB, 2.388 arquivos,
719 MB descompactados**, gerado em 19 s (zipfile, deflate nível 1,
`MANIFESTO.txt` dentro listando tudo). `testzip()` → CRC OK em todos os
arquivos; 11 peças-chave conferidas uma a uma; 0 venvs (único corte,
regeneráveis via `requirements.txt`, documentado). sha256 (32):
`83796ab45ade69f8efd4fdd7da21c853`. chmod 600 (Regra 16: não subir para
nuvem/site — pode conter credencial do bot legado).

### Limpeza executada (somente após o zip verificado)

- `/home/alex`: `OD/` (623 MB), `OD_backup_20260913/` (678 MB),
  `setup_nicky.sh`, unit `omega-drakon.service` (parada+desabilitada,
  depois removida + daemon-reload), `~/.gradle` (7,9 GB), `~/.npm` (1,1 GB).
- Repo: `*.so/` (53 MB), `lib/` (53 MB), `assets/` (52 MB), `archive/`
  (48 KB), `imports/` (vazio), `.od_repair_backups/` (recriado sob
  demanda — `self_repair.py:867` faz `mkdir(parents=True)`), lista de
  nomes de `recovery.py` só exclui por nome; `.aider.tags.cache.v4/`
  (940 KB), `app/build` (1,5 GB — `outputs/` preservados no zip),
  `app/.dart_tool` (540 MB), 12 soltos da era aider (`agent.py`,
  `codigo_gerado.py`, prompts `.sh`, `GPT_preview.png`, históricos
  `.aider*`, `.coverage`), `backups/od-historico-analise-…tar.gz`
  (311 MB; os 10 arquivos versionados de `backups/` permanecem),
  `iniciar/2026-12_conversa_omegadrakon.md` (0 linhas, typo de data).
- `instrucoes_projeto.txt` e `limitacoes.txt` **ficaram** (referenciados
  por `tests/test_orquestrador.py` e `core/limitacoes.py`).
- unit `od-orchestrator.service` removida (legada; content trivial:
  WorkingDirectory=repo + ExecStart=`orquestrador.py`, que o canal
  atual spawna por sessão).

### Resultado (provas)

- `df /`: 81 GB → **71 GB usados; 151 GB livres (32%)**. Repo
  4,0 GB → 1,6 GB.
- Serviços: od-core **active** (health 9/9) · od-llm **active** ·
  omega-drakon fora · zero unit enabled órfã.
- `git status`: apenas os 2 arquivos de registro modificados.
- ZIM: 5,1 GB de 14,4 GB (38%) — download sadio, sem tocar.

### Pendências (novas + anteriores)

- **NOVA:** dono copia `OD_limpeza_2026-10-12.zip` para o HD externo;
  zip fica no servidor até ele confirmar a cópia.
- **NOVA:** `nicky.service` órfã em `/etc/systemd/system` — remoção
  exige sudo (senha).
- `3D/` e demais pessoais: catalogação posterior (decisão dele).
- (anteriores) `tailscale serve` do Kiwix quando o ZIM subir ·
  Vaultwarden HTTPS + conta + signups · fotos da Plêiade · etapa 4 do
  item 2 · itens 3/5 da pauta.

### Confirmação do dono (~22:0x)

"pronto. zip copiado no hd externo" → **regra 9 fechada** (zip pronto +
usuário confirmou + HD externo). Cópia do zip mantida no servidor como
segunda salvaguarda (499 MB; some só se ele pedir, de preferência depois
de conferir no HD que abre). ZIM em 6,4/14,4 GB (48%), kiwix ainda
parado (sobe sozinho ao fim do download).
