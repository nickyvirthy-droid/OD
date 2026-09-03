#!/usr/bin/env bash
# Instala as units de usuário do Omega Drakon (LLM + CORE) e ativa o auto-start.
# Uso: bash runtime/systemd/install-user.sh   (como o próprio usuário 'alex')
set -euo pipefail

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

cp runtime/systemd/od-llm.service runtime/systemd/od-core.service "$UNIT_DIR/"

systemctl --user daemon-reload
systemctl --user enable od-llm.service od-core.service
systemctl --user restart od-llm.service od-core.service

echo "✅ Units instaladas e ativadas:"
systemctl --user status od-llm.service od-core.service --no-pager | head -20

echo
echo "💡 Para manter o OD no ar após logout/reboot (recomendado):"
echo "   sudo loginctl enable-linger $USER"
