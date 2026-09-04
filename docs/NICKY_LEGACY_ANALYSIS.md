# NICKY LEGACY — ANÁLISE COMPLETA DO SISTEMA

> **Status:** Documentação de Análise (Revisão Completa)
> **Data:** 2026-09-02
> **Origem:** Leitura direta do código-fonte em `/home/alex/nicky`
> **Versão analisada:** v0.7.0 (código) / v0.6.0 (estável em produção)
> **Assinatura:** `OD // CORE`

---

## 1. Resumo Executivo

O **Nicky** é um sistema de IA pessoal autônomo rodando em um Dell OptiPlex 3040 com Ubuntu 24.04 LTS. Ele combina:
- Inferência local via **Qwen2.5-3B** (llama.cpp)
- Fallback para **Gemini** (API externa)
- Interface **Telegram Bot** + **API REST FastAPI** + **PWA/WebSocket**
- Percepção sensorial via **webcam + OpenCV** (detecção facial)
- Transcrição de voz via **whisper.cpp** + síntese via **Piper TTS**
- Persistência em **MariaDB** (Docker)
- Memória vetorial via **ChromaDB** (RAG)
- Cache inteligente com **SHA-256** e deduplicação
- **6 perfis de personalidade** com detecção automática

O sistema está **operacional e em produção** desde janeiro de 2025, com evolução contínua até v0.7.0.

---

## 2. Histórico de Versões

| Versão | Data | Status | Mudanças Principais |
|---|---|---|---|
| v0.1.0 | Jan/2025 | Histórico | Integração marca Omega Drakon, Ollama + fallbacks, Telegram básico |
| v0.3.0 | Abr/2026 | Experimental | Modo "all" unificado, FastAPI + Telegram, Pydantic v2 |
| v0.4.0 | Mai/2026 | Alpha | Streaming SSE, API Key, CORS, Dashboard Chart.js, OpenCV |
| v0.5.0 | Jun/2026 | Stable | Event Bus, ProactiveNotifier, /metrics Prometheus, /presenca |
| v0.6.0 | Jul/2026 | Production ✅ | /codigo agêntico, modo silencioso, rate limit IP, rotação API key, PWA |
| v0.7.0 | Jul/2026 | Em progresso (2/5) | STT (whisper.cpp) ✅, TTS (Piper) ✅, RAG (ChromaDB), MQTT, Face Prep |

---

## 3. Arquitetura Geral

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INTERFACES                                  │
│  ┌──────────┐  ┌──────────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ Telegram │  │ API REST     │  │WebSocket │  │ PWA (chat.html)│  │
│  │ Bot      │  │ (FastAPI)    │  │ /ws/chat │  │ + Dashboard    │  │
│  └────┬─────┘  └──────┬───────┘  └────┬─────┘  └────────┬───────┘  │
│       │               │               │                  │          │
│       └───────────────┴───────┬───────┴──────────────────┘          │
│                               │                                     │
│                    ┌──────────▼──────────┐                          │
│                    │    ORCHESTRATOR     │                          │
│                    │  (pipeline 8 etapas)│                          │
│                    └──────────┬──────────┘                          │
│                               │                                     │
│  ┌────────────────────────────┼────────────────────────────┐       │
│  │               CORE                                        │       │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │       │
│  │  │Event Bus │  │DB Pool   │  │Profiles  │  │Personali│ │       │
│  │  │(asyncio) │  │(aiomysql)│  │(6 perfis)│  │ty       │ │       │
│  │  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │       │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐              │       │
│  │  │VectorMem │  │Coder     │  │Main Loop │              │       │
│  │  │(ChromaDB)│  │Engine    │  │          │              │       │
│  │  └──────────┘  └──────────┘  └──────────┘              │       │
│  └─────────────────────────────────────────────────────────┘       │
│                               │                                     │
│  ┌────────────────────────────┼────────────────────────────┐       │
│  │               STORAGE                                      │       │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐              │       │
│  │  │LLM Cache │  │Conv. Hist│  │Quick Resp│              │       │
│  │  │(MariaDB) │  │(JSON)    │  │(MariaDB) │              │       │
│  │  └──────────┘  └──────────┘  └──────────┘              │       │
│  └─────────────────────────────────────────────────────────┘       │
│                               │                                     │
│  ┌────────────────────────────┼────────────────────────────┐       │
│  │               LLM LAYER                                   │       │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐              │       │
│  │  │Qwen Local│  │Gemini    │  │OpenAI    │              │       │
│  │  │(llama.py)│  │(fallback)│  │(optional)│              │       │
│  │  └──────────┘  └──────────┘  └──────────┘              │       │
│  └─────────────────────────────────────────────────────────┘       │
│                               │                                     │
│  ┌────────────────────────────┼────────────────────────────┐       │
│  │               VISION / SENSORS                            │       │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐              │       │
│  │  │Face Det. │  │Presence  │  │Audio Cap.│              │       │
│  │  │(OpenCV)  │  │Monitor   │  │(Whisper) │              │       │
│  │  └──────────┘  └──────────┘  └──────────┘              │       │
│  │  ┌──────────┐  ┌──────────┐                             │       │
│  │  │Piper TTS │  │Cleanup   │                             │       │
│  │  │          │  │Captures  │                             │       │
│  │  └──────────┘  └──────────┘                             │       │
│  └─────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Módulos Detalhados

