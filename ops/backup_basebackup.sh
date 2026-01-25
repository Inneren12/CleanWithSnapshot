#!/usr/bin/env bash
# =============================================================================
# PITR Base Backup Script
# =============================================================================
# Creates a PITR-compatible base backup using pg_basebackup.
# This backup, combined with WAL archives, enables Point-in-Time Recovery.
#
# Usage:
#   ./ops/backup_basebackup.sh
#
# Environment variables:
#   ENV_FILE        - Path to .env file (default: /etc/cleaning/cleaning.env)
#   BACKUP_ROOT     - Backup destination (default: /opt/backups/postgres)
#   WAL_ARCHIVE_VOL - Name of WAL archive volume (default: cleanwithsnapshot_pg_wal_archive)
#
# Output:
#   - Base backup: $BACKUP_ROOT/basebackup_YYYYMMDDTHHMMSSZ.tar.gz
#   - WAL archive snapshot: $BACKUP_ROOT/wal_archive_YYYYMMDDTHHMMSSZ.tar.gz
#   - Manifest: $BACKUP_ROOT/basebackup_YYYYMMDDTHHMMSSZ.manifest
# =============================================================================
set -euo pipefail

ENV_FILE=${ENV_FILE:-/etc/cleaning/cleaning.env}
BACKUP_ROOT=${BACKUP_ROOT:-/opt/backups/postgres}
WAL_ARCHIVE_VOL=${WAL_ARCHIVE_VOL:-cleanwithsnapshot_pg_wal_archive}

umask 077

timestamp=$(date -u "+%Y%m%dT%H%M%SZ")
mkdir -p "$BACKUP_ROOT"

basebackup_tar="$BACKUP_ROOT/basebackup_${timestamp}.tar.gz"
wal_archive_tar="$BACKUP_ROOT/wal_archive_${timestamp}.tar.gz"
manifest_file="$BACKUP_ROOT/basebackup_${timestamp}.manifest"

echo "[basebackup] Starting PITR base backup at $timestamp"

# Get docker compose prefix (project name)
compose_project=${COMPOSE_PROJECT_NAME:-cleanwithsnapshot}

# Create base backup using pg_basebackup
# -Ft: tar format
# -Xf: include WAL files in a separate tar
# -z: compress
# -P: show progress
echo "[basebackup] Creating base backup..."
docker compose --env-file "$ENV_FILE" exec -T db \
    pg_basebackup -U "$POSTGRES_USER" -D /tmp/basebackup -Ft -Xf -z -P 2>&1

# Copy the backup from container
echo "[basebackup] Extracting base backup from container..."
docker compose --env-file "$ENV_FILE" exec -T db \
    cat /tmp/basebackup/base.tar.gz > "$basebackup_tar"

# Clean up temporary backup in container
docker compose --env-file "$ENV_FILE" exec -T db \
    rm -rf /tmp/basebackup

# Also archive the current WAL archive directory
echo "[basebackup] Archiving WAL files..."
wal_archive_path=$(docker volume inspect "${compose_project}_pg_wal_archive" --format '{{.Mountpoint}}' 2>/dev/null || echo "")

if [ -n "$wal_archive_path" ] && [ -d "$wal_archive_path" ]; then
    # Archive WAL files that exist at this moment
    if [ "$(ls -A "$wal_archive_path" 2>/dev/null)" ]; then
        tar -C "$wal_archive_path" -czf "$wal_archive_tar" .
        echo "[basebackup] WAL archive created: $wal_archive_tar"
    else
        echo "[basebackup] WAL archive directory is empty (new installation or recently cleaned)"
        touch "$wal_archive_tar.empty"
    fi
else
    # Fallback: copy from container directly
    echo "[basebackup] Using container to archive WAL files..."
    docker compose --env-file "$ENV_FILE" exec -T db \
        tar -C /var/lib/postgresql/wal_archive -czf /tmp/wal_archive.tar.gz . 2>/dev/null || true
    docker compose --env-file "$ENV_FILE" exec -T db \
        cat /tmp/wal_archive.tar.gz > "$wal_archive_tar" 2>/dev/null || touch "$wal_archive_tar.empty"
    docker compose --env-file "$ENV_FILE" exec -T db \
        rm -f /tmp/wal_archive.tar.gz 2>/dev/null || true
fi

# Create manifest file
cat > "$manifest_file" << EOF
# PITR Base Backup Manifest
# Generated: $(date -u "+%Y-%m-%dT%H:%M:%SZ")
timestamp=$timestamp
base_backup=$basebackup_tar
wal_archive=$wal_archive_tar
postgres_version=$(docker compose --env-file "$ENV_FILE" exec -T db psql -U postgres -t -c "SELECT version();" | head -1 | xargs)
database=${POSTGRES_DB:-cleaning}
EOF

echo "[basebackup] Created manifest: $manifest_file"

# Update heartbeat
printf "%s\n" "$(date -u "+%Y-%m-%dT%H:%M:%SZ")" > "$BACKUP_ROOT/LAST_BASEBACKUP.txt"

# Print summary
base_size=$(du -h "$basebackup_tar" 2>/dev/null | cut -f1 || echo "unknown")
echo ""
echo "[basebackup] PITR base backup complete"
echo "[basebackup] Base backup: $basebackup_tar ($base_size)"
echo "[basebackup] WAL archive: $wal_archive_tar"
echo "[basebackup] Manifest: $manifest_file"
echo ""
echo "[basebackup] To restore to a point in time, see: docs/DISASTER_RECOVERY.md"
