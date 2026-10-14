# Conversa 2026-10-14 — OmegaDrakon

## §1 — Retomada "leia iniciar" (~09:00)

Checkpoint lido (`session.json` atualizado até 13/10 21:50 + transcrição de
13/10 §1–§3). Verificação de estado ao vivo:

- **od-core**: `active` PID 454712 desde 13/10 21:41 (**11 h**), NRestarts=0,
  journal **0 erros** em 12 h. `/app/version` = **1.25.0 / 2055** (sha
  `dbef2965…` == APK publicado). `/health` 401 sem credencial = esperado.
- **Git**: HEAD `4811ead` == `origin/master`, árvore **limpa**.
- **Caixa de entrada**: `txt.txt` sem mensagem nova do dono (última escrita
  nossa 13/10 21:46). `analise/` sem depósito novo (Avatar vazio; as 4 fotos
  de `fotos-adicionais/` guardadas a pedido).

**Estado: sistema estável, nada em andamento.** Últimas entregas: Parte A
(eval + conserto de permissão do user → v1.24.2) e Parte C (referência médica
→ v1.25.0) do Project NOMAD.

**Próximo na ordem acordada (A → C → B → D → E → F): parte B = RAG** —
aguardando o "pode fazer" do dono. Pendências do dono inalteradas (Vaultwarden,
etapa 4 do Registro Mestre, pauta 3/5, rotação de segredos, fotos guardadas,
catalogar `3D/`).

## §2 — Reverificação (~10:49)

Segundo "leia iniciar" do dia. Estado **inalterado e 100% verde**:

- **od-core**: `active` PID 454712 (desde 13/10 21:41, ~13 h), NRestarts=0,
  journal **0 erros** em 14 h. `/app/version` = **1.25.0 / 2055** (sha
  `dbef29654f…` == APK publicado). `/health` 401 sem credencial = esperado.
- **Git**: HEAD `d9659de` (commit da retomada da manhã) == `origin/master`,
  árvore **limpa**.
- **Caixa de entrada**: `txt.txt` sem mensagem nova do dono (última escrita
  nossa 13/10 21:46). `analise/` sem depósito novo (Avatar vazio; as 4 fotos
  de `fotos-adicionais/` guardadas a pedido).

**Nada em andamento — aguardando do dono o "pode fazer" da Parte B (RAG)**
e as pendências dele inalteradas.

## §3 — Parte B do NOMAD (pipeline RAG) ENTREGUE — v1.26.0 (~12:00–13:20)

Dono aprovou **"pode fazer parte B"** (14/10). Entrega completa da Parte B
de `docs/ANALISE_PROJECT_NOMAD.md` §3 na ordem acordada (A → C → **B** → D).

### O que foi feito

| Peça | Detalhe |
|---|---|
| `memory/rag.py` (novo) | Pipeline determinístico (0 chamadas de LLM): reescrita de consulta com histórico (anafóricas/elípticas agregam termos recentes), busca com embedding sem stopwords dos dois lados, **floor duplo medido** (`0.8·cosseno + 0.2·overlap-IDF ≥ 0.36` E `overlap-IDF ≥ 0.22`), reranker pelo combinado, visibilidade por papel e orçamento com métrica do descartado. |
| Corpus + idempotência | `docs/*.md` + `knowledge/*.md` → **850 chunks** (medido no boot). `doc_id` determinístico (fonte+índice) + SHA; sync com remoção de órfãos. `add_many` com `doc_ids` em LOTE: ingestão inicial **86s → 0.66s** (o `add()` unitário persistia o JSON inteiro a cada chunk — O(n²) de I/O, bug achado pela suíte). |
| Etapa 4.5 no orquestrador | REST **e** stream com o mesmo contexto; ordem identidade → data/hora → acervo **travada por teste** (KV-cache do llama-server); fastpaths nunca pagam o RAG; métricas `rag_*` no snapshot do `/dashboard/stats`. |
| Calibração | Floor medido com 16 queries no corpus real: score vetorial puro **não** separava (irrelevante 0.496 > relevante 0.444). Regra final: **8/8 relevantes passam, 8/8 irrelevantes bloqueados** — vira GATE na suíte (`TestCalibracaoCorpusReal`); re-calibrada após cada mudança (hoje: 2×, com `top_k=24` + `termos_da_consulta()`). |
| Eval (Parte A serve à Parte B) | Campos novos `prompt_contem`/`prompt_nao_contem` (validação de tipo incluída); 4 goldens novos; modo `noretrieval` desliga o RAG via `orch.set_rag(None)` e um golden prova; gate do oracle pula declaradamente goldens de prompt. |
| API | `GET /memory/{uid}/search` ligado ao store real (antes **501** — store nunca conectado). |

