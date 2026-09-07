#!/usr/bin/env bash
# Instala as units de usuário do Omega Drakon (LLM + CORE + CONTROL BRIDGE)
# e ativa o auto-start. Uso: bash runtime/systemd/install-user.sh
# (como o próprio usuário 'alex').
set -euo pipefail

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

cp runtime/systemd/od-llm.service \
   runtime/systemd/od-core.service \
   runtime/systemd/od-control-bridge.service "$UNIT_DIR/"

systemctl --user daemon-reload
systemctl --user enable od-llm.service od-core.service od-control-bridge.service
systemctl --user restart od-llm.service od-core.service od-control-bridge.service

echo "✅ Units instaladas e ativadas:"
systemctl --user status od-llm.service od-core.service od-control-bridge.service \
    --no-pager | head -30

echo
echo "💡 Para manter o OD no ar após logout/reboot (recomendado):"
echo "   sudo loginctl enable-linger $USER"

# Verifica se linger já está ativo
if systemctl --user is-enabled od-core.service >/dev/null 2>&1; then
    echo "✅ od-core.service habilitado (auto-start no boot)"
else
    echo "⚠️  od-core.service NÃO habilitado — rode:"
    echo "   systemctl --user enable od-core.service"
fi
