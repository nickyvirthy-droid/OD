#!/usr/bin/env bash
# =============================================================================
# OMEGA DRAKON — vigia de energia: permissão de desligar sem prompt
# Uso: sudo bash runtime/setup/energia_polkit.sh
#
# O od-core roda como usuário comum; `systemctl poweroff` pede autenticação
# (polkit auth_admin). Com esta regra, o vigia de energia consegue desligar a
# Nicky de forma graciosa quando a queda é confirmada. Rodar uma vez só.
# =============================================================================
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "❌ rode com sudo: sudo bash runtime/setup/energia_polkit.sh" >&2
    exit 1
fi

AQUI="$(cd "$(dirname "$0")" && pwd)"
DESTINO=/etc/polkit-1/rules.d/49-od-energia.rules

install -m 0644 "$AQUI/od-energia.rules" "$DESTINO"
systemctl restart polkit.service 2>/dev/null || true

echo "✅ regra instalada em $DESTINO"
echo "   verificação (deve sair 0):"
echo "   pkcheck --action-id org.freedesktop.login1.power-off --process \$\$ && echo autorizado"
