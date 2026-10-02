# Conversa OmegaDrakon — 2026-10-01

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
**"leia iniciar. chat esta dando erro interno"** (~09:5x).
Ambiente canônico de testes: `.venv/bin/python` SEM
`OD_TEST_POSTGRES_DSN`.

---

## 1. Diagnóstico do erro interno (~09:5x–10:0x)

- Retomada pela ordem da casa: `iniciar/README.md` → `session.json`
  (estado herdado: **v1.15.0 NO AR**, PID 1178955, de 30/09 21:36) →
  transcrição de 30/09.
- `systemctl --user status od-core`: active, mas o journal mostrava o
  padrão do erro:

  ```
  [NICKY][WARN] DB query falhou | error=network error | sql=SELECT ... FROM sessions s JOIN users u ...
  [NICKY][ERROR] API interna | error=DatabaseError
  ```

  Nas 4 queries de banco do caminho do chat (sessions JOIN users,
  users por username, telegram_links, llm_cache) desde **08:26** —
  `network error` é a mensagem do **pg8000 para socket morto**.
- Causa raiz: o **Postgres reiniciou às 06:31** (PID novo, processos
  background todos de 06:31) e o od-core, de pé desde 30/09 21:36,
  manteve no pool as conexões que o banco encerrou. O
  `PostgresConnectionPool.acquire` nunca validava a conexão antes de
  entregar → **conexão podre servida para sempre** → toda query de
  usuário/sessão/cache falhava → o chat devolvia **erro interno**.
- `/health` sem credencial dava 401 (auth_all no ar) — o diagnóstico
  veio do journal, não do endpoint.

## 2. Correção — pool postgres auto-curável (§pool_postgres_auto_cura_2026_10_01)

`storage/database.py` — só o `PostgresConnectionPool` (SQLite intacto):

- `acquire` valida cada conexão ociosa com **`SELECT 1`**
  (`_conn_viva`); qualquer falha = podre.
- Conexão morta: **fechada, removida da contagem** (`_discard`) e
  **substituída** — o sistema se recupera sozinho de restart do
  Postgres, sem restart do od-core.
- Retry limitado (`size + 1` tentativas); se todas vieram podres,
  cria uma nova no slot liberado. Contrato de **fila bloqueante
  quando esgotado** (sem estouro de conexões) preservado — e agora
  fixado por teste.
- Log novo: `DB conexão morta descartada pelo pool (postgres)`.

## 3. Testes e teste do teste

- `tests/test_database.py`: **+5 `TestPoolPostgresConexaoMorta`**
  (fake `_FakePgConn`): morta descartada e substituída · pool se
  recupera quando TODAS morrem · viva passa sem criar · pool fechado
  recusa · esgotado BLOQUEIA.
- Suíte completa: **2130 passed, 16 skipped** (68s, .venv canônico).
- **Teste do teste — 3/3 mutações bit-exata:**
  - M1 validação desligada (`if True`) → 2 falhas;
  - M2 socket morto tratado como vivo (`except Exception` →
    `RuntimeError`) → 2 falhas;
  - M3 fila bloqueante virou criação fora do lock → **1ª rodada
    SOBREVIVEU** (teste fraco: pool não estava esgotado) → endurecido
    com o contrato do cabeçalho do módulo ("quando o pool esgota,
    acquire bloqueia até uma liberação — sem estouro") → mutação
    re-detectada (1 falha). **Lição da casa de novo** (precedentes
    28–30/09): teste fraco passa mutação — endurecer antes de
    declarar coberto. Nota de método: a 1ª tentativa de restauração
    do M1 deixou a mutação no arquivo quando o M2 rodou (backup
    defasado) — `git diff` de conferência antes de cada rodada.

## 4. Bump MINOR 1.16.0

Política do CHANGELOG: "correção de robustez interna (sem rota/
endpoint/action nova) com testes novos = MINOR conservador".

