# OMEGA DRAKON — CHANGELOG

> **Finalidade:** registro das mudanças por versão, conforme item 4 da
> Definition of Done (`docs/REGRAS_DE_TRABALHO.md` §2) — toda capacidade
> entregue entra aqui com data, contagem de testes e fase/versão.
> **Regra:** a versão mais recente fica no topo.
> **Assinatura:** `OD // CORE`

> **Nota histórica (2026-09-12):** este arquivo foi criado em 2026-09-12 na
> auditoria de alinhamento de versão — até então o projeto não tinha
> `docs/CHANGELOG.md` e o histórico da série 0.x está em
> `docs/README_VERSAO.md` (§0.1.0 → §0.28.4). A partir daqui, toda entrega
> passa a registrar entrada neste CHANGELOG **além** do README de Versão.

---

## [1.2.0] — App Android 📱 (2026-09-08 · correções em 2026-09-12, 2026-09-14 e 2026-09-15)

### Adicionado

- **App Flutter** em `app/` — telas de chat, ações (catálogo de 57 actions
  via `GET /actions` + `POST /executa`), status (`/health` + manifesto de
  capacidades) e configuração; auth por `OD_API_KEY` no header `X-API-Key`.
- **Push FCM** — `firebase_core` + `firebase_messaging`, com documentação em
  `docs/FIREBASE_SETUP.md`.
- **Compatibilidade de API para o app** — `POST /message` aceita
  `{"message": ...}` além do payload do bot (`tests/test_api.py`).
- **APK release publicado na landing** — `site/OmegaDrakon.apk`
  (build via `app/build_apk.sh`, Flutter 3.47.2 / JDK 17 / Android SDK 36).

### Infraestrutura

- Fonte de verdade da versão do sistema: `OD_VERSION` no `.env`
  (`core/capabilities.py` agora resolve `os.environ` → `OD_VERSION` do `.env`
  → fallback congelado `1.2.0`, o que faz o valor chegar ao manifesto, à API
  e ao bot mesmo em entrypoints que não usam o carregador do launcher).
- `app/pubspec.yaml` alinhado para `1.2.0+3` (antes `1.0.0+1`, o que fazia o
  APK reportar `versionName 1.0.0` enquanto a landing anunciava v1.2.0).
- `docs/CHANGELOG.md` criado; seções v1.0.0/v1.1.0/v1.2.0 do
  `docs/README_VERSAO.md` reconstruídas retroativamente.

### Testes

- `app/`: **36 testes** Flutter (`flutter test`) + `flutter analyze` limpo
  (2026-09-12; 27 na entrega original).
- `tests/` (servidor): **1610 passed, 16 skipped** (suíte completa, auditoria
  de 2026-09-12); marco da v1.0.0 registrado com **1594 passed**.

### Corrigido (2026-09-12)

- **Tela Status quebrava com o manifesto real** — `status_screen.dart` fazia
  `_capabilities['system'] as Map<String, dynamic>?`, mas o servidor devolve
  `"system": "Omega Drakon"` (string), com `version`, `counts` e `runtime` no
  topo do manifesto. O cast estourava `_TypeError: type 'String' is not a
  subtype of type 'Map<String, dynamic>?'` e derrubava a seção "Sistema" da
  aba Status. A leitura agora usa `is` + fallback `'?'` (sem cast) e o card
  mostra versão, nº de modos de runtime, capacidades e actions.
- Publicação: commit **`e2f4960`** — _feat(app): publica o código do app v1.2.0
  e corrige a aba Status_ — em `origin/master` (`f42e5c5..e2f4960`). O commit
  levou junto o código do app que gerou o APK (push FCM, resiliência de rede,
  telas ligadas a `/actions` e `/executa`, projeto Android e testes), que
  nunca tinha sido commitado.

- **Contrato testado com payload real** —
  `app/test/fixtures/capabilities_manifest.json` (manifesto capturado do
  servidor em produção) + teste de regressão em `app/test/widget_test.dart`.
  O mock anterior usava um `system` aninhado que o servidor nunca devolveu —
  o teste passava enquanto a tela quebrava no celular.

### APK republicado (2026-09-12)

Dois builds no mesmo dia:

| Build | `versionName` / `versionCode` | sha256 (full) |
|---|---|---|
| 1º — alinhamento de versão | `1.2.0` / 1003·2003·4003 | `3b800c87…d978ff` |
| 2º — com a correção da tela Status | `1.2.0` / **1004·2004·4004** | `6d3c73a5…b616ade` |

