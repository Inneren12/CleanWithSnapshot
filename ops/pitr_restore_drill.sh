#!/usr/bin/env bash
# =============================================================================
# Automated PITR Restore Drill for Staging
# =============================================================================
# Performs a complete PITR restore drill on staging environment:
# 1. Creates a fresh base backup (or uses existing)
# 2. Inserts a marker record to verify recovery point
# 3. Restores to a specific timestamp using PITR
# 4. Validates application health and data integrity
# 5. Generates a drill report
#
# Usage:
#   # Full automated drill (creates new backup, restores to 5 minutes ago)
#   TARGET_ENV=staging CONFIRM_DRILL=YES ./ops/pitr_restore_drill.sh
#
#   # Drill with specific backup files
#   TARGET_ENV=staging \
#   CONFIRM_DRILL=YES \
#   BASE_BACKUP=/opt/backups/postgres/basebackup_20260125T120000Z.tar.gz \
#   WAL_ARCHIVE=/opt/backups/postgres/wal_archive_20260125T120000Z.tar.gz \
#   TARGET_TIME="2026-01-25 14:30:00 UTC" \
#   ./ops/pitr_restore_drill.sh
#
# Environment variables (required):
#   TARGET_ENV      - Must be "staging" (safety check)
#   CONFIRM_DRILL   - Must be "YES" to proceed
#
# Environment variables (optional):
#   BASE_BACKUP     - Path to existing base backup (auto-creates if not set)
#   WAL_ARCHIVE     - Path to existing WAL archive (auto-creates if not set)
#   TARGET_TIME     - Recovery target time (default: 5 minutes before drill start)
#   ENV_FILE        - Path to .env file (default: .env)
#   DRILL_REPORT_DIR - Where to save drill reports (default: ops/drill-reports)
#   SKIP_BACKUP     - Set to "true" to skip creating fresh backup
#
# Output:
#   - Drill report: $DRILL_REPORT_DIR/pitr_drill_YYYYMMDDTHHMMSSZ.md
#   - Exit code 0 on success, non-zero on failure
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# Required environment variables
TARGET_ENV=${TARGET_ENV:-}
CONFIRM_DRILL=${CONFIRM_DRILL:-}

# Optional environment variables
ENV_FILE=${ENV_FILE:-.env}
BASE_BACKUP=${BASE_BACKUP:-}
WAL_ARCHIVE=${WAL_ARCHIVE:-}
TARGET_TIME=${TARGET_TIME:-}
DRILL_REPORT_DIR=${DRILL_REPORT_DIR:-"$SCRIPT_DIR/drill-reports"}
BACKUP_ROOT=${BACKUP_ROOT:-/opt/backups/postgres}
SKIP_BACKUP=${SKIP_BACKUP:-false}
API_BASE_URL=${API_BASE_URL:-http://localhost:8000}

# Drill metadata
drill_id="pitr_drill_$(date -u '+%Y%m%dT%H%M%SZ')"
drill_start_utc=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
drill_start_epoch=$(date +%s)
drill_status="in_progress"
drill_errors=()

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
    echo -e "[${GREEN}INFO${NC}] $1"
}

log_warn() {
    echo -e "[${YELLOW}WARN${NC}] $1"
}

log_error() {
    echo -e "[${RED}ERROR${NC}] $1" >&2
    drill_errors+=("$1")
}

log_step() {
    echo ""
    echo "============================================================"
    echo "  $1"
    echo "============================================================"
}

# Docker compose setup
compose_cmd() {
    local compose=("docker" "compose")
    if [[ -f "$ENV_FILE" ]]; then
        compose+=("--env-file" "$ENV_FILE")
    fi
    "${compose[@]}" "$@"
}

# =============================================================================
# Safety Validations
# =============================================================================

log_step "Safety Validations"

if [[ "$TARGET_ENV" != "staging" ]]; then
    log_error "TARGET_ENV must be 'staging'. This drill is ONLY for staging environments."
    echo ""
    echo "Usage: TARGET_ENV=staging CONFIRM_DRILL=YES ./ops/pitr_restore_drill.sh"
    exit 1
fi