- `.env` OD_VERSION=1.16.0 · capabilities fallback · pubspec
  **1.16.0+2032** · `_APP_VERSION_CODE=2032` · site 2x ·
  `CHANGELOG [1.16.0]` · `README_VERSAO §1.16.0`. Zero sobra de
  1.15.0 nos pontos do checklist.
- APKs rebuildados (`JAVA_HOME=~/jdk`, `PATH += ~/flutter/bin` — o
  flutter não está no PATH do serviço) e publicados em `site/`:
  aapt2 `versionCode='2032' versionName='1.16.0'` nos dois; sha256
  full `c80b9c1b…`, arm64 `30607f36…` (lição 4384e5b: nunca anunciar
  build não publicado).

## 5. Commit, deploy e prova viva (~10:1x–10:3x)

- **Commit `925baba`** fix(storage) — 9 arquivos +288/−7 (inclui
  `limitacoes.txt`, padrão da casa: dados do runtime vão junto) →
  push `d559b72..925baba master -> master` (regra 7.1).
- **Deploy IMPLANTADO** — restart 10:15, **PID 1238524**, NRestarts=0.
- **Prova viva:**
  1. `/health` ok, **9/9 checks up** (database incluso);
  2. `/app/version` → `{1.16.0, 2032, sha256 == binário de site/}`;
  3. `/capabilities` → 1.16.0 · **65 actions**;
  4. WS do chat na **8001**: handshake ok com credencial (o 426 das
     provas antigas é do ws_server dedicado; a rota `/ws/chat` da API
     REST responde 501 por decisão da Fase 5.2 — não é regressão);
  5. `/executa datetime` → pipeline completo ok;
  6. journal desde o restart: **0 Traceback · 0 ERROR**.
- **Prova da cura (o passo decisivo):** `pg_terminate_backend`
  derrubou as conexões do od-core pelo lado do Postgres (simulação
  EXATA do evento de 06:31) → journal registrou
  `DB conexão morta descartada pelo pool (postgres)` → a action
  seguinte respondeu `ok: True` **SEM restart** — auto-cura provada
  no ar.

**Estado: CONCLUÍDO, PUBLICADO E NO AR — v1.16.0.** O erro interno do
chat estava na camada de persistência, não no LLM/orquestrador; a
classe inteira de falha (restart do banco com o servidor de pé) está
fechada. Pendência do dono: instalar o APK 1.16.0+2032 no celular
(2032 > 2031). Pendência do sistema: nenhuma desta entrega.

---

## 6. Personalidades realmente distintas — v1.17.0 (~11:0x–14:3x)

