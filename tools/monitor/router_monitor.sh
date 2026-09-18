#!/bin/bash
# =============================================================================
# Monitoramento do Roteador — OmegaDrakon
# =============================================================================
# Verifica a disponibilidade do roteador (ping no gateway) e o estado da
# interface de rede, correlacionando com eventos de link change do Tailscale.
#
# Uso:
#   ./router_monitor.sh              # execução contínua (intervalo de 1 min)
#   ./router_monitor.sh --once       # verificação única (é o que o timer usa)
#   ./router_monitor.sh --report     # relatório do log acumulado
#
# Saída (JSON-lines, um registro por verificação):
#   <OD_LOG_DIR>/router_monitor.log     {ts, local, gateway, status, latency_ms, detail?}
#   <OD_LOG_DIR>/interface_monitor.log  {ts, local, interface, state, carrier, speed}
#
# Configuração (env, todos opcionais):
#   OD_ROUTER_IP             gateway a pingar        (padrão 192.168.0.1)
#   OD_NETWORK_INTERFACE     interface a observar    (padrão wlx000f0037acf0)
#   OD_MONITOR_INTERVAL      segundos entre ciclos   (padrão 60)
#   OD_MONITOR_PING_TIMEOUT  timeout do ping (s)     (padrão 2)
#   OD_MONITOR_MAX_BYTES     tamanho que dispara a rotação do log (padrão 5 MiB)
#   OD_LOG_DIR               diretório dos logs      (padrão <repo>/logs)
#
# Exit code: `--once` sai 0 sempre que a verificação rodou — inclusive com o
# roteador FORA. O estado fica no log, e o evento não é erro do monitor: sair
# != 0 faria o unit marcar falha a cada minuto durante uma queda (ruído no
# journal, que é justamente o que a operação deste núcleo evita).
#
# HISTÓRICO (2026-09-18) — por que o script mudou:
#   Ele rodou 17h em produção com 1086 registros "up" e ZERO "down". Não era o
#   roteador: era o `set -e` combinado com `x=$(comando que falha)`.
#     - o ping que falha (roteador fora) derrubava o script ANTES do registro
#       do "down" — o monitor era cego para o único evento que ele existe para
#       medir;
#     - o `cat` de /sys/class/net/<if>/carrier com a interface ausente (nome
#       trocado, adaptador desconectado) abortava o script antes de gravar a
#       linha da interface.
#   Correção na raiz: o script NÃO usa mais `set -e` (monitor precisa sobreviver
#   a falha transitória, não morrer por causa dela) e todo comando externo tem
#   fallback explícito (`|| true` + default numérico), garantindo que a linha
#   de registro sempre saia.
# =============================================================================

# Sem `-e` de propósito: ver o HISTÓRICO acima. `-u` e `pipefail` continuam.
set -uo pipefail

# -- Configuração -------------------------------------------------------------

GATEWAY="${OD_ROUTER_IP:-192.168.0.1}"
INTERFACE="${OD_NETWORK_INTERFACE:-wlx000f0037acf0}"
INTERVAL="${OD_MONITOR_INTERVAL:-60}"
PING_TIMEOUT_S="${OD_MONITOR_PING_TIMEOUT:-2}"
MAX_LOG_BYTES="${OD_MONITOR_MAX_BYTES:-5242880}"
LOG_DIR="${OD_LOG_DIR:-$(dirname "$0")/../../logs}"
LOG_FILE="${LOG_DIR}/router_monitor.log"
INTERFACE_LOG="${LOG_DIR}/interface_monitor.log"
REPORT_FILE="${LOG_DIR}/router_monitor_report.txt"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

mkdir -p "$LOG_DIR" || true

# -- Utilidades ---------------------------------------------------------------

# Milissegundos desde a época. `date +%s%3N` não existe em todo lugar
# (busybox/BSD): se vier algo que não é número puro, cai para segundos × 1000.
now_ms() {
    local ms
    ms=$(date +%s%3N 2>/dev/null || true)
    case "$ms" in
        '' | *[!0-9]*) printf '%s' "$(( $(date +%s) * 1000 ))" ;;
        *) printf '%s' "$ms" ;;
    esac
}

