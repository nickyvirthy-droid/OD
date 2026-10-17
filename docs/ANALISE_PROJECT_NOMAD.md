# OMEGA DRAKON — ANÁLISE DO PROJECT NOMAD

> **Finalidade:** mapear o Project NOMAD (github.com/Crosstalk-Solutions/
> project-nomad) para decidir, com o dono, o que absorver para dentro do
> OmegaDrakon. Pedido do dono no `txt.txt` de 12/10: *"ele tem muitas das
> coisas que já temos e outras que ainda quero. voce consegue ler todo o
> sistema, pode baixar se for necessário, e absorver para dentro do nosso
> projeto."*
> **Assinatura:** `OD // CORE` · **Data:** 2026-10-12
> **Fonte:** repositório clonado (693 arquivos, 29 MB) e lido por inteiro;
> licença Apache-2.0 (reaproveitar trechos é possível com atribuição)
> **Stack deles:** AdonisJS 6 + TypeScript + Inertia/React + MySQL + Redis
> ( **nada de código copiado: absorção é de IDEIAS e PADRÕES** — o nosso é
> Python/Flutter )

---

## 1. Sumário executivo

O NOMAD é um **servidor offline de conhecimento e educação** ("Command
Center") que orquestra um conjunto de ferramentas containerizadas via
Docker: biblioteca offline (Wikipédia ZIM/Kiwix), chat com IA + RAG
(Qdrant), educação (Kolibri), mapas offline, CyberChef, notas, benchmark
de hardware, catálogo de apps ("Supply Depot") e atualização automática em
três camadas. ~55–70 mil linhas de TypeScript/React/shell.

**O que ele tem e já temos** (sem duplicar): chat com streaming, sessões
persistidas, histórico, sistema de persona (o `NOMAD.md` deles é um system
prompt editável — nós já temos personas e system prompt), API, painel
admin, telemetria zero, app web.

**O que ele tem e nós NÃO temos** — a parte que vale absorver, em ordem
de valor para um assistente pessoal com voz:

| # | Capacidade deles | Por que serve ao OmegaDrakon |
|---|---|---|
| 1 | **Pipeline RAG completo** (reescrita de query com histórico, relevance floor + reranker, orçamento de contexto com métrica do que foi descartado, calibração de tokens por modelo) | É o maior ganho de qualidade de resposta — personas e memória do assistente |
| 2 | **Eval harness de RAG** (goldens JSONL, modos oracle/e2e/noretrieval, baseline commitada como gate de CI) | Métrica HONESTA de persona/voz/RAG antes e depois de cada mudança — hoje não medimos nada assim |
| 3 | **Referência médica**: dados openFDA + "condições → o que usar" + interações + **banners de segurança na UI** | Encaixa na voz ("tomou X e Y?"); os dados curados (`collections/conditions.json`, `natural_remedies.json`, `home_remedies.json`) são reaproveitáveis quase literais |
| 4 | **Auto-update em camadas** (janela noturna, cool-off, só minor/patch, cap de bytes, auto-disable após 3 falhas, pre-flight, dry-run testável em CI) | Padrão para atualizar modelos/voz/conteúdo RAG do próprio OmegaDrakon |
| 5 | **Fila de downloads resumable** (retry, progresso ao vivo por SSE, dedup, cancel) | Baixar modelos/datasets/documentos sem perder progresso; vira SSE no app Flutter |
| 6 | **Wizard de setup** por "capabilities" com projeção de disco | Onboarding do usuário no site/app |
| 7 | **Catálogo estilo Supply Depot** (pre-flight ao vivo, edit preserva customização, update com rollback) | Aplicável ao **registro de skills/tools/ferramentas** do orquestrador |
| 8 | **Tradução offline** (`install/nomad-translate/` — já é Python, proxy Bergamot) | Ideia pronta: tradução offline no assistente |

**O que ele tem que NÃO serve**: Kolibri/CyberChef/FlatNotes são só
containers de terceiros; mapas ProtoMaps e benchmark/leaderboard são
peculiaridades dele (o "builder tag" anônimo e a leaderboard pública não
fazem sentido para a nossa instalação privada).

---

## 2. Arquitetura (o que eles construíram)

- **Command Center** (`admin/`, ~45–55k linhas): AdonisJS + Lucid ORM,
  BullMQ (Redis), 46 migrations, 13 jobs, 37 services, 58 specs unit.
- **Orquestração Docker** via socket (`admin/app/services/docker_service.ts`,
  2.443 linhas): cria containers irmãos, rede única, storage único
  reescrito para o host; catálogo de serviços no banco via seeder
  (`service_seeder.ts`, 654 linhas) com merge que preserva edições do user.
- **Tempo real**: `@adonisjs/transmit` (SSE) para progresso de downloads,
  jobs de embed e telemetria de benchmark.
- **Rotas** (`start/routes.ts`, 910 linhas) documentadas por decorator
  `documented()` → OpenAPI gerado e servido **localmente** em `/reference`
  (amigável para offline).
- **Segurança**: **SEM autenticação nenhuma** (session middleware
  comentado, CSRF/CSP desabilitados com "TODO") — a postura do README é
  "proteção é via rede, não exponha à internet". Eles mitigam com guard de
  custom apps (bloqueia bind de `/etc`, `/proc`, docker socket…), SSRF
  (`assertNotPrivateUrl`) e escopo de logs. **Nós já somos mais seguros
  que eles** (auth real, papéis, vedação de IP/portas) — nada a copiar
  daqui, só confirmar que não regredimos.

### 2.1 Padrões de engenharia que valem ouro

1. **Pipeline de decisão puro + dry-run determinístico**: o
   `AutoUpdateService.evaluate(overrides)` aceita relógio/releases/
   pre-flight falsos; o MESMO caminho roda em produção e no CI
   (`node ace auto-update:dry-run --scenarios` — todas as ramificações
   sem rede/DB/Docker). Padrão direto para o nosso orquestrador e para
   qualquer lógica de decisão.
2. **Funções "decision" puras** (uma por dilema) com spec própria —
   `kb_ingest_decision.ts`, `content_auto_update_backoff.ts`,
   `queue_stall_options.ts`… 58 specs. É a mesma filosofia dos nossos
   testes de contrato, mais disciplinada na separação.
3. **Cool-off ancorado em "first seen"** + severidade `skip` vs `failure`
   (falha transitória não conta para auto-disable) — evita loop de update
   e desliga feature sozinha após 3 falhas com motivo gravado.
4. **Guardrails de disco** antes de qualquer ingestão/pull pesado
   (confirmação do usuário, pre-flight de tamanho via manifest).
5. **Eval como gate de CI**: baseline commitada com fingerprint do
   corpus; comparação bloqueia regressão.

---

## 3. Absorção proposta (em partes, com o dono escolhendo a ordem)

> Princípio: **não copiar código** — traduzir o padrão para o nosso
> Python/Flutter, no estilo do que já foi feito com o Legado
> (`docs/ROADMAP_ABSORCAO.md`). Cada parte entra com testes na suíte
> canônica antes de publicar (regra 7.1/7.3).

### Parte A — Eval do assistente (depois: gate de CI)
Goldens JSONL de perguntas reais × respostas esperadas; modos "com RAG /
sem RAG / oracle"; baseline versionada; comparação antes/depois de cada
mudança de persona ou prompt. **Esforço médio.** É o que dá métrica ao
que hoje é achismo.

### Parte B — Pipeline RAG de qualidade ✅ ENTREGUE (v1.26.0, 14/10)
Reescrita de query com histórico, floor de relevância, orçamento de
contexto (quanto foi descartado vira métrica), calibração por modelo.
**Esforço alto** — maior ganho de qualidade. Entregue com floor duplo
medido no corpus real (16 queries viraram gate na suíte), ingestão
idempotente de `docs/` + `knowledge/` (850 chunks no boot de 14/10), visibilidade por
papel (só `admin` recebe o acervo interno) e eval com
`prompt_contem`/`prompt_nao_contem` — o retrieval é provado em modo
oracle sem rede (CHANGELOG 1.26.0).

### Parte C — Referência médica e bem-estar ✅ ENTREGUE (v1.25.0, 13/10)
Actions determinísticas (sem LLM) para "condição → o que usar",
interações de medicamentos e fontes curadas; **disclaimer obrigatório na
resposta** (padrão `SafetyBanner` deles). Encaixa no `fastpath` de
intents que já existe. Dados deles: `collections/*.json` (Apache-2.0).
**Esforço médio.**
> **Implementado:** `saude_condicao`/`saude_interacoes`/`saude_medicamento`
> (`tools/actions/actions.py`), coleções versionadas em
> `tools/saude/collections/` (36 condições, 20 caseiros CDC/NIH, 18
> naturais NCCIH, lexicon de 46 medicamentos PT-BR→FDA), rota
> `_detect_saude` + `_formata_saude` com `SAUDE_AVISO` obrigatório, e a
> regra de que saúde **nunca degrada para o LLM** (fonte ausente = "não
> achei"). Labels de bula via openFDA ao vivo (dipirona não tem label
> FDA — dito como ausência). 45 testes (`tests/test_saude.py`) + 4 goldens.

### Parte D — Fila de downloads resumable ✅ ENTREGUE (v1.27.0, 14/10)
Retry com backoff, progresso ao vivo (SSE → app), dedup, cancelamento.
Útil para modelos, datasets e documentos. **Esforço médio-baixo.**
Entregue como `core/downloads.py` (`DownloadQueue` com worker próprio):
retomada de verdade por `Range` a partir do `.part` (um restart no meio
de 14 GB não zera nada — o boot re-enfileira o que estava em voo), sha256
incremental com `os.replace` atômico, backoff `2·2^(n-1)` limitado a 60 s
com erro permanente (404/sha divergente) fora do caminho de retry, dedup
por URL+destino e destino travado dentro de `OD_DOWNLOADS_DIR`. SSE
`GET /admin/downloads/events` (snapshot + `estado`/`progresso`/`removido`,
ping de 15 s) alimenta a seção **Downloads** do painel `/admin` e a 7ª
aba do app — que cai para polling de 5 s e reassina quando o stream morre
(mesmo contrato do chat com WebSocket). Progresso gravado no disco a cada
2 s, não a cada bloco (mesma lição do O(n²) da Parte B).

### Parte E — Auto-update de modelos/conteúdo
Janela, cool-off, cap de bytes, auto-disable, dry-run testável —
aplicado ao que o assistente baixa (modelos de voz/LLM, índice RAG).
**Esforço médio-alto** (mas o nosso `runtime/launcher` já tem o esqueleto).
✅ **ENTREGUE em 1.28.0** (2026-10-14): `core/auto_update.py` — o
`avaliar()` puro do §2.1.1 em 8 camadas (auto-disable → inativa → sem
mudança → major → janela → cool-off → backoff → cap+preflight), cada
decisão com motivo; cool-off ancorado em "primeiro visto" que recomeça
quando a versão vista muda; severidade `skip` vs `failure` (só falha
dura conta para o auto-disable às 3). O executor enfileira na fila da
Parte D (Parte D virou o motor) e ressincroniza o índice RAG quando
`docs/`+`knowledge/` mudam; downloads ficam staged e conferidos (sha256)
— troca de modelo em uso é decisão do dono. Dry-run = o MESMO caminho
do ciclo sobre cópia do estado (rota + botão do painel). Manifesto
editável `data/auto_update_alvos.json` para pinar url+sha+versão de
arquivos. Suíte +59 testes (tabela de ramificações do pipeline + executor
com fila/relógio falsos + integração REAL com a fila da Parte D).

### Parte F — Registro de ferramentas/skills estilo Supply Depot
Pre-flight (conflito, versão, tamanho), rollback, preservar customização
— evoluindo o catálogo de tools do orquestrador. **Esforço médio.**
✅ **ENTREGUE em 1.29.0** (2026-10-15): `tools/supply_depot.py` — o
`preflight()` puro (conflito → versão semver com downgrade bloqueado e
major só com `substituir=true` → tamanho/disco com a margem 1,1 da Parte
E) fecha a entrada; toda atualização grava backup + histórico (rollback
automático na falha, rollback manual desfazível); `custom` do dono
(descrição/params/permission) sobrevive a update, rollback e restart. O
`/gerar` passou a pré-voar ANTES do LLM (conflito honesto sem custo de
token — antes devolvia "ok" com o registro pulado) e a persistir em
`data/ferramentas/` — o boot (`build_supply_depot`) restaura no
registry: ferramenta gerada não some mais. 5 rotas `/admin/ferramentas`
(73 → 78), seção no painel, bloco no stats, health `supply_depot`
não-crítico, capability `tool-supply-depot`. Suíte +91 testes:
**2863 passed, 16 skipped · 90,52%** (`supply_depot.py` a 95%). Prova
viva em 3 fases no serviço (instalação → conflito 409 → update+backup →
custom sobrevive → rollback → exec → restart `carregadas=1` → limpeza).

### DECISÃO FINAL (12/10) — Virada da análise original

O dono **inverteu o descarte** das ferramentas de terceiros: "Sua razão valeu:
ferramenta de terceiro resolve dias de criação." As 8 ferramentas entram como
containers Docker (receitas do Nômade, Apache-2.0 com atribuição), ProtoMaps vira
tarefa de dev (página MapLibre + tiles, não container), LoRa na geladeira.

| Ferramenta | Decisão | Container | Porta local | Acesso | Notas |
|---|---|---|---|---|---|
| Kiwix (Wikipédia offline) | ✅ ENTRA | ghcr.io/kiwix/kiwix-serve:3.8.1 | 8090 | Tailscale | Precisa baixar ZIM 12,5 GB (URL estável 404 — achar no mirror) |
| Stirling PDF | ✅ ENTRA | ghcr.io/stirling-tools/s-pdf:2.13.1 | 8400 | Tailscale | 50+ ferramentas PDF, SECURITY_ENABLELOGIN=false |
| CyberChef + IT Tools | ✅ ENTRA | ghcr.io/gchq/cyberchef:10.24.0 + ghcr.io/corentinth/it-tools:2024.10.22 | 8100, 8430 | Tailscale | Data tools + dev utilities |
| Vaultwarden | ✅ ENTRA | vaultwarden/server:1.36.0 | 8480 | Tailscale (HTTPS obrigatório) | Cofre de senhas Bitwarden-compatível; criar conta + fechar signups |
| FlatNotes | ✅ ENTRA | dullage/flatnotes:v5.5.4 | 8200 | Tailscale | Notas markdown; auth=none (só Tailscale); API para actions |
| File Browser + Calibre Web | ✅ ENTRA | filebrowser/filebrowser:v2 + linuxserver/calibre-web:0.6.26 | 8410, 8420 | Tailscale | Arquivos + e-books; login admin/admin e admin/admin123 (trocar) |
| Homebox | ✅ ENTRA | ghcr.io/sysadminsmedia/homebox:0.26.2 | 8470 | Tailscale | Inventário ferramentas/peças/produtos; QR + API; login admin@admin.com/123 |
| ProtoMaps | 🛠️ DEV TASK | NÃO (página site) | — | Site | MapLibre GL + tiles; página dedicada no site |
| LoRa | ❄️ GELADERA | Quando comprar rádios | — | — | Preparar tudo depois |

**Descartados de vez** (confirmado): Kolibri, Jellyfin, Excalidraw, benchmark/leaderboard.

**Compose commitado**: `a2bba40` — 9 containers, todos bindados em `127.0.0.1`, limites de memória por container (RAM ~4,5 GB livres). **AINDA NÃO SUBIDO** — sobe quando o dono mandar.

**Segurança**: Funnel é PÚBLICO — só od-core fica nele (X-API-Key em tudo). FlatNotes/Stirling sem login, Homebox/File Browser com senha fraca — expor no Funnel seria buraco (cofre de senha e caderno de notas abertos pro mundo). Caminho certo: `tailscale serve` por ferramenta (só nos devices do dono). Vaultwarden exige HTTPS — o `serve` entrega.

**Bloqueio único**: Wikipédia 12,5 GB — URL estável do Kiwix deu 404 (nome datado). Precisa achar arquivo certo no mirror antes de baixar. Só atrasa o Kiwix — os outros 8 containers sobem sem ele.

---

### IMPLEMENTAÇÃO NO OMEGADRAKON (esta sessão — 12/10)

| Item | Status | Arquivo/Referência |
|---|---|---|
| **Compose Docker** (9 containers; **8 desde 17/10** — Homebox fora) | ✅ Commitado | `docker/tools-compose.yaml` (a2bba40) |
| **Actions nomad_tools_*** (8) | ✅ Implementadas + testadas | `tools/actions/actions.py` · `tests/test_nomad_tools_actions.py` (41 testes) |
| **Capability "nomad-tools"** | ✅ Registrada | `core/capabilities.py` (status: AVAILABLE) |
| **ProtoMaps** (página dev) | ✅ Implementada | `site/protomaps.html` (MapLibre GL + tiles ProtoMaps) |
| **ProtoMaps no site** | ✅ Linkada | `site/index.html` (nav + seção) |
| **Documentação da decisão** | ✅ Atualizada | Este arquivo (seção DECISÃO FINAL + esta tabela) |
| **Homebox fora do ar — stack = 8** | ✅ No ar (v1.34.1+2066, 17/10) | Bloco comentado no compose + `FERRAMENTAS_NOMAD` 8 + imagem removida (−198 MB) + dados preservados. Prova viva: `/health` **tool 8/8 sem `tool_homebox`**, `/dashboard/stats` `total=8 up=8`, journal 0 erros |
| **Cofre do sistema — Vaultwarden interligado (1ª das 3)** | ✅ No ar (v1.35.0+2067, 17/10) | 4 actions `vault_*` (categoria `vault`, só admin) + `integrations/vault.py` (conta de serviço separada, bw **2025.12.1 + Node 22** — 2026.x incompatível com as cifras do Vaultwarden 1.36, apurado ao vivo, LAZY). Prova viva: **E2E status→set→list→get→atualizar→apagar → cofre `[]`**, `/actions` **93** com as 4, `/health` **21 checks fora=nenhum**, journal 0 erros |
| **Pipeline de documentos — Stirling interligado (2ª das 3)** | ✅ No ar (v1.36.0+2068, 17/10) | 4 actions `stirling_*` (categoria `stirling`, só admin) + `integrations/stirling.py` (s-pdf **2.13.1** em `127.0.0.1:8400`, sem login; contrato **apurado ao vivo** — spec em `/v1/api-docs`, 255 rotas; multipart stdlib, mágica `%PDF`/`PK` **antes de gravar**, saída só com `substituir=True`, LAZY). Prova viva pelo `/executa`: **status 2.13.1 → merge 1234 B → page-count=2 → trava `stirling_saida_ocupada` → split ZIP 2 peças → compress 177072→5444 B (−96,9%)**, `/actions` **97**, `/app/version` **1.36.0/2068** (sha `b4a7247d…` == APK), journal 0 erros |
| **Espelho `.env` → cofre (12 credenciais)** | ✅ Feito (17/10) | `vault_env_mirror.py` (raiz): allowlist explícita das 12, MQTT pareado, notas (LEGADO = rotação §8.5 pendente; `OD_VAULT_MASTER` auto-referência), verificação por get+comparação **sem imprimir valores** — **12/12 conferem**, 12 itens no cofre do sistema, `.env` intacto como bootstrap |

**Actions Nômade implementadas** (categoria `nomad`, 8 total):
- `nomad_tools_up` — sobe todos os containers (docker compose up -d)
- `nomad_tools_down` — derruba todos (docker compose down)
- `nomad_tools_status` — status dos containers (docker compose ps)
- `nomad_tools_logs` — logs de serviço (docker compose logs)
- `nomad_tools_restart` — reinicia serviço específico
- `nomad_tools_tailscale_serve` — gerencia tailscale serve (up/down/status por serviço)
- `nomad_wikipedia_zim_download` — baixa arquivo ZIM da Wikipédia para Kiwix
- `nomad_vaultwarden_setup` — cria conta admin + orienta desabilitar signups

**Testes**: 41 testes cobrindo catálogo, constantes, helpers, cada action individual, integração via ActionRegistry (com SecurityManager), degradação graciosa (docker/tailscale indisponíveis). Suíte completa: **2488 passed, 16 skipped**.

---

### Descartado (com motivo - análise original)
Kolibri, CyberChef, FlatNotes, ProtoMaps, Kiwix/ZIM completo, benchmark +
leaderboard, sidecar Docker de update, "Supply Depot" como Docker —
ou é ferramenta de terceiros que já temos equivalente, ou é específico de
instalação offline multi-container, que não é o nosso caso.

---

## 4. Próximos passos (pendências operacionais — exigem acesso ao servidor)

> **Nota**: As tarefas abaixo são OPERACIONAIS (precisam rodar no servidor do dono) e **não** são implementação de código. Exigem autorização explícita ([AUTORIZACAO]) para acesso ao servidor via orquestrador.

| # | Tarefa | Descrição | Bloqueio |
|---|---|---|---|
| 1 | **Subir compose + tailscale serve** | `docker compose -f docker/tools-compose.yaml up -d` + `tailscale serve` por ferramenta | Requer acesso ao servidor |
| 2 | **Baixar ZIM da Wikipédia** | Achar URL correta no mirror Kiwix (URL estável 404) + `nomad_wikipedia_zim_download` | URL 404 — precisa achar no mirror |
| 3 | **Configurar Vaultwarden** | HTTPS via tailscale serve + criar conta admin + `SIGNUPS_ALLOWED=false` | Requer HTTPS (tailscale serve entrega) |
| 4 | **Atualizar docs** | ✅ FEITO — este arquivo reflete a implementação | — |
| 5 | **Tarefa dev: ProtoMaps** | ✅ FEITO — página `site/protomaps.html` no ar | — |

**Próxima sessão do canal** (via orquestrador): executar itens 1–3 acima quando o dono autorizar acesso ao servidor.
