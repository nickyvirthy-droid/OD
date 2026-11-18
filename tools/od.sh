#!/usr/bin/env bash
#
# od - Sessão persistente de CLIs de código no tmux (OmegaDrakon).
#
# Se o terminal SSH cair, a CLI continua rodando no servidor.
# Basta conectar de novo e rodar este script para voltar para a sessão.
#
# Uso:
#   od                 -> menu para escolher a CLI
#   od <cli>           -> abre a CLI numa janela própria
#                         (opencode|kilo|freebuff|aider|agy|openclaude|
#                          openclaw|interpreter|claude|codex|gemini|qwen|
#                          crush|cline)
#   od status          -> mostra se a sessão está rodando e as janelas
#   od lista           -> lista as janelas da sessão
#   od log [cli]       -> mostra as últimas linhas da janela da CLI
#   od shell           -> abre um shell dentro da sessão
#   od doctor          -> testa caminho/versão de cada CLI (e o que instalar)
#   od instalar <cli>  -> mostra o comando de instalação da CLI ausente
#   od reinicia [cli]  -> recria a sessão (ou só a janela da CLI)
#   od sai             -> desconecta sem matar (igual a Ctrl-b d)
#   od mata            -> encerra a sessão e todo o serviço
#   od fecha <cli>     -> encerra só a janela daquela CLI
#
# Variáveis de ambiente:
#   OD_SESSION                      nome da sessão tmux (padrão: clis)
#   OD_SHELL                        shell da janela "shell"
#   OD_<CLI>_BIN                    força o binário (ex.: OD_KILO_BIN=/caminho)
#   OD_OPENCLAUDE_DIR               pasta do OpenClaude Portable
#
set -euo pipefail

# Node 22 LTS por usuário: Gemini/Codex/Claude exigem >=20 e o sistema tem 18.
if [ -d "$HOME/.local/opt/node/bin" ]; then
  case ":$PATH:" in
    *":$HOME/.local/opt/node/bin:"*) ;;
    *) export PATH="$HOME/.local/opt/node/bin:$PATH" ;;
  esac
fi

# Janelas de um servidor tmux antigo herdam o PATH do servidor; atualiza.
if command -v tmux >/dev/null 2>&1; then
  tmux set-environment -g PATH "$PATH" 2>/dev/null || true
fi

VERSAO="1.2.0"
SESSAO="${OD_SESSION:-clis}"
SHELL_EXTERNO="${OD_SHELL:-/usr/bin/env bash}"
TITULO="OD — CLIs de código (OmegaDrakon)"

# Resolve um binário: candidatos explícitos, depois o PATH.
# Sempre devolve 0 para não derrubar o script com "set -e".
resolver_bin() {
  local nome="$1"
  shift
  local c
  for c in "$@"; do
    if [ -n "$c" ] && [ -x "$c" ]; then
      printf '%s' "$c"
      return 0
    fi
  done
  c="$(command -v "$nome" 2>/dev/null || true)"
  if [ -n "$c" ] && [ -x "$c" ]; then
    printf '%s' "$c"
  fi
  return 0
}

OPENCODE_BIN="${OD_OPENCODE_BIN:-$(resolver_bin opencode \
  "$HOME/.npm-global/bin/opencode" \
  "$HOME/.npm-global/lib/node_modules/@opencode/cli/bin/opencode.exe" \
  "$HOME/.local/bin/opencode")}"

KILO_BIN="${OD_KILO_BIN:-$(resolver_bin kilo \
  "$HOME/.npm-global/lib/node_modules/@kilocode/cli/bin/kilo" \
  "$HOME/.npm-global/bin/kilo")}"
FREEBUFF_BIN="${OD_FREEBUFF_BIN:-$(resolver_bin freebuff \
  "/usr/local/bin/freebuff")}"
AIDER_BIN="${OD_AIDER_BIN:-$(resolver_bin aider \
  "$PWD/.venv/bin/aider" \
  "$HOME/OmegaDrakon/.venv/bin/aider")}"
AGY_BIN="${OD_AGY_BIN:-$(resolver_bin agy \
  "$HOME/.local/bin/agy")}"
OPENCLAUDE_DIR="${OD_OPENCLAUDE_DIR:-$HOME/OpenClaude-Portable-main}"
OPENCLAUDE_BIN="${OD_OPENCLAUDE_BIN:-}"
if [ -z "$OPENCLAUDE_BIN" ] && [ -x "$OPENCLAUDE_DIR/start.sh" ]; then
  OPENCLAUDE_BIN="$OPENCLAUDE_DIR/start.sh"
fi
OPENCLAW_BIN="${OD_OPENCLAW_BIN:-$(resolver_bin openclaw \
  "/opt/omegadrakon/builders/openclaw/bin/openclaw")}"
