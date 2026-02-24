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
if [[ -n "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
  echo "[backup] encrypting dump with AES-256-CBC"
  postgres_dump="${postgres_dump}.enc"
  docker compose --env-file "$ENV_FILE" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | \
    gzip -c | \
    openssl enc -aes-256-cbc -salt -pbkdf2 -pass env:BACKUP_ENCRYPTION_KEY -out "$postgres_dump"
else
  echo "[backup] WARNING: BACKUP_ENCRYPTION_KEY not set. Backup will be unencrypted."
  docker compose --env-file "$ENV_FILE" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | \
    gzip -c > "$postgres_dump"
fi

echo "[backup] archiving uploads"
if [[ -n "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
  uploads_archive="${uploads_archive}.enc"
  tar -C "$(dirname "$UPLOADS_ROOT")" -czf - "$(basename "$UPLOADS_ROOT")" | \
    openssl enc -aes-256-cbc -salt -pbkdf2 -pass env:BACKUP_ENCRYPTION_KEY -out "$uploads_archive"
else
  tar -C "$(dirname "$UPLOADS_ROOT")" -czf "$uploads_archive" "$(basename "$UPLOADS_ROOT")"
fi

# Retention Policy: Delete backups older than 30 days
echo "[backup] pruning backups older than 30 days"
find "$BACKUP_ROOT" -name "cleaning_*.sql.gz*" -mtime +30 -delete
find "$BACKUP_ROOT" -name "uploads_*.tar.gz*" -mtime +30 -delete

printf "%s\n" "$(date -u "+%Y-%m-%dT%H:%M:%SZ")" > "$backup_dir/LAST_SUCCESS.txt"

echo "[backup] complete"
