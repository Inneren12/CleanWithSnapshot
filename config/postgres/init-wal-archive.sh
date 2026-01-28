#!/bin/bash
# Initialize WAL archive directory with proper permissions
# This script runs on container startup before PostgreSQL starts

set -e

WAL_ARCHIVE_DIR="/var/lib/postgresql/wal_archive"
ENABLE_WAL_ARCHIVE_INIT="${ENABLE_WAL_ARCHIVE_INIT:-true}"

if [ "$ENABLE_WAL_ARCHIVE_INIT" != "true" ]; then
    echo "[init-wal-archive] Skipping WAL archive init (ENABLE_WAL_ARCHIVE_INIT=$ENABLE_WAL_ARCHIVE_INIT)"
    exit 0
fi

# Create WAL archive directory if it doesn't exist
if [ ! -d "$WAL_ARCHIVE_DIR" ]; then
    echo "[init-wal-archive] Creating WAL archive directory: $WAL_ARCHIVE_DIR"
    mkdir -p "$WAL_ARCHIVE_DIR"
fi

# Ensure correct ownership (postgres user, uid 999 in official image)
chown -R postgres:postgres "$WAL_ARCHIVE_DIR"

# Secure permissions (only postgres can read/write)
chmod 700 "$WAL_ARCHIVE_DIR"

echo "[init-wal-archive] WAL archive directory ready: $WAL_ARCHIVE_DIR"
