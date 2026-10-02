# Conversa OmegaDrakon — 2026-10-02

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
**"leia iniciar"** (~16:2x) e, em seguida, **"1 ja foi feito. vamos aos
proximos"**. Ambiente canônico de testes: `.venv/bin/python` SEM
`OD_TEST_POSTGRES_DSN`.

---

## 1. Retomada e push do checkpoint (~16:2x)

- Leitura da ordem da casa: `iniciar/README.md` → `RULES.md` →
  `session.json` → transcrição de 01/10 (§1–§11).
- Estado herdado: **v1.17.4 NO AR**, PID 10933, `NRestarts=0` desde
  01/10 23:48:57.
- Verificação viva: `/app/version {1.17.4, code 2037, size 53972629,
  sha256 6a10064b…}` == `site/OmegaDrakon.apk`; `/health` 9/9 (401 sem
  chave = portão por design); `/supervision` restarts 0; WS 8001 → 426;
  journal de hoje **0 erros**.
- O commit de registro da retomada (`3ebba79`) estava **1 à frente** de
  `origin/master` → **push** (regra 7.1): `a8c659b..3ebba79`; registro
  do push commitado e publicado (`cc91c1a`).

## 2. Escolha do dono: infra primeiro (cobertura + CI)

Os pontos pendentes herdados eram: (1) APK no celular — **já feito pelo
dono**; (2) Google Drive/Agenda/Gmail (precisa de OAuth do dono); (3) 2
achados de infra de 30/09; (4) gemma quando o hardware crescer. O dono
escolheu **infra primeiro** (`ask_user`).

## 3. Achado 1 — CI quebrava em checkout limpo (§infra_ci_cobertura_2026_10_02)

- `tests/test_version_policy.py::test_env_e_capabilities_na_mesma_versao`
  lia o `.env` da raiz **sem guarda de existência**. O `.env` é
  **gitignored** → em checkout limpo (GitHub) o arquivo não existe e a
  suíte morria com `FileNotFoundError` **antes** de rodar qualquer teste.
- Correção: `_env_version()` devolve `None` quando o `.env` não existe e
  o teste **pula com motivo**. Sem `.env` não há estado local a validar;
  a verdade passa a ser o **fallback congelado**, coberto por
  `test_fallback_congelado_e_a_versao_vigente` (que continua rodando no
  CI).
- Prova à mão: com `.env` real → `1.17.4`; com `ROOT` apontando para
  diretório sem `.env` → `None`.

## 4. Achado 2 — gate de cobertura ≥ 90% vermelho

- Medição real: **89,33%** (12592 stmts, 1343 perdidas) — reproduz o
  achado de 30/09. Faltavam ~84 statements para o gate
  (`--cov-fail-under=90`).
- Foram escritos **26 testes** focados em **ramos reais sem teste** (não
  em inflar número), nos módulos com pior razão:
  - `tests/test_telegram.py` — `TestHandlersBorda`: `/executa`
    (`action_list` com truncamento, gate por nível 1/2 sem admin,
    statuses `denied`/`invalid`/`error`/desconhecido, parsing de params +
    objeto grande), `/entrar`, `/sair`, `/historico`, `/cache`, `/gerar`,
    `_classificar_risco`, `_parse_param_value`.
  - `tests/test_migrate_history_owner.py` — `TestMainCli`: `main()` com
    nada a migrar, dry-run e `--apply`; a Database é injetada e o
    snapshot é **redirecionado para `tmp_path`** (nenhum teste toca
    `backups/`).
  - `tests/test_audio.py` — `_convert_to_wav` (sucesso, falha por
    returncode, timeout), transcrição vazia e WAV inválido no pipeline.
- Resultado do gate: **90,17%** (12592 stmts, 1238 perdidas) —
  `pytest-cov`: *"Required test coverage of 90% reached"*, exit 0.
- Suíte completa: **2175 passed, 16 skipped** (+26); `compileall` limpo.

## 5. Registro e documentação

- `docs/CHANGELOG.md`: seção datada **"Infra — CI verde em checkout
  limpo + gate de cobertura ≥ 90% (2026-10-02, sem bump)"**.