### Prova de fogo em produção (2 bugs reais achados e corrigidos)

A 1ª consulta de acervo no serviço vivo (`POST /message`) voltou
**`rag_trechos=0`, 12 descartados**, e o LLM **inventou** as "regras"
("sem pull requests…" — nem existe no nosso doc; conferido com `grep`).
Diagnóstico com cópia hermética da store real em `/tmp`:

1. **Prefixo de instrução** ("responda curto: ...") inflava a soma_idf com
   idf de palavra rara de comando → overlap 0.211 < 0.22 → floor rejeitava
   a consulta certa. Correção: `termos_da_consulta()` — só o prefixo curto
   (≤5 palavras) antes de `:` sai do **floor**; a busca vetorial continua
   vendo a frase crua.
2. **`top_k=12`**: o chunk certo do doc rankeava em **15º**, fora do pool.
   Correção: `TOP_K_CANDIDATOS` 12 → **24**.

Re-calibração com o código final: 8/8 + 8/8 preservados. Depois do fix,
no serviço: **`rag_trechos=1`**, resposta **literal** do
`docs/REGRAS_DE_TRABALHO.md` ("Nunca publicar com testes vermelhos (ver §8)"
— linha real do arquivo, com referência de seção interna). 7 testes novos
cobrem as duas bordas.

### Verificação e deploy

- **Suíte**: **2666 passed / 16 skipped** (+90 testes da Parte B; era 2576).
- **Evals**: oracle **13/13** · e2e **19/19** (LLM local real) · noretrieval
  **9/9** — `--comparar` sem desvio; baselines regravadas.
- **App**: `flutter analyze` 0 issues · `flutter test` **157 passed / 2 skipped**.
- **Bump MINOR 1.26.0 / versionCode 2056**: `.env`, capabilities fallback,
  pubspec, `_APP_VERSION_CODE` (gate `test_version_policy.py` pegou o 2055
  órfão antes do commit — corrigido em `95fd4a8`), site 3×, CHANGELOG [1.26.0],
  README_VERSAO §1.26.0, ANALISE marcada ✅ ENTREGUE. APKs rebuildados e
  publicados: universal 55.246.176 B sha `26be1efc…`, arm64 19.977.978 B sha
  `6c336e07…` (aapt2: versionName 1.26.0 nos dois; split por ABI dá 4056 no
  arm64 = comportamento padrão do Flutter, universal em 2056).
- **Commits publicados**: `2909e1a` (feature) · `95fd4a8` (version_code) ·
  `72aa17e` (prova de fogo).
- **Deploy** (regra 7.3, verde): restart 13:05 — **PID 1257828**, NRestarts=0,
  journal **0 erros**, `/health` **9/9**, `RAG ligado (janela=8192, chunks=850,
  novos=0/atualizados=6/iguais=844)` — idempotência processou as edições do
  dia no boot. `/app/version` = **1.26.0 / 2056 / sha `26be1efc…`** == APK
  publicado.
- **Canais**: `txt.txt` reescrito (regra 14) · Telegram enviado (regra 15,
  `message_id` 2684).

### Estado

**CONCLUÍDO E NO AR.** Próxima na ordem do dono: **Parte D** (fila de
downloads resumable) — ordem é dele. Fronteira honesta documentada: recall
conservador (pergunta certa com vocabulário fora do corpus volta vazia em vez
de lixo), reranker real depende de modelo de embedding melhor, corpus ainda
só interno (público = próximo passo natural). Pendências do dono inalteradas.

## §4 — Reverificação pós-entrega (~16:11)

Terceiro "leia iniciar" do dia, ~3 h depois do deploy da Parte B. Estado
**inalterado e 100% verde**:

- **od-core**: `active` PID 1257828 desde 14/10 13:05:45 (**3 h 5 min**),
  **NRestarts=0**, journal **0 erros** desde o restart. `/health` 401 sem
  credencial = esperado. `/app/version` = **1.26.0 / 2056 / sha
  `26be1efc…`** == APK publicado.
- **Git**: HEAD `258188b` (commit do registro da Parte B) == `origin/master`,
  árvore **limpa**; nenhum commit novo desde 13:20.
