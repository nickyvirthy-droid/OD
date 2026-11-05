# IAs disponíveis nesta máquina — inventário e medição

> **Antes de pesquisar IAs de novo, leia este documento.** Ele foi medido em
> **05/11/2026** e existe para não repetir a pesquisa (ordem do dono:
> *"sempre guarde essas informações para não ser preciso refazer essas
> pesquisas"*). Só reavalie quando: (a) entrar chave/crédito novo; (b) mudar o
> hardware; (c) um provedor mudar de comportamento (registre a data da nova
> medição numa seção no fim).

## 1. O que existe (inventário)

### Locais (sem custo, sem cota, offline)

| Item | O que é | Como usar | Situação |
|---|---|---|---|
| `od-llm.service` | `llama-server` em `127.0.0.1:8081`, modelo `qwen2.5-coder-3b-instruct-q4_k_m` | `POST /v1/chat/completions` (API OpenAI-compat) | ativo; é o LLM do OD (chat/persona) |
| `/home/alex/llama.cpp/models/gemma-4-E4B-it-Q4_K_M.gguf` | 4,9 GB | — | **não cabe** com latência útil em 8 GB (provado 01/10: ~5 tok/s e resposta vazia no limite do OD) |
| `qwen2.5-coder-7b-instruct-q4_k_m.gguf` | 4,7 GB | — | não servido (RAM) |
| `qwen2.5-3b-instruct-q4_k_m.gguf` | 2,1 GB | — | não servido (alternativa "generalista" ao coder de 3B) |
| `Qwen2.5-0.5B-Instruct` | 0,5 GB | — | não servido (tarefas triviais) |
| `whisper.cpp` (`ggml-base`) | transcrição de voz | `tools/audio/stt.py` | em uso no bot/action `stt_transcrever` |

### Online com chave no `.env`

| Chave | Provedor | Estado em 05/11/2026 | Observação |
|---|---|---|---|
| `GEMINI_API_KEY` | Google (Gemini) | **válida** | só funciona com a chave no **header** `x-goog-api-key`; com `?key=` dá `400 API_KEY_INVALID` na MESMA chave |
| `GROQ_API_KEY` | Groq | **válida** | exige `User-Agent` de navegador (Cloudflare devolve 403 para o UA do Python) |
| `OPENAI_API_KEY` | OpenAI | **sem créditos** | `429 credit_balance_exhausted` |
| `OPENAI_API_KEY2` | OpenAI | **sem créditos** | idem |
| `HBOX_API_KEY` | Homebox | não é IA | inventário de bens |

O "cofre" (Vaultwarden) **só espelha o `.env`** via `vault_env_mirror.py`; não
há chave de IA adicional lá.

### CLIs de agente de código instalados

Estão em `/home/alex/.npm-global/bin` (fora do `PATH` padrão) e no venv do OD.

| CLI | Caminho | Versão / estado | Uso em lote |
|---|---|---|---|
| `freebuff` | `/usr/local/bin/freebuff` | 0.2.36 | agente interativo (TUI); `--help` só expõe `login`/`doctor` — não serve como API |
| `opencode` | `~/.npm-global/bin/opencode` | instalado | `opencode run --standalone --model <provider/modelo> "..."`; **a chave Google dele está inválida** (`API key not valid`) e o modelo `opencode/nemotron-3-ultra-free` citado no `orquestrador.py` **não existe mais** |
| `kilo` / `kilocode` | `~/.npm-global/bin/kilo` | 7.8.1 | `kilo run --model <id> "..."`; **pede login** (`You need to sign in to use this model`); ids mudaram (`kilo/~google/gemini-flash-latest` etc.) |
| `aider` | `OmegaDrakon/.venv/bin/aider` | instalado | precisa de modelo/credencial utilizável (OpenAI está sem créditos) |

> Conclusão: os CLIs são ferramentas de **código**, não motor de lote. Hoje
> nenhum deles está pronto para ser chamado dezenas de vezes por um pipeline.

## 2. Medição (o que decidiu a escolha)

Tarefa real do `musica.py`: mesmo `PROMPT_SISTEMA`, 3 faixas do acervo
(Marcio Couth — *Caminho no Deserto*; *Pais e Filhos*; medley da Morada).
Critérios: latência, aderência aos **8 campos** separados por `|` e acerto de
artista/gênero.

| Ordem | Provedor / modelo | Tempo | 8 campos | Acertos | Veredito |
|---|---|---|---|---|---|
| **1º** | `gemini-3-flash-preview` | 5,6 s | 3/3 | **3/3** | escolhido (padrão) |
| **2º** | groq `openai/gpt-oss-120b` | 3,4 s | 3/3 | **3/3** | reserva rápida |
| 3º | local `qwen2.5-coder-3b` | 31 s | 3/3 | 2/3 | último recurso |
| — | groq `qwen/qwen3.8-27b` | 1,3 s | 0/3 | 0/3 | descartado (ignora o formato) |
| — | OpenAI `gpt-5.4*` (2 chaves) | — | — | — | sem créditos |
| — | `opencode` / `kilo` (CLIs) | — | — | — | sem login/chave válida; pesados para lote |

## 3. Como está no código

`/home/alex/dados/musicas/musica.py` v1.10.0:

- `chamar_ia()` percorre a cadeia; falha de um provedor (429, 403, resposta
  vazia) passa para o próximo **sem backoff longo**;
- ordem padrão `gemini,groq,local`, configurável por `OD_IA_ORDEM`
  (ex.: `local,groq,gemini`);
- `chamar_gemini()` é o nome antigo mantido para os 4 pontos de chamada;
- variáveis: `GEMINI_MODEL`, `GROQ_MODEL`, `OD_GROQ_URL`, `OD_LLM_URL`,
  `OD_LLM_MODEL`.

## 4. Pegadinhas que já custaram tempo (não redescobrir)

1. **Gemini**: `?key=` na URL → `400 API_KEY_INVALID` mesmo com chave boa;
   header `x-goog-api-key` → 200. `API_KEY_INVALID` **não** é chave morta.
2. **Groq**: UA padrão do Python → `403` imediato (Cloudflare). Use
   `User-Agent` de navegador; `gpt-oss` é modelo de raciocínio — com
   `max_tokens` curto o `content` volta **vazio** (use ≥2000).
3. **IDs de modelo mudam** (`opencode/nemotron-3-ultra-free` e
   `kilo/nvidia/nemotron-3-super-120b-a12b:free` morreram). Liste antes:
   `opencode models`, `kilo models`.
4. **`HBOX` não é IA** (é Homebox). O cofre não tem chaves extras de IA.
5. **`gemma-4-E4B` em 8 GB** não é opção: ram + latência inviáveis.

## 5. Histórico de medições

| Data | O que mudou |
|---|---|
| 2026-11-05 | inventário inicial + benchmark (Gemini 3 Flash escolhido; Groq reserva; OpenAI sem créditos; CLIs sem login) |
