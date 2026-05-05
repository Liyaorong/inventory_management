#!/usr/bin/env bash
set -euo pipefail

APP_USER="inventory"
APP_ROOT="/opt/inventory-app"
APP_DIR="$APP_ROOT/app"
ENV_DIR="/etc/inventory-app"

sudo apt update
sudo apt install -y python3-venv python3-pip postgresql postgresql-client nginx git curl

if ! id "$APP_USER" >/dev/null 2>&1; then
  sudo adduser --system --group --home "$APP_ROOT" "$APP_USER"
fi

sudo mkdir -p "$APP_DIR" "$ENV_DIR" /var/backups/inventory-app
sudo chown -R "$APP_USER:$APP_USER" "$APP_ROOT"
sudo chmod 750 "$ENV_DIR"
sudo chmod 700 /var/backups/inventory-app

echo "Base packages and directories are ready."
echo "Next: upload project files to $APP_DIR and create $ENV_DIR/inventory.env."
