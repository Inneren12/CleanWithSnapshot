#!/usr/bin/env bash
set -euo pipefail

LOG_DIR=${LOG_DIR:-/var/log/caddy}
LOGS_ACL_GROUP=${LOGS_ACL_GROUP:-docker}

if ! command -v setfacl >/dev/null 2>&1; then
  echo "setfacl is required; install the 'acl' package first." >&2
  exit 1
fi

# Ensure the log directory exists but leave ownership untouched so the caddy user continues to own files.
sudo mkdir -p "$LOG_DIR"

echo "Applying ACL defaults to $LOG_DIR for group '${LOGS_ACL_GROUP}'"
# Grant recursive read/execute to the group and ensure new files inherit the same default ACL.
sudo setfacl -R -m "g:${LOGS_ACL_GROUP}:rX" "$LOG_DIR"
sudo setfacl -R -m "d:g:${LOGS_ACL_GROUP}:rX" "$LOG_DIR"

# Keep owner read/write/execute and drop world access on new files.
sudo setfacl -R -m u::rwX "$LOG_DIR"
sudo setfacl -R -m d:u::rwX "$LOG_DIR"
sudo setfacl -R -m o::- "$LOG_DIR"
sudo setfacl -R -m d:o::- "$LOG_DIR"

echo "Done. Existing and future log files under $LOG_DIR will allow group read access without changing ownership."
