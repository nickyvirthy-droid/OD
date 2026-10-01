# Conversa OmegaDrakon — 2026-09-30

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
"leia iniciar, depois leia docs e por fim leia o arquivo
instrucoes_projeto.txt" (~03:3x). Ambiente canônico de testes:
`.venv/bin/python` SEM `OD_TEST_POSTGRES_DSN`.

---

## 1. Retomada tripla (~03:3x)

Leitura na ordem pedida: `iniciar/` (session.json, RULES.md, transcrições)
→ `docs/` (README_VERSAO até 1.10.1, REGRAS_DE_TRABALHO, VERSIONAMENTO) →
`instrucoes_projeto.txt`.

- Estado herdado: **v1.10.1 NO AR** (PID 1026393, NRestarts=0) — app sonda
  sozinho os 4 caminhos (LAN → tailnet → Funnel → DDNS); pendências do dono:
  instalar APK 1.10.1+2025 no celular e provar acesso externo sem Tailscale;
  análise de coerência (protocolo §14 de 29/09) aguardando conversas novas.
- **Achado:** `instrucoes_projeto.txt` descreve um CONTEXTO DESATUALIZADO
  ("agente Python integrado ao Home Assistant", Freebuff CLI recém
  instalado) e pede um orquestrador de fallback entre CLIs
  (Freebuff/OpenCode/Kilo) monitorando `pedido.txt` — pedido que não
  constava do session.json. Dono consultado: **"Executar o instruções"**.

## 2. Execução do instruções (~03:4x–04:1x)

### 1) Dependências do sistema

- Node v18.19.1 + NPM 9.2.0 já presentes; `freebuff` em `/usr/local/bin`.
- `npm install -g` direto falhou (EACCES em `/usr/local`, sudo exige senha)
  → instalação com `--prefix ~/.npm-global` (caminho sem root; PATH do
  usuário já contém o bin). 1ª tentativa abortada por timeout de 300s
  (download de binários por plataforma, centenas de MB); 2ª rodada completou
  em 9m usando o cache. Resultado: **opencode v2.0.20 · kilo 7.8.1**.
- `requirements.txt` ganha `python-dotenv>=1.0` e `requests>=2.31` (com
  justificativa, padrão do arquivo); instaladas na `.venv`
  (dotenv 1.2.1, requests 2.32.5 — requests já era transitiva).

### 2) orquestrador.py

- Monitor de `pedido.txt` (5s), leitura+limpeza ANTI-LOOP imediata, prompt
  blindado (código puro, sem ```python), cascata Freebuff → OpenCode →
  Kilo (`CliSpec`: freebuff ask / opencode run / kilo run --auto), timeout
  600s por CLI, ambiente do subprocesso herda `os.environ` (chaves do .env
  via `load_dotenv`).
- **Validação `ast.parse`** como regra central: sintaxe inválida NUNCA é
  gravada — pula para a próxima CLI; todas falhando → nada gravado.
- Extração de cerca markdown como defesa (a CLI pode ignorar a instrução).
- Tipado (type hints em tudo), documentado, dataclasses
  `CliSpec`/`ResultadoPedido`; `pedido.txt` criado em branco; `.gitignore`
  ganha `/pedido.txt`, `/codigo_gerado.py` e `/instrucoes_projeto.txt`
  (material local da raiz).

## 3. Validação e teste do teste (~04:1x)

- `tests/test_orquestrador.py`: **25 passed** (prompt, extração, ast.parse,
  leitura/limpeza, cascata com fakes, contratos das CLIs/ENV_KEYS, comando
  montado + ambiente repassado).
- **Teste do teste — 4 mutações:** M1 validação desligada → 4 falhas;
  M2 falha tratada como sucesso → 4; M3 limpeza anti-loop desligada → 2;
  M4 chaves não repassadas → **1ª rodada SOBREVIVEU** (teste fraco:
  `dict(os.environ)` já continha as chaves — loop era código morto, mesmo
  precedente da mutação fraca de 28-29/09) → teste endurecido para o
  contrato de `executar_cli` (comando montado + env no subprocess.run),
  mutação re-aplicada → **detectada (2 falhas)**, revertida bit-exata
  (backup em /tmp, sha256 conferido; lição de 29/09 aplicada).
- Suíte completa: **2040 passed, 16 skipped** (66s).

## 4. Achados de infra (registrados com honestidade, NÃO causados por esta entrega)

1. **Gate de cobertura já vermelho no HEAD:** `pytest --cov --cov-fail-under=90`
   → 89.44% (TOTAL idêntico 12191/1287 com e sem os arquivos desta entrega;
   lacuna distribuída em módulos antigos — migrate_history_owner 59%,
   control_bridge 62%, actions 68%...). As sessões recentes rodavam só
   `pytest -q`; a sessão de 29/09 registrou "suíte verde" SEM o gate.
2. **CI quebra em checkout limpo:** `test_env_e_capabilities_na_mesma_versao`
   lê o `.env` (gitignored) e não acha OD_VERSION fora da máquina do dono —
   o CI (item 1.1 da v1.0.0, gate ≥90%) não pode estar passando como
   descrito. Acoplamento pré-existente, outside do escopo do instruções.

## 5. Versionamento

**Sem bump** (precedente `runtime/migrate_history_owner.py` + reordenação do
CHANGELOG em 29/09): ferramenta standalone na raiz, fora do od-core e do
app; não altera a API pública nem o runtime implantado; nenhum item do
checklist de bump se aplica (sem mudança em .env/capabilities/pubspec/site).
CHANGELOG ganha seção datada "Ferramenta — Orquestrador de fallback de CLIs
(2026-09-30, sem bump)" no topo (a guarda de ordem exige seções `## [X.Y.Z]`
descendentes e as existentes permanecem intactas).