- **Caixa de entrada**: `txt.txt` sem mensagem nova do dono (última escrita
  nossa 14/10 13:09). `analise/` sem depósito novo (Avatar vazio; as 4 fotos
  de `fotos-adicionais/` guardadas a pedido).

**Nada em andamento — Parte B entregue e estável no ar.** Aguardando do
dono o "pode fazer" da **Parte D** (downloads resumable) e as pendências dele
inalteradas (Vaultwarden, etapa 4 do Registro Mestre, pauta 3/5, rotação de
segredos, fotos guardadas, catalogar `3D/`).

## §5 — Parte D (fila de downloads resumable) entregue — v1.27.0 no ar

Dono autorizou "pode fazer a parte D" (ordem acordada A → C → B → **D** →
E → F). Fila de downloads com retomada real, retry inteligente, dedup,
cancelamento preservando o parcial e progresso ao vivo por SSE — o motor
que a Parte E (auto-update) vai dirigir.

### O que foi construído

- **`core/downloads.py` (novo, 477 stmts)** — `DownloadQueue` com worker
  próprio (thread daemon + `Condition`): stream por `urllib` com
  `Range: bytes=N-` a partir do `.part` (servidor sem Range → 200
  reinicia sozinho sem misturar; 416 → recomeça uma vez), sha256
  incremental (prefixo do parcial entra no mesmo hasher), `os.replace`
  atômico no fim. Estados: `na_fila`/`baixando`/`aguardando`/
  `concluido`/`erro`/`cancelado`. Retry `min(2·2^(n−1), 60 s)`;
  404/403/sha divergente = permanente (não queima tentativa). Persistência
  atômica em `data/downloads_fila.json` (progresso ≤ a cada 2 s — lição
  do O(n²) da Parte B); boot re-enfileira o que estava em voo; histórico
  terminal recortado em 50. Destino SEMPRE dentro de `OD_DOWNLOADS_DIR`.
- **SSE `GET /admin/downloads/events`** — `snapshot` na abertura, depois
  `estado`/`progresso`/`removido`; `: ping` quando 15 s passam sem
  eventos; fila por assinante (overflow descarta o mais antigo).
  `APIServer.stop()` ganhou `encerrando` — sem o sinal o `server_close()`
  do `ThreadingHTTPServer` esperaria o handler SSE fechar em TODO restart.
- **6 rotas admin** (`POST/GET /admin/downloads`, `/events`, `/{id}`,
  `/{id}/cancel`, `DELETE /{id}` com 409 `job_ativo`), 503
  `downloads_indisponivel` sem fila, bloco `downloads` no
  `/dashboard/stats`, seção **Downloads** no painel `/admin` (JS ao vivo
  via `fetch`+`ReadableStream`; o `node --check` da suíte pegou um `\n`
  não-escapado no literal Python).
- **App: 7ª aba "Downloads"** — `OdApi` + `streamDownloads()` (SSE, timeout
  só na abertura), tela com fila/selo/barra/tentativas e etiqueta
  `📡 ao vivo (SSE)`; stream morto → polling de 5 s + reassina em 15 s
  (mesmo contrato do chat). `_initialIndex` do modo avançado foi para 6.
- **Capability `download-queue`** no manifesto.

### Validação (antes do commit)

- Suíte completa **2712 passed / 16 skipped** (+46; `tests/test_downloads.py`
  novo: retomada com Range medindo o header pedido, 200 que reinicia,
  416, retry até concluir, retry esgotado, cancel no meio preservando o
  parcial medido, `stop()` re-enfileirando, boot restaurando `baixando`,
  SSE por socket cru contra o servidor de teste). Gate `--cov-fail-under=90`
  **90,28%**; `core/downloads.py` a **95%**.
- `flutter analyze` **0 issues** · `flutter test` **174 passed / 2 skipped**
  (+17: `downloads_api_test.dart` REST+SSE com `MockClient.streaming`,
  `downloads_screen_test.dart` com SSE aberto de propósito — stream que
  fecha liga o poller de 5 s e o `pumpAndSettle` nunca assenta). Bug real
  achado pelo teste: `TextEditingController` disposeado no `pop` do
  diálogo, com a rota ainda animando a saída → virou campo do Estado.
  Bug real achado também: `_initialIndex = 5` do modo avançado (Config
  era a 6ª aba; agora é a 7ª).
- Guardas `ROUTES` 64 → 70.

### Bump + deploy

