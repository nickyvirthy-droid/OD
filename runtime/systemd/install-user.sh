#!/usr/bin/env bash
# Instala as units de usuário do Omega Drakon (LLM + CORE + CONTROL BRIDGE +
# MONITOR DO ROTEADOR) e ativa o auto-start.
# Uso: bash runtime/systemd/install-user.sh (como o próprio usuário 'alex').
set -euo pipefail

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

cp runtime/systemd/od-llm.service \
   runtime/systemd/od-core.service \
   runtime/systemd/od-control-bridge.service \
   runtime/systemd/router-monitor.service \
   runtime/systemd/router-monitor.timer \
   runtime/systemd/network-watchdog.service \
   runtime/systemd/network-watchdog.timer \
   runtime/systemd/od-vigia-mensagens.service \
   runtime/systemd/od-vigia-mensagens.timer "$UNIT_DIR/"

systemctl --user daemon-reload
systemctl --user enable od-llm.service od-core.service od-control-bridge.service
systemctl --user restart od-llm.service od-core.service od-control-bridge.service

# Monitor do roteador: quem manda é o TIMER (o service é oneshot, rodado a cada
# minuto); habilitar o service não faz sentido. `enable --now` evita ter de
# esperar o próximo boot para o monitor entrar no ar.
systemctl --user enable --now router-monitor.timer

# Vigia da Rede: mesmo molde — timer de 5 min chamando o oneshot.
systemctl --user enable --now network-watchdog.timer

# Vigia das Mensagens (26/10): mesmo molde — timer DIÁRIO (04:30) chamando
# o oneshot que audita as últimas 24 h de conversa e conserta causas
# determinísticas (CoderEngine + gate + rollback; o que não tem estratégia
# vira fila com motivo no Telegram/relatório).
systemctl --user enable --now od-vigia-mensagens.timer

echo "✅ Units instaladas e ativadas:"
systemctl --user status od-llm.service od-core.service od-control-bridge.service \
    router-monitor.timer network-watchdog.timer --no-pager | head -45

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

if systemctl --user is-enabled router-monitor.timer >/dev/null 2>&1; then
    echo "✅ router-monitor.timer habilitado (monitoramento do roteador)"
else
    echo "⚠️  router-monitor.timer NÃO habilitado — rode:"
    echo "   systemctl --user enable --now router-monitor.timer"
fi

if systemctl --user is-enabled od-vigia-mensagens.timer >/dev/null 2>&1; then
    echo "✅ od-vigia-mensagens.timer habilitado (auditoria diária do chat, 04:30)"
else
    echo "⚠️  od-vigia-mensagens.timer NÃO habilitado — rode:"
    echo "   systemctl --user enable --now od-vigia-mensagens.timer"
fi
