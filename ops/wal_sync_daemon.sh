#!/usr/bin/env bash
# =============================================================================
# WAL Archive Sync Daemon
# =============================================================================
# Runs wal_archive_sync.sh periodically to ensure WAL files are synced offsite.
# Intended to be run as a sidecar container in Docker Compose.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC_SCRIPT="$SCRIPT_DIR/wal_archive_sync.sh"
INTERVAL=${WAL_SYNC_INTERVAL_SECONDS:-300}

echo "[wal-sync-daemon] Starting WAL sync daemon (interval: ${INTERVAL}s)"

if [[ ! -x "$SYNC_SCRIPT" ]]; then
    echo "[wal-sync-daemon] ERROR: Sync script not executable: $SYNC_SCRIPT"
    exit 1
fi

while true; do
    echo "[wal-sync-daemon] Running sync..."
    if "$SYNC_SCRIPT"; then
        echo "[wal-sync-daemon] Sync successful. Sleeping for ${INTERVAL}s..."
    else
        echo "[wal-sync-daemon] Sync failed. Retrying in ${INTERVAL}s..."
    fi
    sleep "$INTERVAL"
done