### 4.1 Entry Point — `main.py`

- **Modos de execução:** `all` (padrão), `api`, `telegram`
- **Inicialização `run_all()`:** Event Bus → DB Pool → Orchestrator → PresenceMonitor → TelegramBot → API FastAPI
- **Logging:** JSON em produção (`_JsonFormatter`), formato legível em debug
- **Diretórios criados no startup:** `logs/`, `backups/`, `sandbox/`, `static/icons/`
- **Ordem de desligamento:** PresenceMonitor → Event Bus → DB Pool

### 4.2 Core — `core/`

| Módulo | Responsabilidade | Detalhes Técnicos |
|---|---|---|
| `orchestrator.py` | Pipeline central de 8 etapas | Rate limiting (deque 10msg/60s), detecção datetime PT-BR (regex), AIML, cache SHA-256, history (3 turns), Qwen local (120s timeout), Gemini fallback, RAG ChromaDB, process_stream() para WebSocket |
| `event_bus.py` | Pub/sub assíncrono via `asyncio.Queue` | Fila de 256 eventos, handlers em tasks independentes (`asyncio.ensure_future`), `publish_sync()` para threads não-async, `_safe_call()` com isolamento de exceções |
| `db.py` | Pool `aiomysql` compartilhado | Singleton com `_pool_lock`, minsize=2, maxsize=10, queries: `get_presence_today()`, `get_historico()`, `get_messages_by_hour()`, `get_daily_message_count()`, `get_llm_avg_response_time()`, `get_last_face_detection()`, `ensure_cache_index()` |
| `personality.py` | Personalidade Guardian | `NickyPersonality` dataclass, formatação de alertas (🟢🟡🔴), logs `[NICKY][INFO|WARN|CRIT]`, `get_system_prompt()` com system prompt completo |
| `conversation_history.py` | Histórico em JSON + memória | Persistência em `data/conversations/{user_id}/{profile}.json`, `load_all()` no startup, `get_history()` para ChatML, `add_interaction()` síncrono |
| `vector_memory.py` | RAG via ChromaDB | Singleton `VectorMemory`, modelo `all-MiniLM-L6-v2` (~90MB CPU), `threading.Lock` (não asyncio.Lock) para cross-loop safety, `asyncio.to_thread()` para I/O, `add_memory()` + `retrieve()`, fallback graceful |
| `coder.py` | Orquestrador agêntico | `list_project_tree()`, `read_file()`, `list_backups()`, `rollback_file()`, `full_auto_patch_cycle()` (sandbox → testes → promoção) |
| `main_loop.py` | Referência do event loop | `set_main_loop()` para resolver bug de event loop entre Telegram thread e loop principal |

### 4.3 Interfaces — `interfaces/`