- Publicados em `site/OmegaDrakon.apk` (51.9 MB) e
  `site/OmegaDrakon-arm64.apk` (18.5 MB), com sha256 conferido origem↔site
  e download servido pela API (`GET /site/OmegaDrakon.apk`) verificado.
- O build number subiu para `+4` de propósito: com o mesmo `versionCode`
  (1003) o Android recusaria instalar por cima do APK anterior.
- APKs antigos preservados: `backups/apk-v1.0.0/` e
  `backups/apk-v1.2.0-1003/`.
- `OD_VERSION=1.2.0` gravado no `.env`.

### Publicação

- Commit **`ffeab4f`** — _fix(version): alinha OD_VERSION, pubspec e docs na
  v1.2.0_ — publicado em `origin/master` (`3768bcb..ffeab4f`).
- Binários fora do repo por decisão desta entrega: `site/*.apk`,
  `backups/apk-*/` e `.od_repair_backups/` no `.gitignore`.

### Adicionado — push FCM de ponta a ponta (2026-09-12)

Fecha a pendência do push da v1.2.0: até aqui o app só **recebia** (console),
agora o **OD também envia** para o aparelho.

- **`core/push.py`** — `DeviceRegistry` (tokens em `data/push_devices.json`,
  upsert por token, escrita atômica, tolerante a arquivo corrompido),
  `FcmSender` (FCM HTTP v1: OAuth2 da service account + `messages:send`) e
  `PushService` (fachada `notify`/`sink`/`status`, tokens mascarados em
  log/API). Tokens que o FCM declara mortos (`UNREGISTERED`, `INVALID_ARGUMENT`,
  `SENDER_ID_MISMATCH`) saem do registro sozinhos.
- **API** — `POST /push/register`, `POST /push/unregister`, `POST /push/test` e
  `GET /push/devices` (todos com `X-API-Key`); tabela de rotas 22 → **26**.
- **Runtime** — `build_push()` no launcher; a API e o `ProactiveNotifier`
  recebem o serviço, então os alertas proativos (LLM offline, disco, restart)
  também saem como notificação no celular.
- **App** — `OdApi.registerPushToken`/`unregisterPushToken`,
  `PushService.attach(api)` (registra o token no boot, ao salvar as
  Configurações e a cada rotação de token) e `main.dart` ligando os dois.
- **Dependência nova:** `google-auth` (OAuth2/JWT RS256 da service account) —
  justificativa no `requirements.txt`; o HTTP continua em urllib do stdlib
  (adaptador `UrllibRequest`), então não entrou cliente HTTP novo.
- **Dormente por padrão:** sem a credencial (`OD_FCM_CREDENTIALS` ou
  `config/firebase-service-account.json`) o serviço sobe desligado e
  `/push/test` responde **503** — o registro de tokens continua funcionando.
  Ver `docs/FIREBASE_SETUP.md` (passos 6 e 7).

### Validado no aparelho (2026-09-12) ✅

Redmi Note 14 (`redmi-note-14-1`, Tailscale `100.80.224.73`) com o APK
`1.2.0+4`: **Chat, Ações e Status funcionando sem erro**. Evidência do journal
do `od-core` (processo novo, pós-restart de 11:14:52):

```
11:25:58  Message processed | route=cache | user=app | profile=guardian
          llm=- | latency_ms=32.325          → chat do app respondido
11:27:58  Security decision | action=cpu_info | allowed=True | session_id=api:app
          Action executed    | action=cpu_info | role=admin | duration_ms=5.608
                                            → action real executada pelo app
sem "[NICKY][WARN] API erro" depois do restart → zero 4xx vindos do app
```

A tela Status e a instalação do APK não deixam rastro no servidor (GETs não são
registrados e `/site` não tem log de acesso) — essas partes se apoiam no relato
do usuário.

### Corrigido (2026-09-14) — achados do journal do `od-core`

Dois achados levantados no journal, cada um com teste de regressão novo:

- **`face.presence` ia para dead letter a cada evento** —
  `runtime/launcher.py::_run_vision_forever` registrava o handler como
  `on_change(data)` e chamava `data.get("confirmed")`, mas o Event Bus entrega
  o **`Event`** (o payload vive em `event.data`, como no resto do projeto) →
  `AttributeError: 'Event' object has no attribute 'get'` em todas as 3
  tentativas, seguido de _dead letter_ (09-14: 09:29:55, 09:31:17, 10:27:10 e
  10:27:39). O handler passou a ler `event.data` com guarda de tipo — o bus
  grava apenas o **nome** da exceção no journal, por isso o motivo só apareceu
  na leitura do código.
  - Regressão: `tests/test_launcher_vision.py` (novo, **4 testes**, bus real +
    detector fake) — com o handler anterior restaurado, os 4 falham
    reproduzindo as linhas exatas do journal.
  - Prova em produção: depois do restart de 13:24:40, o `face.presence` real
    das 13:25:09 (`Event published | topic=face.presence | subscribers=1`)
    **não** gerou nenhum `Handler error` nem `dead letter`.