## Estado final

- Árvore: `orquestrador.py` (novo) · `tests/test_orquestrador.py` (novo) ·
  `requirements.txt` · `.gitignore` · `docs/CHANGELOG.md` ·
  `iniciar/session.json` · esta transcrição.
- Monitor NÃO deixado rodando em background (regra 7: mutação de estado
  externo exige pedido explícito). Para usar: `.venv/bin/python
  orquestrador.py` (ou via systemd --user, se o dono quiser).
- Pendências do dono INTACTAS (APK 1.10.1+2025 no celular, prova externa,
  análise de coerência pós-zerada) + 2 achados de infra para decisão
  (cobertura/CI).

---

## 6. Retomada: "leia iniciar" (~12:2x)

Pedido: "leia iniciar". Lidos `iniciar/README.md`, `iniciar/RULES.md`,
`iniciar/session.json` e esta transcrição.

- Estado herdado: HEAD 79a20f1 == origin/master (orquestrador de CLIs);
  v1.10.1 NO AR.
- **Lote órfão encontrado:** 7 arquivos (+472/−9, mtimes 04:57–04:59 de
  30/09 — DEPOIS desta transcrição) — **v1.11.0 CANAL DE DESENVOLVIMENTO**:
  3 rotas `/admin/dev/pedido` (POST injeta no `pedido.txt` com escrita
  atômica e modo acumular; GET estado da fila + detecção do monitor por
  `/proc`; DELETE esvazia) + seção nova no painel `/admin` + bump completo
  (pubspec 1.11.0+2026, `_APP_VERSION_CODE=2026`, .env, capabilities,
  site 2x, CHANGELOG, README_VERSAO) + 10 testes novos
  (`TestAdminDevPedido`, guarda de rotas 42→45).
- Validação: TestAdminDevPedido 10/10 · guardas 26 passed · **suíte
  completa 2050 passed, 16 skipped** (66s).
- **Lacuna:** APK de `site/` ainda é **1.10.1+2025** (aapt2; mtimes 29/09
  22:18) — o lote anunciou 1.11.0+2026 sem rebuild/publicar o APK. Pelo
  precedente 4384e5b, rebuild é obrigatório ANTES de deploy/prova viva.
- Sessão registrada em `session.json`
  (§`retomada_2026_09_30_lote_dev_channel`). Dono escolheu: **concluir o
  fluxo**.

### Conclusão do fluxo (~12:3x)

1. **APKs rebuildados** (backup dos anteriores em
   `/tmp/apk-v1.10.1+2025-*.bak`): full 53.168.295 B (sha256
   `a0ced701…`) · arm64 18.916.050 B (sha256 `8425f219…`) — aapt2
   versionCode='2026' versionName='1.11.0' nos dois; publicados em
   `site/`.
2. **Commit db74fa2** (7 arquivos +472/−9) e push — HEAD ==
   origin/master (regra 7.1).
3. **Deploy IMPLANTADO** — restart 12:34, PID 1097167, NRestarts=0.
4. **Prova viva 7/7**: (1) /health 200 · /app/version {1.11.0, code 2026,
   sha256 == binário}; (2) /capabilities 1.11.0; (3) WS 426 · supervision
   up restarts 0; (4) GET /admin/dev/pedido fila vazia → ok;
   (5) POST injeta → 60 bytes no disco, preview confere; (6) DELETE → 0
   bytes · POST sem credencial → 401 · painel /admin com a seção nova;
   (7) prova de fora pelo Funnel: /health 401 · /ws 426 · /app/version
   code 2026. Journal 0 Traceback/ERROR/CRIT.

**Estado: CONCLUÍDO E NO AR — v1.11.0.** Pendências: auto-atualização do
celular (2026 > 2025); decisão do dono sobre subir o `orquestrador.py`
como serviço (systemd --user) para o canal funcionar fim a fim.

---

## 7. Serviço od-orchestrator — canal fim a fim (~13:0x)

Pedido (follow-up do dono): subir o `orquestrador.py` como serviço
`systemd --user` para o canal de desenvolvimento funcionar fim a fim.

### Implementação

- `deploy/od-orchestrator.service` (NOVO, padrão do `od-core.service`):
  WorkingDirectory do projeto, `EnvironmentFile=.env`, PATH com
  `~/.npm-global/bin` (opencode/kilo ficam fora do PATH default do
  systemd), ExecStart pela `.venv`, `Restart=on-failure`/10s,
  `WantedBy=default.target` (Linger=yes já ativo). Instalado com
  `daemon-reload` + `enable --now`.

### 3 bugs reais pegos pela 1ª prova fim a fim

1. **Freebuff `ask` não existe** no wrapper público 0.2.1 (só `login`) →
   "too many arguments". O binário real `~/.config/manicode/freebuff`
   aceita PROMPT posicional direto.