| Módulo | Responsabilidade | Detalhes Técnicos |
|---|---|---|
| `api.py` | FastAPI REST + WebSocket v0.7.0 | 17 endpoints, middleware rate limit por IP (30req/60s), CORS configurável, `POST /transcribe` (whisper.cpp), `POST /tts` (Piper), `WS /ws/chat` streaming token-a-token, `GET /memory/{user_id}/search` (RAG), API key via header `X-API-Key` |
| `telegram_bot.py` | Bot Telegram v0.7.0 | Thread separada com loop próprio, pymysql síncrono (evita conflito event loop), 14 comandos, backoff crescente [5,15,30,60,90]→120s fixo, modo silencioso via Event Bus, `/codigo` agêntico (arvore/ler/backups/rollback/patch), `/rotacionar_key`, handle_audio_message (STT), `_send_voice_reply()` (TTS) |
| `notifier.py` | Notificações proativas | `ProactiveNotifier` via httpx (sem python-telegram-bot), health check periódico (60s), alertas: restart, LLM offline >5min, disco >85% (1 alerta/hora), anti-spam |
| `text_to_speech.py` | TTS Local via Piper v0.7.0 | Subprocess assíncrono, voz dii (feminina, padrão) + faber (masculina, Regulus), `_resolve_voice()` por perfil, `synthesize()` retorna bytes WAV, limpeza de temporários |

### 4.4 LLM — `llm/`

| Módulo | Provider | Detalhes Técnicos |
|---|---|---|
| `base.py` | Interface base | `BaseLLM` abstrata: `generate()`, `is_available()`, `calculate_cost()` |
| `llama_server_client.py` | Qwen2.5-3B via llama-server | **Primário**, porta 8081, ChatML format (`<|im_start|>`), `_clean_response()` remove leak do system prompt (prefixos, fragmentos, anotações), `repeat_penalty=1.15`, `generate_stream()` via SSE (httpx), stop tokens configuráveis |
| `qwen_client.py` | Qwen API | Com `system_prompt` nativo |
| `gemini_client.py` | Google Gemini | **Fallback** quando Qwen falha, system_prompt combinado com history |
| `openai_client.py` | OpenAI | Opcional |
| `anthropic_client.py` | Anthropic | Opcional |
| `ollama_client.py` | Ollama | Opcional |

**Pipeline LLM:**
```
Mensagem → Qwen LOCAL (8081) → se falhar → Gemini (API) → se falhar → "Nenhum LLM disponível"
```

### 4.5 Storage — `storage/`

| Módulo | Responsabilidade | Backend |
|---|---|---|
| `llm_cache.py` | Cache de respostas LLM | MariaDB `llm_cache`, hash SHA-256 (normalização: lowercase, espaços, pontuação + perfil), `use_count`, `avg_response_time_ms` (média móvel), `ON DUPLICATE KEY UPDATE` |
| `quick_response_db.py` | Respostas rápidas personalizadas | MariaDB `quick_responses`, alternância aleatória `response`/`response_alt`, `response_analytics` com `use_count` e `avg_response_time_ms` |
| `conversation_history.py` | Histórico de conversas | JSON files `data/conversations/{user_id}/{profile}.json`, `load_all()` no startup, max 20 entradas por arquivo |

### 4.6 Vision — `vision/`

| Módulo | Responsabilidade | Detalhes Técnicos |
|---|---|---|
| `face_detector.py` | Detecção facial OpenCV | Haar Cascade com CLAHE (contraste adaptativo), `minNeighbors=8`, `minSize=(80,80)`, `maxSize=(400,400)`, ROI guard (10% bordas), buffer de confirmação (3 ticks consecutivos), `save_detection_frame()` com limite 50/dia |
| `presence_monitor.py` | Loop de monitoramento | Intervalo 30s, publica `face_first_detection_today` e `presence_lost` no Event Bus, grava `presence_log` no MariaDB, silêncio após 30min sem detecção |
| `audio_capture.py` | STT via whisper.cpp v0.7.0 | Subprocess assíncrono, `ggml-base.bin` (multilingue), conversão ffmpeg (qualquer formato → WAV 16kHz mono), `transcribe_audio_bytes()`, timeout 120s, cleanup automático |
| `cleanup_captures.py` | Limpeza de capturas | Remove JPGs com mais de N dias (configurável `CAPTURE_RETENTION_DAYS=7`) |

### 4.7 Profiles — `profiles/`

| Módulo | Responsabilidade |
|---|---|
| `profile_manager.py` | 6 perfis com system prompts completos, domains para auto-detecção, `get_combined_prompt()` para modos híbridos, `add_custom_profile()` |

### 4.8 Knowledge — `knowledge/`

| Módulo | Responsabilidade |
|---|---|
| `hybrid_aiml_processor.py` | AIML (detecção <1ms) + MariaDB (resposta ~5) + cache em memória (5min TTL) |