- **Snapshots do SelfRepair cresciam sem limite** — `core/self_repair.py`
  criava um `.bak` por tentativa mesmo sem mudança no arquivo: um arquivo
  doente no escopo do `RecoveryLoop` (ciclo de 5 min) rendeu **557 snapshots,
  8,8 MB** em ~2 dias. Agora `_take_snapshot` faz **dedup** (bytes idênticos
  reutilizam o snapshot existente) e **retenção** por arquivo
  (`max_snapshots_per_file`, default `5`) via `_prune_snapshots`;
  `_next_snapshot_path` evita a colisão de nome dentro do mesmo segundo (antes
  o snapshot anterior era sobrescrito).
  - Regressão: `TestSnapshotDedupERetencao` em `tests/test_self_repair.py`
    (**4 testes**) — com o comportamento anterior restaurado, os 4 falham.
  - Limpeza retroativa: dos 557 snapshots (3 conteúdos distintos), 552 saíram
    e os 5 mais novos ficaram → `8,8 MB → 116 KB`.
- `od-core` reiniciado às 13:24:40 para subir as correções; `/health` ok (8
  checks) e o `RecoveryLoop` rodando sem detecções.

### Ativado (2026-09-14) — push FCM em produção 🔔

A service account chegou e o envio saiu do modo dormente **sem nenhuma mudança
de código** (o que faltava era só a credencial):

- Credencial instalada em `config/firebase-service-account.json`
  (`chmod 600`), coberta pelo `.gitignore` — nada de credencial no repositório.
- **Validação antes do restart**: o `FcmSender` do próprio `core/push.py`
  (`available=True`, `project_id=nicky-e4f99`) emitiu um **access token OAuth2
  real** — a chave é válida e tem permissão no FCM (nenhuma mensagem enviada
  nessa etapa).
- `od-core` reiniciado às 14:06:53: `Push FCM inicializado | enabled=True |
  motivo= | credencial=config/firebase-service-account.json | dispositivos=1`
  (todos os restarts desde 13/09 registravam `enabled=False |
  credencial_ausente`).
- **Teste de ponta a ponta**: `POST /push/test` → **HTTP 200**
  `{ok:true, sent:1, failed:0, skipped:0, errors:[]}`; journal
  `Push enviado | enviados=1 | falhas=0 | titulo=OmegaDrakon`; e o aparelho
  registrado (Redmi Note 14) foi para `sent=1, failed=0` no
  `GET /push/devices`. O token foi registrado pelo **próprio app**, sem ação
  manual no servidor.
- Nenhuma variável nova no `.env`: sem `OD_PUSH_ENABLED` o default é "ligado
  se houver credencial" (`PushService.enabled` cai em `sender.available`).

> ⚠️ **Achado de segurança desta rodada:** um dos dumps de tela guardados na
> pasta local `000/` (fora do git) contém a **chave legada do servidor FCM**
> (API legada, descontinuada em 2024) e um par de chaves de push da Web. A
> chave legada **não** é usada pelo OD (o envio é HTTP v1 com service account) e
> deve ser excluída no console — *Cloud Messaging → chave do servidor*.

### Corrigido (2026-09-15) — resiliência do core

- **Timeout de rede do Telegram derrubava o core.** O `HTTPTransport` só
  envolvia `HTTPError`/`URLError`; um `TimeoutError` estourando na **leitura da
  resposta** não passa pelo `URLError` e escapava do `bot.run()` (que tolera
  apenas `TransportError`) até o `asyncio.gather` do launcher, matando o
  **processo inteiro**: 89 quedas e 89 restarts do `od-core` entre 2026-09-13 e
  2026-09-15, uma delas num **crash loop de 4h30** (85 quedas a cada 2–3 min).
  As três chamadas de rede do transporte passaram a capturar `OSError` (cobre
  `TimeoutError`, `ConnectionResetError` e `ssl.SSLError`). Commit **`b215d07`**
  (regressão em `tests/test_telegram.py`, 3 testes).
