#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=${ENV_FILE:-/etc/cleaning/cleaning.env}
BACKUP_ROOT=${BACKUP_ROOT:-/opt/backups/postgres}
UPLOADS_ROOT=${UPLOADS_ROOT:-/opt/cleaning/var/uploads}

umask 077

timestamp=$(date -u "+%Y%m%dT%H%M%SZ")
backup_dir="$BACKUP_ROOT"
mkdir -p "$backup_dir"

postgres_dump="$backup_dir/cleaning_${timestamp}.sql.gz"
uploads_archive="$backup_dir/uploads_${timestamp}.tar.gz"

if [ ! -d "$UPLOADS_ROOT" ]; then
  mkdir -p "$UPLOADS_ROOT"
fi

echo "[backup] starting postgres dump"
docker compose --env-file "$ENV_FILE" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip -c > "$postgres_dump"

echo "[backup] archiving uploads"
tar -C "$(dirname "$UPLOADS_ROOT")" -czf "$uploads_archive" "$(basename "$UPLOADS_ROOT")"

printf "%s\n" "$(date -u "+%Y-%m-%dT%H:%M:%SZ")" > "$backup_dir/LAST_SUCCESS.txt"

echo "[backup] complete"
