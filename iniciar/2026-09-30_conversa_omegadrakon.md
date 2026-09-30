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
