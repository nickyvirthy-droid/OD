#!/usr/bin/env bash
# Instala as regras udev que montam as HDs externas do Omega Drakon quando
# elas aparecem (trocar de porta USB deixa de exigir comando manual).
#
# Uso: sudo bash runtime/udev/install.sh
#
# Por que existe: em 08/11/2026 a troca de porta da HD "Arquivos" derrubou o
# mount e o /health ficou "HD desconectada" por dois dias, embora o disco
# estivesse plugado. O fstab já estava certo (UUID + nofail); faltava só
# remontar no hotplug.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGRA="99-omega-hds.rules"
DESTINO="/etc/udev/rules.d/$REGRA"

if [[ ${EUID} -ne 0 ]]; then
    echo "precisa de root: sudo bash $0" >&2
    exit 1
fi

install -m 0644 -o root -g root "$AQUI/$REGRA" "$DESTINO"
udevadm control --reload-rules
echo "✅ $DESTINO instalado"

# Conferência: cada UUID do arquivo precisa casar no udev do host. O device
# pode não estar plugado agora — nesse caso só avisamos.
while IFS= read -r uuid; do
    dev="/dev/disk/by-uuid/$uuid"
    if [[ ! -e $dev ]]; then
        echo "• $uuid: não plugado agora (regra vale no próximo plug)"
        continue
    fi
    sys="/sys$(udevadm info -q path -n "$dev")"
    # saída em variável: `udevadm test | grep -q` morre por SIGPIPE e o
    # pipefail derrubaria o script sem a regra estar errada.
    saida="$(udevadm test "$sys" 2>&1 || true)"
    if grep -q "$REGRA" <<<"$saida"; then
        disco="$(basename "$(readlink -f "$dev")")"
        ponto="$(findmnt -n -o TARGET --source "$(readlink -f "$dev")" 2>/dev/null || echo 'sem mount')"
        echo "• $uuid: regra OK ($disco → $ponto)"
    else
        echo "• $uuid: a regra NÃO casou — verifique o ID_FS_UUID" >&2
        exit 1
    fi
done < <(grep -o 'ID_FS_UUID}=="[0-9a-f-]*"' "$DESTINO" | cut -d'"' -f2)

echo
echo "A regra dispara quando a partição aparece (plug/boot). Mount caído com"
echo "a HD já plugada (umount manual, erro de I/O) continua exigindo:"
echo "  systemctl start <unit-do-mount>"
