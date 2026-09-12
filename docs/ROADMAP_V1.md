# OMEGA DRAKON — ROADMAP v1.x 🐉

> **Status:** Em execução (v1.2.0) · **Data:** 2026-09-04 (atualizado 2026-09-08)
> **Base:** série 0.x congelada na v0.28.1 (tag `v0.28.1`) — esta é a
> **primeira entrega da série v1** (v1.0.0 em diante).
> **Progresso v1.0.0:** itens **1.1** a **1.10** entregues — **v1.0.0 COMPLETA!**
> **Progresso v1.1.0:** Tailscale (item 2.1) **ENTREGUE** (2026-09-07) —
> **v1.1.0 COMPLETA!**
> **Progresso v1.2.0:** app Flutter (chat/actions/status/config) + testes
> (37 passed) + push FCM implementados; **APK release `1.2.0+4` publicado na
> landing** (`site/OmegaDrakon.apk`). **Validado no Redmi Note 14 via Tailscale
> em 2026-09-12** — chat, ações e status sem erro. Pendente: ativar o push
> (credencial Firebase).
> **Assinatura:** `OD // CORE`

---

## 0. A Plêiade Completa — 7 Entidades (lacuna resolvida na v1.0.0)

O legado Nexus define em `~/nexus/config/pleiade.yaml` as **7 entidades da
Plêiade**. O OmegaDrakon absorveu **6 perfis** na série 0.x — o **7º**, o
próprio **Nexus**, foi implementado na v1.0.0 (item 1.3).

| # | Entidade | Nome | Papel (pleiade.yaml) | No OD? |
|---|---|---|---|---|
| 1 | `nexus` | **Nexus** | **Conector e Sétima Entidade. O equilíbrio que une a plêiade** | ✅ `agents/profiles.py` (v1.0.0) |
| 2 | `guardian` | Nicky Virthy | Execução técnica e soberania do servidor | ✅ `agents/profiles.py` |
| 3 | `regulus` | Conselheiro | Equilíbrio lógico e visão de longo prazo | ✅ |
| 4 | `luma` | Mentora | Didática e evolução do usuário | ✅ |
| 5 | `vox` | Arauta | Narrativa e registro da jornada | ✅ |
| 6 | `athenae` | Arquiteta | Organização e estruturação de processos | ✅ |
| 7 | `nyx` | Guardiã do Limiar | Introspecção e criatividade profunda | ✅ |

**Lacuna resolvida (v1.0.0, item 1.3):** o OD tinha 6 perfis + `auto` e o
**Conector Nexus** não existia como perfil — agora a **Plêiade está
completa** com o 7º perfil `nexus` em `agents/profiles.py` (selecionável e
detectável por domínio).

---

## 1. v1.0.0 — Fundação v1 (release-grade)

> Objetivo: transformar o marco congelado em release-grade + completar a
> Plêiade. **Nenhuma feature nova de superfície** — só o que torna a v1.0.0
> defensável como versão 1.