INTERPRETER_BIN="${OD_INTERPRETER_BIN:-$(resolver_bin interpreter \
  "/opt/omegadrakon/builders/open-interpreter/.venv/bin/interpreter")}"

# CLIs de código ainda não instaladas: o menu mostra a instrução.
CLAUDE_BIN="${OD_CLAUDE_BIN:-$(resolver_bin claude "$HOME/.npm-global/bin/claude")}"
CODEX_BIN="${OD_CODEX_BIN:-$(resolver_bin codex "$HOME/.npm-global/bin/codex")}"
GEMINI_BIN="${OD_GEMINI_BIN:-$(resolver_bin gemini "$HOME/.npm-global/bin/gemini")}"
QWEN_BIN="${OD_QWEN_BIN:-$(resolver_bin qwen "$HOME/.npm-global/bin/qwen")}"
CRUSH_BIN="${OD_CRUSH_BIN:-$(resolver_bin crush "$HOME/.npm-global/bin/crush")}"
CLINE_BIN="${OD_CLINE_BIN:-$(resolver_bin cline "$HOME/.npm-global/bin/cline")}"

# Ordem preferida no menu.
CLIS=(
  opencode kilo freebuff aider agy openclaude openclaw interpreter
  claude codex gemini qwen crush cline
)

rotulo() {
  case "$1" in
    opencode)    echo "OpenCode" ;;
    kilo)        echo "Kilo Code" ;;
    freebuff)    echo "Freebuff" ;;
    aider)       echo "Aider" ;;
    agy)         echo "Antigravity (agy)" ;;
    openclaude)  echo "OpenClaude (portátil)" ;;
    openclaw)    echo "OpenClaw" ;;
    interpreter) echo "Open Interpreter" ;;
    claude)      echo "Claude Code" ;;
    codex)       echo "OpenAI Codex" ;;
    gemini)      echo "Gemini CLI" ;;
    qwen)        echo "Qwen Code" ;;
    crush)       echo "Crush" ;;
    cline)       echo "Cline" ;;
    *)           echo "$1" ;;
  esac
}

binario() {
  case "$1" in
    opencode)    printf '%s' "$OPENCODE_BIN" ;;
    kilo)        printf '%s' "$KILO_BIN" ;;
    freebuff)    printf '%s' "$FREEBUFF_BIN" ;;
    aider)       printf '%s' "$AIDER_BIN" ;;
    agy)         printf '%s' "$AGY_BIN" ;;
    openclaude)  printf '%s' "$OPENCLAUDE_BIN" ;;
    openclaw)    printf '%s' "$OPENCLAW_BIN" ;;
    interpreter) printf '%s' "$INTERPRETER_BIN" ;;
    claude)      printf '%s' "$CLAUDE_BIN" ;;
    codex)       printf '%s' "$CODEX_BIN" ;;
    gemini)      printf '%s' "$GEMINI_BIN" ;;
    qwen)        printf '%s' "$QWEN_BIN" ;;
    crush)       printf '%s' "$CRUSH_BIN" ;;
    cline)       printf '%s' "$CLINE_BIN" ;;
  esac
  return 0
}

disponivel() {
  [ -n "$(binario "$1")" ]
}

comando_cli() {
  local cli="$1"
  local bin
  bin="$(binario "$cli")"
  case "$cli" in
    openclaude) printf 'bash %q --offline' "$bin" ;;
    openclaw)   printf '%q chat' "$bin" ;;
    *)          printf '%q' "$bin" ;;
  esac
}

pacote_npm() {
  case "$1" in
    claude) echo "@anthropic-ai/claude-code" ;;
    codex)  echo "@openai/codex" ;;
    gemini) echo "@google/gemini-cli" ;;
    qwen)   echo "@qwen-code/qwen-code" ;;
    crush)  echo "@charmland/crush" ;;
    cline)  echo "cline" ;;
  esac
}

instalacao() {
  local cli="$1"
  local pacote
  pacote="$(pacote_npm "$cli")"
  if [ -z "$pacote" ]; then
    return 0
  fi
  # O prefixo global desta máquina é /usr/local (sem permissão de escrita):
  # instalar no prefixo do usuário, que já está no PATH.
  printf 'npm install -g --prefix "$HOME/.npm-global" %s' "$pacote"
}

sessao_existe() {
  tmux has-session -t "=$SESSAO" 2>/dev/null
}

janela_existe() {
  tmux list-windows -t "=$SESSAO" -F '#{window_name}' 2>/dev/null | grep -Fxq "$1"
}

exigir_sessao() {
  if ! sessao_existe; then
    echo "Sessão '$SESSAO' não está rodando. Use: od <cli>"
    return 1
  fi
}