# Mantém UMA geração anterior (`<log>.1`) quando o arquivo passa do limite.
# Sem isso o log cresce sem teto (1 linha/min ≈ 130 MB/ano nesta instalação).
rotate_if_needed() {
    local file="$1"
    [ -f "$file" ] || return 0
    local size
    size=$(wc -c < "$file" 2>/dev/null || echo 0)
    case "$size" in
        '' | *[!0-9]*) return 0 ;;
    esac
    if [ "$size" -ge "$MAX_LOG_BYTES" ]; then
        mv -f "$file" "${file}.1" 2>/dev/null || true
    fi
}

# Registra uma verificação do roteador (uma linha JSON por chamada).
log_event() {
    local status="$1"
    local latency_ms="$2"
    local detail="${3:-}"
    local timestamp local_time json

    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "?")
    local_time=$(date +"%Y-%m-%d %H:%M:%S %z" 2>/dev/null || echo "?")
    # Aspas dentro do detail quebrariam o JSON-lines (o relatório depende disso).
    detail="${detail//\"/\'}"

    rotate_if_needed "$LOG_FILE"

    json="{\"ts\":\"${timestamp}\",\"local\":\"${local_time}\",\"gateway\":\"${GATEWAY}\",\"status\":\"${status}\",\"latency_ms\":${latency_ms}"
    if [ -n "$detail" ]; then
        json="${json},\"detail\":\"${detail}\""
    fi
    json="${json}}"

    echo "$json" >> "$LOG_FILE"
}

# -- Verificações -------------------------------------------------------------

# Ping no gateway. Sempre registra; o retorno diz só se está de pé.
check_router() {
    local start_ms end_ms latency_ms real_latency ping_result

    start_ms=$(now_ms)

    # `if comando=$(...)` em vez de `cmd; local code=$?`: com o antigo `set -e`,
    # o ping que falhava matava o script antes do registro do "down".
    if ping_result=$(ping -c 1 -W "$PING_TIMEOUT_S" "$GATEWAY" 2>&1); then
        end_ms=$(now_ms)
        latency_ms=$(( end_ms - start_ms ))
        real_latency=$(printf '%s\n' "$ping_result" | grep -oP 'time=\K[0-9.]+' || true)
        real_latency="${real_latency:-$latency_ms}"
        log_event "up" "$real_latency" ""
        printf '%b✓%b Router UP | %sms | %s\n' \
            "$GREEN" "$NC" "$real_latency" "$(date +%H:%M:%S)"
        return 0
    fi

    end_ms=$(now_ms)
    latency_ms=$(( end_ms - start_ms ))
    log_event "down" "$latency_ms" "ping_failed"
    printf '%b✗%b Router DOWN | %sms | %s\n' \
        "$RED" "$NC" "$latency_ms" "$(date +%H:%M:%S)"
    return 1
}

# Estado da interface (operstate/carrier/speed), sempre registrado.
check_interface() {
    local state carrier speed timestamp local_time

    state=$(cat "/sys/class/net/$INTERFACE/operstate" 2>/dev/null || true)
    state="${state:-unknown}"
    # `|| true` no FIM da pipeline: com pipefail, um `cat` que falha (interface
    # renomeada ou removida) abortava o script antes de gravar esta linha.
    carrier=$(cat "/sys/class/net/$INTERFACE/carrier" 2>/dev/null | tr -d '\n' || true)
    speed=$(cat "/sys/class/net/$INTERFACE/speed" 2>/dev/null | tr -d '\n' || true)
    # carrier/speed entram no JSON sem aspas: precisam ser numéricos.
    case "${carrier:-}" in '' | *[!0-9]*) carrier=0 ;; esac
    case "${speed:-}" in '' | *[!0-9]*) speed=0 ;; esac

    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "?")
    local_time=$(date +"%Y-%m-%d %H:%M:%S %z" 2>/dev/null || echo "?")

    rotate_if_needed "$INTERFACE_LOG"
    echo "{\"ts\":\"${timestamp}\",\"local\":\"${local_time}\",\"interface\":\"${INTERFACE}\",\"state\":\"${state}\",\"carrier\":${carrier},\"speed\":${speed}}" \
        >> "$INTERFACE_LOG"

    if [ "$state" = "up" ]; then
        printf '%b●%b Interface %s: %s (carrier=%s)\n' \
            "$GREEN" "$NC" "$INTERFACE" "$state" "$carrier"
    else
        printf '%b●%b Interface %s: %s (carrier=%s)\n' \
            "$RED" "$NC" "$INTERFACE" "$state" "$carrier"
    fi
}

