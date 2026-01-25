#!/usr/bin/env bash
# =============================================================================
# Point-in-Time Recovery (PITR) Restore Script
# =============================================================================
# Restores PostgreSQL database to a specific point in time using:
# - A PITR base backup (from backup_basebackup.sh)
# - WAL archive files
#
# Usage:
#   TARGET_TIME="2026-01-25 14:30:00 UTC" \
#   BASE_BACKUP=/opt/backups/postgres/basebackup_20260125T120000Z.tar.gz \
#   WAL_ARCHIVE=/opt/backups/postgres/wal_archive_20260125T120000Z.tar.gz \
#   CONFIRM_PITR_RESTORE=YES \
#   ./ops/pitr_restore.sh
#
# Environment variables (required):
#   TARGET_TIME         - Recovery target time (e.g., "2026-01-25 14:30:00 UTC")
#   BASE_BACKUP         - Path to base backup .tar.gz
#   WAL_ARCHIVE         - Path to WAL archive .tar.gz
#   CONFIRM_PITR_RESTORE - Must be "YES" to proceed
#
# Environment variables (optional):
#   ENV_FILE            - Path to .env file (default: .env)
#   RECOVERY_TARGET     - "time" (default), "immediate", or "latest"
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# Required environment variables
TARGET_TIME=${TARGET_TIME:-}
BASE_BACKUP=${BASE_BACKUP:-}
WAL_ARCHIVE=${WAL_ARCHIVE:-}
CONFIRM_PITR_RESTORE=${CONFIRM_PITR_RESTORE:-}

# Optional environment variables
ENV_FILE=${ENV_FILE:-.env}
RECOVERY_TARGET=${RECOVERY_TARGET:-time}

# Validation
if [[ "$CONFIRM_PITR_RESTORE" != "YES" ]]; then
    echo "[pitr] ERROR: Set CONFIRM_PITR_RESTORE=YES to proceed."
    echo "[pitr] This operation will DESTROY the current database and restore from backup."
    exit 1
fi

if [[ -z "$BASE_BACKUP" ]]; then
    echo "[pitr] ERROR: BASE_BACKUP is required (path to basebackup_*.tar.gz)." >&2
    exit 1
fi

if [[ ! -f "$BASE_BACKUP" ]]; then
    echo "[pitr] ERROR: Base backup file not found: $BASE_BACKUP" >&2
    exit 1
fi

if [[ -n "$WAL_ARCHIVE" ]] && [[ ! -f "$WAL_ARCHIVE" ]]; then
    echo "[pitr] ERROR: WAL archive file not found: $WAL_ARCHIVE" >&2
    exit 1
fi

if [[ "$RECOVERY_TARGET" == "time" ]] && [[ -z "$TARGET_TIME" ]]; then
    echo "[pitr] ERROR: TARGET_TIME is required when RECOVERY_TARGET=time" >&2
    echo "[pitr] Example: TARGET_TIME=\"2026-01-25 14:30:00 UTC\"" >&2
    exit 1
fi

# Docker compose setup
compose=("docker" "compose")
if [[ -f "$ENV_FILE" ]]; then
    compose+=("--env-file" "$ENV_FILE")
fi

echo "============================================================"
echo "  Point-in-Time Recovery (PITR)"
echo "============================================================"
echo "Base backup:      $BASE_BACKUP"
echo "WAL archive:      ${WAL_ARCHIVE:-none}"
echo "Recovery target:  $RECOVERY_TARGET"
if [[ "$RECOVERY_TARGET" == "time" ]]; then
    echo "Target time:      $TARGET_TIME"
fi
echo "============================================================"
echo ""
echo "WARNING: This will DESTROY the current database!"
echo "Press Ctrl+C within 5 seconds to abort..."
sleep 5

echo "[pitr] Starting Point-in-Time Recovery..."

# Step 1: Stop application services
echo "[pitr] Stopping application services..."
"${compose[@]}" stop api web jobs caddy 2>/dev/null || true

# Step 2: Stop PostgreSQL
echo "[pitr] Stopping PostgreSQL..."
"${compose[@]}" stop db

# Step 3: Get volume paths
compose_project=${COMPOSE_PROJECT_NAME:-cleanwithsnapshot}
pg_data_vol="${compose_project}_pg_data"
pg_wal_archive_vol="${compose_project}_pg_wal_archive"

pg_data_path=$(docker volume inspect "$pg_data_vol" --format '{{.Mountpoint}}' 2>/dev/null || echo "")
pg_wal_path=$(docker volume inspect "$pg_wal_archive_vol" --format '{{.Mountpoint}}' 2>/dev/null || echo "")