if [[ "$CONFIRM_DRILL" != "YES" ]]; then
    log_error "Set CONFIRM_DRILL=YES to proceed."
    echo ""
    echo "This drill will:"
    echo "  1. Create a database backup"
    echo "  2. DESTROY the current staging database"
    echo "  3. Restore from PITR backup"
    echo "  4. Validate the restore"
    echo ""
    echo "This is SAFE for staging, but will cause temporary downtime."
    exit 1
fi

# Verify we're not accidentally running against production
if [[ -f "$ENV_FILE" ]]; then
    if grep -qE 'APP_ENV\s*=\s*["\x27]?prod' "$ENV_FILE" 2>/dev/null; then
        log_error "ENV_FILE appears to be a production environment (APP_ENV=prod). Aborting."
        exit 1
    fi
fi

log_info "Safety checks passed (TARGET_ENV=staging)"

# =============================================================================
# Initialize Drill Report
# =============================================================================

mkdir -p "$DRILL_REPORT_DIR"
report_file="$DRILL_REPORT_DIR/${drill_id}.md"

# Start building report
cat > "$report_file" << EOF
# PITR Restore Drill Report

**Drill ID:** \`$drill_id\`
**Environment:** staging
**Start Time (UTC):** $drill_start_utc
**Operator:** $(whoami)@$(hostname)

---

## Configuration

| Parameter | Value |
|-----------|-------|
| TARGET_ENV | $TARGET_ENV |
| ENV_FILE | $ENV_FILE |
| API_BASE_URL | $API_BASE_URL |
| BACKUP_ROOT | $BACKUP_ROOT |

---

## Drill Steps

EOF

log_info "Drill report initialized: $report_file"

# =============================================================================
# Step 1: Pre-Drill Health Check
# =============================================================================

log_step "Step 1: Pre-Drill Health Check"
echo "### Step 1: Pre-Drill Health Check" >> "$report_file"

pre_health_status="unknown"
pre_ready_status="unknown"
pre_db_connected="unknown"

# Check API health
if curl -fsS --max-time 10 "$API_BASE_URL/healthz" > /tmp/healthz_pre.json 2>/dev/null; then
    pre_health_status=$(jq -r '.status // "unknown"' /tmp/healthz_pre.json 2>/dev/null || echo "parse_error")
    pre_db_connected=$(jq -r '.db_connected // "unknown"' /tmp/healthz_pre.json 2>/dev/null || echo "parse_error")
    log_info "Pre-drill /healthz: status=$pre_health_status, db_connected=$pre_db_connected"
else
    log_warn "Pre-drill /healthz check failed (API may not be running)"
fi

# Check readiness
if curl -fsS --max-time 10 "$API_BASE_URL/readyz" > /tmp/readyz_pre.json 2>/dev/null; then
    pre_ready_status=$(jq -r '.status // "unknown"' /tmp/readyz_pre.json 2>/dev/null || echo "parse_error")
    log_info "Pre-drill /readyz: status=$pre_ready_status"
else
    log_warn "Pre-drill /readyz check failed"
fi

cat >> "$report_file" << EOF

| Check | Result |
|-------|--------|
| /healthz status | $pre_health_status |
| /healthz db_connected | $pre_db_connected |
| /readyz status | $pre_ready_status |

EOF

# =============================================================================
# Step 2: Insert Marker Record (for recovery verification)
# =============================================================================

log_step "Step 2: Insert Marker Record"
echo "### Step 2: Insert Marker Record" >> "$report_file"

marker_timestamp=$(date -u '+%Y-%m-%d %H:%M:%S')
marker_id="drill_marker_${drill_id}"

log_info "Creating marker record to verify PITR recovery..."

# Create marker table if not exists and insert marker
marker_sql=$(cat << EOF
-- Create drill marker table if not exists
CREATE TABLE IF NOT EXISTS _pitr_drill_markers (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    drill_id TEXT NOT NULL,
    note TEXT
);

-- Insert marker for this drill
INSERT INTO _pitr_drill_markers (id, drill_id, note)
VALUES ('$marker_id', '$drill_id', 'Marker inserted at $marker_timestamp UTC');

-- Record the marker timestamp
SELECT NOW() as marker_time;
EOF
)

if compose_cmd exec -T db psql -U postgres -d cleaning -c "$marker_sql" > /tmp/marker_result.txt 2>&1; then
    marker_insert_time=$(grep -E '^[0-9]{4}-' /tmp/marker_result.txt | head -1 || echo "$marker_timestamp")
    log_info "Marker record inserted: $marker_id at $marker_insert_time"
    echo "- Marker ID: \`$marker_id\`" >> "$report_file"
    echo "- Insert time: $marker_insert_time" >> "$report_file"
else
    log_warn "Could not insert marker record (database may be empty)"
    echo "- Marker: skipped (database may be empty)" >> "$report_file"
fi

# Get current record counts for later comparison
log_info "Recording current data counts..."
bookings_count_pre=$(compose_cmd exec -T db psql -U postgres -d cleaning -t -c "SELECT COUNT(*) FROM bookings;" 2>/dev/null | tr -d ' ' || echo "N/A")
leads_count_pre=$(compose_cmd exec -T db psql -U postgres -d cleaning -t -c "SELECT COUNT(*) FROM leads;" 2>/dev/null | tr -d ' ' || echo "N/A")
clients_count_pre=$(compose_cmd exec -T db psql -U postgres -d cleaning -t -c "SELECT COUNT(*) FROM client_users;" 2>/dev/null | tr -d ' ' || echo "N/A")

cat >> "$report_file" << EOF

**Pre-restore record counts:**
| Table | Count |
|-------|-------|
| bookings | $bookings_count_pre |
| leads | $leads_count_pre |
| client_users | $clients_count_pre |

EOF

# =============================================================================
# Step 3: Create Fresh Backup (if not provided)
# =============================================================================

log_step "Step 3: Create/Validate Backup"
echo "### Step 3: Create/Validate Backup" >> "$report_file"

if [[ -z "$BASE_BACKUP" ]] && [[ "$SKIP_BACKUP" != "true" ]]; then
    log_info "Creating fresh base backup for drill..."

    # Export required vars for backup script
    export ENV_FILE BACKUP_ROOT

    if "$SCRIPT_DIR/backup_basebackup.sh"; then
        # Find the most recent backup
        BASE_BACKUP=$(ls -t "$BACKUP_ROOT"/basebackup_*.tar.gz 2>/dev/null | head -1)
        WAL_ARCHIVE=$(ls -t "$BACKUP_ROOT"/wal_archive_*.tar.gz 2>/dev/null | head -1)

        if [[ -n "$BASE_BACKUP" ]]; then
            log_info "Base backup created: $BASE_BACKUP"
            echo "- Base backup created: \`$(basename "$BASE_BACKUP")\`" >> "$report_file"
        else
            log_error "Failed to find created base backup"
            exit 1
        fi
    else
        log_error "Base backup creation failed"
        exit 1
    fi
else
    log_info "Using provided backup files"
    echo "- Using existing backups" >> "$report_file"
fi

# Validate backup files exist
if [[ ! -f "$BASE_BACKUP" ]]; then
    log_error "Base backup file not found: $BASE_BACKUP"
    exit 1
fi

base_backup_size=$(du -h "$BASE_BACKUP" 2>/dev/null | cut -f1 || echo "unknown")
log_info "Base backup: $BASE_BACKUP ($base_backup_size)"

if [[ -n "$WAL_ARCHIVE" ]] && [[ -f "$WAL_ARCHIVE" ]]; then
    wal_archive_size=$(du -h "$WAL_ARCHIVE" 2>/dev/null | cut -f1 || echo "unknown")
    log_info "WAL archive: $WAL_ARCHIVE ($wal_archive_size)"
    echo "- WAL archive: \`$(basename "$WAL_ARCHIVE")\` ($wal_archive_size)" >> "$report_file"
fi

echo "- Base backup: \`$(basename "$BASE_BACKUP")\` ($base_backup_size)" >> "$report_file"

# =============================================================================
# Step 4: Determine Recovery Target Time
# =============================================================================

log_step "Step 4: Determine Recovery Target"
echo "### Step 4: Recovery Target" >> "$report_file"

if [[ -z "$TARGET_TIME" ]]; then
    # Default: recover to 1 minute before marker insertion (to verify PITR works)
    # In a real drill, you'd typically recover to a known good state
    TARGET_TIME=$(date -u -d "1 minute ago" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || \
                  date -u -v-1M '+%Y-%m-%d %H:%M:%S' 2>/dev/null || \
                  echo "")

    if [[ -z "$TARGET_TIME" ]]; then
        # Fallback: use current time minus 60 seconds
        target_epoch=$(($(date +%s) - 60))
        TARGET_TIME=$(date -u -d "@$target_epoch" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || \
                      date -u -r "$target_epoch" '+%Y-%m-%d %H:%M:%S' 2>/dev/null)
    fi
    TARGET_TIME="$TARGET_TIME UTC"
    log_info "Auto-determined target time: $TARGET_TIME"
else
    log_info "Using provided target time: $TARGET_TIME"
fi

cat >> "$report_file" << EOF

- **Recovery target:** \`$TARGET_TIME\`
- **Recovery mode:** time-based PITR

EOF

# =============================================================================
# Step 5: Perform PITR Restore
# =============================================================================

log_step "Step 5: Perform PITR Restore"
echo "### Step 5: PITR Restore" >> "$report_file"

restore_start_epoch=$(date +%s)
log_info "Starting PITR restore..."

# Build restore command
restore_env=(
    "TARGET_TIME=$TARGET_TIME"
    "BASE_BACKUP=$BASE_BACKUP"
    "CONFIRM_PITR_RESTORE=YES"
    "ENV_FILE=$ENV_FILE"
)

if [[ -n "$WAL_ARCHIVE" ]] && [[ -f "$WAL_ARCHIVE" ]]; then
    restore_env+=("WAL_ARCHIVE=$WAL_ARCHIVE")
fi

# Run the PITR restore
if env "${restore_env[@]}" "$SCRIPT_DIR/pitr_restore.sh" 2>&1 | tee /tmp/pitr_restore_output.txt; then
    restore_end_epoch=$(date +%s)
    restore_duration=$((restore_end_epoch - restore_start_epoch))
    log_info "PITR restore completed in ${restore_duration}s"
    echo "- **Status:** SUCCESS" >> "$report_file"
    echo "- **Duration:** ${restore_duration} seconds" >> "$report_file"
else
    restore_end_epoch=$(date +%s)
    restore_duration=$((restore_end_epoch - restore_start_epoch))
    log_error "PITR restore failed after ${restore_duration}s"
    echo "- **Status:** FAILED" >> "$report_file"
    echo "- **Duration:** ${restore_duration} seconds" >> "$report_file"
    echo "" >> "$report_file"
    echo '```' >> "$report_file"
    tail -50 /tmp/pitr_restore_output.txt >> "$report_file" 2>/dev/null || true
    echo '```' >> "$report_file"
    drill_status="failed"
