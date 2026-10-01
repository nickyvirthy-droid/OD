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
