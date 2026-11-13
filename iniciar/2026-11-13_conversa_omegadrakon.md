# Conversa OmegaDrakon — 2026-11-13

## §1 — Relatórios do Vigia para fora de `analise/` (13/11 ~00:15, fechado 04:05)

**Pedido do dono:** por que `relatorio_chat_audit_*` e
`relatorio_vigia_mensagens_*` estão em `analise/` — a pasta é dele, para
ele depositar arquivos e pedir análise (regra 17); esses relatórios "não
estão sendo analisados".

### 1. Causa (lida no código, não suposta)

- Quem gera: timer diário **04:30** (`od-vigia-mensagens.timer`) roda
  `core/vigia_mensagens.py`, que chama o `core/chat_audit.py` — cada ciclo
  grava **2 JSONs** (`--horas 24`).
- Por que `analise/`: caminho hardcoded com o motivo registrado em
  `chat_audit.py` — *"relatório sai em `analise/` (gitignorado)"*. Escolha
  pela comodidade do `.gitignore` (linha 189 `/analise/`), feita em 22/10 e
  26/10, **depois** da regra 17 (12/10) — ninguém ligou para o significado
  da pasta.
- Efeito: 2 arquivos/dia acumulando desde 07/11 na caixa do dono.

### 2. Correção

Destino → **`data/relatorios/`** (`data/` já gitignorado inteiro, sem mexer
no `.gitignore`):

| Arquivo | Linhas mudadas |
|---|---|
| `core/chat_audit.py` | default de `--destino` (`raiz/"data"/"relatorios"`) + 2 docstrings |
| `core/vigia_mensagens.py` | `RAIZ / "data" / "relatorios"` (2 usos: relatório do vigia + relatório da auditoria) + 2 docstrings |
| `tests/test_chat_audit.py` | `test_salvar_relatorio_em_analise` → `test_salvar_relatorio_no_destino` (só o nome mentia; o corpo já usava `tmp_path`) |

Os **9 arquivos acumulados** (07/11→12/12) movidos para
`data/relatorios/`; `analise/` ficou só com `NV/` e `Projeti/`, do dono.

Referências que **não** mudaram (são input do dono, não saída do sistema):
`analise/AIML/...` como fonte de logs legados no `chat_audit`.

### 3. Verificação

- 104 passed nos dois suites afetados (`test_chat_audit` +
  `test_vigia_mensagens`).
- **Prova viva:** CLI do chat_audit **sem** `--destino` →
  `Relatório: .../data/relatorios/relatorio_chat_audit_20261113-035633.json`
  (arquivo de prova removido depois).
- Gate completo: **4539 passed / 17 skipped / 0 falha** (186,08 s).
- **Sem deploy:** o vigia é oneshot via timer — a próxima execução (04:30)
  já usa o caminho novo; nenhum serviço residente muda.

**Sem bump:** app segue **1.44.0/2080**.

## §2 — Análise das pastas que ficaram em `analise/`: NV e Projeti (13/11 ~04:30)

**Pedido do dono:** analisar as pastas que restaram em `analise/` — o que tem,
para que serve, se dá para usar no sistema, se já existe, o que melhorar;
pros e contras; incorporações/melhorias/referências viram checkbox no TODO.
E criar a regra se não existisse.

### 1. Regra nova (regra 22 em `iniciar/RULES.md`)

`analise/` é caixa de entrada: **tudo** que ele depositar passa por análise
completa antes de destino — (a) inventário medido, (b) serventia lida no
conteúdo, (c) uso/incorporação no sistema, (d) equivalente já existente
(medido), (e) pros/contras, (f) destino proposto. Incorporação/referência →
checkbox no TODO no mesmo passo; destino que altera o que é dele (apagar/
mover para fora) → só com aprovação (regra 7).

### 2. `analise/NV/` — 1,2 GB, 19.915 arquivos: Nicky Virthy Runtime

**O que é:** o projeto predecessor direto — 11 versões (v0.1.0 → v1.9.X),
cada uma com código, docs e alguns com `.git`/`.venv` próprios. O mapa do
Legado (§2) confirma: NV "gerou o esqueleto do sistema atual: tool runtime,
security layer, workflows".

**Duplicação medida vs. Legado:** `Legado/NV/docs/` (84 KB) tem os docs
**canônicos e mais novos** (SECURITY_LAYER v1.11.0-security-enforcement,
agosto/2026; HOMOLOGACAO_v1.11.0). O `analise/NV` traz os mesmos docs em
versões antigas (v1.7.0) — mas **o código das 11 versões só existe aqui**
(Legado tem só docs). Diffs: docs idênticos em conteúdo só nos casos
comuns; CHANGELOG/FOUNDATION/MILESTONE/PROMPT diferem (camadas geológicas —
não merge, não apagar, conforme o próprio mapa do Legado).