cmd_status() {
  if sessao_existe; then
    echo "✔ Sessão '$SESSAO' rodando:"
    tmux list-windows -t "=$SESSAO" -F '  #{window_index}: #{window_name} #{?window_active,[ativa],}'
  else
    echo "✘ Sessão '$SESSAO' não está rodando."
    return 1
  fi
}

cmd_lista() {
  exigir_sessao || return 1
  tmux list-windows -t "=$SESSAO" -F '#{window_index}: #{window_name}'
}

conectar() {
  local alvo="=$SESSAO${1:+:$1}"
  if [ -n "${TMUX:-}" ]; then
    tmux switch-client -t "$alvo" 2>/dev/null \
      || tmux attach-session -t "$alvo" 2>/dev/null \
      || true
    return 0
  fi
  exec tmux attach-session -t "$alvo"
}

cmd_instrucoes() {
  local cli="$1"
  local comando
  comando="$(instalacao "$cli")"
  if [ -z "$comando" ]; then
    echo "'$cli' não está instalada e não há receita automática registrada." >&2
    return 1
  fi
  echo "$(rotulo "$cli") não está instalada."
  echo
  echo "Instale com:"
  echo "  $comando"
  if [ "$(pacote_npm "$cli")" != "cline" ]; then
    echo
    echo "O binário fica em \$HOME/.npm-global/bin (já presente no PATH)."
  fi
  echo
  echo "Depois abra com: od $cli"
}

abrir_cli() {
  local cli="$1"
  local bin nome cmd
  bin="$(binario "$cli")"
  nome="$(rotulo "$cli")"
  if [ -z "$bin" ]; then
    cmd_instrucoes "$cli"
    return 1
  fi

  cmd="$(comando_cli "$cli")"
  local criada=0
  if ! sessao_existe; then
    tmux new-session -d -s "$SESSAO" -n "$cli" -c "$PWD"
    criada=1
  elif ! janela_existe "$cli"; then
    tmux new-window -t "=$SESSAO" -n "$cli" -c "$PWD"
    criada=1
  fi

  # Só digita o comando em janela recém-criada (evita rodar duas vezes).
  if [ "$criada" -eq 1 ]; then
    tmux send-keys -t "=$SESSAO:$cli" -l "$cmd"
    tmux send-keys -t "=$SESSAO:$cli" C-m
  fi

  echo "▶ $nome em '$SESSAO:$cli' ($bin)"
  conectar "$cli"
}

cmd_shell() {
  if ! sessao_existe; then
    tmux new-session -d -s "$SESSAO" -n shell -c "$PWD" "$SHELL_EXTERNO"
  elif ! janela_existe shell; then
    tmux new-window -t "=$SESSAO" -n shell -c "$PWD" "$SHELL_EXTERNO"
  fi
  conectar shell
}

cmd_log() {
  exigir_sessao || return 1
  local cli="${1:-}"
  if [ -z "$cli" ]; then
    cli="$(tmux list-windows -t "=$SESSAO" -F '#{window_name}' | head -n1)"
  fi
  if ! janela_existe "$cli"; then
    echo "Janela '$cli' não existe. Janelas: $(tmux list-windows -t "=$SESSAO" -F '#{window_name}' | paste -sd', ' -)"
    return 1
  fi
  tmux capture-pane -pt "=$SESSAO:$cli" -S -300
}

cmd_mata() {
  if sessao_existe; then
    tmux kill-session -t "=$SESSAO"
    echo "Sessão '$SESSAO' encerrada."
  else
    echo "Sessão '$SESSAO' já não existe."
  fi
}

cmd_fecha() {
  local cli="${1:-}"
  if [ -z "$cli" ]; then
    echo "Uso: od fecha <cli>" >&2
    return 2
  fi
  exigir_sessao || return 1
  if janela_existe "$cli"; then
    tmux kill-window -t "=$SESSAO:$cli"
    echo "Janela '$cli' encerrada."
  else
    echo "Janela '$cli' não existe."
    return 1
  fi
}

cmd_reinicia() {
  local cli="${1:-}"
  if [ -n "$cli" ]; then
    if sessao_existe && janela_existe "$cli"; then
      tmux kill-window -t "=$SESSAO:$cli"
    fi
    abrir_cli "$cli"
    return 0
  fi
  cmd_mata || true
  echo "Sessão encerrada. Escolha uma CLI no menu."
  menu
}

