# Conversa 2026-10-13 — OmegaDrakon

## §1 — Retomada "leia iniciar" (~19:05)

Checkpoint lido (`session.json` atualizado até 13/10 01:20 + transcrição de
12/10 §1–§8, `txt.txt` sem mensagem nova do dono). Verificação de estado ao vivo:

- **od-core**: `active` PID 3480132 desde 12/10 23:23, NRestarts=0, journal
  sem erros (30 min). `/app/version` = **1.24.1 / 2053** (sha bate com o APK
  publicado). `/health` responde 401 sem credencial = comportamento esperado.
- **Git**: HEAD `a0a3227` == `origin/master`, árvore **limpa**.
- **Funnel/serve**: `# Funnel on` → `/`→8000 e `/ws`→8001 na 443; prova ao vivo
  `https://nicky-server.tail1b1f51.ts.net/site/index.html` → **200**. Na 8443
  (tailnet) as 9 ferramentas, com `/wiki` (Kiwix, ZIM de 14,4 GB) → **200**.
- **Docker**: 10 containers `Up` (od-kiwix 19h, od-stirling-pdf healthy 23h,
  vaultwarden/homebox/filebrowser healthy).
- **Caixa de entrada**: `analise/Avatar/` vazio (13 PNG já publicados);
  `analise/fotos-adicionais/` com as 4 fotos que o dono mandou guardar
  ("vou usar depois"); `txt.txt` sem pedido novo.

**Estado: sistema estável, nada em andamento.** Pendências do dono (inalteradas):
conta Vaultwarden · etapa 4 do Registro Mestre · itens 3/5 da pauta · ordem das
partes A–F do Project NOMAD · rotação de segredos (adiada) · catalogar `3D/`.

---

## §2 — Parte A (eval) implementada + 2 bugs reais consertados → v1.24.2 no ar (~19:1x–20:35)

Dono: "ok. pode fazer" → execução da Parte A na ordem acordada (A → C → B → D → E → F).

### O que foi entregue (`evals/`)

- **Goldens** (`goldens.jsonl`, 12 casos): pergunta real × resposta esperada
  (hora, data, matemática ×2, senha mqtt, wifi anônimo, IP, portas, clima,
  dólar, capital, identidade). Carga valida id único, modo/papel, regex e
  **derruba campo desconhecido** (expectativa morta não existe).
- **3 modos**: `oracle` (pipeline real + `RecordingProvider` — sem rede/LLM,
  CI-safe), `e2e` (`build_orchestrator()` + registry + LLM local), `noretrieval`
  (e2e sem ActionRegistry = LLM puro). Toda rodada com `persist=False` — o eval
  **nunca escreve em produção**.
- **Baseline por modo** (`baseline-<modo>.json`) + `--comparar` antes/depois +
  CLI `python -m evals` (exit 1 em falha). `evals/README.md`.
- **Gate na suíte/CI**: `tests/test_eval_oracle.py` (roda os goldens oraculares
  no pipeline real; regressão vs baseline derruba) + `tests/test_eval.py`
  (máquina: carga, avaliação pura, baseline, CLI) — **+41 testes**.

### A 1ª rodada do e2e pegou 2 bugs reais (permissão do papel `user`)

1. user + "temperatura em presidente venceslau" → **PERMISSION DENIED**
   (`weather_city` fora da allowlist do user) → LLM sem dado (rota llm).
2. user + "quanto está o dólar?" → idem (`exchange_rate`) → o LLM
   **ALUCINOU "USD 5.478 (USD/CLP)"** (probe de evidência, 19:32).

**Causa raiz**: as duas actions nasceram para o chat do usuário (v1.12.0 e
v1.14.0) e esqueceram da allowlist do papel user (ha_weather já estava desde a
v1.8.0 — mesma natureza: API pública de leitura, sem chave, sem segredo).
**Conserto**: `weather_city` e `exchange_rate` na allowlist do user, com teste
de regressão novo garantindo que IP/portas/segredos/escrita/ha_summary
**seguem vedados** (menor privilégio intacto).

### Hermeticidade

Os testes de clima que agora executam a action fakeiam a Open-Meteo
(`_fakeia_rede_do_clima`; bloqueio via `urlopen` nos testes de retry) — a suíte
não faz chamada de rede (CI do GitHub incluído). Teste novo do contrato
user → fastpath com fonte fakeada ("27.3°C", "Presidente Venceslau").

### Gate de cobertura — achado colateral

O HEAD anterior (`3372552`) reprovaria o gate local: **89,80% < 90** (medido em
worktree `/tmp/opencode/od-headcov`, removido depois). A entrega fecha em
**90,04%** (o teste do corpo da `weather_city` foi o fôlego + as demais coberturas).

### Validação (regra 6/7.3)

- Suíte do servidor com gate: **2531 passed / 16 skipped · 90,04%**.
- Eval: **oracle 8/8 · e2e 12/12 · noretrieval 8/8** (baselines gravadas).
- App (pubspec mudou): `flutter analyze` 0 issues · `flutter test` 157/2.