| # | Item | Origem | Entrega |
|---|---|---|---|
| 1.1 | **CI no GitHub Actions** | Roadmap §8 (promessa pendente) | ✅ **Entregue (2026-09-07).** `.github/workflows/ci.yml` (Python 3.12, push + PR): `compileall` + `pytest -q` com gate de **cobertura ≥ 90%** via `.coveragerc` (escopo: pacotes de produção, `runtime/launcher.py` omitido) e `requirements-dev.txt` |
| 1.2 | **Migração JSON → PostgreSQL** | Pendência v0.28.0 | ✅ **Entregue (2026-09-07).** `memory/adapters.py` (schemas + `migrate_all()` idempotente); `history.py`, `cache.py`, `quick_responses.py`, `vector.py` ganharam param `database=None`; launcher injeta Database; fallback JSON mantido. 46 testes novos |
| 1.3 | **7º perfil: `nexus` (Conector)** | Lacuna da Plêiade (pleiade.yaml) | ✅ **Entregue (2026-09-07).** Novo perfil em `agents/profiles.py`: o equilíbrio que une a plêiade — domínio de **integração/coordenação** entre os perfis; detecção automática (domínio "conexão", "integração", "plêiade") |
| 1.4 | **Health checks externos** | Pendência v0.24.0 | ✅ **Entregue (2026-09-07).** Checks não-críticos de **HA** e **MQTT/Mosquitto** no Health Monitor (placeholders em `build_health` + `register_external_health_checks()` no launcher); `PresenceMonitor.health()` agora reflete alcance real do HA |
| 1.5 | **Control Bridge no repo** | Pendência P1 (auditoria) | ✅ **Entregue (2026-09-07).** `tests/test_control_bridge.py` (26 testes: allowlist, tokens, escape de path, legados §7.1, auditoria, execute) + unit systemd `runtime/systemd/od-control-bridge.service` no `install-user.sh` |
| 1.6 | **Systemd service `od-core`** | Análise do servidor (2026-09-05) | ✅ **Entregue (2026-09-07).** `runtime/systemd/od-core.service` com hardening (NoNewPrivileges, ProtectSystem=strict, ProtectKernel*, MemoryMax=6G, CPUQuota=200%, ReadWritePaths); `install-user.sh` com verificação de linger; 29 testes (tests/test_systemd_units.py) |
| 1.7 | **SWAP 4 GB** | Análise do servidor (2026-09-05) | ✅ **Entregue (2026-09-07).** SWAP 8 GB criado (`/swapfile`) + `vm.swappiness=10` via `runtime/setup/setup-server.sh` |
| 1.8 | **UFW Firewall** | Análise do servidor (2026-09-05) | ✅ **Entregue (2026-09-07).** UFW ativo: 22 (SSH), 8000 (OD API), 8123 (HA) permitidos; resto bloqueado |
| 1.9 | **Variáveis de ambiente ausentes** | Análise do servidor (2026-09-05) | ✅ **Entregue (2026-09-07).** 6 variáveis configuradas no `.env` (`OD_PRESENCE_ENABLED`, `OD_PRESENCE_POLL_S`, `OD_RECOVERY_INTERVAL_S`, `OD_SELF_REPAIR_ENABLED`, `OD_NOTIFIER_ENABLED`) |
| 1.10 | **Montar disco sdb1** | Análise do servidor (2026-09-05) | ✅ **Entregue (2026-09-07).** `/dev/sdb1` montado em `/home/alex/dados` (801 GB livres) + automount via `/etc/fstab` |

**Critérios de aceite:** ✅ CI verde no GitHub (push + PR) · ✅ cobertura ≥ 90% — **95%**
 · ✅ suíte local — **1594 passed** · ✅ perfil `nexus` selecionável e detectável
 · ✅ migração JSON→DB sem perda · ✅ `/health` com 7 checks (5 internos + HA + MQTT)
 · ✅ od-core como systemd service com sandboxing · ✅ SWAP 8 GB ativo
 · ✅ UFW ativo (22/8000/8123) · ✅ variáveis de ambiente configuradas
 · ✅ disco sdb1 montado (801 GB). **v1.0.0 COMPLETA!**

---

## 2. v1.1.0 — Acesso Externo Seguro 🔐 ✅

> Objetivo: acessar o OD de qualquer lugar **sem abrir portas públicas**.

### 2.1 Tailscale (VPN mesh, WireGuard) — ENTREGUE

| Aspecto | Detalhe |
|---|---|
| **IP Tailscale** | `100.77.67.53` |
| **Tailnet** | `nickyvirthy` |
| **Versão** | 1.102.2 |
| **Interface** | `tailscale0` |

**Acesso:** `http://100.77.67.53:8000` (exige `X-API-Key`)

**Segurança em camadas:** VPN WireGuard + X-API-Key + UFW (22/8000/8123) + sem portas no roteador.

**Documentação:** `docs/TAILSCALE_SETUP.md`

**Critérios de aceite:** ✅ API acessível via Tailscale (100.77.67.53:8000) · ✅ 0 portas abertas no roteador · ✅ journal sem exposição de segredos.

---

## 3. v1.2.0 — App Android 📱 🚧

> Objetivo: o OD no bolso — **novidade v1** (o roadmap antigo descartou o
> Flutter em favor de PWA; agora o pedido é um app nativo Android).
> **Status 2026-09-12:** **APK release `1.2.0+4`** (`app/build_apk.sh`, com
> Flutter 3.47.2/JDK 17/Android SDK 36 — 51.9 MB, com desugaring) publicado em
> `site/OmegaDrakon.apk`. Testes: **37 passed** + analyze limpo (suíte com
> fixture do manifesto real do `/capabilities`). **Validado no aparelho**
> (Redmi Note 14, `http://100.77.67.53:8000`): chat, ações e status OK —
> journal do `od-core` registra a mensagem do app e a execução de `cpu_info`
> via `session_id=api:app`. Falta: ativar o push com o `google-services.json`
> (conta Firebase — `docs/FIREBASE_SETUP.md`).

### 3.1 Stack proposta

