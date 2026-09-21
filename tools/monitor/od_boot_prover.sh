#!/usr/bin/env bash
# Prova de boot autônomo do OmegaDrakon (regra 12 — teste antes de afirmar).
#
# Roda como serviço one-shot do SYSTEM no boot (WantedBy=multi-user.target).
# O cenário provado: a máquina reiniciou, NINGUÉM logou, e a pilha tem de
# voltar sozinha — od-core (unidade de USUÁRIO de alex, mantenida pelo
# linger=yes) + Funnel/serve do tailscaled (config persistente do daemon).
#
# Este script NÃO inicia nada: só observa e grava evidência.
# Saída: /var/lib/od-boot-prover/last.txt (e cópia do journal do serviço).
set -uo pipefail

# Diretório de evidência (override por env só para ensaio como usuário comum)
OUT_DIR="${OD_BOOT_PROVER_DIR:-/var/lib/od-boot-prover}"
OUT="$OUT_DIR/last.txt"
FUNNEL_HOST="nicky-server.tail1b1f51.ts.net"

mkdir -p "$OUT_DIR"

{
  echo "=== od-boot-prover $(date --iso-8601=seconds) ==="
  echo "boot_id: $(cat /proc/sys/kernel/random/boot_id)"
  echo "uptime_s: $(cut -d' ' -f1 /proc/uptime)"

  # 1) Gerenciador de usuário do alex (linger — sobe SEM login)
  linger=$(loginctl show-user alex -p Linger 2>/dev/null | awk '{print $2}')
  echo "user_manager_linger: ${linger:-desconhecido}"
  umgr="inativo"
  systemctl is-active user@1000.service >/dev/null 2>&1 && umgr="ativo"
  echo "user_manager: $umgr"

  # 2) tailscaled (sistema) — quem executa o Funnel
  echo "tailscaled: $(systemctl is-active tailscaled 2>/dev/null) / $(systemctl is-enabled tailscaled 2>/dev/null)"

  # 3) Funnel/serve — estado persistido no daemon
  if command -v tailscale >/dev/null 2>&1; then
    # Conta só a linha de estado "(Funnel on)" — o cabeçalho "# Funnel on:"
    # também contém o texto e duplicaria a contagem.
    funnel=$(tailscale serve status 2>/dev/null | grep -c "(Funnel on)" || true)
    paths=$(tailscale serve status 2>/dev/null | grep -cE "proxy http://127.0.0.1:(8000|8001)" || true)
    echo "funnel_ativo: $funnel (1 = sim)"
    echo "funnel_caminhos_8000_8001: $paths (2 = / e /ws)"
  else
    echo "funnel_ativo: tailscale não encontrado no PATH"
  fi

  # 4) od-core (unidade de USUÁRIO) — usa o bus do alex via XDG_RUNTIME_DIR
  XDG_RUNTIME_DIR=/run/user/1000 systemctl --user -M alex@ is-active od-core >/dev/null 2>&1
  if [ $? -eq 0 ]; then
    pid=$(XDG_RUNTIME_DIR=/run/user/1000 systemctl --user -M alex@ show od-core -p MainPID --value 2>/dev/null)
    echo "od_core: ativo (MainPID=$pid)"
  else
    echo "od_core: INATIVO"
  fi

  # 5) Portas locais respondendo (REST e WS) —probe HTTP direto
  code8000=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/health || echo 000)
  code8001=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8001/ 2>/dev/null || echo 000)
  echo "rest_8000_health: HTTP $code8000 (401 = API no ar exigindo chave)"
  echo "ws_8001: HTTP $code8001 (426 = servidor WS no ar)"

  # 6) Probe do Funnel pela URL pública — só conta quando a rede já subiu
  #    (antes disso o próprio prover ainda nem teria rede para resolver DNS;
  #    por isso tenta até 3x com espera e registra o melhor resultado).
  best=000
  for _ in 1 2 3; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "https://$FUNNEL_HOST/health" || echo 000)
    [ "$code" != "000" ] && { best=$code; break; }
    sleep 10
  done
  echo "funnel_https_health: HTTP $best (401 = chegou no od-core pela internet)"

  echo "=== fim ==="
} > "$OUT" 2>&1

# RESULTADO em uma linha: tudo que tem de estar de pé, de pé.
ok=1
grep -q "user_manager: ativo" "$OUT" || ok=0
grep -q "tailscaled: active" "$OUT" || ok=0
grep -q "funnel_ativo: 1 " "$OUT" || ok=0
grep -q "funnel_caminhos_8000_8001: 2 " "$OUT" || ok=0
grep -q "od_core: ativo" "$OUT" || ok=0
grep -q "rest_8000_health: HTTP 401" "$OUT" || ok=0
grep -q "ws_8001: HTTP 426" "$OUT" || ok=0
if [ "$ok" -eq 1 ]; then
  echo "RESULTADO: BOOT_AUTONOMO_OK" >> "$OUT"
else
  echo "RESULTADO: FALHOU (ver linhas acima)" >> "$OUT"
fi

chmod 644 "$OUT"
cat "$OUT"
