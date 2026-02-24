#!/usr/bin/env bash
# =============================================================================
# WAL Archive Offsite Sync Script
# =============================================================================
# Syncs WAL archive files to an offsite location for disaster recovery.
# Run this periodically (e.g., every 5 minutes via cron) to minimize RPO.
#
# Usage:
#   # Sync to S3-compatible storage
#   WAL_SYNC_TARGET="s3://bucket/wal-archive/" ./ops/wal_archive_sync.sh
#
#   # Sync to remote server via rsync
#   WAL_SYNC_TARGET="rsync://backup-server/wal-archive/" ./ops/wal_archive_sync.sh
#
#   # Sync to local directory (for testing)
#   WAL_SYNC_TARGET="/mnt/backup/wal-archive/" ./ops/wal_archive_sync.sh
#
# Environment variables:
#   WAL_SYNC_TARGET     - Destination URL (s3://, rsync://, or local path)
#   WAL_SYNC_DELETE     - Delete files at destination not in source (default: false)
#   AWS_PROFILE         - AWS profile for S3 sync (optional)
#   STATE_DIR           - Directory for sync state files (default: ops/state)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR=${STATE_DIR:-"$SCRIPT_DIR/state"}

WAL_SYNC_TARGET=${WAL_SYNC_TARGET:-}
WAL_SYNC_DELETE=${WAL_SYNC_DELETE:-false}

# Get WAL archive path from env or Docker volume
wal_source=${WAL_SOURCE_PATH:-}

if [[ -z "$wal_source" ]]; then
    # Fallback to docker volume inspect if not provided explicitly
    compose_project=${COMPOSE_PROJECT_NAME:-cleanwithsnapshot}
    pg_wal_archive_vol="${compose_project}_pg_wal_archive"
    wal_source=$(docker volume inspect "$pg_wal_archive_vol" --format '{{.Mountpoint}}' 2>/dev/null || echo "")
fi

if [[ -z "$wal_source" ]]; then
    echo "[wal-sync] ERROR: Could not resolve WAL archive path." >&2
    echo "[wal-sync] Set WAL_SOURCE_PATH or ensure Docker volume exists." >&2
    exit 1
fi

if [[ ! -d "$wal_source" ]]; then
    echo "[wal-sync] ERROR: WAL archive directory does not exist: $wal_source" >&2
    exit 1
fi

if [[ -z "$WAL_SYNC_TARGET" ]]; then
    echo "[wal-sync] ERROR: WAL_SYNC_TARGET is required" >&2
    echo "[wal-sync] Examples:" >&2
    echo "[wal-sync]   WAL_SYNC_TARGET=s3://mybucket/wal-archive/" >&2
    echo "[wal-sync]   WAL_SYNC_TARGET=user@server:/backup/wal-archive/" >&2
    echo "[wal-sync]   WAL_SYNC_TARGET=/mnt/backup/wal-archive/" >&2
    exit 1
fi

mkdir -p "$STATE_DIR"

# Determine sync method based on target URL
sync_wal() {
    local target="$1"

    case "$target" in
        s3://*)
            # AWS S3 or S3-compatible storage
            echo "[wal-sync] Syncing to S3: $target"
            local s3_args=("s3" "sync" "$wal_source/" "$target")
            if [[ "$WAL_SYNC_DELETE" == "true" ]]; then
                s3_args+=("--delete")
            fi
            aws "${s3_args[@]}"
            ;;
        rsync://*)
            # rsync protocol
            echo "[wal-sync] Syncing via rsync: $target"
            local rsync_args=("-av" "--partial")
            if [[ "$WAL_SYNC_DELETE" == "true" ]]; then
                rsync_args+=("--delete")
            fi
            rsync "${rsync_args[@]}" "$wal_source/" "${target#rsync://}"
            ;;
        *:*)
            # SSH/rsync to remote host (user@host:/path)
            echo "[wal-sync] Syncing via SSH: $target"
            local rsync_args=("-av" "--partial" "-e" "ssh")
            if [[ "$WAL_SYNC_DELETE" == "true" ]]; then
                rsync_args+=("--delete")
            fi
            rsync "${rsync_args[@]}" "$wal_source/" "$target"
            ;;
        /*)
            # Local path
            echo "[wal-sync] Syncing to local path: $target"
            mkdir -p "$target"
            local rsync_args=("-av" "--partial")
            if [[ "$WAL_SYNC_DELETE" == "true" ]]; then
                rsync_args+=("--delete")
            fi
            rsync "${rsync_args[@]}" "$wal_source/" "$target"
            ;;
        *)
            echo "[wal-sync] ERROR: Unsupported target format: $target" >&2
            echo "[wal-sync] Supported formats: s3://, rsync://, user@host:/path, /local/path" >&2
            exit 1
            ;;
    esac
}

# Count files before sync
file_count=$(find "$wal_source" -type f 2>/dev/null | wc -l || echo "0")
echo "[wal-sync] Found $file_count WAL files to sync"

if [[ "$file_count" -eq 0 ]]; then
    echo "[wal-sync] No WAL files to sync (this is normal for new installations)"
    exit 0
fi

# Perform sync
start_time=$(date +%s)
sync_wal "$WAL_SYNC_TARGET"
end_time=$(date +%s)

# Update heartbeat
timestamp=$(date -u "+%Y-%m-%dT%H:%M:%SZ")
printf "%s\n" "$timestamp" > "$STATE_DIR/wal_sync_last_ok.txt"

duration=$((end_time - start_time))
echo "[wal-sync] Sync complete in ${duration}s"
echo "[wal-sync] Heartbeat: $STATE_DIR/wal_sync_last_ok.txt ($timestamp)"
