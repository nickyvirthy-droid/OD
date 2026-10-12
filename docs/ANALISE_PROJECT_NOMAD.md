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

### Parte B — Pipeline RAG de qualidade
Reescrita de query com histórico, floor de relevância, orçamento de
contexto (quanto foi descartado vira métrica), calibração por modelo.
**Esforço alto** — maior ganho de qualidade.

### Parte C — Referência médica e bem-estar
Actions determinísticas (sem LLM) para "condição → o que usar",
interações de medicamentos e fontes curadas; **disclaimer obrigatório na
resposta** (padrão `SafetyBanner` deles). Encaixa no `fastpath` de
intents que já existe. Dados deles: `collections/*.json` (Apache-2.0).
**Esforço médio.**

### Parte D — Fila de downloads resumable
Retry com backoff, progresso ao vivo (SSE → app), dedup, cancelamento.
Útil para modelos, datasets e documentos. **Esforço médio-baixo.**

### Parte E — Auto-update de modelos/conteúdo
Janela, cool-off, cap de bytes, auto-disable, dry-run testável —
aplicado ao que o assistente baixa (modelos de voz/LLM, índice RAG).
**Esforço médio-alto** (mas o nosso `runtime/launcher` já tem o esqueleto).

### Parte F — Registro de ferramentas/skills estilo Supply Depot
Pre-flight (conflito, versão, tamanho), rollback, preservar customização
— evoluindo o catálogo de tools do orquestrador. **Esforço médio.**

### Descartado (com motivo)
Kolibri, CyberChef, FlatNotes, ProtoMaps, Kiwix/ZIM completo, benchmark +
leaderboard, sidecar Docker de update, "Supply Depot" como Docker —
ou é ferramenta de terceiros que já temos equivalente, ou é específico de
instalação offline multi-container, que não é o nosso caso.

---

## 4. Próximo passo

Dono escolhe a **ordem das partes A–F** (sugestão: A primeiro — eval dá
métrica para julgar B e C; depois C, que é quick win visível no chat).
Cada parte é implementada em sessão própria do canal de desenvolvimento,
com teste, commit e publicação pelas regras da casa.
