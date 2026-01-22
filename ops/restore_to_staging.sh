#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

TARGET_ENV=${TARGET_ENV:-}
CONFIRM_STAGING_RESTORE=${CONFIRM_STAGING_RESTORE:-}
BACKUP_ROOT=${BACKUP_ROOT:-/opt/backups/postgres}
BACKUP_FILE=${BACKUP_FILE:-}
UPLOADS_ARCHIVE=${UPLOADS_ARCHIVE:-}
UPLOADS_ROOT=${UPLOADS_ROOT:-"$REPO_ROOT/var/uploads"}
ENV_FILE=${ENV_FILE:-}

if [[ "$TARGET_ENV" != "staging" ]]; then
  echo "[restore] ERROR: TARGET_ENV must be 'staging'." >&2
  exit 1
fi

if [[ "$CONFIRM_STAGING_RESTORE" != "YES" ]]; then
  echo "[restore] ERROR: set CONFIRM_STAGING_RESTORE=YES to proceed." >&2
  exit 1
fi

if [[ -z "$BACKUP_FILE" ]]; then
  echo "[restore] ERROR: BACKUP_FILE is required (path to .sql.gz)." >&2
  exit 1
fi

if [[ "$BACKUP_FILE" != /* ]]; then
  BACKUP_FILE="$BACKUP_ROOT/$BACKUP_FILE"
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "[restore] ERROR: backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

if [[ "$BACKUP_FILE" != *.sql.gz ]]; then
  echo "[restore] ERROR: BACKUP_FILE must be a .sql.gz file." >&2
  exit 1
fi

if [[ -n "$UPLOADS_ARCHIVE" ]]; then
  if [[ "$UPLOADS_ARCHIVE" != /* ]]; then
    UPLOADS_ARCHIVE="$BACKUP_ROOT/$UPLOADS_ARCHIVE"
  fi
  if [[ ! -f "$UPLOADS_ARCHIVE" ]]; then
    echo "[restore] ERROR: uploads archive not found: $UPLOADS_ARCHIVE" >&2
    exit 1
  fi
  if [[ "$UPLOADS_ARCHIVE" != *.tar.gz ]]; then
    echo "[restore] ERROR: UPLOADS_ARCHIVE must be a .tar.gz file." >&2
    exit 1
  fi
fi

compose=("docker" "compose")
if [[ -n "$ENV_FILE" ]]; then
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "[restore] ERROR: ENV_FILE not found: $ENV_FILE" >&2
    exit 1
  fi
  compose+=("--env-file" "$ENV_FILE")
fi

echo "[restore] starting staging restore"
echo "[restore] repo: $REPO_ROOT"
echo "[restore] backup: $BACKUP_FILE"
if [[ -n "$UPLOADS_ARCHIVE" ]]; then
  echo "[restore] uploads: $UPLOADS_ARCHIVE"
fi

"${compose[@]}" stop api web jobs caddy

"${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";"'
"${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE \"$POSTGRES_DB\";"'

gzip -cd "$BACKUP_FILE" | "${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

if [[ -n "$UPLOADS_ARCHIVE" ]]; then
  timestamp=$(date -u "+%Y%m%dT%H%M%SZ")
  uploads_parent=$(dirname "$UPLOADS_ROOT")
  if [[ -d "$UPLOADS_ROOT" ]]; then
    backup_dir="${UPLOADS_ROOT}.pre_restore_${timestamp}"
    echo "[restore] moving existing uploads to $backup_dir"
    mv "$UPLOADS_ROOT" "$backup_dir"
  fi
  mkdir -p "$uploads_parent"
  echo "[restore] restoring uploads into $uploads_parent"
  tar -C "$uploads_parent" -xzf "$UPLOADS_ARCHIVE"
fi

"${compose[@]}" up -d --remove-orphans api web jobs caddy

"${compose[@]}" exec -T api alembic upgrade head

echo "[restore] staging restore complete"
cat <<'NEXT_STEPS'
[restore] Next steps:
- curl -fsS http://localhost:8000/healthz | jq .
- curl -fsS http://localhost:8000/readyz | jq .
- docker compose exec -T db psql -U postgres -d cleaning -c "SELECT COUNT(*) FROM bookings;"
NEXT_STEPS
