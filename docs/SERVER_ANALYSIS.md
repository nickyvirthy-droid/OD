# OMEGA DRAKON — ANÁLISE DO SERVIDOR 🖥️

> **Data:** 2026-09-05
> **Servidor:** nicky-server (Ubuntu 24.04, Intel i5-6500, 7.7GB RAM)
> **Objetivo:** Mapear TODO o servidor para habilitar controle total do OD na v1.x

---

## 1. HARDWARE

| Componente | Detalhe |
|---|---|
| **Hostname** | `nicky-server` |
| **OS** | Ubuntu 24.04 LTS (kernel 6.8.0-136-generic) |
| **CPU** | Intel Core i5-6500 @ 3.20GHz (4 cores, sem Hyper-Threading) |
| **RAM** | 7.7 GB total (5.3 GB em uso, 2.4 GB disponível) |
| **Swap** | **NENHUM configurado** ⚠️ |
| **Disco principal** | 232 GB LVM (66 GB usado / 156 GB livre = 30%) |
| **Disco externo 1** | Seagate 1 TB (`/dev/sdb1`) — **NÃO MONTADO** ⚠️ |
| **Disco externo 2** | Seagate 1 TB (`/dev/sdc1`) — montado em `/mnt/Arquivos` (750 GB usado / 120 GB livre = 87%) |
| **Uptime** | 37 dias (desde 29/07/2026) |
| **Câmera** | Alcor Micro 1080P USB (`/dev/video0`, `/dev/video1`) |
| **Áudio** | HDA Intel PCH (ALC3234 Analog + Alt) + Webcam USB Audio |
| **Wi-Fi** | 2x Ralink MT7601U USB (1 ativo: `wlx000f0037acf0`) |
| **Ethernet** | `enp2s0` — DOWN (não conectado) |

---

## 2. REDE

| Item | Valor |
|---|---|
| **IP LAN** | `192.168.0.250/24` |
| **IP Tailscale** | `100.77.67.53` (IPv6: `fd7a:115c:a1e0::dd33:4335`) |
| **Tailnet** | `nickyvirthy@` (7 dispositivos, só server online) |
| **Gateway** | `192.168.0.1` |
| **DNS** | `127.0.0.53` (systemd-resolved) |
| **Wi-Fi** | `wlx000f0037acf0` (conectado, modo DORMANT) |

### Dispositivos no Tailnet

| Dispositivo | Tipo | Última vez visto |
|---|---|---|
| `nicky-server` | linux | ✅ Online |
| `desktop-4icaj6f` | windows | 14h atrás |
| `alex-rv411...` | linux | 259 dias |
| `nickyserver` | linux | 96 dias |
| `note-positivo` | windows | 135 dias |
| `redmi-note-14` | android | 156 dias |
| `xiaomi-24117rn76l` | android | 252 dias |

---

## 3. PORTAS E SERVIÇOS ATIVOS

| Porta | Serviço | Bind | Status |
|---|---|---|---|
| **22** | SSH (OpenSSH) | `0.0.0.0` | ✅ Ativo |
| **53** | DNS (systemd-resolved) | `127.0.0.53/54` | ✅ Ativo |
| **1883** | MQTT (Mosquitto) | `127.0.0.1` | ✅ Ativo |
| **5432** | PostgreSQL 16 | `127.0.0.1` | ✅ Ativo |
| **8000** | **OD API REST** (Python) | `0.0.0.0` | ✅ Ativo |
| **8081** | **LLM Server** (llama-server) | `127.0.0.1` | ✅ Ativo |
| **8123** | **Home Assistant** | `0.0.0.0` | ✅ Ativo |
| **8765** | OD (placeholder/auxiliar) | `127.0.0.1` | ✅ Ativo |
| **18554-18555** | Tailscale (DERP/coord) | `*` | ✅ Ativo |
| **55870** | Tailscale (relay) | tailscale IP | ✅ Ativo |

---

## 4. DOCKER

### Containers