fi

# =============================================================================
# Step 6: Wait for Services to Stabilize
# =============================================================================

log_step "Step 6: Wait for Services"
echo "### Step 6: Service Stabilization" >> "$report_file"

log_info "Waiting for services to stabilize..."

# Wait for API to be ready (up to 2 minutes)
max_wait=120
waited=0
api_ready=false

while [[ $waited -lt $max_wait ]]; do
    if curl -fsS --max-time 5 "$API_BASE_URL/healthz" > /dev/null 2>&1; then
        api_ready=true
        break
    fi
    sleep 5
    waited=$((waited + 5))
    echo -n "."
done
echo ""

if [[ "$api_ready" == "true" ]]; then
    log_info "API became ready after ${waited}s"
    echo "- API ready after ${waited}s" >> "$report_file"
else
    log_error "API did not become ready within ${max_wait}s"
    echo "- API did not become ready within ${max_wait}s" >> "$report_file"
    drill_status="failed"
fi

# =============================================================================
# Step 7: Post-Restore Health Checks
# =============================================================================

log_step "Step 7: Post-Restore Health Checks"
echo "### Step 7: Post-Restore Health Checks" >> "$report_file"

post_health_status="unknown"
post_ready_status="unknown"
post_db_connected="unknown"
post_migrations_current="unknown"

