# OMEGA DRAKON — VERSÃO 1.0.0 — ESCOPO

> **Versão:** 1.0.0 (escopo de entrega)
> **Base:** série 0.x congelada na v0.28.1 (tag `v0.28.1`)
> **Data:** 2026-09-06 (atualizado 2026-09-07 — itens 1.1, 1.3, 1.4 e 1.5 entregues)
> **Idioma da sessão:** pt-BR (obrigatório, conforme regras da pasta `iniciar`)
> **Assinatura:** `OD // CORE`

---

## 1. Objetivo

Transformar o marco congelado em **release-grade + completar a Plêiade**.
Esta é a **primeira entrega da série v1**. Nenhuma feature nova de
superfície — só o que torna a v1.0.0 defensável como versão 1.

## 2. Decisões de escopo (v1.0.0)

### 2.1 Entregas incluídas

| # | Item | Origem | Como |
|---|---|---|---|
| 1.1 | **CI no GitHub Actions** | Roadmap v1.x §8 (promessa pendente) | ✅ **Entregue (2026-09-07).** `.github/workflows/ci.yml` (Python 3.12, push + PR): `compileall` + `pytest -q` + gate ≥ 90% (`pytest-cov`, `.coveragerc` com escopo de produção) + `requirements-dev.txt` (pytest-cov, PyYAML, numpy, opencv headless) |
| 1.2 | **Migração JSON → PostgreSQL** | Pendência v0.28.0 | `memory/history.py` + cache LLM + quick responses saem dos JSON para tabelas no Postgres (adapter + migração do `data/` existente) |
| 1.3 | **7º perfil: `nexus` (Conector)** | Lacuna da Plêiade (`pleiade.yaml`) | ✅ **Entregue (2026-09-07).** Novo perfil em `agents/profiles.py` (prioridade 7): domínio de integração/coordenação entre os perfis; detecção automática por domínio; tom em `personality.py`; listas de bot/API/capabilities atualizadas |
| 1.4 | **Health checks externos** | Pendência v0.24.0 | ✅ **Entregue (2026-09-07).** Checks não-críticos de HA e MQTT/Mosquitto no Health Monitor (placeholders + registro real no launcher) |
| 1.5 | **Control Bridge no repo** | Pendência P1 (auditoria) | ✅ **Entregue (2026-09-07).** `tests/test_control_bridge.py` + unit systemd `od-control-bridge.service` |
| 1.6 | **Systemd service `od-core`** | Análise do servidor 2026-09-05 | Service unit para o launcher `all` — sobe no boot, restart on-failure, user `odrunner` com sandboxing |
| 1.7 | **SWAP 4 GB** | Análise do servidor 2026-09-05 | Criar swap file (`/swapfile`) — o LLM local consome 4.8 GB de 7.7 GB RAM |
| 1.8 | **UFW Firewall** | Análise do servidor 2026-09-05 | Configurar UFW: permitir 22, 8000, 8123; bloquear o resto; Tailscale already provides secure external access |
| 1.9 | **Variáveis de ambiente ausentes** | Análise do servidor 2026-09-05 | Configurar no `.env`: `OD_PRESENCE_ENABLED`, `OD_PRESENCE_POLL_S`, `OD_HA_CREDENTIALS`, `OD_RECOVERY_INTERVAL_S`, `OD_SELF_REPAIR_ENABLED`, `OD_NOTIFIER_ENABLED` |
| 1.10 | **Montar disco sdb1** | Análise do servidor 2026-09-05 | Montar `/dev/sdb1` (Seagate 1 TB não montado) + automount via `/etc/fstab` |

### 2.2 Critérios de aceite

- ✅ CI verde no GitHub (push + PR) — pipeline criado (aguarda 1º push)
- ✅ Cobertura ≥ 90% — 90.76% local (2026-09-07)
- ✅ Suíte local ≥ 1453 testes passando — 1507 passed, 16 skipped
- ✅ Perfil `nexus` selecionável e detectável (entregue 2026-09-07)
- Migração de dados sem perda (JSON → Postgres)
- `/health` com 7 checks (5 internos + HA + MQTT)
- od-core como systemd service
- SWAP 4 GB ativo
- UFW ativo
- Todas as variáveis de ambiente configuradas

### 2.3 Não está na v1.0.0 (para versões futuras ou decisão posterior)

- WebSocket `/ws/chat` (hoje 501) — v1.3.0+
- Plugins reais em `plugins/actions/` — v1.3.0+
- `/codigo` completo no bot — v1.3.0+
- Cliente interno do Control Bridge no OD — v1.3.0+
- App Android (Flutter) — v1.2.0
- Acesso externo seguro (Tailscale) — v1.1.0
- Voz no app, dashboard PWA aprimorado, auto-reparo LLM assistido — v1.3.0+

## 3. Registro da sessão

Pasta `iniciar/` contém as regras da sessão e o checkpoint atual
(`session.json`). A tarefa atual é definir o escopo da v1.0.0 e,
se aprovado, criamos os artefatos de entrega (CHANGELOG v1.0.0,
eventuais documentos deRelease, ajustes no ROADMAP_V1.md se necessário).

## 4. Próximos passos

1. ~~Validar este escopo com o usuário~~ — escopo aprovado
2. ~~Item 1.3 (perfil `nexus`)~~ — **entregue em 2026-09-07**
3. ~~Item 1.4 (health checks externos HA/MQTT)~~ — **entregue em 2026-09-07**
4. ~~Item 1.5 (Control Bridge no repo)~~ — **entregue em 2026-09-07**
   (suíte 1490 passed)
5. Criar `docs/CHANGELOG.md` com a seção v1.0.0 (ou atualizar existente)
6. Para cada item restante (1.1, 1.2, 1.6–1.10), levantar dependências de
   execução (alguns exigem `sudo` ou acesso ao servidor nicky-server)
7. Conectar com o checkpoint `iniciar/session.json`: atualizar
   `topic`, `next` e `notes` à medida que avançarmos