2. **OpenCode default `build` morre sem créditos** OpenAI
   (`credit_balance_exhausted`). Modelo grátis
   `opencode/nemotron-3-ultra-free` responde certo.
3. **Kilo default gemini → quota 0** e modelos groq → TPM 8000 estourado
   pelo prompt de sistema (`Compaction exhausted`). Modelo grátis
   `kilo/inclusionai/ling-3.0-flash-sante:free` + `--pure` responde certo.

### Correção (`orquestrador.py`)

- `CliSpec` ganha `caminho_candidato` (binário fora do PATH do serviço) e
  `comando_base()` (PATH → candidato expandido);
- Freebuff sem `ask` (prompt posicional); `OPENCODE_MODELO`/`KILO_MODELO`
  grátis como constantes do contrato;
- `tests/test_orquestrador.py`: +2 testes e guarda de binário ausente
  endurecida (M2 sobreviveu à 1ª rodada — `subprocess.run` agora é
  proibido no teste); 27 passed no arquivo.

### Teste do teste (3 mutações, todas detectadas e revertidas bit-exata)

- M1 candidato removido de `comando_base()` → 2 falhas;
- M2 guarda de indisponível removida → 1ª rodada SOBREVIVEU (teste fraco,
  precedente de 28–30/09), teste endurecido, 2ª rodada 1 falha;
- M3 modelo pago de volta → 1 falha.

### Validação e deploy

- Suíte completa: **2052 passed, 16 skipped** (67s).
- Commit `d790e0b` (3 arquivos +156/−9) e push — HEAD == origin/master.
- Serviço NO AR: `od-orchestrator` active **PID 1104579** NRestarts=0
  (restart 13:12 com o fix); API vê `monitor_ativo=true` com pid.

### Prova fim a fim (pós-fix)

`POST /admin/dev/pedido` ("crie o arquivo prova_canal.py com uma funcao
saudacao()...") → 95 bytes na fila → journal: `Pedido recebido` →
`Freebuff falhou` (BUG-1, cai para OpenCode) → **`Código válido gravado
em codigo_gerado.py (via OpenCode)`** → fila 0 bytes (anti-loop) →
`codigo_gerado.py` executado: `saudacao()` → **"canal fim a fim ok"**.
Arquivo da prova removido em seguida.

**Estado: CONCLUÍDO E NO AR — o canal funciona FIM A FIM:** painel
`/admin` → `POST /admin/dev/pedido` → fila → serviço → cascata
(OpenCode → Kilo; Freebuff entra quando o wrapper público ganhar modo
não-interativo) → `codigo_gerado.py`.

---

## 8. Retomada + verificação geral (~14:3x)

Pedido: "leia iniciar" → depois "Rodar a verificação geral do sistema".

- Retomada: od-core PID 1097167 (v1.11.0) e od-orchestrator PID 1104579
  no ar; HEAD c96a2f4 == origin/master. Nota: `omega-drakon.service` não
  existe mais — o bot Telegram foi embutido no od-core.
- **Verificação VERDE:** /health 9/9 · /supervision restarts 0 ·
  /capabilities 1.11.0 · 63 actions · /app/version {1.11.0, 2026,
  sha256 == binário} · Funnel provado de fora (401/426/200) · banco
  users 2 · sessions 31 (25 válidas) · msgs 32 (alex 30) · llm_cache 55
  com 0 etiquetadas · journal 0 erros. Nada reiniciado.

## 9. Análise de coerência §14 (~15:0x)

Pedido: "Analisar as 30 conversas novas do alex com o protocolo de
coerência §14" — 15 turnos (29/09 14:00 → 30/09 07:53).

**Veredicto: 11 coerentes · 3 devaneios · 1 inconclusivo.**

- **D1 (T12):** 'sou o dono adm' → o gemma INVENTOU uma agenda com 3
  tarefas falsas — o sistema NÃO tem agenda (0 ocorrências em
  tools/actions; 41 capacidades sem calendário).
- **D2 (T14):** 'qual o LLM que está usando' → 'Estou utilizando a
  OpenAI GPT-4' FALSO (roda gemma-4-E4B local; nenhum prompt declarava
  o motor).
- **D3 (T10):** dólar servido do route=cache — a entrada foi CRIADA
  PELO GEMMA às 13:34 com 'US$ 1 = R$ 4,73 · Atualizado: 29/09 às
  13h56' (nem o horário bate) — alucinação PRÉ-guarda perpetuada pelo
  cache.
- Coerentes: rotas datetime/action_intent todas corretas com dado real
  (IP, temperatura 52.5°C, clima HA 36.1°C), 'Alex Projeti' confirmado
  no prompt, cache só para pergunta idêntica. Critério 5 (formato
  imitado): ZERO.
- Inconclusivo: T13 recusou 'configuração do llama.cpp' como 'código
  proprietário' (é open-source) — motivo errado, não devaneio estrito.

## 10. Poda do dólar + prompt honesto v1.11.1 (~15:2x)

### Poda (D3)

- Snapshot `backups/cache-dolar-pre-guarda-20260930.json` (1 entrada,
  sha256 cf9c6c0224f5d4e…).