cmd_doctor() {
  echo "od $VERSAO — sessão tmux: $SESSAO"
  echo
  local cli bin saida instaladas=0 ausentes=0
  for cli in "${CLIS[@]}"; do
    bin="$(binario "$cli")"
    if [ -z "$bin" ]; then
      ausentes=$((ausentes + 1))
      printf '✘ %-22s instalar: %s\n' "$(rotulo "$cli")" "$(instalacao "$cli")"
      continue
    fi
    instaladas=$((instaladas + 1))
    printf '✔ %-22s %s\n' "$(rotulo "$cli")" "$bin"
    case "$cli" in
      openclaude)
        printf '  launcher portátil (start.sh); provedor em %s/data/ai_settings.env\n' "$OPENCLAUDE_DIR"
        ;;
      interpreter)
        saida="$(timeout 20 "$bin" --version 2>&1 | grep -m1 'Open Interpreter' || true)"
        printf '  %s\n' "${saida:-sem saída de --version}"
        ;;
      *)
        saida="$(timeout 15 "$bin" --version 2>&1 | head -n 2 || true)"
        printf '  %s\n' "${saida:-sem saída de --version}"
        ;;
    esac
  done
  echo
  echo "$instaladas instalada(s), $ausentes ausente(s)."
}

mostrar_menu() {
  echo "╭─ $TITULO ─────────────────────────────────"
  echo "│  Sessão tmux: $SESSAO"
  echo "├───────────────────────────────────────────"
  MENU_ITENS=()
  local i=1 cli
  for cli in "${CLIS[@]}"; do
    if disponivel "$cli"; then
      MENU_ITENS[$i]="$cli"
      printf '│ %2d) %-24s disponível\n' "$i" "$(rotulo "$cli")"
      i=$((i + 1))
    fi
  done
  local tem_ausente=0
  for cli in "${CLIS[@]}"; do
    if ! disponivel "$cli"; then
      if [ "$tem_ausente" -eq 0 ]; then
        echo "├───────────────────────────────────────────"
        echo "│  Instalar:"
        tem_ausente=1
      fi
      MENU_ITENS[$i]="$cli"
      printf '│ %2d) %-24s não instalada\n' "$i" "$(rotulo "$cli")"
      i=$((i + 1))
    fi
  done
  unset "MENU_ITENS[$i]"
  echo "├───────────────────────────────────────────"
  echo "│  g) Shell          s) Status"
  echo "│  w) Janelas        l) Log de uma CLI"
  echo "│  d) Testar CLIs    k) Encerrar sessão"
  echo "│  q) Sair"
  echo "╰───────────────────────────────────────────"
}

menu() {
  local opcao cli
  MENU_ITENS=()
  while true; do
    mostrar_menu
    if ! read -r -p "Escolha: " opcao; then
      echo
      return 0
    fi
    case "${opcao,,}" in
      g|shell)         cmd_shell ;;
      s|status)        cmd_status || true ;;
      w|lista|janelas) cmd_lista || true ;;
      l|log)
        read -r -p "CLI para o log (vazio = primeira janela): " cli || true
        cmd_log "$cli" || true
        ;;
      d|doctor)        cmd_doctor ;;
      k|mata|kill)     cmd_mata ;;
      q|sair)          return 0 ;;
      "")
        ;;
      *)
        if [[ "$opcao" =~ ^[0-9]+$ ]] && [ -n "${MENU_ITENS[$opcao]:-}" ]; then
          abrir_cli "${MENU_ITENS[$opcao]}" || true
        else
          echo "Opção desconhecida: $opcao"
        fi
        ;;
    esac
    echo
  done
}

acao="${1:-menu}"

case "$acao" in
  menu|m|conecta|connect|up)
    menu
    ;;
  opencode|kilo|freebuff|aider|agy|openclaude|openclaw|interpreter|claude|codex|gemini|qwen|crush|cline)
    abrir_cli "$acao"
    ;;
  status)
    cmd_status
    ;;
  lista|ls|windows|janelas)
    cmd_lista
    ;;
  log|logs)
    shift || true
    cmd_log "${1:-}"
    ;;
  shell)
    cmd_shell
    ;;
  doctor|teste|testar)
    cmd_doctor
    ;;
  instalar|instala|instrucoes)
    shift || true
    cmd_instrucoes "${1:-}"
    ;;
  reinicia|restart)
    shift || true
    cmd_reinicia "${1:-}"
    ;;
  fecha|fecha-cli)
    shift || true
    cmd_fecha "${1:-}"
    ;;
  versao|version|-V|--version)
    echo "od $VERSAO"
    ;;
  sai|detach|d)
    if [ -n "${TMUX:-}" ]; then
      tmux detach-client
    else
      tmux detach-client -s "=$SESSAO" 2>/dev/null \
        || echo "Nada anexado à sessão '$SESSAO'."
    fi
    ;;
  mata|kill|down)
    cmd_mata
    ;;
  ajuda|-h|--help|help)
    sed -n '3,28p' "$0"
    ;;
  *)
    echo "Opção desconhecida: $acao (use: od ajuda)" >&2
    exit 2
    ;;
esac