- **Loops do core sem rede de segurança.** Os laços de **MQTT**, **presença** e
  **visão** chamavam `poll_once()`/`tick()` sem proteção, e o `HAClient` deixava
  `TimeoutError` de leitura escapar cru (mesma classe do bug acima). Cada loop
  ganhou o try/except do "ciclo nunca morre" — a disciplina que o
  `RecoveryLoop` já tinha — e o `launcher._all` passou a **supervisionar** cada
  loop (`_supervise`: contém a exceção, registra e reinicia com espera em vez de
  derrubar o processo; a API entra com `restart=False`, porque recriar o
  servidor conflita na porta 8000). Commit **`0c5b9d8`**;
  `tests/test_launcher_supervisor.py` é novo.

### Adicionado (2026-09-15) — supervisão dos loops visível 🔍

- **`core/supervision.py`** (novo) — registro thread-safe das quedas e
  reinícios de cada loop do modo `all` (`failures`, `restarts`, `last_kind`,
  `last_error`, `age_s`). "Degradado" = queda dentro da **janela de 300 s**;
  passada a janela o estado volta a ok sozinho, sem intervenção. O objetivo é
  direto: a supervisão da rodada anterior continha a queda, mas ela ficava
  silenciosa — e foi esse silêncio que deixou as 89 quedas passarem até a
  leitura do journal.
- **Check `loops` no `/health`** — não-crítico (`critical=False`): loop
  reiniciado **degrada** o agregado em vez de derrubá-lo, com o nome do loop e
  o erro no detalhe.
- **Alerta pelo notifier** — nova sonda `_check_loops` nas sondas padrão
  (`integrations/notifier.py`): alerta **WARN** por loop reiniciado, escalando
  para **CRIT** com 3+ reinícios (laço de falha) e limpando o problema quando o
  loop estabiliza; o anti-spam continua o do notifier (1 alerta/hora por loop).
  Commit **`fc2abe0`**.
- **`GET /supervision`** (novo endpoint com `X-API-Key`) — expõe o mesmo estado
  para o app: `{ok, status, window_s, degraded[], restarts, loops[], ts}`.
  `ok=false` + `status=degraded` significam "loop caiu dentro da janela" (o core
  segue de pé, HTTP 200); passada a janela volta a ok. A raiz (`GET /`) passou a
  reportar **27 endpoints**.
- **Testes:** **1686 passed, 16 skipped** (1683 na observabilidade + 3 do
  endpoint novo), com teste do teste nas duas rodadas — 15 de 18 testes-alvo
  falharam com as mutações da observabilidade e 2 falharam com as mutações da
  rota (flag de auth e sinal de degradação).

### App republicado (2026-09-15) — supervisão na aba Status 📱

- **Aba Status** ganhou o card **"Supervisão dos loops"**: mostra se há loop
  reiniciado (`degraded`), a janela considerada, o total de reinícios e, por
  loop, o nome, quantos reinícios e o tipo do último erro (`TimeoutError`…).
  Até aqui o app só sabia de um loop caído pelo Telegram/push.
- **`OdApi.getSupervision()`** consome o `GET /supervision`; `ok=false` +
  `status=degraded` são tratados como **resposta válida** (HTTP 200) — o core
  está de pé, e a tela mostra o loop caído em vez de erro de rede.
- **Best-effort:** falha na rota não derruba a aba — o card avisa "Supervisão
  dos loops indisponível" e o resto da tela continua (a lição do bug do
  `system` aninhado no APK 1.2.0).
- **APK 1.2.0+6** (versionCode 1006/2006/4006) publicado em
  `site/OmegaDrakon.apk` (51.935.427 B) e `site/OmegaDrakon-arm64.apk`
  (18.518.638 B), com sha256 origem == site (`b325ad23…` full · `f3f86059…`
  arm64); o build anterior (**1.2.0+5**) foi preservado em
  `backups/apk-v1.2.0-1005/`. O `versionCode` subiu de propósito: com o mesmo
  código o Android recusa instalar por cima do anterior.
- **Testes do app:** `flutter analyze` sem issues · `flutter test` →
  **48 passed** (42 na entrega anterior; +6: 3 do cliente de API e 3 de
  widget). Teste do teste: tratando `degraded` como erro e omitindo a chamada
  na `_refresh()`, **4 testes falham**.
- **Verificação do binário:** a string `supervision` aparece **2x** no APK novo
  e **0x** no anterior, e `Nenhum loop reiniciado` **1x** contra **0x** —
  diferencial que confirma que o código novo está no binário (a string de
  controle `OmegaDrakon Online` aparece 1x nos dois). A API serviu o arquivo
  novo em `GET /site/OmegaDrakon.apk` (HTTP 200, mesmo tamanho e sha256).