- `docs/VERSIONAMENTO.md` §6: **"Guarda de checkout limpo (2026-10-02)"**.
- **Sem bump**: é infraestrutura de teste/CI, sem mudança de
  comportamento em produção — mesmo precedente do orquestrador de CLIs
  (2026-09-30).

## 6. Achado extra (não tocado)

- Ramo **morto** em `integrations/telegram/commands.py:169`:
  `if name == "auto" and name not in PROFILES` é **inalcançável** porque
  `PROFILES` **inclui** `"auto"`. Na prática `/perfil auto` define o
  perfil `auto` (comportamento válido) — por isso não foi alterado.

## 7. Estado final (ponto de infra)

- CI verde em checkout limpo e **gate de cobertura ≥ 90%** (90,17%).
- Commit + push do lote (regra 7.1).

## 8. Integração Google (Drive/Agenda/Gmail) — arquitetura OAuth (leitura)

Pedido do dono (~16:5x): **"Preparar a arquitetura OAuth do Google
Drive/Agenda/Gmail (sem credencial ainda)"**. Decisões (ask_user): **stdlib
puro** (zero deps novas), **leitura primeiro**, **dono + user (leitura)**.

### 8.1 Pacote novo `integrations/google/`

- `transport.py` — `UrllibTransport` (stdlib) + `GoogleError` + `checked`.
- `models.py` — `GoogleCredentials` (aceita o JSON do Cloud Console),
  `GoogleToken` (access+refresh+expiração) e os escopos de leitura.
- `oauth.py` — URL de consentimento (`access_type=offline`,
  `prompt=consent`), `extract_code` (URL colada ou código), `exchange_code`
  e `refresh_access_token`.
- `client.py` — `GoogleClient` (Bearer, renovação automática, persistência
  em `data/google_token.json` 0600) e `load_token`/`save_token`.
- `drive.py` / `calendar.py` / `gmail.py` — serviços de LEITURA.

Sem token salvo, `ensure_access_token` levanta `GoogleError` legível — nada
estoura no pipeline.

### 8.2 Ligação no sistema

- 6 actions novas (categoria `google`, catálogo **65 → 71**):
  `google_drive_list`, `google_drive_read`, `google_calendar_events`,
  `google_gmail_list`, `google_gmail_read`, `google_gmail_labels`. Degradam
  com `ok=False` sem credencial (mesmo padrão do HA).
- Launcher injeta o cliente (`config/google_credentials.json`).
- `permissions.py`: admin pleno; `user` com as 6 de leitura.
- Intents determinísticas no chat ("meus e-mails", "minha agenda", "meus
  arquivos no google drive") + formatters HONESTOS quando não configurado.
- Prompt por perfil atualizado: o Google (leitura) existe quando
  configurado; escrita/lembretes/redes sociais continuam inexistentes.
- `capabilities`: `google-workspace` (PARTIAL).

### 8.3 Autorização e docs

- `runtime/google_auth.py`: CLI headless (imprime a URL → o dono cola a URL
  de retorno) + `--check`/`--url`/`--code`.
- `config/google_credentials.example.json` e `docs/GOOGLE.md` (passo a passo
  do Cloud Console, escopos, troubleshooting).

### 8.4 Validação

- `tests/test_google.py` (+54 testes, HTTP 100% mockado).
- Suíte **2229 passed, 16 skipped**; gate de cobertura **90,24%**.
- Launcher smoke: registry 71 actions, HA segue ligado; `google_auth --check`
  reporta credencial ausente sem crash.

### 8.5 Achado e pendência

- A guarda `test_nenhuma_referencia_a_versao_futura_no_codigo` (v1.17.4)
  pegou os rótulos `v1.18.0` (versão não lançada) → removidos; o bump MINOR
  fica para o deploy com credencial.
- **Pendência do dono:** criar o OAuth client no Google Cloud Console,
  salvar `config/google_credentials.json` e rodar `runtime/google_auth.py`.
  Depois: deploy + bump + prova viva com dados reais. Escrita = 2º lote.
- Pendências restantes: alternativa futura do **gemma** (hardware).

---

Interface Viva: Nicky Virthy · Arquiteto: Alex Projeti
Assinatura: `OD // CORE`
