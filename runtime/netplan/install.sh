#!/usr/bin/env bash
# Instala o Wi-Fi de reserva do Omega Drakon (dongle USB em 192.168.0.250).
#
# Uso: sudo bash runtime/netplan/install.sh
#      sudo bash runtime/netplan/install.sh --aplicar
#      sudo bash runtime/netplan/install.sh --mac 00:11:22:33:44:55 --psk 'senha'
#
# Por que existe: em 08/11/2026 a reserva vivia só no /etc/netplan/50-cloud-init.yaml,
# que é gerado pelo cloud-init — uma reinstalação (ou uma regeração) apagaria a
# única segunda saída de rede do servidor. Este instalador leva a configuração
# provada em produção para dentro do repo e a recoloca em qualquer host.
#
# A senha NUNCA entra no git: o YAML do repo tem um marcador. O instalador usa,
# nesta ordem: --psk, $OD_WIFI_PSK, ou a senha que já estiver em
# /etc/netplan/*.yaml para o mesmo SSID (host que já funciona).
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGEM="$AQUI/70-wifi-reserva.yaml"
SSID="Drakon"
MARCADOR="SENHA-DO-WIFI-AQUI"
MAC="00:0f:00:37:ac:f0"
PREFIXO=""
PSK="${OD_WIFI_PSK:-}"
APLICAR=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --psk) PSK="${2:-}"; shift 2 ;;
        --mac) MAC="${2:-}"; shift 2 ;;
        --ssid) SSID="${2:-}"; shift 2 ;;
        --prefixo) PREFIXO="${2:-}"; shift 2 ;;   # só para teste (sandbox)
        --aplicar) APLICAR=1; shift ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "argumento desconhecido: $1" >&2; exit 2 ;;
    esac
done

if [[ ${EUID} -ne 0 ]]; then
    echo "precisa de root: sudo bash $0" >&2
    exit 1
fi

# networkd não aceita match por MAC em wifi; o nome da interface é derivado do
# MAC pelo systemd (wlx + mac sem ':').
IFACE="wlx$(tr -d ':' <<<"$MAC" | tr 'A-Z' 'a-z')"
DIR_NETPLAN="$PREFIXO/etc/netplan"
DESTINO="$DIR_NETPLAN/70-wifi-reserva.yaml"

if [[ ! -d $DIR_NETPLAN ]]; then
    echo "não achei $DIR_NETPLAN (o netplan está instalado?)" >&2
    exit 1
fi

# Senha: sem --psk/ambiente, aproveita a que já está no host (nunca imprime).
if [[ -z $PSK ]]; then
    for arq in "$DIR_NETPLAN"/*.yaml; do
        [[ -e $arq ]] || continue
        grep -q "\"$SSID\"" "$arq" || continue
        # primeira senha declarada no arquivo que menciona o SSID
        PSK="$(sed -n 's/^[[:space:]]*password:[[:space:]]*//p' "$arq" | head -1)"
        PSK="${PSK%\"}"; PSK="${PSK#\"}"; PSK="${PSK%\'}"; PSK="${PSK#\'}"
        [[ -n $PSK ]] && break
    done
fi

if [[ -z $PSK || $PSK == "$MARCADOR" ]]; then
    echo "sem senha do Wi-Fi: passe --psk '<senha>' ou exporte OD_WIFI_PSK." >&2
    echo "o arquivo do repo mantém o marcador '$MARCADOR' — senha não vai para o git." >&2
    exit 1
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
# Substituição em python: a senha pode ter espaço, aspas ou '&' — sed trataria
# esses caracteres como sintaxe. json.dumps gera escalar YAML válido e citado.
python3 - "$ORIGEM" "$TMP" "$PSK" "$IFACE" "$SSID" "$MARCADOR" <<'PY'
import json, re, sys
origem, destino, psk, iface, ssid, marcador = sys.argv[1:7]
texto = open(origem, encoding="utf-8").read()
if f'"{marcador}"' not in texto:
    sys.exit(f"marcador '{marcador}' sumiu do template")
texto = texto.replace(f'"{marcador}"', json.dumps(psk))
texto = re.sub(r"^    wlx[0-9a-f]+:", f"    {iface}:", texto, count=1, flags=re.M)
texto = re.sub(r'^        "Drakon":', f"        {json.dumps(ssid)}:", texto, count=1, flags=re.M)
open(destino, "w", encoding="utf-8").write(texto)
PY

# Segunda cópia de segurança: o arquivo antigo (se houver) volta se o generate falhar.
ANTERIOR="$DESTINO.bak-$(date +%Y%m%d-%H%M%S)"
if [[ -e $DESTINO ]]; then
    cp -p "$DESTINO" "$ANTERIOR"
fi
install -m 0600 -o root -g root "$TMP" "$DESTINO"
echo "✅ $DESTINO instalado (interface $IFACE, SSID $SSID)"

# Confere com o próprio netplan, sem aplicar nada na rede.
if [[ -n $PREFIXO ]]; then
    netplan generate --root-dir "${PREFIXO%/}"
else
    netplan generate
fi

# Prova de que a config virou unit de verdade (endereço e métrica no .network).
GERADO="${PREFIXO%/}/run/systemd/network/10-netplan-$IFACE.network"
if [[ -e $GERADO ]]; then
    IP="$(sed -n 's/^Address=//p' "$GERADO" | head -1)"
    MET="$(sed -n 's/^Metric=//p' "$GERADO" | head -1)"
    echo "• netplan generate OK: Address=$IP Metric=$MET"
else
    echo "• netplan generate passou, mas não achei $GERADO — confira o nome da interface" >&2
    [[ -e $DESTINO ]] && rm -f "$DESTINO"
    exit 1
fi

# Avisa (sem falhar) quando a mesma interface já é definida em outro arquivo:
# o netplan mescla, mas dados divergentes (IP/métrica/senha) viram surpresa.
for arq in "$DIR_NETPLAN"/*.yaml; do
    [[ -e $arq && $arq != "$DESTINO" ]] || continue
    if grep -q "^[[:space:]]*$IFACE:" "$arq"; then
        echo "• atenção: $IFACE também está definida em $(basename "$arq") — o netplan mescla;"
        echo "  se um dia os dados divergirem, esta é a cópia que deve mandar (instalada pelo repo)."
    fi
done

if [[ $APLICAR -eq 1 ]]; then
    netplan apply
    sleep 3
    ip -br addr show "$IFACE" || true
    echo "• aplicado; se não houver IP, veja: wpa_cli -i $IFACE status"
else
    echo
    echo "Nada foi aplicado na rede (o endereço atual continua). Para ativar agora:"
    echo "  sudo netplan apply    # ou rode este instalador com --aplicar"
    echo "Depois confirme: ip -br addr show $IFACE  (esperado 192.168.0.250/24)"
fi
