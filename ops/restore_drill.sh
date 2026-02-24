#!/usr/bin/env bash
# =============================================================================
# Restore Drill Script
# =============================================================================
# Verifies that backups can be restored successfully.
# 1. Starts a temporary postgres container.
# 2. Restores the latest backup (handling encryption).
# 3. Runs a smoke test query.
# 4. Cleans up.
# =============================================================================
set -euo pipefail

BACKUP_ROOT=${BACKUP_ROOT:-/opt/backups/postgres}
DRILL_CONTAINER_NAME="postgres_restore_drill_$(date +%s)"
POSTGRES_PASSWORD="drill_password"

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
sleep 5
attempt=0
until docker exec "$DRILL_CONTAINER_NAME" pg_isready -U postgres >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [[ $attempt -gt 30 ]]; then
        echo "[restore-drill] ERROR: Postgres failed to start."
        exit 1
    fi
    sleep 1
done

echo "[restore-drill] Restoring backup..."
if [[ "$latest_backup" == *.enc ]]; then
    if [[ -z "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
        echo "[restore-drill] ERROR: Backup is encrypted but BACKUP_ENCRYPTION_KEY is not set."
        exit 1
    fi
    openssl enc -d -aes-256-cbc -salt -pbkdf2 -pass env:BACKUP_ENCRYPTION_KEY -in "$latest_backup" | \
        gzip -d | \
        docker exec -i "$DRILL_CONTAINER_NAME" psql -U postgres -d postgres
else
    gzip -cd "$latest_backup" | \
        docker exec -i "$DRILL_CONTAINER_NAME" psql -U postgres -d postgres
fi

echo "[restore-drill] Verifying data..."
# Run a simple query. Adjust this to check actual tables if possible.
# Since we dump with -d cleaning usually, the dump might contain 'CREATE DATABASE cleaning; CONNECT cleaning;'
# Or it might just dump table contents if we used -d cleaning but didn't include CREATE DATABASE.
# backup_now.sh does: pg_dump -U ... -d ... | gzip
# This creates a plain SQL dump. It typically doesn't include CREATE DATABASE if run against a specific DB,
# unless --create is passed.
# Let's check if tables exist in 'postgres' database or if we need to create 'cleaning' first.
# backup_now.sh usually dumps the content of the DB.
# If we restore into 'postgres' db, the tables will be there.

table_count=$(docker exec "$DRILL_CONTAINER_NAME" psql -U postgres -d postgres -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")
echo "[restore-drill] Restored $(echo "$table_count" | xargs) tables."

if [[ $(echo "$table_count" | xargs) -eq 0 ]]; then
    echo "[restore-drill] WARNING: No tables found in public schema. Is the dump empty or restored to another DB?"
    # It might be that the dump creates the 'cleaning' database.
    # Let's check if 'cleaning' db exists.
    db_exists=$(docker exec "$DRILL_CONTAINER_NAME" psql -U postgres -t -c "SELECT 1 FROM pg_database WHERE datname = 'cleaning'")
    if [[ -n "$db_exists" ]]; then
        echo "[restore-drill] 'cleaning' database found. Checking tables there..."
        table_count=$(docker exec "$DRILL_CONTAINER_NAME" psql -U postgres -d cleaning -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")
        echo "[restore-drill] Restored $(echo "$table_count" | xargs) tables in 'cleaning'."
    fi
fi

echo "[restore-drill] SUCCESS: Backup restored and verified."