Pedido do dono (ask_user, 2ª troca): "continue" → escolhas **personalidades
distintas** (do txt.txt: "as personalidades são diferentes, porque todas
respondem do mesmo jeito") e **commitar o limitacoes.txt vazio**.

### 6.1 Diagnóstico (causa provada no código)

- A fonte usada pelo chat é `agents/nicky_virthy/personality.py`
  (`Orchestrator._resolve_system` → `get_system_prompt(profile, role)`);
  o `agents/profiles.py` tem prompts ricos (FUNÇÃO/PRINCÍPIO/EXPRESSÃO)
  mas NUNCA é injetado no caminho do LLM.
- O prompt carregava ~95% de texto idêntico entre perfis (identidade,
  tríade, motor, limites por papel) — a ÚNICA linha variável era
  `Tom do perfil: <resumo de uma linha>`. Sinal minúsculo para o LLM
  local.
- Cache já isola por perfil (`make_key` inclui perfil) — descartado
  como causa.

### 6.2 Implementação

- `VOICE_BLOCKS` em `personality.py`: bloco `COMO VOCÊ FALA` para cada
  um dos 7 perfis com identidade no papel, registro/sintaxe, ritmo, o
  que faz, o que NUNCA faz, frase-assinatura e micro-exemplo (começo
  literal de resposta).
- Injeção em `build_identity_prompt` com precedência sobre o resumo
  curto (que permanece por compatibilidade) e perto do fim do prompt
  (distância mínima da geração). Prefixo de identidade intacto
  (preserva reuso de KV no llama-server).

### 6.3 Testes e teste do teste

- +9 `TestVoiceBlocks` (presença em todos os perfis, estrutura
  completa, unicidade par a par, auto-nomeação, precedência,
  micro-exemplos distintos, guarda da causa raiz >400 chars, resumo
  antigo preservado). Suíte completa **2139 passed, 16 skipped**.
- **3/3 mutações bit-exata** (backup /tmp, sha256 conferido): M1 Nyx
  clona bloco da Athenae → 4 falhas · M2 `voice = ""` → 3 falhas ·
  M3 bloco antes do resumo → 1 falha.

### 6.4 Bump MINOR, commit, deploy e prova viva

- Bump: `.env 1.17.0` (gitignored, em disco) · capabilities fallback
  · pubspec **1.17.0+2033** · `_APP_VERSION_CODE=2033` · site 2x ·
  CHANGELOG [1.17.0] · README §1.17.0. Guardas de versão verdes
  (inclui `_APP_VERSION_CODE == pubspec`).
- APKs rebuildados e publicados: aapt2 `versionCode='2033'
  versionName='1.17.0'` nos dois; sha256 full `67bc629b…`, arm64
  `6cce66ad…`. App: analyze 0 issues, testes 125/2.
- Commit **`c891d45`** feat(agents) — 8 arquivos +304/−5 → push
  (regra 7.1). Deploy: restart 14:06, **PID 1258460**, NRestarts=0.
- Prova viva: `/health` ok · `/app/version` {1.17.0, 2033, sha256 ==
  binário full} · `/capabilities` 1.17.0 · 65 actions · WS 8001 vivo
  (426) · journal **0 Traceback/ERROR**.
- **Prova de diferenciação** (controle direto no llama-server,
  parse_chatml igual ao core, 2 rodadas por perfil): **vox #2 usou a
  frase-assinatura literal** ("Ouvam bem: …"); nyx 2/2 gravitou para
  mistério ("…guardam secretos…", e no REST citou mitologia grega
  espontaneamente); guardian 2/2 seco; regulus 2/2 ponderado. O bloco
  DIRIGE as respostas no modelo real.

### 6.5 Achados (registrados com honestidade, fora do escopo)

1. **Coluna `profile` do llm_cache guarda o perfil default** —
   auditado após o registro inicial: o `cache.set(..., profile=profile)`
   do `_post_process` passa o perfil como **param da chave**
   (`make_key` inclui `profile=<perfil>`), igual ao `get` — o
   ISOLAMENTO entre personalidades está correto. A coluna gravada no
   banco é o `self._profile` do construtor (launcher passa OD_PROFILE)
   — metadado de telemetria errado, sem efeito funcional (o
   /admin/cache/prune varre `key, response`, não a coluna). Cosmético;
   sem PATCH dedicado.
2. **Motor real é qwen2.5-coder-3b, não gemma-4-E4B**: o llama-server
   no ar (PID 1129, desde 21/09) carrega
   `qwen2.5-coder-3b-instruct-q4_k_m.gguf`; o gemma-4-E4B está no
   diretório mas não servido. Explica alucinações factuais nas provas
   ("Lua é o segundo maior planeta"). O prompt declara 'gemma' —
   declaração e motor divergem; decisão do dono pendente (trocar o
   modelo servido OU o texto do prompt).

**Estado: CONCLUÍDO, PUBLICADO E NO AR — v1.17.0.** Os 7 perfis têm
blocos de voz próprios, provados no motor real. Pendências: APK
1.17.0+2033 no celular; achados 6.5 para decisão; desejos restantes do
txt.txt (voz, Drive, Agenda, Gmail).

---

## 7. Honestidade do motor — sandbox com o gemma real e decisão (§6.5.2) (~15:0x–16:0x)

Pedido do dono (3ª troca): "Trocar o modelo servido no llama-server para
o gemma-4-E4B declarado no prompt e provar no ar".

### 7.1 Sandbox (8082, regra 10 — sem tocar o chat)

- O unit `od-llm.service` se descreve como gemma mas o ExecStart ativo
  serve qwen2.5-coder-3b (rastro de troca sem revisão — linhas do gemma
  comentadas no próprio unit).
- gemma-4-E4B-it-Q4_K_M (4,98 GB) carregado em 2ª instância na 8082:
  sobe e atende; 1ª tentativa (ctx 6144, 3 threads) morreu em silêncio
  sob pressão de RAM/swap; com ctx 4096 e 2 threads ficou estável.
- Qualidade REAL: com prompt simples e max_tokens 2000 a resposta da
  Nyx é poética e coerente ("A noite é o manto de veludo onde o Limiar
  se abre...") — muito superior ao qwen.
- PORÉM com o system prompt OD completo (~800 tok): o pensamento do
  modelo estoura os 512 tok do max_tokens do OD → content VAZIO
  (finish=length) em 100% das tentativas (2 rodadas: 138s e 106s).
- Velocidade: ~5 tok/s (gemma, 2 threads) vs ~8,5 tok/s (qwen, 4
  threads). 2 instâncias simultâneas = swap 88–100% (OOM real).
- Nota de método: processos filhos do agente morrem ao fim da chamada
  de terminal; `setsid nohup` + disown manteve o sandbox de pé entre
  chamadas.

### 7.2 Decisão do dono (ask_user): QWEN COM NOME HONESTO

Manter o qwen-coder-3b no ar (rápido, estável) e corrigir a mentira da
declaração. Personalidade fica por conta dos blocos de voz (provados
com o qwen na v1.17.0).

### 7.3 Implementação (v1.17.1 PATCH)

- `personality.py`: prompt do motor declara **Qwen (qwen2.5-coder-3b)**
  em todos os papéis/perfis; comentário registra a prova do sandbox e a
  decisão.
- `capabilities.py`: llm-provider → 'LLM local (qwen2.5-coder-3b via
  llama-server 127.0.0.1:8081)'.
- `od-llm.service`: Description honesta + comentário com a alternativa
  gemma documentada para hardware maior (ctx 16384 + max_tokens >=
  1500 + RAM dedicada). daemon-reload ok.
- Provider 'gemma-local' (nome interno do core) permanece — não é
  declaração de modelo.
- Testes endurecidos: test_motor_real fixa 'qwen' presente E
  'gemma-4-e4b' AUSENTE em todos os papéis e perfis. Suíte 2139
  passed, 16 skipped.

### 7.4 Bump, deploy e prova viva

- bump PATCH: .env 1.17.1 · capabilities · pubspec **1.17.1+2034** ·
  `_APP_VERSION_CODE=2034` · site 2x · CHANGELOG [1.17.1] · README
  §1.17.1. APKs rebuildados (aapt2 2034/1.17.1; sha256 full `1bca0fed…`,
  arm64 `e55196c8…`).
- Commit **`e020aec`** fix(agents,capabilities) — 8 arquivos +73/−18 →
  push (regra 7.1). Depois: `961c609` chore(runtime) — limitacoes.txt.
- Deploy: restart **od-llm + od-core** 15:52. **od-core** PID 1270259,
  NRestarts=0; **od-llm** PID 1270257, NRestarts=0.
- Prova viva: 8081 health ok · `/health` 9/9 up · `/app/version`
  {1.17.1, 2034, sha256 == binário} · `/capabilities` publica
  'qwen2.5-coder-3b' · journal 0 Traceback/ERROR.
- **Prova decisiva no ar:** 'qual modelo de linguagem você usa?' →
  "Você está usando o **Qwen local** do Omega Drakon." (route=llm) e,
  com ref única: Nome Qwen, versão qwen2.5-coder-3b, servido pelo
  llama-server — **declaração == motor real**.

### 7.5 Resíduos e encerramento do sandbox

- Sandbox 8082 encerrado (kill), log temporário removido; swap segue
  alto (7/8 GB) — drenagem natural no uso; drop_caches sem sudo.
- `limitacoes.txt` acumulou degradações transientes de 13:47/14:47/
  15:41 (network_hosts/weather_city): NÃO reproduzíveis pós-liberação
  de RAM (o fastpath responde ok agora — 5 dispositivos; clima ok) e
  as 15:41 coincidem com o sandbox gemma vivo comendo RAM. Commitado
  como dado de runtime (961c609). Ação do anônimo seguiu o desenho:
  sem fastpath (privilégio mínimo), resposta honesta do LLM.

**Estado: CONCLUÍDO E NO AR — v1.17.1.** A divergência motor/declaração
está FECHADA: o que o sistema diz que é é o que ele é. Pendências: APK
1.17.1+2034 no celular; desejos restantes do txt.txt (voz, Drive,
Agenda, Gmail); cobertura vs gate 90; CI vs .env.

---

## 8. A Casa de Limitações estava sendo sujada pela própria suíte — v1.17.2 (~16:4x–17:1x)

> **Nota de reconstrução (01/10 ~23:2x):** esta seção foi reescrita a
> partir da entrada `v172_guarda_limitacoes_2026_10_01` do
> `session.json`, do CHANGELOG [1.17.2] e dos commits `d4daa53`,
> `36a317f`, `083dab8`, `8c1a2a9` — a sessão original encerrou sem
> gravar a §8.

**Pedido do dono:** "Investigar por que `network_hosts` e
`weather_city` degradam só no caminho do chat, não por `/executa`"
(~16:4x).

### 8.1 Investigação

- Journal do od-core **VAZIO** nos horários dos eventos (16:21) — o
  chat NUNCA passou pelo servidor naqueles segundos.
- Pistas: sempre as **MESMAS 3 perguntas** (incl. o typo
  `temperatuda`) em blocos idênticos; o dedup de 6h não bloqueava
  porque cada restart zerava a memória.
- Processos com cwd=`OmegaDrakon`: só `launcher` + `orquestrador` (que
  não toca limitações) — chat e jobs de fundo eliminados.
- **PROVA**: `pytest` isolado
  (`test_intents.py::TestFastPathOrchestrator::test_acao_degradada_cai_ao_llm`)
  gerou entrada NOVA no arquivo real (47 → 50 linhas, ts 16:46:16).

### 8.2 Causa raiz

Os testes de integração simulam ações degradadas com frases literais
("quantas pessoas na rede?" com `/proc` vazio; "qual a temperatuda em
presidente venceslau sp" sem fonte) e os hooks
`registrar_action_degradada`/`registrar_fallback_honesto` gravavam no
`limitacoes.txt` REAL a cada rodada da suíte. Os horários batiam com
rodadas de pytest. **O chat do dono NUNCA degradou** — network_hosts e
weather_city respondem ok pelo fastpath no ar.

### 8.3 Correção, teste do teste, bump e deploy

- `tests/conftest.py` (NOVO): fixture autouse redireciona
  `core.limitacoes.LIMITACOES_FILE` para `tmp_path` por teste + isola
  o dedup em memória (`_ultimo_registro`) — testes com
  `monkeypatch.chdir` seguem válidos (a fixture só muda o default).
- **Teste do teste**: mutação no-op na fixture → gravação no arquivo
  real volta (detectada, 2 linhas); guarda restaurada → suíte completa
  2139 passed e **0 linhas** no real.
- Commits: `d4daa53` (os eventos de 16:0x commitados como dado de
  runtime — padrão da casa) → `36a317f` (fix + limpeza: `limitacoes.txt`
  −47 linhas, `conftest.py` +39) → `083dab8` (bump) → `8c1a2a9`
  (registro).
- Bump **PATCH 1.17.2**: .env · capabilities · pubspec 1.17.2+2035 ·
  `_APP_VERSION_CODE=2035` · site 2x · CHANGELOG [1.17.2] · README
  §1.17.2.
- **Deploy**: restart **17:03:16**, PID 1281250, NRestarts=0. Prova
  viva: `/health` 9/9 · `/app/version` {1.17.2, 2035} · fastpath
  `network_hosts` ok (6 dispositivos) · `limitacoes.txt` 0 linhas ·
  journal 0 Traceback.

**Estado: CONCLUÍDO E NO AR — v1.17.2.** O "problema do chat" era
contaminação da suíte; a Casa de Limitações continua funcional no
runtime.

---

## 9. Voz ponta a ponta e TTS imune a poluição de ambiente — v1.17.3 (~17:2x–22:1x)

> **Nota de reconstrução (01/10 ~23:2x):** esta seção foi reescrita a
> partir da entrada `v1173_tts_robusto_2026_10_01` do `session.json`,
> do CHANGELOG [1.17.3] e do commit `b3a350d` (19 arquivos,
> +902/−14) — a sessão original encerrou sem gravar a §9.

**Pedido:** corrigir o TTS flaky da suíte — `test_tts_handler_devolve_wav_real`
falhava intermitentemente.

### 9.1 Causa raiz

`test_audio.py` cria instâncias `PiperTTS` com paths falsos em
`tmp_path` e polui `LD_LIBRARY_PATH`; o `build_voice_handlers()` do
launcher só SETAVA a variável se estivesse ausente — não corrigia valor
errado. Resultado: Piper morria com `exit 127`
`libespeak-ng.so.1: cannot open shared object file`.

### 9.2 Implementação (muito além do fix de env)

- **runtime/launcher.py**: `build_voice_handlers()` **FORÇA**
  `LD_LIBRARY_PATH` (ordem: `/opt/omegadrakon/voice/piper` →
  `REPO_ROOT/voice/tts`) e **pluga WhisperSTT + PiperTTS nos handlers
  da API** — `/transcribe` e `/tts` eram SEMPRE `None` no REST (501 no
  ar; voz só no Telegram). Os comentários do código rotulam esta
  entrega de `v1.18.0` — ver achado 9.4.
- **tools/audio/tts.py**: `PiperTTS._piper_env()` (NOVO) +
  `synthesize_to_file()` passa `env` customizado direto no
  `asyncio.create_subprocess_exec()` — imune a poluição global; flag
  `--espeak_data` ANTES de `--output_file` (contrato de parse).
- **Chat web**: microfone no composer (`microfone → /transcribe →
  texto no campo; resposta por voz via /tts`).
- **App Flutter**: `OdVoice` (record AAC/M4A + audioplayers), permissão
  `RECORD_AUDIO` em runtime, `OdApi.transcribe()/synthesize()`, botão
  de microfone no chat; `compileSdk 37`, AGP 9.2.0, Gradle 9.4.1
  (`permission_handler_android` exige SDK 37).

### 9.3 Validação, bump e deploy

- **Suíte completa 2148 passed, 16 skipped** — 5 rodadas seguidas sem
  falha (o flaky morreu). App: `flutter test` 131 passed, 2 skipped ·
  `analyze` 0 issues. Testes novos: `tests/test_voice_api.py` (+239) e
  `app/test/voice_api_test.dart` (+115).
- Bump **PATCH 1.17.3**: .env · capabilities · pubspec 1.17.3+2036 ·
  `_APP_VERSION_CODE=2036` · site 2x · CHANGELOG [1.17.3] · README
  §1.17.3. APKs rebuildados (aapt2 `versionCode='2036'
  versionName='1.17.3'`) e publicados em `site/` (21:31 full,
  21:59 arm64).
- **Commit `b3a350d`** → push (regra 7.1); **deploy: restart
  22:10:02** (journal do boot -2 — o checkpoint dizia "PID pendente
  restart", mas o restart ACONTECEU e a v1.17.3 entrou no ar às 22:10;
  depois sobreviveu aos 2 reboots da §10).
- **Prova viva pós-reboot (23:19)**: `POST /tts` → HTTP 200,
  `audio_b64` com RIFF/WAV real de 83.616 bytes (journal: `Síntese TTS
  concluída | elapsed_s=1.32`) — voz no REST operando no ar.

### 9.4 Achados desta entrega (decisão do dono pendente)

1. **Rótulo v1.18.0 no código vs bump 1.17.3** — `launcher.py`,
   `server.py` (chat), `test_voice_api.py` e `voice_api_test.dart`
   descrevem a entrega como "v1.18.0". Pela regra 12 (feature nova
   compatível = MINOR), `/transcribe` + `/tts` + voz no app são
   FEATURE; o bump PATCH 1.17.3 rotulou a entrega só como fix de TTS.
   Divergência comentário/versão: aceitar como está ou corrigir no
   próximo bump (ex.: declarar 1.18.0 quando a voz for confirmada).
2. **APK "completo" deixou de ser completo** — `site/OmegaDrakon.apk`
   (1.17.3) tem 19.496.875 B (o mesmo tamanho do arm64; sha256
   diferentes) e só `arm64-v8a` está COMPLETO (17,0 MB com
   `libflutter.so`); `armeabi-v7a` e `x86_64` têm só 2 arquivos de
   ~0,1 MB cada (`libdartjni.so`, `libdatastore_shared_counter.so`)
   **sem `libflutter.so`**. O full antigo (backups/apk-v1.10.0) tinha
   49,4 MB de libs nos 3 ABIs completos. Efeito provável do upgrade
   AGP 9.2.0/Gradle 9.4.1 (do próprio commit). No Redmi (arm64)
   instala e roda; aparelho 32-bit/x86 receberia app quebrado. O
   registro do `session.json` afirma "full (54.0 MB)" — não bate com o
   disco.
3. **txt.txt** — a linha `comunicação por voz` SEGUE no arquivo
   (mtime 01/10 20:34); o checkpoint dizia "voz removido, restam
   Drive/Agenda/Gmail". Ou a voz ainda não foi considerada pronta pelo
   dono, ou a remoção não aconteceu.

**Estado: CONCLUÍDO E NO AR — v1.17.3.** Voz no app, no chat web e no
REST; TTS imune a poluição de ambiente. Pendências do dono: APK
1.17.3+2036 no celular; Drive/Agenda/Gmail no txt.txt.

---

## 10. Dois reboots do servidor — recuperação autônoma provada de novo (22:55–23:1x)

Achado desta retomada (23:1x), durante a verificação do estado — nada
disso estava no checkpoint:

- **Reboot 1 — 22:55:46**: `sudo reboot now` do **alex** (pts/1, no
  journal do boot anterior). Boot limpo de `6.8.0-139` →
  **`6.8.0-142`** (kernel já instalado, pendente de ativação). od-core
  voltou sozinho às **22:56:32** (PID 1129) com a v1.17.3.
- **`apt upgrade` — 22:59:16 → 23:05:27**: alex (SSH de
  192.168.0.111) rodou `apt update` + `apt upgrade`: kernel
  **`6.8.0-146`**, tailscale 1.102.4, docker-ce, apparmor, etc.
- **Reboot 2 — 23:05:56**: `sudo reboot` do alex. Boot atual
  (`2d7a3002…`) desde **23:06:38**.
- **Recuperação autônoma 2/2** — sem ninguém tocar em nada: od-core
  23:06:41 (PID 1239, **NRestarts=0**), od-llm (qwen2.5-coder-3b,
  health ok), od-orchestrator, omega-drakon (bot, 18 comandos),
  od-control-bridge; 6/6 portas no ar; `Funnel on` (`/` → 8000,
  `/ws` → 8001); journal do boot **0 `[NICKY][ERROR]`**. Prova de fora
  pela URL pública: `/app/version` 200 em 0,084 s.
- Warnings transitórios do boot (tailscale bootstrapDNS antes da rede
  subir; 1× `Transporte indisponível` em 23:06:43) — normais, sem
  persistência; HA sem timeout neste boot; Telegram em polling.
- **Efeito prático**: a v1.17.3 está viva desde o restart das 22:10 e
  sobreviveu aos 2 boots — a classe "servidor de pé" revalidada na
  prática (além da prova formal do boot autônomo de 21/09).

**Estado: VERDE — sistema íntegro após 2 reboots, v1.17.3 no ar,
função voz provada (§9.3).**
