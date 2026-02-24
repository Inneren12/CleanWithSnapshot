#!/usr/bin/env bash
# =============================================================================
# Restore Drill Script
# =============================================================================
# Verifies that backups can be restored successfully.
# 1. Starts a temporary postgres container.
# 2. Creates an isolated database 'drill'.
# 3. Restores the latest backup (handling encryption) into 'drill'.
# 4. Runs a smoke test query against 'drill'.
# 5. Cleans up.
#
# Environment Variables:
#   ENV_FILE: Path to environment file (default: /etc/cleaning/cleaning.env)
#   BACKUP_ROOT: Directory containing backups (default: /opt/backups/postgres)
#   BACKUP_ENCRYPTION_KEY: (Optional) If set (via ENV_FILE or shell), decrypts
#                          artifacts with AES-256-CBC.
# =============================================================================
set -euo pipefail

ENV_FILE=${ENV_FILE:-/etc/cleaning/cleaning.env}
BACKUP_ROOT=${BACKUP_ROOT:-/opt/backups/postgres}
DRILL_CONTAINER_NAME="postgres_restore_drill_$(date +%s)"
POSTGRES_PASSWORD="drill_password"
DRILL_DB="drill"

# Load environment variables from ENV_FILE if it exists
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi

cleanup() {
    echo "[restore-drill] Cleaning up container: $DRILL_CONTAINER_NAME"
    docker stop "$DRILL_CONTAINER_NAME" >/dev/null 2>&1 || true
    docker rm "$DRILL_CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[restore-drill] Looking for latest backup in $BACKUP_ROOT"
latest_backup=$(ls -1t "$BACKUP_ROOT"/cleaning_*.sql.gz* | head -n 1)

if [[ -z "$latest_backup" ]]; then
    echo "[restore-drill] ERROR: No backup found."
    exit 1
fi

echo "[restore-drill] Found backup: $latest_backup"

echo "[restore-drill] Starting temporary postgres container..."
docker run -d --name "$DRILL_CONTAINER_NAME" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    postgres:16

echo "[restore-drill] Waiting for postgres to be ready..."
# Loop with timeout (max 30s)
max_attempts=30
attempt=0
while true; do
    if docker exec "$DRILL_CONTAINER_NAME" pg_isready -U postgres >/dev/null 2>&1; then
        echo "[restore-drill] Postgres is ready."
        break
    fi
    attempt=$((attempt + 1))
    if [[ $attempt -ge $max_attempts ]]; then
        echo "[restore-drill] ERROR: Postgres failed to start within ${max_attempts}s."
        exit 1
    fi
    echo "[restore-drill] Waiting for DB... ($attempt/$max_attempts)"
    sleep 1
done

echo "[restore-drill] Creating isolated database '$DRILL_DB'..."
docker exec "$DRILL_CONTAINER_NAME" createdb -U postgres "$DRILL_DB"

echo "[restore-drill] Restoring backup into '$DRILL_DB'..."
# Note: backups are typically plain SQL dumps (not custom format with db info).
# We pipe the SQL into the drill database.
if [[ "$latest_backup" == *.enc ]]; then
    if [[ -z "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
        echo "[restore-drill] ERROR: Backup is encrypted but BACKUP_ENCRYPTION_KEY is not set."
        exit 1
    fi
    openssl enc -d -aes-256-cbc -salt -pbkdf2 -pass env:BACKUP_ENCRYPTION_KEY -in "$latest_backup" | \
        gzip -d | \
        docker exec -i "$DRILL_CONTAINER_NAME" psql -U postgres -d "$DRILL_DB"
else
    gzip -cd "$latest_backup" | \
        docker exec -i "$DRILL_CONTAINER_NAME" psql -U postgres -d "$DRILL_DB"
fi

echo "[restore-drill] Verifying data in '$DRILL_DB'..."
table_count=$(docker exec "$DRILL_CONTAINER_NAME" psql -U postgres -d "$DRILL_DB" -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")
count=$(echo "$table_count" | xargs)
echo "[restore-drill] Restored $count tables."

if [[ $count -eq 0 ]]; then
    echo "[restore-drill] WARNING: No tables found in public schema. Dump might be empty or Schema mismatch."
    # Fail drill if 0 tables, as we expect a valid dump to have schema
    exit 1
fi

echo "[restore-drill] SUCCESS: Backup restored and verified in isolated DB."