# Quantos link changes do Tailscale na última hora (correlação com quedas).
check_tailscale_links() {
    command -v journalctl >/dev/null 2>&1 || return 0

    local count
    count=$(journalctl --since "1 hour ago" --no-pager 2>/dev/null \
        | grep -c "LinkChange: major" || true)
    case "${count:-}" in '' | *[!0-9]*) count=0 ;; esac

    if [ "$count" -gt 0 ]; then
        printf '%b⚠%b %s LinkChange(s) do Tailscale na última hora\n' \
            "$YELLOW" "$NC" "$count"
    fi
}

# -- Relatório ----------------------------------------------------------------

generate_report() {
    echo "=========================================="
    echo "  RELATÓRIO DE MONITORAMENTO DO ROTEADOR"
    echo "  $(date +"%Y-%m-%d %H:%M:%S")"
    echo "=========================================="
    echo ""

    if [ ! -f "$LOG_FILE" ]; then
        echo "Nenhum dado de monitoramento encontrado."
        echo "Execute: $0"
        return 0
    fi

    local total up down uptime_pct
    total=$(wc -l < "$LOG_FILE" 2>/dev/null | tr -d '[:space:]' || echo 0)
    up=$(grep -c '"status":"up"' "$LOG_FILE" 2>/dev/null || true)
    down=$(grep -c '"status":"down"' "$LOG_FILE" 2>/dev/null || true)
    case "${up:-}" in '' | *[!0-9]*) up=0 ;; esac
    case "${down:-}" in '' | *[!0-9]*) down=0 ;; esac

    echo "Resumo:"
    echo "  Total de verificações: $total"
    printf '  %bRouter UP: %s%b\n' "$GREEN" "$up" "$NC"
    printf '  %bRouter DOWN: %s%b\n' "$RED" "$down" "$NC"
    if [ "${total:-0}" -gt 0 ]; then
        uptime_pct=$(echo "scale=1; $up * 100 / $total" | bc 2>/dev/null || true)
        echo "  Uptime: ${uptime_pct:-N/A}%"
    fi
    echo ""

    if ! command -v python3 >/dev/null 2>&1; then
        echo "(python3 ausente: sem as seções detalhadas)"
        echo "Log completo: $LOG_FILE"
        return 0
    fi

    echo "Últimas 10 verificações:"
    tail -10 "$LOG_FILE" | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line.strip())
        status = '✓' if d['status'] == 'up' else '✗'
        print(f'  {status} {d[\"local\"]} | {d[\"latency_ms\"]}ms | {d.get(\"detail\", \"\")}')
    except Exception:
        pass
"
    echo ""

    echo "Incidentes por dia (registros com status=down):"
    python3 -c "
import json
from collections import defaultdict

events = []
with open('${LOG_FILE}') as f:
    for line in f:
        try:
            events.append(json.loads(line.strip()))
        except Exception:
            pass

if not events:
    print('  Nenhum evento registrado')
else:
    by_date = defaultdict(list)
    for e in events:
        by_date[e['local'][:10]].append(e)

    for date in sorted(by_date):
        downs = [e for e in by_date[date] if e.get('status') == 'down']
        if downs:
            print(f'  {date}: {len(downs)} registro(s) down')
            for d in downs[:5]:
                print(f'    - {d[\"local\"]} ({d.get(\"detail\", \"\")})')
"
    echo ""
    echo "Log completo: $LOG_FILE"
    if [ -f "${LOG_FILE}.1" ]; then
        echo "Geração anterior: ${LOG_FILE}.1"
    fi
    return 0
}

# -- Principal ----------------------------------------------------------------

main() {
    local mode="${1:-}"

    case "$mode" in
        --report)
            generate_report
            exit 0
            ;;
        --once)
            echo "=== Verificação Única do Roteador ==="
            echo "Gateway: $GATEWAY"
            echo "Interface: $INTERFACE"
            echo ""
            check_router || true
            check_interface
            check_tailscale_links
            # 0 de propósito, mesmo com o roteador fora: ver o cabeçalho.
            exit 0
            ;;
        *)
            echo "=== Monitoramento do Roteador - OmegaDrakon ==="
            echo "Gateway: $GATEWAY"
            echo "Interface: $INTERFACE"
            echo "Intervalo: ${INTERVAL}s"
            echo "Log: $LOG_FILE"
            echo ""
            echo "Pressione Ctrl+C para parar"
            echo ""

            check_router || true
            check_interface
            echo ""

            while true; do
                sleep "$INTERVAL"
                check_router || true
                check_interface
                check_tailscale_links
            done
            ;;
    esac
}

main "$@"