**Composição do tamanho:** ~501 MB de `.venv` (4 venvs: 108+108+136+149 MB),
69 MB de `.git` (4 repositórios), ~61 MB de tars, o resto código/docs.

**O que já existe no OD (herdado do NV):** `core/security/` (1.742 linhas —
SecurityManager/Policy/Permission/Scope/Approval/Audit, o fluxo do
SECURITY_LAYER_DOC), `core/workflows.py` (WorkflowEngine sequencial, com
crédito no docstring: "NV Runtime core/workflows/"). Não duplicar.

**O que é único e pode servir:** o `nested-workflows.tar.gz` (v1.9.2) tem
`dag_engine.py` (347 linhas, grafo com paralelismo) + `scheduler_engine.py`
(413 linhas, cron/interval com persistência) + 8 testes — **o OD não tem
isso** (só workflow sequencial). vira checkbox "referência para
Semanas 9-10/R1".

**Pros:** último exemplar do código-fonte das versões; referência de
arquitetura (DAG/scheduler) para quando o OD precisar; docs da security
layer como intenção revisável.
**Contras:** 1,2 GB na caixa de entrada do dono; ~570 MB é venv+git (lixo
estrutural); duplica docs com o Legado (risco de confusão sobre qual é
canônico); nada roda aqui (é projeto de outra era, Python de outra venv).

**Destino proposto (aguarda aprovação):** zipar para `backups/` (ou mover
para `Legado/NV-codigo/`) e tirar de `analise/`; extrair os `.venv`
primeiro (501 MB de lixo). **Não apagar sem ordem** (regra 9).

### 3. `analise/Projeti/` — 235 MB, 953 arquivos: trabalho PM + ferramentas

**O que é:** (1) notebooks `pyautogui` de RPA do site Orion (mapa de força
da 42.BPM/I — 124 chamadas no `mapa.ipynb`, 76 no `inserirmapa.ipynb`);
(2) dados de escala de 2024 (`Mapa.csv`, `MapaForcaTudo.txt` — **com nomes,
matrículas e viaturas de policiais**); (3) `google-services.json` +
`app.txt` (export do Firebase `nicky-e4f99`); (4) `OmegaDrakon.apk` 51 MB;
(5) ferramentas Windows: FileZillaPortable (82 MB), PuTTYPortable,
MQTT-Explorer (74 MB), tailscale-setup 1.92.5.

**Duplicação medida:**
- `google-services.json` **é byte a byte o mesmo** do
  `app/android/app/google-services.json` (sha256 `5e64634c…` nos dois) —
  redundante.
- `OmegaDrakon.apk` **não bate com nenhum backup** (`b845c044…` vs todos os
  `backups/apk-*`): build antigo, mais velho que v1.39.3-2075 (17/10); o
  atual é 1.44.0+2080. Não extraí a versão (Manifesto compactado).
- Tailscale do desktop: instalador é 1.92.5; o **servidor** está em
  **1.104.6** — o instalador é velho (medido agora).

**Pros:** os notebooks são um RPA funcional e completo (referência de
padrão para automação — e candidatos a virar action/workflow no OD, que já
tem action engine + CoderEngine sandbox); dados do Orion podem virar action
de leitura ("qual o turno de amanhã"); FileZilla/PuTTY/MQTT-Explorer úteis
para o desktop Windows dele (que está na tailnet ativo).
**Contras:** dados pessoais de policiais expostos na pasta (não podem ir
para git/site em hipótese nenhuma — regra 16); APK órfão sem versão;
Google-services duplicado; tailscale instalador velho vs. real; pyautogui é
frágil (tabulação cega — se um dia automatizar de verdade, é API/scraping
autorizado).

**Destinos propostos (aguardam aprovação):** instalar as ferramentas no
desktop Windows (copiar `.exe`); APK e google-services → lixo (ou me diga a
origem do APK que eu arquivo); dados do Orion ficam como referência de
parsing mas **fora de qualquer publicação**.

### 4. O que foi para o TODO

