# Conversa OmegaDrakon — 2026-09-28

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
"leia iniciar" (~18:1x). Ambiente canônico de testes: `.venv/bin/python`
SEM `OD_TEST_POSTGRES_DSN`.

---

## 1. Retomada e resgate do lote órfão v1.7.1 (~18:1x)

Pedido: "leia iniciar".

### Diagnóstico

- O fechamento do dia 27/09 registrou "git limpo" em `168c7b5`, mas o
  working tree tinha **10 arquivos modificados** (+257/−31) com
  comentários datados de 27/09 que NÃO estavam na transcrição nem no
  session.json — a sessão anterior morreu no meio de um lote novo:
  - **Action nova `cpu_temp`** (catálogo 58 → 59): temperatura real do
    servidor via `/sys/class/thermal` + fallback `/sys/class/hwmon`
    (stdlib, sem root); sensor mais quente + zonas.
  - **`detect_external_intent`** (core/intents.py): clima/temperatura de
    CIDADE é mundo externo — NÃO é infraestrutura. Caso real do dono:
    "temperatuda em presidente venceslau sp" recebia 🔒 (a vedação de
    infra capturava a palavra 'temperatura'). "temperatura do servidor"
    segue para a action real (dado da máquina).
  - **Papel user ganha `cpu_temp`** em permissions.py (leitura não
    prejudica o sistema; IP/portas seguem vedados).
  - **Anti-recusa endurecido** (orchestrator): etiqueta `[NICKY][...]`
    detectada em QUALQUER posição (o gemma entregava '[NICKY][WARN] Não
    posso fornecer informações sobre o clima...' e o startswith deixava
    passar) + 7 padrões novos de recusa; reforço do retry cita "mundo
    externo = conversa livre".
  - **personality.py**: limites do user agora vedam APENAS o que pode
    PREJUDICAR O SISTEMA (IPs, portas, paths, credenciais, segredos);
    o resto é conversa livre.
  - Testes: +8 em test_resposta_transparente.py e ajustes de contagem
    (58 → 59) em 4 arquivos.
- O comentário do teste citava "v1.7.2" — versão errada (não existia
  1.7.1); corrigido no commit.

### Validação em sandbox (regra 13, passo 1)

- Suíte completa: **1974 passed, 16 skipped** (+7 sobre a 1.7.0).
- App: flutter analyze 0 issues; flutter test **96 passed, 2 skipped**.

### Bump 1.7.1 (PATCH — precedente 1.6.1) + versionCode 2018

- Política: correção com capacidade nova de leitura = PATCH (a intenção
  nova é caminho para dado existente; nenhuma API nova). O app não muda
  de conteúdo, mas o versionCode sobe para **2018** (> 2017) para
  manter a linhagem monotônica da auto-atualização.
- Checklist: `.env` OD_VERSION=1.7.1 (via sed — arquivo bloqueado para
  as ferramentas de edição, é gitignored mesmo) · capabilities fallback
  1.7.1 · pubspec 1.7.1+2018 · site (2×) · CHANGELOG [1.7.1] ·
  README_VERSAO §1.7.1.
- Guardas de coerência (test_version_policy) verdes no lote.
- APKs rebuildados e publicados em site/: aapt2 versionCode='2018'
  versionName='1.7.1' nos DOIS; sha256 full 5c6c05fb… · arm64
  4f41ff45….

### Commit e publicação (regra 7.1)

`b0961aa` fix(core,intents,actions): temperatura do servidor como dado
real + clima de cidade sem bloqueio indevido (v1.7.1) — 15 arquivos
+327/−35. Nota: `.env` é gitignored (segredos); o fallback rastreado é
o `core/capabilities.py`.

## 2. Deploy e prova viva

Restart (autorização permanente de 09-23): PID 861284 → após o fix,
**PID 861815, NRestarts=0** (18:4x).

### Bug pego pela prova viva: /app/version anunciava o APK errado

- 1º restart: `/app/version` devolvia `version_code: 2017` com o
  sha256 do binário **2018** publicado — o lote reversionou o pubspec
  mas ninguém atualizou `_APP_VERSION_CODE` (server.py:57). A
  auto-atualização nunca dispararia (2018 > 2017 nunca anunciado).
- Correção: `_APP_VERSION_CODE = 2018` + commit separado `4384e5b`
  (fix(api)) — test_api.py 106 passed; 2º restart.

### Prova viva 6/6 (pós-fix)

1. `/app/version` público → 200 `{version 1.7.1, version_code 2018,
   sha256 5c6c05fb…}` — sha256 anunciado == binário de site/.
2. `/capabilities` com chave → 1.7.1, 59 actions.
3. **"qual a temperatura do servidor"** (POST /message, admin) →
   `route=action_intent · llm_used=fastpath:cpu_temp` → 🌡️ 57.0°C
   (pch_skylake) + zonas acpitz 27.8/29.8°C e x86_pkg_temp 53.0°C —
   dado REAL, ZERO LLM.
4. `/health` com chave → ok=true, status up.
5. WS :8001 → 426 (nosso WS no ar).
6. Journal pós-deploy: 0 Traceback/ERROR/CRIT · `/supervision` up,
   restarts 0, degraded [].

HEAD `4384e5b` == origin/master; árvore limpa (só o snapshot de
rollback `backups/cache-entrada-pre-guarda-20260927.json` untracked,
da poda cirúrgica registrada em 27/09).

## Estado final

- **CONCLUÍDO E NO AR** — v1.7.1 implantada, provada e publicada.
- O app 1.7.0+2017 do celular deve receber o 1.7.1+2018 pela
  auto-atualização (versionCode maior; conteúdo do app é o mesmo).
- Nota para as próximas versões: quando o app reversionar, o checklist
  ganha o item `_APP_VERSION_CODE` (server.py) — hoje a guarda de
  coerência cobre .env/capabilities/pubspec/site/CHANGELOG, mas NÃO a
  constante; o bug de hoje veio dessa lacuna (pegos pela prova viva).

