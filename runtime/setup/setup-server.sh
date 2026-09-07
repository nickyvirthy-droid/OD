#!/usr/bin/env bash
# =============================================================================
# OMEGA DRAKON — Setup do servidor (itens 1.7–1.10 da v1.0.0)
# Uso: sudo bash runtime/setup/setup-server.sh
# Executar no nicky-server como root ou com sudo.
# =============================================================================
set -euo pipefail

echo "🐉 OmegaDrakon — Setup do servidor"
echo "==================================="
echo

# ---------------------------------------------------------------------------
# 1.7 — SWAP 4 GB
# ---------------------------------------------------------------------------
echo "📦 [1.7] Criando SWAP 4 GB..."

if swapon --show | grep -q '/swapfile'; then
    echo "   ✅ SWAP já existe e está ativo"
else
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    # Adiciona ao fstab se não estiver lá
    if ! grep -q '/swapfile' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi
    echo "   ✅ SWAP 4 GB criado e ativado"
fi

# Ajusta swappiness para servidores (10 = troca mínima)
if ! grep -q 'vm.swappiness' /etc/sysctl.conf; then
    echo 'vm.swappiness=10' >> /etc/sysctl.conf
    sysctl vm.swappiness=10
    echo "   ✅ swappiness=10 configurado"
else
    echo "   ✅ swappiness já configurado"
fi

echo

# ---------------------------------------------------------------------------
# 1.8 — UFW Firewall
# ---------------------------------------------------------------------------
echo "🔥 [1.8] Configurando UFW Firewall..."

if ufw status | grep -q 'Status: active'; then
    echo "   ✅ UFW já está ativo"
else
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow 22/tcp comment 'SSH'
    ufw allow 8000/tcp comment 'OD API REST'
    ufw allow 8123/tcp comment 'Home Assistant'
    ufw --force enable
    echo "   ✅ UFW ativado (22, 8000, 8123)"
fi

echo

# ---------------------------------------------------------------------------
# 1.9 — Variáveis de ambiente ausentes no .env
# ---------------------------------------------------------------------------
echo "⚙️  [1.9] Configurando variáveis de ambiente..."

OD_ENV="/home/alex/OmegaDrakon/.env"
ENV_ADDITIONS=(
    "OD_PRESENCE_ENABLED=1"
    "OD_PRESENCE_POLL_S=30"
    "OD_HA_CREDENTIALS=config/iot_credentials.json"
    "OD_RECOVERY_INTERVAL_S=300"
    "OD_SELF_REPAIR_ENABLED=1"
    "OD_NOTIFIER_ENABLED=1"
)

for entry in "${ENV_ADDITIONS[@]}"; do
    key="${entry%%=*}"
    if grep -q "^${key}=" "$OD_ENV" 2>/dev/null; then
        echo "   ✅ $key já existe no .env"
    else
        echo "$entry" >> "$OD_ENV"
        echo "   ✅ $key adicionado ao .env"
    fi
done

chown alex:alex "$OD_ENV"
chmod 600 "$OD_ENV"

echo

# ---------------------------------------------------------------------------
# 1.10 — Montar disco sdb1
# ---------------------------------------------------------------------------
echo "💾 [1.10] Montando disco sdb1 (Seagate 1 TB)..."

if mount | grep -q '/dev/sdb1'; then
    echo "   ✅ /dev/sdb1 já está montado"
else
    mkdir -p /home/alex/dados
    # Formata apenas se não tiver filesystem
    if ! blkid /dev/sdb1 | grep -q 'TYPE='; then
        mkfs.ext4 /dev/sdb1
        echo "   ✅ Filesystem ext4 criado em /dev/sdb1"
    fi
    mount /dev/sdb1 /home/alex/dados
    chown alex:alex /home/alex/dados
    # Adiciona ao fstab para automount
    if ! grep -q '/dev/sdb1' /etc/fstab; then
        echo '/dev/sdb1 /home/alex/dados ext4 defaults,noatime 0 2' >> /etc/fstab
    fi
    echo "   ✅ /dev/sdb1 montado em /home/alex/dados"
fi

echo

# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------
echo "==================================="
echo "🐉 Setup concluído!"
echo
echo "Status:"
free -h | head -2
echo
echo "SWAP:"
swapon --show
echo
echo "UFW:"
ufw status | head -10
echo
echo "Disco:"
df -h /home/alex/dados 2>/dev/null || echo "   (sdb1 não montado)"
echo
echo "💡 Lembre-se de:"
echo "   1. Reiniciar o OD: systemctl --user restart od-core.service"
echo "   2. Verificar health: curl -H 'X-API-Key: \$OD_API_KEY' http://localhost:8000/health"