6 checkboxes em `docs/ANALISE_SISTEMA_TODO.md` §4 (seção "Análise de
`analise/` — NV e Projeti"): referência DAG/scheduler do NV; destino dos
1,2 GB do NV; SECURITY_LAYER como referência; automatizar mapa de força
(referência RPA); instalar ferramentas no desktop; google-services/APK como
lixo candidato; dados do Orion como referência de leitura.

**Sem bump:** app segue **1.44.0/2080**.

## §3 — Zips de `analise/` em `backups/` + tabela `pessoas` no Postgres (13/11 ~05:30, fechado 06:30)

**Pedido do dono:** (1) "zipar para backups, não tirar nada" das pastas que
ficaram em `analise/` (as ferramentas Windows: "não precisa fazer nada
apenas zipar também em backups"); (2) escolha em pergunta — salvar os dados
dos policiais extraídos de `analise/Projeti/Cod` na **tabela `pessoas` do
Postgres `od`** (o banco não existia; colunas aprovadas: nome, posto,
matricula, viatura, unidade, fonte, atualizado_em — com `dv` somando).

### 1. Os zips (nada tirado de `analise/`)

- `backups/analise_NV_20261113.zip` — 822 MB, 19.915 entradas.
- `backups/analise_Projeti_20261113.zip` — 167 MB, 953 entradas (inclui as
  ferramentas Windows, conforme a ordem).
- `testzip()` íntegro nos dois arquivos (via `zipfile` do Python — o CLI
  `zip` não existe neste ambiente). Originais **intactos**; `backups/` é
  gitignored.

### 2. Tabela `pessoas` — 92 policiais no Postgres `od`

**`runtime/importa_pessoas.py`** (novo) cria a tabela (se preciso) e importa
o efetivo de `analise/Projeti/Cod`:

- **Fontes (6, ordem de precedência do merge):** `efetivo.txt` (linhas
  posto + matrícula + dv + nome, dv pode ser letra) → `MapaForca.txt` /
  `MapaForcaTudo.txt` (tokens de colchete `[POSTO_PM_MAT_NOME]`, com o
  trecho `_-_1C_` e nomes com espaço) → saídas do `ler.ipynb` (o source é
  código, não conta) → `Mapa.csv` / `Mapa.txt` (vínculo matrícula →
  viatura + unidade; cabeçalho tem 14 campos e os dados 15, por índice
  0-based: unidade col.3, viatura col.8, re col.11, re2 col.13).
- **Viatura por linha:** colchete primeiro, senão a col0 tabulada
  (`SD`+dígitos, `NN-NN` — linhas que só têm a viatura ali), senão
  a "pendente" da linha anterior (é o padrão do efetivo: a linha 79 traz
  a viatura em colchete e a linha 80 traz os 2 policiais; a pendente é consumida no
  uso, não vaza).
- **Merge idempotente por matrícula** (fallback: nome): a 1ª fonte preenche
  os vazios (o efetivo vem primeiro de propósito — posto legível, dv e
  caixa mista vencem os tokens em caixa alta); listas (viatura/fonte) somam
  sem repetir; o UPDATE só acontece quando algo mudou, então re-rodar que
  nada muda **não toca `atualizado_em`**.
- **Resultado medido no `od`:** 92 pessoas (185 registros extraídos), 0 sem
  nome, 1 sem viatura, 24 com dv, 26 com múltiplas viaturas (rodou em mais
  de uma), 26 com unidade, 0 fontes duplicadas. Re-execução no banco real:
  **0 nova(s), 0 atualizada(s)**.
- **Honestidade do dado:** `unidade` só onde a fonte declara (cabeçalho OPM
  do efetivo e col.3 do Mapa) — quem só aparece em MapaForca/notebook fica
  vazio em vez de presumir; postos guardados como a fonte traz (`CB` vs
  `CB PM`).
- **Sensibilidade (regra 16):** os testes usam só fixtures sintéticas
  (matrículas e nomes inventados); nenhum dado real em arquivo commitado;
  a tabela mora só no Postgres `od` (actions `database_*` são admin) e
  `analise/` segue gitignored.

### 3. Testes e dois defeitos pegos antes do gate

`tests/test_importa_pessoas.py` (novo) — **40 testes**: parsers das 4
famílias de fonte, viatura (colchete/col0/pendente/reset/colchete vence
col0), Mapa.csv (aspas, cabeçalho, campos inválidos), cabeçalho OPM,
outputs de notebook, merge idempotente (timestamp intocado, listas somando,
fallback por nome) e a CLI (dir ausente, sem DSN, sucesso, reexecução sem
duplicar, dir vazio).

Defeitos medidos e corrigidos **antes** do gate: (1) um assert esperava
string onde o parser devolve lista; (2) o `_lista_csv` não tirava o espaço
do `split(',')` — os itens nunca batiam com os da memória, derrubando
**40 "atualizados" falsos** e gravando `fonte` com espaço duplo
(`'efetivo.txt,  Mapa.txt'`) na re-execução. Corrigido com `strip` e
reprovado pelo teste de idempotência.

**Gate completo: 4579 passed / 17 skipped / 0 falha** (era 4539 + 40).

**Sem bump:** app segue **1.44.0/2080**; nada desta tarefa exige restart do
od-core (é script + banco, o serviço não muda).

## §4 — Dono esvaziou `analise/` (13/11 ~13:50, verificado)

**Aviso do dono:** "pasta analise já foi analisada, apaguei o conteudo atual
para deixar pronto para o proximo" — o conteúdo de `analise/` (NV e
Projeti) foi apagado **pelo próprio dono** (regra 7 não se aplica: quem
apagou é ele; nada foi movido/apagado por mim).

**Verificação feita antes de registrar:**

- `analise/` existe e está **vazia** (pronta para o próximo depósito — a
  regra 22 segue valendo para o que entrar).
- Os zips são agora a **única cópia** daqueles 1,4 GB: revalidados por
  leitura integral (`testzip()` + contagem) —
  `analise_NV_20261113.zip` **OK, 19.915 entradas**;
  `analise_Projeti_20261113.zip` **OK, 953 entradas**.
- Nada mudou no git (`analise/` é gitignored; HEAD segue `99e6259`).

**Sem bump:** app segue **1.44.0/2080**; mudança só de arquivos de
registro (`.md`/`.json`), sem código — sem restart do od-core.

## §5 — Auditoria de `backups/` antes da HD do dono (13/11 ~14:00)

**Pedido do dono:** "a pasta backups é um lugar intermediário antes de eu
salvar em uma HD externa. Se existe algum arquivo lá que deva permanecer
no servidor transfira para outro lugar porque hoje vou colocar tudo que
estiver no backups na minha HD e limpar a pasta."

### 1. Veredito: **nada precisa ficar** — não houve o que transferir

Auditoria categoria a categoria, com prova (nada foi movido por mim):

- **`auto/` (7 tars diários, ~4 MB)** — o `core/backup.py` faz
  `raiz.mkdir(parents=True, exist_ok=True)` antes de gravar: apagar até o
  diretório inteiro é seguro, o próximo nasce sozinho (03:00). E o
  offsite **já enviou o de hoje** para o canal do Telegram
  (`od-2026-11-13_0314.tar.gz`, sha conferido em
  `data/offsite_state.json`) — redundância HD + canal.
- **`auto-capturas/` (4 semanais, ~1,67 GB)** — idem:
  `od-capturas-2026-11-13_0414.tar.gz` (11 partes) já está no canal;
  próximo snapshot domingo 04:00.
- **`apk-v1.24.1 … v1.39.3` (6 pastas, ~400 MB)** — APKs antigos de
  bump; o APK **atual é servido de `site/`** (fora de `backups/`),
  verificado ao vivo: `/app/version` anuncia 1.44.0/2080 com sha256 =
  arquivo do site (mtime 20/10 = data do bump 1.44.0 no CHANGELOG).
  `app/build_apk.sh` não escreve em `backups/`.
- **`backup_od_2026-10-16/` (~16,7 GB)** — backup completo pontual.
- **2 zips de `analise/` (1 GB)** — única cópia → destino certo é a HD.
- **arquivos soltos** (caches pre-guarda, llm-cache, `env-backup` de
  04/11 — **contém segredos**, ok na HD do dono, nunca publicar —,
  snapshots do tailscale-serve, yml do azuracast, SPEC, txt) — histórico
  sem leitura pelo sistema.

O snapshot diário para as HDs (`core/hd_backup.py`, 03:44, rsync com
`--link-dest` para `/home/alex/dados/od_snapshots/` e
`/mnt/Arquivos/od_snapshots/`) **exclui `backups/` de propósito** ("os
tars locais têm retenção e destino próprios") — a limpeza não o afeta.
Check de saúde do offsite usa `data/offsite_state.json` (não some com a
pasta). Testes `test_backup.py` + `test_offsite.py`: **107 passed**.

### 2. Achado: o Postgres `od` **não tem dump automático em lugar nenhum**

Medido, não presumido: `pg_dump` só aparece em
`runtime/install_postgres.sh` (script de instalação); sem crontab de
usuário nem timer do sistema; o tar diário cobre `.env` + `data/`
(SQLite: checkpoints.db, memory.db) e o snapshot das HDs cobre
3D/repo/tools/srv/fstab — **`/var/lib/postgresql` (16/main) não entra em
nenhum dos dois**. O único dump existente era o manual de 16/10
(`postgres_od_2026-10-16.sql.gz`, 16 KB) — que agora vai para a HD.

**Ações no passo:** (1) gerei o dump **atual** para viajar junto na HD de
hoje — `backups/postgres_od_2026-11-13.sql.gz` (32 KB, gzip OK, 14
tabelas = todas do `od`, banco de 8,9 MB, sha256
`f5467dcc…d9336`); (2) a pendência de virar **job diário** entrou como
checkbox no TODO §4 (Continuidade, junto de "Backup fora da máquina") —
criar timer exige aprovação do dono.

### 3. Registro

session.json (chave `backups_auditoria_antes_da_hd_2026_11_13` no topo),
esta transcrição (§5), CHANGELOG (entrada no topo, sem bump), Telegram ao
dono. **Gate: 4579 passed / 17 skipped / 0 falha** (mudança só de
registro `.md`/`.json`).

**Sem bump:** app segue **1.44.0/2080**; sem restart do od-core.

## §6 — Digest do TODO + higiência de status (13/11 ~14:40)

**Pedido do dono** (enquanto copia os 16 GB para a HD): "quando terminar
aviso. o temos pra fazer no TODO?"

### 1. Auditoria de status no código (não de memória)

Dos **45 itens abertas**, conferi os que suspeitei de desatualizados:

- **I4 Query Router e I5 Streaming SSE: já ENTREGUES** —
  `core/query_router.py` integrado na etapa de intenções e no grafo
  (CHANGELOG com prova viva), `GET /api/v1/chat/stream` (SSE) +
  `process_stream_sse()`, testes passando (47 passed/1 skipped nos 4
  arquivos da área). **Checkboxes marcados** (45 → 43 abertos).
- **I1 Semantic Cache e I2 Hybrid Search: módulo pronto, NÃO LIGADOS** —
  `memory/semantic_cache.py` (threshold 0.95, em processo — **sem Redis**)
  e `core/hybrid_search.py` (BM25 + cross-encoder) existem e são testados,
  mas **nenhum ponto da produção passa `semantic_cache=`** (orquestrador
  roda com `None`) e a `memory/rag.py` não usa o hybrid. **Checkbox
  mantido aberto** com anotação do que falta + decisão do dono (ligar muda
  comportamento de resposta — risco de servir resposta parecida na ≥0.95).
- **Destino do NV (1,2 GB): marcado como decidido/executado** (opção b,
  ordem dele — zip → HD, `analise/` esvaziada).

Contagem final: **42 abertos / 35 feitos** (era 45/32).

### 2. Refs extraídas para `data/refs_todo/` (266 KB, gitignored)

Antes de a limpeza da HD terminar, tirei dos zips o que os itens abertos
precisam: `NV/` = `nested-workflows.tar.gz` + bootstrap v1.9.2 +
`SECURITY_LAYER_ARCHITECTURE.md`; `Projeti/Cod/` = os 5 notebooks +
`efetivo.txt` + `Mapa*` (dados pessoais — **só no gitignored**, nunca no
git). Itens que dependem de `.exe` grandes (ferramentas Windows) ficaram
anotados como "traar da HD se executar".

### 3. O digest entregue (resposta ao dono)

**🔴 Só ele decide/compra (8):** nobreak com USB (compra nº 1), 2º nó de
comunicação, backup offsite em SSD criptografado, ferramentas Windows no
desktop, descartar google-services/APK antigo, política das 20 req/dia do
Gemini, ligar I1/I2, reteste do 7B quando houver RAM.

**🟡 Eu executo (ordem sugerida):** dump automático do Postgres (fecha o
achado de hoje), disjuntores + cota do Groq no `/health`, action de
pesquisa web, enxugar contexto do Gemini (+ OpenAI automático), segurança
(`stt_transcrever` + `/tmp`), rádio (formatador + sink), corpus de
intenções, `pyproject.toml` + `ARCHITECTURE_v2.md` + Bluetooth (§8), refs
NV→grafo e mapa-de-força→action, cache de embedding, OTel
coletor/dashboards/alertas, Task Queue (R1), Eval no CI (R5), continuidade
(UPS/ZIMs/espelho/fila/modo colapso/mapas não-latinos).

### 4. Registro e verificação

session.json (chave `todo_digest_e_higiene_2026_11_13`), esta transcrição
(§6), CHANGELOG (entrada no topo). **Gate: 4579 passed / 17 skipped / 0
falha.** `data/refs_todo/` confirmado gitignored (`git check-ignore`).

**Sem bump:** app segue **1.44.0/2080**; sem restart do od-core.
