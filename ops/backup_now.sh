#!/usr/bin/env bash
# =============================================================================
# Backup Script (Immediate)
# =============================================================================
# Creates a database dump and uploads archive.
#
# Environment Variables:
#   ENV_FILE: Path to environment file (default: /etc/cleaning/cleaning.env)
#   BACKUP_ROOT: Directory to store backups (default: /opt/backups/postgres)
#   UPLOADS_ROOT: Directory containing uploads (default: /opt/cleaning/var/uploads)
#   BACKUP_ENCRYPTION_KEY: (Optional) If set (via ENV_FILE or shell), encrypts
#                          artifacts with AES-256-CBC.
# =============================================================================

set -euo pipefail

ENV_FILE=${ENV_FILE:-/etc/cleaning/cleaning.env}
BACKUP_ROOT=${BACKUP_ROOT:-/opt/backups/postgres}
UPLOADS_ROOT=${UPLOADS_ROOT:-/opt/cleaning/var/uploads}

# Load environment variables from ENV_FILE if it exists and variables aren't already set
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi

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
  # Note: --env-file is for docker compose to find DB creds.
  # BACKUP_ENCRYPTION_KEY is read by openssl from the host environment (loaded above).
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
