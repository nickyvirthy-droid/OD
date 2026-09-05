# OMEGA DRAKON — ROADMAP v1.x 🐉

> **Status:** Planejamento (vigente) · **Data:** 2026-09-04
> **Base:** série 0.x congelada na v0.28.1 (tag `v0.28.1`) — esta é a
> **primeira entrega da série v1** (v1.0.0 em diante).
> **Assinatura:** `OD // CORE`

---

## 0. A Plêiade Completa — 7 Entidades (descoberta da lacuna)

O legado Nexus define em `~/nexus/config/pleiade.yaml` as **7 entidades da
Plêiade**. O OmegaDrakon absorveu **6 perfis** — falta o **7º**: o próprio
**Nexus**.

| # | Entidade | Nome | Papel (pleiade.yaml) | No OD? |
|---|---|---|---|---|
| 1 | `nexus` | **Nexus** | **Conector e Sétima Entidade. O equilíbrio que une a plêiade** | ❌ **FALTA** |
| 2 | `guardian` | Nicky Virthy | Execução técnica e soberania do servidor | ✅ `agents/profiles.py` |
| 3 | `regulus` | Conselheiro | Equilíbrio lógico e visão de longo prazo | ✅ |
| 4 | `luma` | Mentora | Didática e evolução do usuário | ✅ |
| 5 | `vox` | Arauta | Narrativa e registro da jornada | ✅ |
| 6 | `athenae` | Arquiteta | Organização e estruturação de processos | ✅ |
| 7 | `nyx` | Guardiã do Limiar | Introspecção e criatividade profunda | ✅ |

**Lacuna confirmada:** o OD tem 6 perfis + `auto`, mas o **Conector Nexus**
não existe como perfil. A v1.0.0 nasce corrigindo isso.

---

## 1. v1.0.0 — Fundação v1 (release-grade)

> Objetivo: transformar o marco congelado em release-grade + completar a
> Plêiade. **Nenhuma feature nova de superfície** — só o que torna a v1.0.0
> defensável como versão 1.

| # | Item | Origem | Entrega |
|---|---|---|---|
| 1.1 | **CI no GitHub Actions** | Roadmap §8 (promessa pendente) | Pipeline: `pytest -q` em Python 3.12 + `compileall` + gate de **cobertura ≥ 90%** (`pytest-cov`) — o maior gap de maturidade |
| 1.2 | **Migração JSON → PostgreSQL** | Pendência v0.28.0 | Histórico (`memory/history.py`), cache LLM e quick responses saem dos arquivos JSON para tabelas no Postgres (adapter + migração do `data/` existente) |
| 1.3 | **7º perfil: `nexus` (Conector)** | Lacuna da Plêiade (pleiade.yaml) | Novo perfil em `agents/profiles.py`: o equilíbrio que une a plêiade — domínio de **integração/coordenação** entre os perfis; detecção automática (domínio "conexão", "integração", "plêiade") |
| 1.4 | **Health checks externos** | Pendência v0.24.0 | Registra no Health Monitor os checks não-críticos de **HA** e **MQTT/Mosquitto** (hoje só os internos) |
| 1.5 | **Control Bridge no repo** | Pendência P1 (auditoria) | Testes do bridge (`tests/test_control_bridge.py`) + unit systemd versionada em `runtime/systemd/` |
| 1.6 | **Systemd service `od-core`** | Análise do servidor (2026-09-05) | Service unit para o launcher `all` — sobe automaticamente no boot, restart on-failure, user `odrunner` com sandboxing |
| 1.7 | **SWAP 4 GB** | Análise do servidor (2026-09-05) | Criar swap file (`/swapfile`) — o LLM local consome 4.8 GB de 7.7 GB RAM, sem swap o OOM killer derruba processos |
| 1.8 | **UFW Firewall** | Análise do servidor (2026-09-05) | Configurar UFW: permitir 22 (SSH), 8000 (OD API), 8123 (HA); bloquear o resto; Tailscale já fornece acesso externo seguro |
| 1.9 | **Variáveis de ambiente ausentes** | Análise do servidor (2026-09-05) | Configurar no `.env`: `OD_PRESENCE_ENABLED`, `OD_PRESENCE_POLL_S`, `OD_HA_CREDENTIALS`, `OD_RECOVERY_INTERVAL_S`, `OD_SELF_REPAIR_ENABLED`, `OD_NOTIFIER_ENABLED` |
| 1.10 | **Montar disco sdb1** | Análise do servidor (2026-09-05) | Montar `/dev/sdb1` (Seagate 1 TB não montado) + configurar automount via `/etc/fstab` — +1 TB disponível para backups e dados |

**Critérios de aceite:** CI verde no GitHub (push + PR) · cobertura ≥ 90% ·
suíte local ≥ 1453 · perfil `nexus` selecionável e detectável · migração de
dados sem perda · `/health` com 7 checks (5 internos + HA + MQTT) ·
od-core como systemd service · SWAP 4 GB ativo · UFW ativo ·
todas as variáveis de ambiente configuradas.

---

## 2. v1.1.0 — Acesso Externo Seguro 🔐

> Objetivo: acessar o OD de qualquer lugar **sem abrir portas públicas**.
> Pesquisa (Gravity Index): **Tailscale** recomendado; Cloudflare Tunnel é a
> alternativa.

### 2.1 Recomendação: Tailscale (VPN mesh, WireGuard)

| Aspecto | Detalhe |
|---|---|
| **Por quê** | Zero-config, NAT traversal automático (sem port forwarding), **free tier generoso p/ uso pessoal**, clientes Linux + Android |
| **Modelo** | Servidor entra no seu tailnet privado; o celular entra no MESMO tailnet → acessa `http://<ip-tailscale>:8000` como se estivesse na LAN |
| **Segurança em camadas** | VPN (criptografia WireGuard) **+** o OD já exige `X-API-Key` em todos os endpoints (`auth_all`) **+** nada exposto à internet |
| **Alternativa** | Cloudflare Tunnel — URLs públicas com domínio custom + Zero Trust, porém mais setup (DNS) e não exige app VPN no celular |

**Passos (v1.1.0):**
1. Instalar Tailscale no servidor (`curl -fsSL https://tailscale.com/install.sh | sh` + `tailscale up` com auth key)
2. Instalar o app Tailscale no celular Android e entrar no mesmo tailnet
3. Validar `https://<ip-tailscale>:8000` com `X-API-Key` de fora da LAN
4. **Opcional:** proxy HTTPS local (Caddy) na frente da API para o app usar `https` + cert local

**Critérios de aceite:** acesso do celular (fora da LAN) à API com chave ·
0 portas abertas no roteador · journal sem exposição de segredos.

---

## 3. v1.2.0 — App Android 📱

> Objetivo: o OD no bolso — **novidade v1** (o roadmap antigo descartou o
> Flutter em favor de PWA; agora o pedido é um app nativo Android).

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