### Bump/deploy/restart (regra 12/7.3)

- PATCH **1.24.1 → 1.24.2** + versionCode **2053 → 2054** (regra §5.3) em `.env`,
  capabilities fallback, pubspec, `_APP_VERSION_CODE`, site (badge/meta/histórico),
  CHANGELOG e README de Versão (§1.24.2).
- APKs rebuildados (`build_apk.sh`, force-version-code) e publicados em `site/`;
  aapt2: **2054 / 1.24.2** nos dois · sha completo `54790889…`, arm64 `3e5a2c2d…`.
  APKs 1.24.1 guardados em `backups/apk-v1.24.1+2053-20261013/`.
- Commit `c07f83c` == origin/master, árvore limpa (inclui `limitacoes.txt` com
  as 2 degradações REAIS do dia — a do weather_city 19:29 e a do dólar 19:32,
  que motivaram o conserto). Restart verde (7.3) às 20:33.

### Provas ao vivo pós-restart

- od-core **PID 390802**, NRestarts=0, active desde 20:33:01, journal **0 erros**.
- `/app/version` = **1.24.2 / 2054**, sha `54790889…` == APK publicado ·
  `/health` **9/9** · `/capabilities` 1.24.2 (86 actions, 43 caps) ·
  `/supervision` restarts 0, degraded [].
- Prova de permissão do user: suite determinística + e2e 12/12 com o MESMO
  código que o serviço carrega (sem conta de teste criada em produção —
  honestidade da regra 7).

### Comunicação

- Telegram do dono enviado (message_id 2651 — regra 15).
- `txt.txt` reescrito com a conclusão, verificação, próximo passo (parte C) e
  pendências do dono (regra 14).

**Próximo passo na ordem acordada: parte C = referência médica** (explicar
igual a A — o que é, como o dono acessa, como o sistema controla — antes de
implementar). Pendências do dono inalteradas (Vaultwarden, etapa 4, pauta 3/5,
fotos guardadas).

---

## §3 — Parte C (referência médica) implementada → v1.25.0 no ar (~21:0x–21:50)

O dono respondeu "pode fazer" à explicação da Parte C (três eixos, como o
padrão firmado). Implementação:

### O que entrou

- **3 actions na categoria `saude`** (`tools/actions/actions.py`):
  `saude_condicao` (curadoria CDC/NIH/NCCIH/MedlinePlus por condição),
  `saude_interacoes` e `saude_medicamento` (bula FDA verbatim via openFDA,
  com checagem de menção cruzada).
- **Coleções versionadas** `tools/saude/collections/` (36 condições, 20
  caseiros, 18 naturais, lexicon de 46 medicamentos PT-BR→FDA — só nomes).
  Atribuição obrigatória; original EM Inglês preservado em `origem_en`
  (auditoria); PT-BR = tradução fiel da fonte citada (nada autoral).
- **`core/intents.py`**: `_detect_saude` (gatilhos conservadores —
  "posso tomar café com leite" não é saúde) + `_formata_saude` com
  `SAUDE_AVISO` obrigatório em todo ramo. Saúde **nunca** degrada para o
  LLM (nem com `ok=False`).
- **Permissões**: papel `user` +3 (leitura de fonte pública); regressão
  mantém segredos/escrita/IP vedados.
- **Gate**: `tests/test_saude.py` (+45 testes, openFDA 100% fakeado) +
  4 goldens (2 oracle herméticos, 2 e2e com rede real).

### Provas

- Suíte: **2576 passed / 16 skipped · 90,08%** · flutter analyze 0 ·
  flutter test 157/2.
- Eval: oracle **10/10**, e2e **16/16** (openFDA real — dipirona×losartana
  e bula de losartana consultadas na FDA de verdade), noretrieval 8/8.
- Deploy: bump MINOR **1.25.0+2055**; APKs rebuildados (aapt2 2055/1.25.0,
  sha `dbef2965…`/`75902540…`; 1.24.2 guardados em
  `backups/apk-v1.24.2+2054-20261013/`); commit `e6d6681` == origin/master.
- Restart verde 21:41 (user systemd): od-core **PID 454712**, NRestarts=0,
  journal 0 erros; `/app/version` 1.25.0/2055 (sha == site); `/health`
  9/9; `/capabilities` 89 actions / 44 caps (`saude-reference` available);
  `/supervision` degraded [], restarts 0.
- Comunicação: Telegram message_id **2662** (regra 15); `txt.txt`
  reescrito (regra 14).

### Fronteira honesta (documentada)

"Para que serve X?" sem bula/efeitos/interação ainda cai no LLM; anônimo
segue o fluxo normal. Pendências do dono inalteradas (Vaultwarden, etapa 4,
pauta 3/5, rotação de segredos, fotos).

**Próximo na ordem acordada: parte B = RAG** (com o eval da parte A no
largo, a qualidade passa a ser medida antes/depois).
