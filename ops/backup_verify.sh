#!/usr/bin/env bash
set -euo pipefail

BACKUP_ROOT=${BACKUP_ROOT:-/opt/backups/postgres}
STATE_DIR=${STATE_DIR:-"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/state"}

backup_glob=("$BACKUP_ROOT"/cleaning_*.sql.gz)
if [ ! -e "${backup_glob[0]}" ]; then
  echo "[backup-verify] no backups found in $BACKUP_ROOT" >&2
  exit 1
fi

latest_backup=$(ls -1t "$BACKUP_ROOT"/cleaning_*.sql.gz | head -n 1)
if [ -z "$latest_backup" ]; then
  echo "[backup-verify] unable to locate latest backup" >&2
  exit 1
fi

if [ ! -f "$latest_backup" ]; then
  echo "[backup-verify] backup file missing: $latest_backup" >&2
  exit 1
fi

echo "[backup-verify] checking gzip integrity: $latest_backup"
gzip -t "$latest_backup"

header=$(gzip -cd "$latest_backup" | head -n 20)
if ! printf "%s\n" "$header" | grep -q "PostgreSQL database dump"; then
  echo "[backup-verify] backup header missing 'PostgreSQL database dump'" >&2
  exit 1
fi
if ! printf "%s\n" "$header" | grep -q "Dumped from database"; then
  echo "[backup-verify] backup header missing 'Dumped from database'" >&2
  exit 1
fi

mkdir -p "$STATE_DIR"
heartbeat_file="$STATE_DIR/backup_last_ok.txt"

timestamp=$(date -u "+%Y-%m-%dT%H:%M:%SZ")
printf "%s\n" "$timestamp" > "$heartbeat_file"

echo "[backup-verify] ok: $latest_backup"
echo "[backup-verify] heartbeat: $heartbeat_file ($timestamp)"