# Check /healthz
if curl -fsS --max-time 10 "$API_BASE_URL/healthz" > /tmp/healthz_post.json 2>&1; then
    post_health_status=$(jq -r '.status // "unknown"' /tmp/healthz_post.json 2>/dev/null || echo "parse_error")
    post_db_connected=$(jq -r '.db_connected // "unknown"' /tmp/healthz_post.json 2>/dev/null || echo "parse_error")
    log_info "Post-restore /healthz: status=$post_health_status, db_connected=$post_db_connected"
else
    log_error "Post-restore /healthz check failed"
fi

# Check /readyz
if curl -fsS --max-time 10 "$API_BASE_URL/readyz" > /tmp/readyz_post.json 2>&1; then
    post_ready_status=$(jq -r '.status // "unknown"' /tmp/readyz_post.json 2>/dev/null || echo "parse_error")
    post_migrations_current=$(jq -r '.migrations_current // "unknown"' /tmp/readyz_post.json 2>/dev/null || echo "parse_error")
    log_info "Post-restore /readyz: status=$post_ready_status, migrations_current=$post_migrations_current"
else
    log_error "Post-restore /readyz check failed"
fi

cat >> "$report_file" << EOF

| Check | Result | Expected |
|-------|--------|----------|
| /healthz status | $post_health_status | ok or ready |
| /healthz db_connected | $post_db_connected | true |
| /readyz status | $post_ready_status | ready |
| /readyz migrations_current | $post_migrations_current | true |