| Container | Image | Status | Portas |
|---|---|---|---|
| **homeassistant** | `ghcr.io/home-assistant/home-assistant:stable` | ✅ Up 42h | 8123 (host) |
| **mosquitto** | `eclipse-mosquitto` | ❌ Exited (9 dias) | — (usa systemd) |
| **mariadb** | `mariadb:latest` | ❌ Exited (9 dias) | — (legado) |
| **hello-world** | `hello-world` | ❌ Exited (5 meses) | — (teste) |

### Redes

| Nome | Driver | Status |
|---|---|---|
| `nicky-net` | bridge | ✅ |
| `br-818a617b1197` | bridge | ⚠️ NO-CARRIER |
| `docker0` | bridge | ⚠️ NO-CARRIER |

### Volumes

- 3 volumes anônimos (provavelmente do HA)

### Compose

- `/home/alex/nexus/infra/ha/docker-compose.yml`

---

## 5. SERVIÇOS SYSTEMD

### Ativos

| Serviço | Status | Descrição |
|---|---|---|
| `od-control-bridge.service` | ✅ Ativo (3 dias) | OmegaDrakon Control Bridge (user: `odrunner`) |
| `mosquitto.service` | ✅ Ativo | MQTT Broker |
| `postgresql@16-main` | ✅ Ativo | PostgreSQL 16 |
| `tailscaled.service` | ✅ Ativo | Tailscale node agent |
| `docker.service` | ✅ Ativo | Docker Engine |
| `homeassistant` | ✅ Ativo (Docker) | Home Assistant |

### Habilitados no Boot

- `od-control-bridge.service` ✅
- `mosquitto.service` ✅
- `postgresql.service` ✅
- `tailscaled.service` ✅
- `docker.service` ✅

### ⚠️ CRÍTICO: Não existe systemd service para `od-core`

O Omega Drakon principal (launcher `all`) roda como **processo manual do usuário `alex`** (PID 1644919). Não sobe automaticamente no boot.

---

## 6. LLM LOCAL

| Item | Detalhe |
|---|---|
| **Runtime** | llama.cpp v0.3.0 (`/opt/omegadrakon/ai/runtimes/llama/`) |
| **Modelo ativo** | `gemma-4-E4B-it-Q4_K_M.gguf` (4.9 GB) |
| **Endereço** | `127.0.0.1:8081` |
| **Parâmetros** | ctx-size 16384, parallel 1, temp 0.7, top-p 0.9 |
| **Consumo RAM** | ~4.8 GB (60% do total) ⚠️ |

### Modelos Disponíveis

| Modelo | Tamanho | Localização |
|---|---|---|
| `gemma-4-E4B-it-Q4_K_M.gguf` | 4.9 GB | `~/LLM/data/models/` (ativo) |
| `qwen2.5-coder-7b-instruct-q4_k_m.gguf` | ~4 GB | `~/llama.cpp/models/` |
| `qwen2.5-3b-instruct-q4_k_m.gguf` | ~2 GB | `~/llama.cpp/models/` |
| `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` | ~400 MB | `~/llama.cpp/models/` |

---

## 7. FERRAMENTAS DE VOZ

| Ferramenta | Binário | Status |
|---|---|---|
| **Whisper (STT)** | `~/nicky/whisper.cpp/` (modelo `ggml-base.bin`) | ⚠️ Binário não encontrado no PATH |
| **Piper (TTS)** | `~/nicky/piper/piper/piper` | ✅ Binário presente |
| **Piper vozes** | `dii_pt-BR.onnx` + `pt_BR-faber-medium.onnx` | ✅ 2 vozes pt-BR |
| **FFmpeg** | `/usr/bin/ffmpeg` v6.1.1 | ✅ Sistema |

---

## 8. HOME ASSISTANT

| Item | Detalhe |
|---|---|
| **Status** | ✅ Ativo (Docker, porta 8123) |
| **Config** | `/srv/omegadrakon/homeassistant/config/` |
| **Backup** | `/srv/omegadrakon/homeassistant/backups/` |
| **Custom Components** | HACS, Sonoff LAN |
| **Automações** | Nenhuma configurada (`[]`) |