- **1.27.0 / versionCode 2057** (MINOR, capacidade nova) em todas as
  fontes vivas: `.env`, fallback de capabilities, `pubspec.yaml`,
  `_APP_VERSION_CODE`, `site/index.html` ×4, `CHANGELOG [1.27.0]`,
  `README_VERSAO §1.27.0`, `ANALISE_PROJECT_NOMAD.md` (Parte D ✅).
- APKs pelo build canônico (`./app/build_apk.sh`, `JAVA_HOME=/home/alex/jdk`):
  universal 55.508.376 B sha `f9c6ad8e…` · arm64 20.043.570 B sha
  `3730814f…` (APKs 2056 anteriores sobrescritos em site/).
- Commits `d455635` (feature) e `3e6073a` (prova de fogo) — HEAD ==
  `origin/master`; árvore limpa.
- Deploy: `systemctl --user restart od-core` → **PID 1531296** desde
  18:10:49 (NRestarts=0), journal **0 erros**, "Fila de downloads no ar"
  no boot.

### Prova viva na fila de produção (14/10, `proof.ovh.net`, 100 MB c/ Range)

| Passo | Resultado |
|---|---|
| Enfileirar pela API pública | `POST /admin/downloads` → `dl-0001` (201), `na_fila` → `baixando` a ~2 MB/s |
| Progresso ao vivo | SSE: `snapshot` + **42 eventos `progresso`**; fila ociosa → **1 `: ping`** aos 15 s |
| Integridade | `sha256_real` do job **== `sha256sum`** do disco (`20492a4d…`) |
| Dedup | POST idêntico durante a transferência → **HTTP 200 `duplicado: true`**, MESMO job |
| Cancelamento | `dl-0002` cancelado aos 28,5 MB → `.part` preservado com **o mesmo tamanho do contador** (28 573 696 B), arquivo final intocado |
| Retomada | `dl-0003`: 33,5 MB em 4 s (impossível do zero naquela taxa) e terminou com o **MESMO sha256** do download integral — cauda de 71 MB byte a byte |
| Journal | `Download retomado (Range) | id=dl-0005 | de_bytes=7077888 | total=104857600` (linha nova, provada ao vivo) |
| Higiene | `.part` some no sucesso; 5 registros de prova apagados (DELETE 200); `data/downloads` limpo; fila zerada |

Achados da prova e corrigidos no commit `3e6073a`: (1) não existia linha
de log para a retomada — agora existe e foi vista ao vivo; (2) docstring
e docs explicitaram que o `: ping` dispara quando 15 s passam SEM eventos
(enquanto há progresso o próprio fluxo mantém o canal vivo).

### Canais

- `txt.txt` reescrito (regra 14).
- Telegram msg 2708 (regra 15, chat OD_TELEGRAM_ADMINS).

### Estado

**CONCLUÍDO E NO AR.** Próxima na ordem do dono: **Parte E** (auto-update
de modelos/conteúdo: janela, cool-off, cap de bytes, auto-disable,
dry-run) usando esta fila como motor. Pendências do dono inalteradas.

---

## §6 — Parte E (auto-update de modelos/conteúdo) entregue — v1.28.0 no ar (~19:20–19:40)

Ordem do dono: "pode fazer a parte E". Segui o padrão do Nômade
(`docs/ANALISE_PROJECT_NOMAD.md` §2.1.1 — pipeline de decisão puro +
dry-run determinístico) sobre o esqueleto do launcher e o motor da fila
da Parte D.

### O que entrou

- **`core/auto_update.py` (novo, 471 stmts):** `avaliar()` PURO com
  relógio/estado/disco/alvos injetáveis — 8 camadas em ordem, cada
  decisão com motivo: ① auto-disable → ② inativa no manifesto →
  ③ sem mudança → ④ major (só minor/patch; versões-hash não têm major)
  → ⑤ janela (default 02:00–06:00) → ⑥ cool-off ancorado em "primeiro
  visto" (recomeça quando a versão vista muda) → ⑦ backoff pós-falha →
  ⑧ cap de bytes + pre-flight (disco×1,1, sha 64 hex, URL http(s)).
  Severidade `skip` vs `failure`: só falha DURA conta para o
  auto-disable (3 → desligado com motivo; religar é do dono).
- **Executor contido:** `tick()` avalia e executa — `rag_sync`
  idempotente (thread; VectorStore é RLock) e `baixar` enfileirado na
  fila da Parte D (retomada/sha/dedup grátis); eventos terminais da fila
  alimentam o estado (atômico em `data/auto_update_estado.json`).
  `pos_download: mover` = `os.replace` atômico travado na árvore do repo.