if [[ -z "$pg_data_path" ]]; then
    echo "[pitr] ERROR: Could not find pg_data volume. Is the database initialized?" >&2
    exit 1
fi

# Step 4: Backup current data directory (safety)
timestamp=$(date -u "+%Y%m%dT%H%M%SZ")
backup_current="${pg_data_path}.pre_pitr_${timestamp}"
echo "[pitr] Backing up current data directory to: $backup_current"
sudo mv "$pg_data_path" "$backup_current"
sudo mkdir -p "$pg_data_path"
sudo chown 999:999 "$pg_data_path"

# Step 5: Extract base backup
echo "[pitr] Extracting base backup..."
sudo tar -xzf "$BASE_BACKUP" -C "$pg_data_path"
sudo chown -R 999:999 "$pg_data_path"

# Step 6: Prepare WAL archive for recovery
if [[ -n "$pg_wal_path" ]]; then
    echo "[pitr] Preparing WAL archive directory..."
    sudo rm -rf "$pg_wal_path"/*
    if [[ -n "$WAL_ARCHIVE" ]] && [[ -f "$WAL_ARCHIVE" ]]; then
        sudo tar -xzf "$WAL_ARCHIVE" -C "$pg_wal_path"
        sudo chown -R 999:999 "$pg_wal_path"
        echo "[pitr] WAL archive extracted"
    fi
fi

# Step 7: Create recovery configuration
echo "[pitr] Creating recovery configuration..."

# PostgreSQL 12+ uses postgresql.auto.conf and recovery.signal
recovery_conf="$pg_data_path/postgresql.auto.conf"
recovery_signal="$pg_data_path/recovery.signal"

# Append recovery settings to postgresql.auto.conf
sudo tee -a "$recovery_conf" > /dev/null << EOF

# PITR Recovery Configuration (added by pitr_restore.sh)
restore_command = 'cp /var/lib/postgresql/wal_archive/%f %p || true'
EOF

# Add target-specific settings
case "$RECOVERY_TARGET" in
    time)
        sudo tee -a "$recovery_conf" > /dev/null << EOF
recovery_target_time = '$TARGET_TIME'
recovery_target_action = 'promote'
EOF
        ;;
    immediate)
        sudo tee -a "$recovery_conf" > /dev/null << EOF
recovery_target = 'immediate'
recovery_target_action = 'promote'
EOF
        ;;
    latest)
        sudo tee -a "$recovery_conf" > /dev/null << EOF
recovery_target_action = 'promote'
EOF
        ;;
esac

# Create recovery.signal to trigger recovery mode
sudo touch "$recovery_signal"
sudo chown 999:999 "$recovery_signal"

# Step 8: Start PostgreSQL (it will enter recovery mode)
echo "[pitr] Starting PostgreSQL in recovery mode..."
"${compose[@]}" up -d db

# Step 9: Wait for recovery to complete
echo "[pitr] Waiting for recovery to complete..."
max_attempts=60
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if "${compose[@]}" exec -T db pg_isready -U postgres 2>/dev/null; then
        # Check if recovery is complete (no recovery.signal)
        if ! "${compose[@]}" exec -T db test -f /var/lib/postgresql/data/recovery.signal 2>/dev/null; then
            echo "[pitr] Recovery complete!"
            break
        fi
    fi
    attempt=$((attempt + 1))
    echo "[pitr] Waiting for recovery... ($attempt/$max_attempts)"
    sleep 5
done

if [ $attempt -ge $max_attempts ]; then
    echo "[pitr] WARNING: Recovery taking longer than expected. Check PostgreSQL logs."
    echo "[pitr] Run: docker compose logs db"
fi

# Step 10: Run Alembic migrations (schema may have changed)
echo "[pitr] Running database migrations..."
"${compose[@]}" up -d api
sleep 5
"${compose[@]}" exec -T api alembic upgrade head || true

# Step 11: Start remaining services
echo "[pitr] Starting application services..."
"${compose[@]}" up -d

# Step 12: Verify recovery
echo ""
echo "============================================================"
echo "  PITR Recovery Complete"
echo "============================================================"
echo ""
echo "Previous data backed up to: $backup_current"
echo ""
echo "Verification steps:"
echo "  curl -fsS http://localhost:8000/healthz | jq ."
echo "  curl -fsS http://localhost:8000/readyz | jq ."
echo "  docker compose exec -T db psql -U postgres -d cleaning -c \"SELECT COUNT(*) FROM bookings;\""
echo ""
echo "If recovery failed, restore from the pre-PITR backup:"
echo "  docker compose stop db"
echo "  sudo rm -rf $pg_data_path"
echo "  sudo mv $backup_current $pg_data_path"
echo "  docker compose up -d"
echo ""
