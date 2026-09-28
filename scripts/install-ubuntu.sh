#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${REPO_URL:-https://github.com/lmworkod/doubleMfinancial.git}"
APP_DIR="/opt/doublemfinancial"
CONFIG_DIR="/etc/doublemfinancial"
DATA_DIR="/var/lib/doublemfinancial"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Ejecuta este script como root: sudo bash scripts/install-ubuntu.sh" >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends git python3 python3-venv python3-pip postgresql postgresql-client ca-certificates

if ! id -u doublem >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --create-home --shell /usr/sbin/nologin doublem
fi
install -d -o doublem -g doublem -m 0750 "$DATA_DIR"
install -d -o root -g doublem -m 0750 "$CONFIG_DIR"

if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone --branch main --depth 1 "$REPO_URL" "$APP_DIR"
else
  echo "Ya existe $APP_DIR; no se sobrescribe el código local."
fi
chown -R doublem:doublem "$APP_DIR"

if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='doublem'" | grep -q 1; then
  runuser -u postgres -- createuser --no-superuser --no-createdb --no-createrole doublem
fi
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='doublem'" | grep -q 1; then
  runuser -u postgres -- createdb --owner=doublem doublem
fi

if [[ ! -f "$CONFIG_DIR/doublem.env" ]]; then
  install -o root -g doublem -m 0640 "$APP_DIR/.env.example" "$CONFIG_DIR/doublem.env"
  sed -i 's|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg:///doublem?host=/var/run/postgresql|' "$CONFIG_DIR/doublem.env"
  echo
  echo "Se ha creado $CONFIG_DIR/doublem.env. Añade TELEGRAM_BOT_TOKEN y TELEGRAM_ALLOWED_USER_IDS antes de iniciar."
else
  echo "Se conserva la configuración existente en $CONFIG_DIR/doublem.env."
fi

runuser -u doublem -- python3 -m venv "$APP_DIR/.venv"
runuser -u doublem -- "$APP_DIR/.venv/bin/pip" install --upgrade pip
runuser -u doublem -- "$APP_DIR/.venv/bin/pip" install "$APP_DIR"

install -o root -g root -m 0644 "$APP_DIR/deploy/doublem.service" /etc/systemd/system/doublem.service
systemctl daemon-reload
systemctl enable postgresql
systemctl enable doublem
echo "Instalación preparada. Configura $CONFIG_DIR/doublem.env y ejecuta: systemctl start doublem"