### Pendente

- ~~Gerar a **service account** no console do Firebase e gravá-la em
  `config/firebase-service-account.json` para o envio sair do modo dormente
  (o app já está registrando o token).~~ **Feito em 2026-09-14** — ver
  *Ativado (2026-09-14)* acima.

---

## [1.1.0] — Acesso Externo Seguro 🔐 (2026-09-07)

### Adicionado

- **Tailscale (VPN mesh WireGuard)** — IP `100.77.67.53`, tailnet
  `nickyvirthy`, interface `tailscale0`, versão 1.102.2; API acessível de fora
  da LAN em `http://100.77.67.53:8000` com `X-API-Key`.
- **Documentação** — `docs/TAILSCALE_SETUP.md`.

### Infraestrutura

- Segurança em camadas: VPN + `X-API-Key` + UFW (22/8000/8123) — **zero portas
  abertas no roteador**.
- Journal sem exposição de segredos (verificado no roadmap).

### Testes

- Sem suíte nova (item de infraestrutura/rede); critérios de aceite validados
  contra o servidor nicky-server — ver `docs/README_VERSAO.md` §[1.1.0].

---

## [1.0.0] — Fundação v1 (release-grade) 🏛️ (2026-09-07)

### Adicionado

- **7º perfil `nexus`** (Conector) em `agents/profiles.py` — a Plêiade fica
  completa (7 entidades), com detecção automática por domínio
  (conexão/integração/plêiade).
- **Health checks externos** — Home Assistant e MQTT/Mosquitto no Health
  Monitor; `/health` passa a expor 7 checks (5 internos + HA + MQTT).
- **Control Bridge no repositório** — `tests/test_control_bridge.py`
  (allowlist, tokens, escape de path, legados §7.1, auditoria, execute) e o
  unit systemd `runtime/systemd/od-control-bridge.service`.

### Infraestrutura

- **CI no GitHub Actions** — `.github/workflows/ci.yml` (Python 3.12, push +
  PR): `compileall` + `pytest -q` com gate de cobertura ≥ 90% (`.coveragerc`,
  `runtime/launcher.py` omitido).
- **Migração JSON → PostgreSQL** — `memory/adapters.py` (schemas +
  `migrate_all()` idempotente); `history.py`, `cache.py`, `quick_responses.py`
  e `vector.py` ganharam `database=None`; fallback JSON mantido.
- **Systemd `od-core`** — `runtime/systemd/od-core.service` (NoNewPrivileges,
  ProtectSystem=strict, ProtectKernel*, MemoryMax=6G, CPUQuota=200%,
  ReadWritePaths) + `install-user.sh` com verificação de linger.
- **SWAP 8 GB** (`/swapfile`) + `vm.swappiness=10` via
  `runtime/setup/setup-server.sh`.
- **UFW ativo** — 22 (SSH), 8000 (OD API), 8123 (HA) permitidos; resto
  bloqueado.
- **Variáveis de ambiente ausentes** — 6 configuradas no `.env`
  (`OD_PRESENCE_ENABLED`, `OD_PRESENCE_POLL_S`, `OD_RECOVERY_INTERVAL_S`,
  `OD_SELF_REPAIR_ENABLED`, `OD_NOTIFIER_ENABLED`).
- **Disco `sdb1` montado** em `/home/alex/dados` (801 GB livres) + automount
  via `/etc/fstab`.

### Testes

- Suíte local: **1594 passed**; cobertura **95%** (gate ≥ 90% no CI).
- Novos: 46 testes da migração JSON→DB; 29 de `tests/test_systemd_units.py`;
  26 de `tests/test_control_bridge.py`.

---

## Série 0.x — congelada em [0.28.1] ❄️ (2026-09-04)

A série 0.x está **congelada**: a v0.28.1 é o marco estável final (PostgreSQL
nativo no ar, loop de auto-recuperação fechado, fast path de intenções,
57 actions, 1453 testes verdes, tag git `v0.28.1` no commit `ba2f7c8`).
O histórico detalhado de cada versão 0.1.0–0.28.4 está em
`docs/README_VERSAO.md` e nas Fases 1–7 de `docs/ROADMAP_ABSORCAO.md`
(37/37 capacidades absorvidas).

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/CHANGELOG.md
Descrição: Registro de mudanças por versão (item 4 da Definition of Done).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```
