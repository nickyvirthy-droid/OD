#!/bin/sh
# OpenClaude headless — entrada do orquestrador do OmegaDrakon (18/11/2026).
#
# O `start.sh` do OpenClaude-Portable-main é um MENU interativo (banner,
# update check, "Select Action") — ele não aceita prompt. Quem aceita é a
# ENGINE `@gitlawb/openclaude` (fork do Claude Code): "starts an
# interactive session by default, use -p/--print for non-interactive
# output" (medido no --help de 18/11). Este wrapper aplica o MESMO perfil
# portátil do start.sh e executa a engine com os argumentos recebidos —
# o orquestrador monta `-p PROMPT --yolo --provider nvidia-nim --model …`.
#
# Prova em 18/11 (prompt real, sem cota de ninguém além do NIM free):
#   - exit=0, result "ok", 3 turns, 3,5s (modelo vivo)
#   - `--yolo` criou arquivo de verdade (/tmp/od_oc_yolo_teste.txt)
# O modelo gravado em data/ai_settings.env (deepseek-v3.1-terminus) está
# FORA do catálogo do NIM (404/EOL medido em 18/11) — por isso o --model
# vem do orquestrador, sem mexer no config do app do dono (regra 7).
set -e

ENGENHO=/home/alex/OpenClaude-Portable-main

# Perfil do provedor (switchboard do próprio app; não é segredo novo —
# o start.sh faz o mesmo `source`).
set -a
. "$ENGENHO/data/ai_settings.env"
set +a

# O engine pede NVIDIA_API_KEY para --provider nvidia-nim, mas o
# switchboard salva a mesma chave em OPENAI_API_KEY (start.sh:853).
export NVIDIA_API_KEY="${NVIDIA_API_KEY:-$OPENAI_API_KEY}"

# Estado portátil (mesmos exports do start.sh:170-177) — a sessão salva
# fica em data/, não no HOME real do dono.
export CLAUDE_CONFIG_DIR="$ENGENHO/data/openclaude"
export HOME="$ENGENHO/data/home"
export USERPROFILE="$HOME"
export APPDATA="$ENGENHO/data/app_data"
export LOCALAPPDATA="$ENGENHO/data/local_app_data"
export XDG_CONFIG_HOME="$ENGENHO/data/config"
export XDG_DATA_HOME="$ENGENHO/data/app_data"
export XDG_CACHE_HOME="$ENGENHO/data/cache"
export CLAUDE_CODE_PROVIDER_PROFILE_ENV_APPLIED=1
export CLAUDE_CODE_PROVIDER_PROFILE_ENV_APPLIED_ID=portable-env

# Node da própria engine (o PATH do serviço não tem node).
export PATH="$ENGENHO/engine/node-linux-x64/bin:$PATH"

exec "$ENGENHO/engine/node-linux-x64/bin/node" \
    "$ENGENHO/engine/node_modules/@gitlawb/openclaude/bin/openclaude" "$@"
