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

## [1.2.0] — App Android 📱 (2026-09-08 · correção de versão em 2026-09-12)

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

### Pendente

- Ativar o push (credencial Firebase / `google-services.json`).

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