### Dispositivos Sonoff (7 switches)

| Switch | Cômodo |
|---|---|
| `switch.luz_sala_sonoff_1000ab4e0d` | Sala |
| `switch.luz_corredor_sonoff_1000aba345` | Corredor |
| `switch.luz_cozinha_sonoff_1000ab588f` | Cozinha |
| `switch.luz_da_varanda_sonoff_1000ab096e` | Varanda |
| `switch.luz_area_sonoff_1000a5283c` | Área |
| `switch.luz_quarto_nicoly_sonoff_1000aaddb6` | Quarto Nicoly |
| `switch.luz_suite_sonoff_1000aac8b1` | Suíte |

### Outras Entidades

- `person.alex_projeti` (presença)
- `weather.forecast_casa` (clima)
- `tts.google_translate_en_com` (TTS Google)
- `todo.lista_de_compras` (lista)
- `switch.note_servidor_socket_1` (socket servidor)
- `switch.luz_oficina_socket_1` (socket oficina)

### ⚠️ Presença Monitor

O OD já tem módulo (`integrations/homeassistant/presence.py`) mas **não está configurado**:
- `OD_PRESENCE_ENABLED` — ausente do `.env`
- `OD_HA_CREDENTIALS` — ausente do `.env`
- API HA retorna 401 (precisa token de longa duração)

---

## 9. SEGURANÇA

| Item | Status |
|---|---|
| **UFW (firewall)** | ❌ NÃO configurado |
| **fail2ban** | ❌ NÃO instalado |
| **SSH** | ✅ Ativo porta 22 (bind 0.0.0.0 — exposto) |
| **OD API** | ✅ X-API-Key obrigatória (auth_all) |
| **OD port 8000** | ⚠️ Bind 0.0.0.0 — exposto na LAN |
| **HA port 8123** | ⚠️ Bind 0.0.0.0 — exposto na LAN |
| **PostgreSQL** | ✅ Só 127.0.0.1 |
| **MQTT** | ✅ Só 127.0.0.1 |

---

## 10. ESTRUTURA DE DIRETÓRIOS

| Caminho | Tamanho | Descrição |
|---|---|---|
| `~/OmegaDrakon/` | 294 MB | Projeto OD principal (v0.28.0, 1469 testes) |
| `~/nicky/` | 6.4 GB | Legado Nicky v0.6 (código + binários whisper/piper) |
| `~/nexus/` | — | Legado Nexus (router, config, scripts) |
| `~/Legado/` | — | Backup do legado (Nexus, Nicky, NV, OMEGA_DRAKON) |
| `~/LLM/` | ~5 GB | Modelos LLM (gemma-4 4.9 GB) |
| `~/llama.cpp/` | 7.6 GB | Build do llama.cpp (src + binaries) |
| `/opt/omegadrakon/` | — | Runtime OD (llama runtime, builders, tools) |
| `/srv/omegadrakon/` | — | Dados OD (HA config + backups) |
| `/mnt/Arquivos/` | 750 GB usado | Disco externo Seagate (backup/arquivos) |
| `~/.openclaw/` | — | OpenClaw (agentes, plugins, skills) |

---

## 11. CONEXÕES ATIVAS

| Destino | Porta | Processo |
|---|---|---|
| `172.237.61.190:443` | 443 | (sem processo identificado) |
| `216.24.57.1:443` | 443 | freebuff (PID 1655525) |
| `216.24.57.7:443` | 443 | freebuff (PID 1655525) |
| `216.24.57.15:443` | 443 | freebuff (PID 1655525) |
| `149.154.166.110:443` | 443 | python/Telegram (PID 1644919) |
| `52.52.228.195:443` | 443 | (sem processo identificado) |
| `192.168.0.111:61714` | 22 | SSH (conexão externa) |
| `127.0.0.1:1883` | 1883 | python/OD ↔ Mosquitto MQTT |

---

## 12. ATUALIZAÇÃO: Limpeza do Servidor (2026-09-05)