---

## 5. Pipeline do Orchestrator (8 Etapas)

```
1. Rate Limiting      → deque temporal por usuário (10 msg/60s), admins isentos
2. Data/Hora           → regex PT-BR ("que horas", "que dia"), resposta sem LLM
3. AIML                → HybridAIMLProcessor: detecção + MariaDB quick_responses
4. Cache LLM (SHA-256) → normalização + hash SHA-256 + perfil → MariaDB llm_cache
5. Histórico           → últimos 3 turns (6 mensagens) via JSON files
6. Qwen LOCAL          → llama-server porta 8081, ChatML, timeout 120s
7. Gemini FALLBACK     → API externa quando Qwen falha
8. Pós-processamento   → gravação no cache + histórico + analytics

Extensão v0.7.0 (RAG):
  - Antes do LLM: ChromaDB retrieve → injeta no system_prompt
  - Cobertura: Qwen local E Gemini fallback (mesmo system_prompt)
```

---

## 6. Perfis de Personalidade (6)

| Perfil | Título | Emoji | Estilo | Domínios | Preferência |
|---|---|---|---|---|---|
| `guardian` | A Guardiã | 🛡️ | Técnico, vigilante, objetivo | monitoramento, alertas, status, sistema, validação | **Padrão** |
| `regulus` | O Conselheiro | ⚖️ | Formal, sábio, ponderado | história, direito, ética, filosofia, política | Gemini |
| `luma` | A Mentora | 🌟 | Empático, didático, acessível | educação, aprendizado, psicologia, tutoriais | Gemini |
| `vox` | A Arauta | 📢 | Dinâmica, magnética, radiofônica | comunicação, storytelling, retórica, anúncios | Gemini |
| `athenae` | A Arquiteta do Saber | 🏛️ | Metódica, precisa, sistemática | taxonomia, ontologia, metodologia, classificação | Gemini |
| `nyx` | A Guardiã do Limiar | 🌙 | Mística, oracular, integradora | religião, mitologia, esoterismo, arquétipos | Gemini |

**Detecção automática:** Analisa `domains` de cada perfil e conta matches com palavras da mensagem. Score mínimo de 2 para troca. Override manual via `/perfil <nome>`.

---

## 7. Dependências

### 7.1 Core
- `fastapi` 0.109.0 + `uvicorn` 0.27.0
- `pydantic` 2.5.3 + `pydantic-settings` 2.1.0
- `aiomysql` 0.2.0
- `python-telegram-bot` 20.7
- `httpx` 0.25.2
- `psutil` 5.9.7
- `python-multipart` 0.0.9

### 7.2 LLM
- `openai` 1.10.0
- `anthropic` 0.18.1
- `google-generativeai` 0.3.2

### 7.3 Vision
- `opencv-python` (via `cv2`)
- `numpy`

### 7.4 RAG (v0.7.0)
- `chromadb` ≥ 0.4.0
- `sentence-transformers` ≥ 2.2.0

### 7.5 Infraestrutura
- MariaDB 10.11 (Docker)
- llama.cpp (compilado localmente)
- whisper.cpp (compilado localmente)
- Piper TTS (binário local)
- Tailscale VPN
- ffmpeg

---

## 8. Tabelas MariaDB

| Tabela | Propósito | Colunas Principais |
|---|---|---|
| `llm_cache` | Cache de respostas LLM | query_hash, query_text, profile, response, llm_used, tokens_used, use_count, avg_response_time_ms |
| `quick_responses` | Respostas rápidas | pattern, category, profile, response, response_alt, priority |
| `response_analytics` | Métricas de uso | pattern, profile, use_count, avg_response_time_ms, last_used_at |
| `conversation_messages` | Histórico de mensagens | user_id, profile, role, content, llm_used, created_at |
| `presence_log` | Detecções faciais | detected_at, face_count, date_only |

---

## 9. Endpoints da API (Porta 8000)