- POST /admin/cache/prune com a key → removidas 1; provado no BANCO:
  total 55 → 54, entrada 6873cd7d… = 0. /health ok; journal 0 erros.
- Nota de método: o dry_run com keys ecoa a chave como candidata mesmo
  depois de removida ('motivo: chave informada') — a prova é o SELECT.

### Prompt honesto (v1.11.1)

Pedido (ações 2 e 3 da §14): "Declarar o LLM real (gemma local) no
prompt do perfil e a inexistência de agenda".

- `agents/nicky_virthy/personality.py` — prompt canônico de TODOS os
  perfis e papéis ganha dois blocos:
  - **Motor real:** gemma (gemma-4-E4B) via llama-server local; nunca
    afirmar ser GPT/OpenAI, Claude ou Gemini.
  - **Capacidades inexistentes:** agenda/calendário/lembretes/e-mail
    não existem — 'isso não existe no sistema'; NUNCA inventar tarefas
    ou conteúdo para preencher a lacuna.
- Guardas: +3 testes em test_personality.py (motor em 3 papéis · motor
  nos 7 perfis · agenda em 3 papéis). Teste do teste: 3/3 mutações
  detectadas (bloco removido → 3 falhas · NÃO→não → 1 ·
  llama-server removido → 1), restaurações bit-exata.
- Suíte completa: **2055 passed, 16 skipped** (+3).
- Bump PATCH 1.11.1: .env · capabilities fallback · pubspec
  1.11.1+2027 · _APP_VERSION_CODE=2027 · site 2x · CHANGELOG [1.11.1] ·
  README_VERSAO §1.11.1. APKs rebuildados e publicados.

**Estado:** ver o checkpoint (§`analise_coerencia_2026_09_30` e
§`poda_dolar_2026_09_30`); deploy e prova viva registrados ao concluir.

### Deploy e prova viva da 1.11.1 (~15:2x–15:4x)

- Deploy IMPLANTADO — restart, PID **1121164**, NRestarts=0.
- Prova viva 7/7: (1) /app/version {1.11.1, code **2027**, sha256
  `ebfb3970…` == binário de site/}; (2) /capabilities 1.11.1;
  (3) /health 9/9 · supervision restarts 0; (4) WS 426; (5)
  **D2 eliminado:** 'qual o LLM que esta usando' → 'O sistema utiliza um
  modelo de linguagem local chamado "gemma"' (route=llm, ZERO alucinação
  de GPT); (6) **D1 eliminado:** 'como esta minha agenda' → 'não tenho a
  capacidade de gerenciar agendas ou calendários' (honesto); (7) prova
  de fora pelo Funnel: /health 401 · /ws 426 · /app/version 2027.
- **BUG pego pela prova 7:** 'sou o dono adm' → route=cache serviu a
  agenda inventada de 29/09 21:36 (pré-guarda, key 45a33548…) — o
  prompt novo não alcança entrada JÁ CACHEADA (mesma classe do D3).
  Snapshot `backups/cache-agenda-pre-guarda-20260930.json` (sha256
  `12d16b30…`) → poda real removidas 1 (cache 55 → 54, entrada 0 no
  banco) → reprova: 'sou o dono adm' agora responde honesto (route=llm,
  sem inventar tarefas).
- App: flutter analyze 0 issues · flutter test **114 passed, 2 skipped**.
- Journal da janela do deploy/provas: 0 Traceback/ERROR/CRIT.

**Estado: CONCLUÍDO E NO AR — v1.11.1** com as duas declarações de
honestidade no prompt canônico e o legado pré-guarda do cache limpo
(dólar + agenda). Pendência do dono: auto-atualização do celular
(2027 > 2026).

---

## 11. Retomada "continue" + v1.12.0: clima de cidade real (~16:1x–16:3x)

### Retomada (~16:1x)

"continue" → o lote weather_city (código + testes) já estava no working
tree da sessão anterior, SEM validação/bump/deploy. Ordens executadas:
validação → teste do teste → bump → APK → deploy.

### Validação

- 1 teste v1.8.0 quebrado (`test_resposta_transparente.py` fixava
  cidade → `ha_weather`) — atualizado ao contrato da 1.12.0 (cidade
  EXPLÍCITA → `weather_city`; genérico → `ha_weather` INTACTO).
- Endurecimento: teste da M3 era réplica inline do contrato (mutação
  sobreviveria); extraída a conversão real `_wmo_condition`
  (falsy-safe: `is not None`, nunca `or` — weather_code 0 é céu limpo).
- Suíte: **2075 passed, 16 skipped** (ambiente canônico .venv).

### Teste do teste — 4/4 mutações detectadas e revertidas bit-exata

- M1 rota de cidade desligada → **9 falhas**; M2 extração só com a
  última palavra → **8 falhas**; M3 falsy engole o 0 → **1 falha**;
  M4 degradação respondendo texto quebrado → 1ª rodada **SOBREVIVEU**
  (teste fraco) → endurecido com os 4 erros + contrato sem
  `temperature` → re-detectada (1 falha). Lição da casa repetida: teste
  fraco passa mutação — endurecer antes de declarar coberto.

### Bump MINOR 1.12.0 (action nova: catálogo 63 → 64, iot=5)

