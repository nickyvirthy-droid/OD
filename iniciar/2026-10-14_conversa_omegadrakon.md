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
