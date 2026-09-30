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
