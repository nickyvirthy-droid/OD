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