- `.env` OD_VERSION=1.12.0 · capabilities fallback · pubspec
  **1.12.0+2028** · `_APP_VERSION_CODE=2028` · site (2x) · CHANGELOG
  [1.12.0] · README_VERSAO §1.12.0. Zero sobra de "1.11.1" nas fontes.
- JAVA_HOME para o gradle: `~/jdk` (novo no ambiente; antes o build
  achava o java sozinho). flutter analyze **0 issues** · flutter test
  **114 passed, 2 skipped**. APKs publicados em site/ — versionName
  1.12.0 e versionCode 2028 confirmados DENTRO do binário (sem aapt2:
  manifest UTF-16 + resources.arsc). sha256 full `92e9b71b…`.

### Deploy e prova viva (~16:3x)

- Restart do od-core — PID **1136569**, NRestarts=0.
- Prova viva: (1) `/executa` weather_city(presidente venceslau) →
  **31.2°C, parcialmente nublado, sensação 32.9°C, umidade 51%, vento
  14.6 km/h** · city "Presidente Venceslau, São Paulo, Brasil" ·
  Open-Meteo · duration 1568ms; (2) /app/version {1.12.0, 2028,
  sha256 == binário}; (3) /capabilities 1.12.0 · 64 actions ·
  loop_fechado=true; (4) GET / → 45 endpoints.

### Publicação no GitHub (pedido do dono)

- Commit **`0206d7c`** `feat(iot): clima de cidade real via Open-Meteo —
  'temperatura em presidente venceslau' responde a CIDADE pedida
  (v1.12.0)` (14 arquivos, +445/−40) → push `813c71f..0206d7c master
  -> master`. Working tree limpo; APKs fora do repo (gitignore).

### Verificação geral pós-publicação (pedido do dono) — 4/4 verde

- Serviço: active (running), NRestarts=0, mem 126M.
- /health **9/9 up** (orchestrator, llm=gemma-local, audit, metrics,
  database 5 tabelas, homeassistant, mqtt, loops, perception — CPU 0% ·
  mem 89% · disco 30%).
- Contratos: /app/version 1.12.0/2028 com sha256 == site/ ·
  /capabilities 1.12.0/64/loop_fechado=true · GET / 45 endpoints ·
  journal "Action registered | action=weather_city | category=iot".
- Journal desde o restart: **0 Traceback · 0 ERROR/CRIT**.
- Guardas na suíte: test_version_policy + test_api + test_capabilities
  → **135 passed** (coerência .env/capabilities/pubspec/_APP_VERSION_CODE).

**Estado: CONCLUÍDO, PUBLICADO E NO AR — v1.12.0.** Pendências do dono:
instalar o APK 1.12.0+2028 no celular (auto-atualização, 2028 > 2027) e
provar "clima em presidente venceslau" pelo chat/app. Pendência do
sistema: nenhuma desta entrega.

## 12. v1.13.0 — Casa de limitações + canal de ideias: o sistema percebe o que não sabe (~16:4x–19:5x)

**Pedido do dono:** o sistema não sabia responder dólar/temperatura de
outra cidade e não PERCEBEU a própria limitação — a action só nasceu
porque o agente criou na mão, e ele NÃO quer isso. Além disso, o txt.txt
viraria canal de interação (ideias de melhoria), com entrada no painel
admin e paridade total no app (o app deve refletir o site).

**Decisões (via ask_user):** (1) separar em 2 arquivos — `txt.txt` fica
100% do dono (ideias); o sistema auto-registra limitações em
`limitacoes.txt`, com seção própria no painel; (2) zerar txt.txt com
snapshot em backups/; (3) app com paridade total: pedidos + ideias +
limitações (escrever/ler/limpar).

**Entregado:**
- `core/limitacoes.py` (NOVO): `registrar_limitacao(motivo, pergunta)`
  com teto 128 KB (poda por blocos `\n\n`), dedup 6h, append atômico,
  defesa TOTAL (nunca propaga exceção). **Bug real corrigido:** separador
  era 1 `\n` — leitura juntava entradas e o teto nunca podava.
- 3 hooks no orchestrator: fallback honesto esgotado (`_resolve_refusal`)
  e 2 caminhos de action degradada (stream + REST).
- 5 rotas admin: GET/PUT/DELETE `/admin/ideias` (txt.txt, 20 KB, escrita
  atômica tmp+rename) + GET/DELETE `/admin/limitacoes`; `do_PUT` novo no
  handler; guarda de rotas 45 → 50.
- Painel /admin: seções Ideias e Limitações. **Bug de escape pego pela
  guarda node --check:** `\n` em triple-quoted Python é escape real — JS
  precisava `\\n`.
- App: `od_api.dart` +8 métodos; dashboard com cards Pedido de
  desenvolvimento / Ideias / Limitações (paridade total com o site).
- Snapshot do txt.txt (dump roteador TP-Link) em
  `backups/txt-pre-canal-ideias-20260930.txt` (sha256 e3c7305c…) e zerado.

**Teste do teste — 4/4 mutações bit-exata:** M1 dedup `if False` → 2
falhas; M2 defesa `raise` → 1 falha — 1ª rodada SOBREVIVEU por falta de
teste; criado TestDefesaDoPipeline (monkeypatch `_append_atomico` com
OSError), mutação re-detectada; M3 teto `while False` → 1; M4 hook
desligado no orchestrator → 1.