| Método | Path | Auth | Descrição |
|---|---|---|---|
| GET | `/` | Não | Info do serviço |
| GET | `/health` | Não | Health check + LLMs disponíveis |
| GET | `/profiles` | Não | Lista de perfis |
| GET | `/profiles/{name}` | Não | Detalhes de um perfil |
| GET | `/presence/today` | Não | Resumo de presença do dia |
| GET | `/dashboard` | Não | Dashboard HTML |
| GET | `/chat` | Não | Chat PWA HTML |
| GET | `/metrics` | Não | Prometheus metrics |
| POST | `/message` | API Key | Pipeline completa (8 etapas) |
| POST | `/transcribe` | API Key | STT via whisper.cpp |
| POST | `/tts` | API Key | TTS via Piper |
| GET | `/dashboard/stats` | API Key | Stats em JSON |
| GET | `/llms` | API Key | LLMs disponíveis |
| DELETE | `/history/{user_id}` | API Key | Limpa histórico |
| GET | `/history/{user_id}/stats` | API Key | Stats de histórico |
| GET | `/memory/{user_id}/search` | API Key | Busca semântica RAG |
| WS | `/ws/chat` | API Key (query) | Chat WebSocket bidirecional |

---

## 10. Comandos Telegram

| Comando | Acesso | Descrição |
|---|---|---|
| `/start` | Público | Boas-vindas |
| `/help` | Público | Lista de comandos |
| `/perfil [nome]` | Público | Trocar/listar perfis (auto/guardian/regulus/luma/vox/athenae/nyx) |
| `/limpar` | Público | Limpar histórico |
| `/status` | Admin | Status do sistema (LLMs, API, Tailscale) |
| `/uptime` | Admin | Tempo ativo + métricas (msgs hoje, LLM avg, última detecção) |
| `/stats` | Admin | Estatísticas detalhadas (total, desde, cache hit rate) |
| `/dashboard` | Admin | Link do dashboard |
| `/historico [@ID] [N]` | Admin | Últimas N mensagens (próprias ou de outro usuário) |
| `/cache [limpar]` | Admin | Gerenciar cache LLM |
| `/presenca` | Admin | Detecções faciais do dia |
| `/codigo [subcmd]` | Admin | Orquestrador agêntico (arvore/ler/backups/rollback/patch) |
| `/rotacionar_key` | Admin | Rotacionar API Key (atualiza .env + settings) |
| 🎤 (áudio) | Público | Transcrição de voz via whisper.cpp |

---

## 11. Serviços Systemd

| Serviço | Porta | Comando | Status |
|---|---|---|---|
| `nicky.service` | 8000 | `python main.py all` | ✅ Ativo |
| `llama-server.service` | 8081 | `llama-server -m qwen2.5-3b...` | ✅ Ativo |

---

## 12. Scripts de Deploy e Operação

| Script | Função |
|---|---|
| `scripts/deploy_v050.sh` | Deploy completo: backup → stop → copy → directories → icons → env → ruff → start → healthcheck |
| `scripts/healthcheck.sh` | Health check com 10 tentativas (3s intervalo) |
| `scripts/generate_icons.py` | Gera ícones PWA placeholder (192x192, 512x512) via Pillow |

---

## 13. Pontos Fortes

1. **Soberania de dados** — Inferência 100% local (Qwen2.5-3B). Nuvem é fallback.
2. **Pipeline bem definido** — 8 etapas claras com fallbacks encadeados.
3. **Event Bus desacoplado** — Presença, Telegram e notifier são independentes.
4. **Rate limiting duplo** — Por usuário (deque 10/60s) e por IP (middleware 30/60s).
5. **Cache inteligente** — SHA-256 com normalização, deduplicação, métricas de latência.
6. **Perfis ricos** — 6 personalidades com system prompts completos e detecção automática.
7. **Presença sensorial** — Buffer de confirmação multi-frame (3 ticks) elimina falsos positivos.
8. **RAG local** — ChromaDB + sentence-transformers, thread-safe via threading.Lock.
9. **STT + TTS locais** — whisper.cpp + Piper, subprocess assíncronos (não residem em RAM).
10. **Observabilidade** — Logs JSON, métricas Prometheus, dashboard, uptime.
11. **Testes** — 80+ testes (60 unitários + 20 integração).
12. **Resiliência** — Backoff crescente no Telegram, health check, notificações proativas.
13. **Coder Engine** — Modificação segura de código via LLM com sandbox e rollback.
14. **PWA completa** — Chat.html com sidebar, tema claro/escuro, botões de voz.

---

## 14. Problemas e Dívida Técnica