### Ações Executadas
1. **Removido ~/LLM/** (19 GB) - pasta de teste, modelo movido para ~/llama.cpp/models/
2. **Service od-llm atualizado** - path do modelo corrigido em ~/.config/systemd/user/od-llm.service
3. **Voice tools organizados** - whisper/piper movidos para /opt/omegadrakon/voice/
4. **Docker limpo** - 3 containers parados removidos + 3 volumes não utilizados
5. **Logs antigos** - ~/nicky/logs/ limpo

### Estrutura Permanente do OD (atualizada)
```
/opt/omegadrakon/
├── ai/runtimes/llama/     # llama-server v0.3.0 (suporta gemma4)
├── voice/
│   ├── whisper/           # whisper-cli + ggml-base.bin (141 MB)
│   └── piper/             # piper + vozes pt-BR + libs (165 MB)
└── builders/ + tools/

~/llama.cpp/models/
├── gemma-4-E4B-it-Q4_K_M.gguf (4.7 GB - ATIVO)
├── qwen2.5-coder-7b (4.4 GB - disponível)
├── qwen2.5-3b (2.0 GB - disponível)
└── Qwen2.5-0.5B (469 MB - disponível)
```

### Descoberta Importante
O build do `llama.cpp` compilado localmente (build 8444) **NÃO suporta a arquitetura `gemma4`**. Apenas o build do `/opt/omegadrakon` (v0.3.0, mais recente) suporta. O runtime do LLM DEVE ser mantido em `/opt/omegadrakon/`.

### Espaço
- Antes: 71 GB usado (32%)
- Depois: 52 GB usado (24%)
- Liberado: ~19 GB

---

## 13. VARIÁVEIS DE AMBIENTE DO OD

```env
# OD Runtime
TELEGRAM_BOT_TOKEN=8515534015:AAEEGApOzPvyXTsMRaF5c_45D1vkM5LX2JY
OD_TELEGRAM_ADMINS=660518870
OD_API_KEY=hadWWXwOKOzzCkLvByJOMDf4xfAHwyrhaevqA4OeC1M
OD_VISION_ENABLED=1
OD_VISION_DEVICE=/dev/video0
OD_VISION_POLL_S=5
OD_DB_URL=postgres://od:***@127.0.0.1:5432/od
```

### Variáveis AUSENTES (precisam ser configuradas)

- `OD_PRESENCE_ENABLED` — habilitar Presence Monitor
- `OD_PRESENCE_POLL_S` — intervalo de poll do HA
- `OD_HA_CREDENTIALS` — credenciais do Home Assistant
- `OD_RECOVERY_INTERVAL_S` — intervalo do Recovery Loop
- `OD_SELF_REPAIR_ENABLED` — habilitar auto-reparo
- `OD_NOTIFIER_ENABLED` — habilitar ProactiveNotifier

---

## 13. AÇÕES CRÍTICAS PARA v1.0.0

| Prioridade | Ação | Impacto |
|---|---|---|
| 🔴 P1 | Criar systemd service para `od-core` | Estabilidade — sobe no boot |
| 🔴 P1 | Configurar Presence Monitor no OD | HA + OD integrados |
| 🔴 P1 | Configurar UFW (firewall) | Segurança — limitar portas |
| 🔴 P1 | Criar SWAP (2-4 GB) | Estabilidade com LLM |
| 🟡 P2 | Montar disco sdb1 + automount | +1 TB disponível |
| 🟡 P2 | Compilar/symlink Whisper | STT funcionando |
| 🟡 P2 | Configurar HA token long-lived | Integração completa |
| 🟡 P2 | Configurar variáveis de ambiente ausentes | Todos os módulos ativos |
| 🟢 P3 | Configurar cron de backup | Proteção de dados |
| 🟢 P3 | Limpar /mnt/Arquivos (87%) | Espaço em disco |
| 🟢 P3 | Desativar containers Docker legados | Limpeza |

---

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/SERVER_ANALYSIS.md
Descrição: Análise completa do servidor nicky-server para habilitar
           controle total do OmegaDrakon na série v1.x.
Data: 2026-09-05
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```