**Evidência:** pytest tests/ → **2097 passed, 16 skipped** (+14
test_limitacoes, +10 test_api); flutter analyze **0 issues**; flutter test
**125 passed, 2 skipped** (+11 dart). APK 1.13.0+2029 publicado em site/
(OmegaDrakon.apk armv7 + arm64; manifest 1.13.0 UTF-16LE ✓, versionCode
2029 ✓). Guardas de versão: 143 passed.

**Prova viva no ar** (restart od-core): /app/version 1.13.0/2029 com
sha256 965a6f4a… == site/ · /capabilities 1.13.0 · 64 actions · /health
9/9 checks up · GET /admin/limitacoes com 13 entradas reais (o sistema
já se auto-registrou: action_degradada:network_hosts, weather_city,
fallback_honesto_esgotado) · PUT/GET/DELETE /admin/ideias ok no ar
(1ª tentativa com campo errado `texto` → 400 conteudo_obrigatorio;
contrato correto é `conteudo`) · journal 0 Traceback/ERROR. Reparo na
mão: entradas antigas gravadas antes do fix do separador estavam coladas
(1º bloco continha 5) — re-splitadas por `\n(?=## \[)`.

**Commit:** `0cd74a2` feat(api,admin): canal de ideias do dono + casa de
limitações — o sistema percebe o que não sabe (v1.13.0) — 15 arquivos,
+1478/−10, push 32aa7ee..0cd74a2.

**Estado: CONCLUÍDO, PUBLICADO E NO AR — v1.13.0.** Pendências do dono:
instalar o APK 1.13.0+2029 (auto-atualização, 2029 > 2028) e usar o canal
de ideias pelo painel /admin (ou pelo app). Pendência do sistema: nenhuma.

### §12.1 — Prova viva do dono: teste da limitação auto-registrada (~20:1x–20:3x)

**Pedido:** testar pergunta que o sistema não sabe (cotação do dólar) e
conferir o auto-registro no painel. Resultado em 3 atos:

1. **Cache podre interceptou a pergunta.** 'quanto está a cotação do
   dólar hoje?' → `route: cache` com alucinação antiga pré-1.11.1: 'US$
   5.20 por real' (inventada). Auditoria do `llm_cache` (Postgres, 57
   entradas): **18 podres** — mentiras (dólar, 'temperatura em PV é
   23°C', 'clima em campo grande', religião mais antiga=Budismo),
   **'Estou utilizando a OpenAI GPT-4'** (a mentira que a 1.11.1
   enterrou — renascia do cache!), estado efêmero (IP/portas/memória/
   arquivos) e **1 SEGREDO VAZADO: senha do MQTT em texto plano**
   ('OmegaDrakon2026'). **Podadas as 18** via POST /admin/cache/prune
   cirúrgico (removidas: 18; restaram 39 limpas). NOTA: a senha do MQTT
   aparece no cache antigo — ROTACIONAR a senha no broker/HA.
2. **Sem cache, o gemma alucinou de novo** ('US$ 5.20', `route: llm`,
   confiança, sem recusa). **GAP REAL descoberto:** os 3 hooks da
   1.13.0 pegam RECUSA esgotada e ACTION DEGRADADA — mentira confiante
   não é recusa, passa reto e nem registra limitação. E a mentira nova
   entrou no cache de novo (mesma chave) — precisa de nova poda ou
   guarda anti-mentira-tempo-real.
3. **O caminho desenhado FUNCIONA quando o pipeline falha de verdade:**
   'qual a temperatura em atlantis sul?' (cidade inexistente) →
   `route: fallback`, resposta honesta no ar, **limitações 13 → 15**
   (action_degradada:weather_city + fallback_honesto_esgotado
   registrados sozinhos, dedup 6h ativo).

**Conclusão:** a casa de limitações cumpre o contrato nos casos de falha
real; o caso dólar é uma NOVA classe (alucinação confiante de dado
tempo-sensível) — candidata a: (a) guardian anti-mentira para temas de
dado em tempo real (câmbio/temperatura/quote) que exija action ou recusa
honesta; (b) action de câmbio (mesma receita da weather_city, API
awesomeapi/open.erapi gratuita); (c) re-podar o cache quando a mentira
renascer. **Decisão pendente do dono.**

**Estado pós-teste: no ar (sem bump — nenhuma linha de código mudada;
só poda operacional de cache).** Pendências novas: rotacionar senha do
MQTT; decidir o rumo do gap (a)/(b)/(c).

## 13. v1.14.0 — Câmbio real: 'cotação do dólar' vem da FONTE, não da alucinação (~20:4x–21:1x)

**Decisão do dono:** "consegue concluir" → fechado o gap do §12.1 pela
receita (b) + espírito da (a): a pergunta de câmbio NUNCA chega ao gemma
— action intercepta antes do modelo com dado REAL (a casa nunca depende
da honestidade do modelo para dado que tem fonte).

**Entregado:**
- **Action `exchange_rate`** (catálogo 64 → 65, system=17): AwesomeAPI
  (economia.awesomeapi.com.br, gratuita, sem chave, urllib stdlib —
  mesma receita da weather_city); USD/EUR/GBP/ARS/JPY/CNY/CAD/AUD/CHF/
  BTC contra o real; bid/ask/variação %/faixa do dia; aliases da fala
  ('dólar', 'libra', 'iene', 'bitcoin'…) + sigla solta ('usd').
- **Detecção** (core/intents.py, ANTES do bloco de clima): moeda + sinal
  de cotação ('cotação', 'quanto está/custa/vale', 'valor', 'preço').
  'história do dólar' e 'quantos dólares cabem numa mala' NÃO pegam.
- **Formatter pt-BR**: `_brl()` 4 casas sem zeros à direita, SEM
  notação científica (o `.4g` viraria '3.501e+05' pro BTC); seta
  📈/📉; degradado → None → degradação guiada + Casa de Limitações.
- **3 bugs LATENTES corrigidos:** `log.warning` não existe no
  NickyLogger (só `.warn`) — ha_states, ha_state e weather_city usavam
  `.warning` no except de rede: o AttributeError esconderia o erro real
  exatamente numa queda de rede. Achado ao vivo: o novo código reproduziu
  o padrão e a suíte de mutação/settings expôs.

**Teste do teste — 4/4 mutações bit-exata:** M1 detecção desligada
(`if False and`) → 6 falhas; M2 formatter zumbi (return "zumbi" nos 2
None do bloco) → 1 falha (nota: os 2 primeiros replaces não aplicaram
por encoding — verificação bit-exata com diff obrigatória antes de
correr a suíte); M3 validação de entrada morta (`moeda or "usd"`) → 1
falha; M4 spec fora do catálogo → 6 falhas.

**Evidência:** pytest tests/ → **2113 passed, 16 skipped** (+6
TestExchangeRate; guardas 64 → 65 em 4 arquivos). APK 1.14.0+2030
publicado em site/ (manifest 1.14.0 UTF-16LE ✓, versionCode 2030 ✓,
sem resquício de 1.13.0; sha256 babe2169…/4577dc61…). Guardas de versão:
143 passed.

**Prova viva no ar** (restart od-core): /app/version 1.14.0/2030 ·
A PERGUNTA DO DONO: 'quanto está a cotação do dólar hoje?' →
**route: action_intent · fastpath:exchange_rate · R$ 5,1844 REAL**
(não mais 'US$ 5.20' inventado) · health 9/9 · capabilities 65 actions ·
journal 0 erros. Mentira renascida do dólar (regravada pelo LLM no §12.1)
deletada do Postgres antes do teste.

**Commit:** `744d9fc` feat(actions) — 14 arquivos, +389/−30, push
818a182..744d9fc. Nota: site/*.apk é ignorado por design (.gitignore —
APK não versiona, é publicado no site).

**Estado: CONCLUÍDO, PUBLICADO E NO AR — v1.14.0.** Pendências do dono:
instalar o APK 1.14.0+2030 (2030 > 2029) e perguntar o dólar no app/chato;
ROTACIONAR a senha do MQTT (§12.1). Pendência do sistema: nenhuma.

## 14. Rotação da senha do MQTT — vazamento do §12.1 fechado (~21:0x)

**Inventário (achado importante):** o Home Assistant NÃO usa MQTT — zero
integração mqtt no `core.config_entries` do container (docker, rede host;
chegou a abrir 127.0.0.1:1883 mas nunca se autenticou). A senha
'OmegaDrakon2026' era alucinação do LLM que NINGUÉM usava: o od-core
conectava ANÔNIMO (o launcher nem passava credenciais) e o broker aceitava
anônimo (`allow_anonymous` default, sem password_file). Rotação real =
ativar auth no broker + cabeamento de credenciais no od-core.

**Entregado:**
- Nova senha forte (secrets.token_urlsafe(24), 32 chars) — nunca exibida
  em log/chat; vive SÓ no `.env` (OD_MQTT_USERNAME=od-core /
  OD_MQTT_PASSWORD) e no hash do mosquitto.
- `runtime/launcher.py`: MQTTClient agora recebe OD_MQTT_USERNAME/
  OD_MQTT_PASSWORD do `.env` (documentado no header de OD_MQTT_*).
- Broker: `/etc/mosquitto/conf.d/od-auth.conf` (allow_anonymous false +
  password_file) + `/etc/mosquitto/passwd` — instalado pelo DONO via
  `rotacionar_mqtt.sh` (sudo manual; o agente não tem senha de sudo).
  Broker continua ONLY LOCAL (listener 127.0.0.1:1883).

**Validação (5 provas):** (1) anônimo REJEITADO ('broker recusou a
conexão: não autorizado'); (2) credencial nova ACEITA; (3) pub/sub fim a
fim ok (od/rot/teste); (4) senha VELHA 'OmegaDrakon2026' REJEITADA;
(5) od-core no ar: ponte conectada ('MQTT conectado | client_id=od-core'),
health 9/9 com mqtt up, e prova no ar: publish em od/in/prova-rotacao →
'Mensagem MQTT recebida | topic=od/in/prova-rotacao' no journal do
processo novo (pid 1173039, 0 erros — os WARNs de 21:02 eram do processo
velho na janela de transição). /app/version segue 1.14.0/2030.

**Higiene:** script rotacionar_mqtt.sh e artefatos de /tmp (senha plana,
passwd) apagados após o uso.

**Estado: ROTAÇÃO CONCLUÍDA E VALIDADA NO AR — sem bump (nenhuma linha
de produto mudou: launcher recebe env que antes não existia; docs/iniciar
registram).** Pendência do sistema: nenhuma. Pendência do dono: só o APK
1.14.0+2030 no celular.

## 15. Auditoria final do cache LLM — as 39 restantes (~21:2x)

**Varredura completa das 39 entradas** (post-rotação) contra padrões de
segredo/mentira/estado efêmero. Veredito:
- **4 PODRES removidas** (prune cirúrgico, removidas 4/4):
  - [14] resposta de limpeza com **vazamento de etiqueta interna**
    ('[INFO] Limpeza solicitada no dia…' embutido no texto) — o ban
    oficial só pega etiqueta no INÍCIO da resposta (`startswith`), esta
    tinha no meio;
  - [18] resposta quebrada '"Em construção..."' (estado de página, não
    conhecimento);
  - [29] **controle do lar** 'Acesse a luz do corredor!' — estado de
    conversa (o ban da v1.9.1 pega '💡 Confirmar:' e '✅ ', não a
    frase seca);
  - [36] **recusa falsa** 'Não posso compartilhar detalhes específicos
    sobre configurações do llama.cpp' — o llama.cpp é do PRÓPRIO dono e
    open-source; recusa-alucinação que renascia do cache.
- **35 OK mantidas:** saudações, identidade Nicky Virthy, factoides
  (Brasília), instruções genéricas — zero segredos (regex de
  senha/password/token/api_key/secret/IPs = 0 real; a única casada é o
  tutorial do HA com IP de EXEMPLO 192.168.0.100, placeholder de
  documentação) e zero mentiras conhecidas (GPT-4/US$ 5.20/23°C = 0).

**Achado estrutural para o futuro:** o `cache_failure_reason` tem 3
cegas — etiqueta no MEIO do texto, frase seca de controle do lar, e
recusas de "código proprietário". Candidata a v1.15.x: estender os
padrões (regex de etiqueta em qualquer posição + verbos imperativos do
lar + 'código proprietário'). **Decisão pendente do dono.**

**Estado: AUDITORIA CONCLUÍDA — cache 39 → 35, zero segredos, zero
mentiras conhecidas.** Pendência do sistema: nenhuma. Pendência do
dono: APK no celular; decidir se endurece os padrões de ban (v1.15.x).

## 16. v1.15.0 — Guardas do cache endurecidas: as 3 cegas fechadas (~21:3x–21:5x)

**Decisão do dono:** endurecer os padrões de ban (a pendência deixada na
§15). As 4 podas manuais da §15 NÃO deviam ter nascido no cache.

**Entregado (core/orchestrator.py, cache_failure_reason):**
- **Etiqueta em QUALQUER posição:** `_CACHE_ETIQUETA_EM_QUALQUER_POSICAO`
  (regex `\[(nicky])?(crit|warn|online|info)]`, case-insensitive) — antes
  só `startswith`; a resposta de limpeza com '[INFO] …' NO MEIO entrava.
- **Lar seco:** `_CACHE_BAN_LAR_SECOS` (imperativo
  acessa/acenda/apague/desligue/ligue ancorado no início) — 'Acesse a luz
  do corredor!' era estado de conversa cacheado (o ban v1.9.1 só pegava
  '💡 Confirmar:'/'✅ ' com emoji).
- **Recusa falsa de código:** 'código proprietário' + 'não posso
  compartilhar detalhes específicos' em `_CACHE_BAN_REFUSALS` — llama.cpp
  é open-source E do próprio dono.
- **Placeholder:** `_CACHE_BAN_ESTADO_PAGINA` ('Em construção…' âncora no
  início) — 'obra em construção avança' no MEIO segue cacheável (prova
  nos testes).

**Teste do teste — 4/4 mutações bit-exata:** M1 etiqueta-em-qualquer-
posição desligada → 3 falhas; M2 lar seco desligado → 4; M3 recusa
código proprietário removida → 1; M4 estado de página desligado → 2.

**Evidência:** pytest tests/ → **2125 passed, 16 skipped** (+12
TestCacheBansV115 com os casos REAIS do cache da §15). APK 1.15.0+2031
publicado (manifest ✓, code 2031 ✓, sem resquício de 1.14.0; sha256
161501ca…/6e646e75…). Guardas de versão verdes.

**Prova viva no ar** (restart od-core): /app/version 1.15.0/2031 ·
sha256 == site/ · health 9/9 (mqtt conectado) · **prune dry_run = 0
candidatas** (as classes novas não acham NADA — o cache já está são e
agora as classes podres NÃO entram mais) · journal 0 erros.

**Commit:** `2a3c173` feat(orchestrator) — 8 arquivos, +182/−5, push
93f073f..2a3c173. Nota: .env é ignorado por design (gitignore) — o bump
de versão nele não versiona (capacities fallback carrega a versão).

**Estado: CONCLUÍDO, PUBLICADO E NO AR — v1.15.0.** Pendência do
dono: APK 1.15.0+2031 no celular (ou pular direto para a próxima).
Pendência do sistema: nenhuma.