### 14.1 Arquiteturais

| Problema | Impacto | Esforço |
|---|---|---|
| **Monólito concorrente** — FastAPI, Telegram, PresenceMonitor no mesmo processo | Bloqueio mútuo, difícil de isolar | Alto |
| **3 pools de conexão** — db.py (aiomysql) + llm_cache.py (aiomysql próprio) + Telegram (pymysql síncrono) | Overhead de conexões | Médio |
| **Acoplamento ao Telegram** — Thread separada com pymysql síncrono | Código duplicado | Médio |
| **Singletons explícitos** — `_pool`, `_cache_manager`, `_quick_response_db`, `_orchestrator` | Testes difíceis | Médio |
| **ConversationHistory event loop bug** — Perde mensagens do Telegram por conflito de loop | Histórico incompleto | Médio |

### 14.2 De Código

| Problema | Local | Impacto |
|---|---|---|
| **Bare `except:`** — `_initialize_llm_clients()` | `core/orchestrator.py` | Erros silenciados |
| **f-strings em logs** — `logger.warning(f"...")` | Diversos | Performance |
| **Cache pool próprio** — `LLMCacheManager` cria pool separado | `storage/llm_cache.py` | Waste de conexões |
| **Variáveis de ambiente misturadas** — Pydantic + `os.getenv()` | Diversos | Config fragmentada |
| **Arquivos .bak** — 15+ arquivos de backup no diretório | Interfaces, config, core | Dívida visual |

### 14.3 De Segurança

| Problema | Local | Risco |
|---|---|---|
| **Senhas hardcoded** — `"nicky_senha_123"` | `config/settings.py` | Médio |
| **API key em .env** — `/rotacionar_key` edita em disco | `telegram_bot.py` | Baixo (admin) |
| **WebSocket sem auth robusta** — API key via query param | `api.py` | Baixo (loopback) |
| **Botão de mic requer HTTPS** — `getUserMedia` bloqueado em HTTP | `chat.html` | Funcional com Nginx |

### 14.4 De Performance

| Problema | Impacto |
|---|---|
| **3 pools de conexão** | Sobrecarga MariaDB |
| **History em JSON files** | Sem índice, busca linear |
| **ClaHE em cada frame** | CPU extra (aceitável, 30s) |
| **RAG sentence-transformers** | Lento no first run (~90MB modelo) |

---

## 15. Capacidades Planejadas (v0.4.0–v0.7.0)

