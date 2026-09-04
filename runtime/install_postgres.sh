#!/usr/bin/env bash
# ============================================================================
# OMEGA DRAKON — Provisionamento PostgreSQL local (v0.28.0)
# ============================================================================
# Migra a Database Layer de SQLite para PostgreSQL no servidor:
#   1. Instala o PostgreSQL (apt);
#   2. Cria o usuário `od` e o banco `od` com senha aleatória (openssl);
#   3. Desinstala o MariaDB legado (parado — nada o utiliza);
#   4. Grava `OD_DB_URL=postgres://od:<senha>@127.0.0.1:5432/od` no .env
#      do projeto (o od-core passa a usar Postgres no próximo restart).
#
# Rode como root:
#   sudo bash runtime/install_postgres.sh
#
# A senha NUNCA é exibida no terminal — fica apenas no .env (gitignored).
# ============================================================================
set -euo pipefail

# 1. PostgreSQL -------------------------------------------------------------
echo "==> Instalando PostgreSQL..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql

# 2. Usuário e banco do OD ---------------------------------------------------
echo "==> Criando usuário/banco 'od'..."
PASSWORD="$(openssl rand -hex 24)"
runuser -u postgres -- psql -v ON_ERROR_STOP=1 <<SQL
CREATE USER od WITH PASSWORD '${PASSWORD}';
CREATE DATABASE od OWNER od;
SQL

# 3. MariaDB legado (parado — nada usa) --------------------------------------
echo "==> Desinstalando MariaDB legado..."
systemctl stop mariadb 2>/dev/null || true
systemctl disable mariadb 2>/dev/null || true
apt-get remove -y -qq mariadb-server mariadb-client 2>/dev/null || true
apt-get autoremove -y -qq 2>/dev/null || true

# 4. OD_DB_URL no .env do projeto --------------------------------------------
REPO_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
DSN="postgres://od:${PASSWORD}@127.0.0.1:5432/od"
echo "==> Gravando OD_DB_URL no ${ENV_FILE}"
if [ -f "$ENV_FILE" ] && grep -q '^OD_DB_URL=' "$ENV_FILE"; then
  sed -i "s|^OD_DB_URL=.*|OD_DB_URL=${DSN}|" "$ENV_FILE"
else
  touch "$ENV_FILE"
  echo "OD_DB_URL=${DSN}" >> "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

echo ""
echo "✅ PostgreSQL instalado e configurado."
echo "   OD_DB_URL gravada no .env — reinicie o od-core para ativar:"
echo "   systemctl --user restart od-core"
echo "   Valide: .venv/bin/python -m runtime.launcher health  (ou /health)"