- **Manifesto** `data/auto_update_alvos.json` (criado no boot com
  exemplo; edição nunca é sobrescrita) para o dono pinar url+sha256+
  versão de arquivos. Alvo vivo de hoje: **`indice-rag`** — hash do
  conteúdo de `docs/`+`knowledge/` como "versão": editou `.md`, o ciclo
  na janela ressincroniza o índice SEM reboot (antes só no boot).
- **Rotas** `GET /admin/auto-update`, `POST .../dry-run` (o MESMO
  caminho do ciclo, sobre cópia do estado), `POST .../reset` (religa) —
  todas admin, 503 sem serviço. Bloco `auto_update` no
  `/dashboard/stats`. Seção **Auto-update** no painel `/admin` (config,
  tabela de alvos, 🧪 dry-run, ⟳ religar). `ROUTES` 70 → 73.
- **Launcher:** loop `_supervise("auto-update")` com tick em
  `asyncio.to_thread` (sync do RAG não prende o loop), health check
  `auto_update` não-crítico, `OD_UPDATE_ENABLED=0` desliga; fila da Parte
  D construída uma vez no modo all e compartilhada pela API e pelo
  auto-update.
- **Capability** `content-auto-update` (runtime). **versionCode**
  2057 → 2058 (bump completo: .env, fallback, pubspec, _APP_VERSION_CODE,
  site ×4 — APKs reconstruídos e republicados, mesma base de código,
  carimbo novo).

### Verificação

- Suíte: **2772 passed / 16 skipped · gate 90.42%** (+59 testes;
  `core/auto_update.py` a **94%**) — tabela de TODAS as ramificações do
  pipeline, executor com fila/relógio falsos, auto-disable nas 3 falhas,
  religação, mover travado, manifesto, integração REAL com a fila da
  Parte D (download completo + sha divergente), rotas e health.
- `flutter analyze` 0 issues · `flutter test` 174/2 · política de versão 9/9.
- JS do painel validado pelo `node --check` da suíte (pegou um `\n` meu
  dentro do literal Python — corrigido com `String.fromCharCode(10)`).

### Prova viva no serviço (PID 1608225)

| Fase | Resultado |
|---|---|
| Boot padrão | `Auto-update no ar \| janela=02:00-06:00 \| rag=ligado` + loop habilitado; tick `alvos=1 \| aplicar=0 \| resumo=indice-rag=aguardar` (19:27, fora da janela) — camada ⑤ viva; dry-run: `aguardar \| fora_da_janela (abre 02:00)` |
| Executor (janela larga temporária) | Tick `alvos=2 \| aplicar=2` → `Índice RAG re-sincronizado \| arquivos=18 \| chunks=862` (idempotente) + `enfileirou download \| alvo=proof-modelo \| job=dl-0001 \| bytes=10485760` → `download concluído e verificado` em **7 s**, staged com **sha256 == pin** (`e5b844cc…`) |
| Idempotência | `GET /admin/auto-update`: `indice-rag` instalada=`50ab0b74d8c8`, `proof-modelo`=`1.0.0`, 0 falhas; dry-run seguinte: ambos `pular \| sem_atualizacao` (camada ③) |
| Bug achado no ar | `HealthMonitor` invoca `check(monitor)` — assinatura sem argumento → "check quebrado: TypeError", /health degraded. Fix (`health_check(_monitor=None)`), teste de regressão com o monitor real, /health **up** revalidado |
| Restauração | `.env`/manifesto de volta ao padrão, resíduos apagados (staged + estado + dl-0001), restart limpo: `indice-rag=aguardar`, journal 0 erros, NRestarts=0 |

### Canais e commits

- Commits `d0e5524` (Parte E) + `b9fd489` (limitações de 13/10 consumidas
  pelo fluxo do dono — commit separado para não sujar a história) — ==
  origin/master.
- `txt.txt` reescrito (regra 14); Telegram (regra 15) a seguir.

### Estado

**CONCLUÍDO E NO AR.** Próxima na ordem do dono: **Parte F** (registro de
ferramentas/skills estilo Supply Depot — pre-flight, rollback). Pendências
do dono inalteradas (Vaultwarden, Registro Mestre etapa 4, pauta 3/5,
rotação de segredos — verificada fechada, fotos `analise/fotos-adicionais/`
e catálogo `3D/` adiados pelo dono).