| Capacidade | Status |
|---|---|
| App Flutter multiplataforma | ❌ Não implementado |
| PWA com Service Worker | ✅ Parcial (chat.html + manifest + sw.js) |
| Streaming SSE/WebSocket | ✅ Implementado (WebSocket funcional) |
| Summarização de contexto longo | ❌ Não implementado |
| Autenticação JWT | ❌ Não implementado (API key estática) |
| RAG ChromaDB | 🔄 Em progresso (Item #3 v0.7.0) |
| MQTT Home Assistant | ❌ Não implementado (Item #4 v0.7.0) |
| Face Embeddings | ❌ Não implementado (Item #5 v0.7.0) |

---

## 16. Mapeamento para OmegaDrakon

> **Status (atualizado em 2026-09-04):** todas as capacidades abaixo foram
> absorvidas e implementadas no OmegaDrakon — ver a tabela "Já Implementado"
> em `docs/ROADMAP_ABSORCAO.md` (37/37 capacidades, 1382 testes).

| Capacidade Nicky | Destino OmegaDrakon | Status |
|---|---|---|
| Event Bus | `core/event_bus.py` | ✅ Implementado |
| Orchestrator pipeline | `core/orchestrator.py` | ✅ Implementado (Fase 3.4 + `execute_action` Pós-Fase 7) |
| State Manager | `core/state.py` | ✅ Implementado |
| Message Router | `core/router.py` | ✅ Implementado |
| Profiles (6 perfis) | `agents/profiles.py` + `agents/nicky_virthy/` | ✅ Implementado (Fase 6.5) |
| Cache LLM (SHA-256) | `memory/cache.py` | ✅ Implementado (Fase 2.2) |
| Conversation History | `memory/history.py` | ✅ Implementado (Fase 2.1) |
| Vector Memory (RAG) | `memory/vector.py` | ✅ Implementado (Fase 2.4) |
| Quick Responses | `memory/quick_responses.py` | ✅ Implementado (Fase 2.3) |
| AIML Processor | rota "quick responses (AIML legado)" do Orchestrator | ✅ Substituído (Fase 2.3) |
| Vision (face detection) | `tools/vision/face_detector.py` | ✅ Implementado (Fase 6.1) |
| Audio (STT) | `tools/audio/stt.py` | ✅ Implementado (Fase 6.3) |
| TTS (Piper) | `tools/audio/tts.py` | ✅ Implementado (Fase 6.4) |
| ProactiveNotifier | `integrations/notifier.py` | ✅ Implementado (Fase 5.3) |
| Telegram Bot | `integrations/telegram/` | ✅ Implementado (Fase 5.1) |
| API REST | `integrations/api/` | ✅ Implementado (Fase 5.2) |
| Config (Settings) | `configs/manager.py` | ✅ Implementado (Fase 1.1) |
| Coder Engine | `core/coder.py` | ✅ Implementado (Fase 4.1) |
| Tests (80+) | `tests/` | ✅ Implementado (1382 testes) |

---

## 17. Recomendações para Absorção

| Prioridade | Capacidade | Origem | Destino |
|---|---|---|---|
| 1 | Config Manager | `config/settings.py` | `configs/` |
| 2 | Cache LLM | `storage/llm_cache.py` | `memory/` |
| 3 | Conversation History | `storage/conversation_history.py` | `memory/` |
| 4 | Vector Memory (RAG) | `core/vector_memory.py` | `memory/` |
| 5 | Quick Responses | `storage/quick_response_db.py` | `tools/` |
| 6 | AIML Processor | `knowledge/hybrid_aiml_processor.py` | `tools/` |
| 7 | Vision | `vision/face_detector.py` + `presence_monitor.py` | `tools/vision/` |
| 8 | Audio (STT) | `vision/audio_capture.py` | `tools/audio/` |
| 9 | TTS (Piper) | `interfaces/text_to_speech.py` | `tools/audio/` |
| 10 | Coder Engine | `core/coder.py` | `core/coder.py` |
| 11 | ProactiveNotifier | `interfaces/notifier.py` | `integrations/` |
| 12 | Telegram Bot | `interfaces/telegram_bot.py` | `integrations/telegram/` |
| 13 | API REST | `interfaces/api.py` | `integrations/api/` |
| 14 | Personality | `core/personality.py` | `agents/nicky_virthy/` |
| 15 | Profile Manager | `profiles/profile_manager.py` | `agents/` |
| 16 | Tests (80+) | `tests/` | `tests/` |

**Princípio:** Absorver feature-by-feature, nunca copiar o monólito.

---

## 18. Arquiteturas de Referência para Reimplementação

### 18.1 Cache LLM (SHA-256)
```
Input: (query_normalized, profile) → SHA-256 → query_hash
Lookup: SELECT WHERE query_hash = %s AND profile = %s
Insert: ON DUPLICATE KEY UPDATE use_count + 1, avg_response_time_ms (média móvel)
```

### 18.2 Presence Monitor
```
A cada 30s:
  frame = webcam.capture()
  faces = FaceDetector.detect(frame)  # CLAHE + Haar + ROI guard
  confirmed = buffer.update(faces)    # 3 ticks consecutivos
  if confirmed and first_today:
    EventBus.publish("face_first_detection_today")
  if no_faces for 60 ticks:
    EventBus.publish("presence_lost")
  db.record(faces)
```

### 18.3 RAG Pipeline
```
1. VectorMemory.retrieve(query, user_id) → top 3 documentos
2. Monta bloco: "--- Memórias relevantes ---\n- ...\n--- Fim ---"
3. Anexa ao system_prompt ANTES da chamada ao LLM
4. Qwen E Gemini recebem o mesmo system_prompt enriquecido
```

### 18.4 Coder Engine
```
1. read_file(path) → código atual
2. LLM.generate(prompt + código) → novo código
3. sandbox(new_code) → cópia isolada
4. pytest(sandbox) → validação
5. if passed: backup(original) → promote(sandbox → original) → git commit
6. if failed: rollback → healing payload
```

---

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/NICKY_LEGACY_ANALYSIS.md
Descrição: Análise completa e revisada do sistema legado Nicky v0.7.0.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```