EOF

# Validate health checks
health_ok=true
if [[ "$post_health_status" != "ok" ]] && [[ "$post_health_status" != "ready" ]]; then
    log_error "Health check failed: status=$post_health_status"
    health_ok=false
fi
if [[ "$post_db_connected" != "true" ]]; then
    log_error "Database not connected after restore"
    health_ok=false
fi
if [[ "$post_migrations_current" != "true" ]]; then
    log_warn "Migrations not current (may need manual intervention)"
fi

# =============================================================================
# Step 8: Data Integrity Verification
# =============================================================================

log_step "Step 8: Data Integrity Verification"
echo "### Step 8: Data Integrity Verification" >> "$report_file"

# Get post-restore record counts
bookings_count_post=$(compose_cmd exec -T db psql -U postgres -d cleaning -t -c "SELECT COUNT(*) FROM bookings;" 2>/dev/null | tr -d ' ' || echo "N/A")
leads_count_post=$(compose_cmd exec -T db psql -U postgres -d cleaning -t -c "SELECT COUNT(*) FROM leads;" 2>/dev/null | tr -d ' ' || echo "N/A")
clients_count_post=$(compose_cmd exec -T db psql -U postgres -d cleaning -t -c "SELECT COUNT(*) FROM client_users;" 2>/dev/null | tr -d ' ' || echo "N/A")

log_info "Post-restore record counts:"
log_info "  bookings: $bookings_count_post (pre: $bookings_count_pre)"
log_info "  leads: $leads_count_post (pre: $leads_count_pre)"
log_info "  clients: $clients_count_post (pre: $clients_count_pre)"

cat >> "$report_file" << EOF

**Post-restore record counts:**
| Table | Pre-Restore | Post-Restore |
|-------|-------------|--------------|
| bookings | $bookings_count_pre | $bookings_count_post |
| leads | $leads_count_pre | $leads_count_post |
| client_users | $clients_count_pre | $clients_count_post |

EOF

# Check if marker record exists (should NOT exist if we recovered to before it was inserted)
marker_exists=$(compose_cmd exec -T db psql -U postgres -d cleaning -t -c \
    "SELECT COUNT(*) FROM _pitr_drill_markers WHERE id = '$marker_id';" 2>/dev/null | tr -d ' ' || echo "error")

if [[ "$marker_exists" == "0" ]]; then
    log_info "PITR verification PASSED: Marker record not found (recovered to before insertion)"
    echo "- **Marker verification:** PASSED (marker not found, as expected)" >> "$report_file"
elif [[ "$marker_exists" == "1" ]]; then
    log_warn "PITR verification: Marker record found (recovered to after insertion time)"
    echo "- **Marker verification:** Marker found (recovery point was after insertion)" >> "$report_file"
else
    log_warn "Could not verify marker record (table may not exist)"
    echo "- **Marker verification:** Could not verify (table may not exist)" >> "$report_file"
fi

# =============================================================================
# Step 9: Run Smoke Tests
# =============================================================================

log_step "Step 9: Smoke Tests"
echo "### Step 9: Smoke Tests" >> "$report_file"