| Decisão | Escolha | Por quê |
|---|---|---|
| Framework | **Flutter** | Um código para Android (+ iOS futuro), Dart, consumo direto da API REST existente; reavaliação do roadmap antigo (o app agora é requisito) |
| Backend | **API REST do OD (já no ar)** | `POST /message` (chat), `GET /capabilities`, `GET /health`, `/executa` via Orchestrator — sem novo servidor |
| Auth | **Chave do dispositivo** | App guarda `OD_API_KEY` (ou chave derivada por device) no keystore do Android (encrypted storage), nunca em texto; envio via `X-API-Key` |
| Push | **Firebase Cloud Messaging (FCM)** | Alertas do ProactiveNotifier / RecoveryLoop / Presence chegam ao celular mesmo com o app fechado |
| Conectividade | REST hoje · **WebSocket `/ws/chat` na v1.3** | Streaming token-a-token quando o WebSocket sair do 501 |

### 3.2 Telas (MVP)

| Tela | Função |
|---|---|
| **Chat** | Conversa com o OD (perfis incluindo o novo `nexus`), bolhas, histórico |
| **Ações** | Catálogo de 57 actions: executar `system_info`, `network_hosts` (pessoas na rede), etc. com o mesmo gate de risco do bot |
| **Status** | `/health` + métricas + capacidades (manifesto) |
| **Notificações** | Alertas push (FCM) com deep link para a tela de origem |

**Critérios de aceite:** app no celular conversando com o servidor **de fora
da LAN** (via Tailscale) · auth por chave criptografada · push recebido ao
vivo · 57 actions executáveis.

---

## 4. v1.3.0 em diante — Novidades e Evoluções

| # | Item | Origem | Tipo |
|---|---|---|---|
| 4.1 | **WebSocket `/ws/chat`** (streaming token-a-token) | Pendência v0.13.0 | Evolução — substitui o 501; habilita streaming no app |
| 4.2 | **Plugins reais** em `plugins/actions/` | Pendência v0.25.0 | Evolução — primeiro plugin: portar `system_exec` **mediado** pelo Control Bridge? |
| 4.3 | **`/codigo` completo no bot** | Pendência v0.27.x | Evolução — ler/backups/rollback/patch via Telegram |
| 4.4 | **Cliente interno do Control Bridge** | Pendência v0.27.x | Evolução — OD passa a chamar a ponte (execução mediada com allowlist) |
| 4.5 | **Auditoria de integridade** (arquivos/serviços do Nexus) | Pendência v0.22.0 | Evolução |
| 4.6 | **Voz no app** (STT/TTS) | Novidade | Evolução — aproveita whisper.cpp/Piper já ativos |
| 4.7 | **Dashboard PWA aprimorado** | Novidade | Evolução — o dashboard estático ganha números vivos (métricas) |
| 4.8 | **Auto-reparo LLM assistido** (providers) | Pendência v0.9.0 | Experimental — correções geradas via LLM dentro do pipeline do Coder (sandbox→testes→backup) |

---

## 5. Critérios de Aceite por Versão (resumo)

| Versão | Entrega | Aceite mínimo |
|---|---|---|
| **v1.0.0** | Fundação + Plêiade completa | CI verde + cobertura ≥ 90% + perfil `nexus` + dados no Postgres |
| **v1.1.0** | Acesso externo seguro | Tailscale ativo · celular acessa a API de fora da LAN · 0 portas abertas |
| **v1.2.0** | App Android | App publicado (APK) · chat + actions + push funcionando via Tailscale |
| **v1.3.0+** | Evoluções/novidades | Conforme item (WebSocket, plugins, voz no app…) |

---

## 6. Referências

- `~/nexus/config/pleiade.yaml` — as 7 entidades da Plêiade (fonte da lacuna)
- `docs/ROADMAP_ABSORCAO.md` — Fases 1–7 (37/37 absorvidas, série 0.x)
- `docs/README_VERSAO.md` [0.28.4] — análise do servidor + atualização do roadmap
- `docs/SERVER_ANALYSIS.md` — análise completa do servidor nicky-server (2026-09-05)
- Gravity Index — Tailscale (VPN mesh) para acesso externo seguro
- `agents/profiles.py` — perfis atuais (6 + auto)

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/ROADMAP_V1.md
Descrição: Roadmap da série v1.x — fundação release-grade (v1.0.0),
           acesso externo seguro (v1.1.0), app Android (v1.2.0) e
           novidades/evoluções (v1.3.0+). Inclui a Plêiade completa com o
           7º agente (Nexus) que faltava.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```