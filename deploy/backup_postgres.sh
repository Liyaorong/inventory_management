#!/usr/bin/env bash
set -euo pipefail

APP_ENV="/etc/inventory-app/inventory.env"
BACKUP_DIR="/var/backups/inventory-app"
KEEP_DAYS=14

if [[ -f "$APP_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$APP_ENV"
  set +a
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

timestamp="$(date +%Y%m%d_%H%M%S)"
backup_file="$BACKUP_DIR/inventory_db_${timestamp}.dump"

pg_dump "$DATABASE_URL" --format=custom --file="$backup_file"
gzip "$backup_file"

find "$BACKUP_DIR" -type f -name 'inventory_db_*.dump.gz' -mtime +"$KEEP_DAYS" -delete

echo "Backup written to ${backup_file}.gz"