smoke_result="skipped"
if [[ -x "$SCRIPT_DIR/smoke.sh" ]]; then
    log_info "Running smoke tests..."
    export API_BASE_URL
    export WEB_BASE_URL=${WEB_BASE_URL:-http://localhost:3000}

    if "$SCRIPT_DIR/smoke.sh" 2>&1 | tee /tmp/smoke_output.txt; then
        smoke_result="passed"
        log_info "Smoke tests PASSED"
    else
        smoke_result="failed"
        log_error "Smoke tests FAILED"
        drill_status="failed"
    fi
else
    log_warn "Smoke test script not found, skipping"
fi

echo "- **Smoke tests:** $smoke_result" >> "$report_file"

# =============================================================================
# Step 10: Finalize Drill Report
# =============================================================================

log_step "Step 10: Finalize Report"

drill_end_utc=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
drill_end_epoch=$(date +%s)
drill_duration=$((drill_end_epoch - drill_start_epoch))
drill_duration_min=$((drill_duration / 60))

# Determine final status
if [[ ${#drill_errors[@]} -eq 0 ]] && [[ "$health_ok" == "true" ]] && [[ "$smoke_result" != "failed" ]]; then
    drill_status="passed"
else
    drill_status="failed"
fi

# Calculate RTO (time from restore start to healthy state)
rto_seconds=$((restore_duration + waited))
rto_minutes=$((rto_seconds / 60))

cat >> "$report_file" << EOF

---

## Drill Summary

| Metric | Value | Target |
|--------|-------|--------|
| **Status** | **${drill_status^^}** | passed |
| Start Time (UTC) | $drill_start_utc | - |
| End Time (UTC) | $drill_end_utc | - |
| Total Duration | ${drill_duration_min} minutes (${drill_duration}s) | < 90 min |
| RTO Achieved | ${rto_minutes} minutes (${rto_seconds}s) | < 120 min |

EOF

if [[ ${#drill_errors[@]} -gt 0 ]]; then
    echo "" >> "$report_file"
    echo "### Errors Encountered" >> "$report_file"
    echo "" >> "$report_file"
    for error in "${drill_errors[@]}"; do
        echo "- $error" >> "$report_file"
    done
fi

cat >> "$report_file" << EOF

---

## Verification Checklist

- [$([ "$post_health_status" == "ok" ] || [ "$post_health_status" == "ready" ] && echo "x" || echo " ")] \`/healthz\` returns HTTP 200 with status \`ok\` or \`ready\`
- [$([ "$post_db_connected" == "true" ] && echo "x" || echo " ")] \`/healthz\` shows \`db_connected=true\`
- [$([ "$post_ready_status" == "ready" ] && echo "x" || echo " ")] \`/readyz\` returns HTTP 200 with status \`ready\`
- [$([ "$post_migrations_current" == "true" ] && echo "x" || echo " ")] \`/readyz\` shows \`migrations_current=true\`
- [$([ "$smoke_result" == "passed" ] && echo "x" || echo " ")] Smoke tests passed
- [$([ "$bookings_count_post" != "N/A" ] && echo "x" || echo " ")] Sample queries return data

---

## Next Steps

$(if [ "$drill_status" == "passed" ]; then
    echo "The PITR restore drill completed successfully. No further action required."
    echo ""
    echo "Recommended follow-up:"
    echo "- Archive this report"
    echo "- Schedule next quarterly drill"
else
    echo "The PITR restore drill encountered issues. Please investigate:"
    echo ""
    echo "1. Review the errors listed above"
    echo "2. Check PostgreSQL logs: \`docker compose logs db\`"
    echo "3. Check API logs: \`docker compose logs api\`"
    echo "4. Verify WAL archiving is working: \`ls -la /var/lib/postgresql/wal_archive/\`"
fi)

---

*Report generated by \`ops/pitr_restore_drill.sh\` at $drill_end_utc*
EOF

# =============================================================================
# Final Output
# =============================================================================

echo ""
echo "============================================================"
if [[ "$drill_status" == "passed" ]]; then
    echo -e "  ${GREEN}PITR RESTORE DRILL: PASSED${NC}"
else
    echo -e "  ${RED}PITR RESTORE DRILL: FAILED${NC}"
fi
echo "============================================================"
echo ""
echo "Drill ID:       $drill_id"
echo "Duration:       ${drill_duration_min} minutes"
echo "RTO achieved:   ${rto_minutes} minutes"
echo "Report:         $report_file"
echo ""

if [[ "$drill_status" == "passed" ]]; then
    log_info "All health checks passed. Staging environment restored successfully."
    exit 0
else
    log_error "Drill failed. Review report for details: $report_file"
    exit 1
fi
