#!/usr/bin/env bash
# =============================================================================
# PITR Restore Verification Script
# =============================================================================
# Verifies that a PostgreSQL PITR restore completed successfully by checking:
# - API health endpoints (/healthz, /readyz)
# - Database connectivity and data integrity
# - Application boot status
#
# Usage:
#   ./ops/pitr_verify.sh
#
# Environment variables (optional):
#   API_BASE_URL    - API endpoint (default: http://localhost:8000)
#   ENV_FILE        - Path to .env file (default: .env)
#   VERBOSE         - Set to "true" for detailed output
#
# Exit codes:
#   0 - All checks passed
#   1 - One or more checks failed
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# Configuration
API_BASE_URL=${API_BASE_URL:-http://localhost:8000}
ENV_FILE=${ENV_FILE:-.env}
VERBOSE=${VERBOSE:-false}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Track results
checks_passed=0
checks_failed=0
checks_warned=0

# =============================================================================
# Helper Functions
# =============================================================================

log_pass() {
    echo -e "[${GREEN}PASS${NC}] $1"
    ((checks_passed++))
}

log_fail() {
    echo -e "[${RED}FAIL${NC}] $1"
    ((checks_failed++))
}

log_warn() {
    echo -e "[${YELLOW}WARN${NC}] $1"
    ((checks_warned++))
}

log_info() {
    if [[ "$VERBOSE" == "true" ]]; then
        echo "[INFO] $1"
    fi
}

compose_cmd() {
    local compose=("docker" "compose")
    if [[ -f "$ENV_FILE" ]]; then
        compose+=("--env-file" "$ENV_FILE")
    fi
    "${compose[@]}" "$@"
}

# =============================================================================
# Health Check Functions
# =============================================================================

check_healthz() {
    echo ""
    echo "Checking /healthz endpoint..."

    local response
    local http_code

    response=$(curl -sS --max-time 10 -w "\n%{http_code}" "$API_BASE_URL/healthz" 2>/dev/null) || {
        log_fail "/healthz - endpoint unreachable"
        return 1
    }

    http_code=$(echo "$response" | tail -1)
    local body=$(echo "$response" | sed '$d')

    log_info "Response: $body"

    if [[ "$http_code" != "200" ]]; then
        log_fail "/healthz - HTTP $http_code (expected 200)"
        return 1
    fi

    local status=$(echo "$body" | jq -r '.status // "unknown"' 2>/dev/null || echo "parse_error")
    local db_connected=$(echo "$body" | jq -r '.db_connected // "unknown"' 2>/dev/null || echo "parse_error")

    if [[ "$status" == "ok" ]] || [[ "$status" == "ready" ]]; then
        log_pass "/healthz - status=$status"
    else
        log_fail "/healthz - status=$status (expected ok or ready)"
    fi

    if [[ "$db_connected" == "true" ]]; then
        log_pass "/healthz - db_connected=true"
    else
        log_fail "/healthz - db_connected=$db_connected (expected true)"
    fi
}

check_readyz() {
    echo ""
    echo "Checking /readyz endpoint..."

    local response
    local http_code

    response=$(curl -sS --max-time 10 -w "\n%{http_code}" "$API_BASE_URL/readyz" 2>/dev/null) || {
        log_fail "/readyz - endpoint unreachable"
        return 1
    }

    http_code=$(echo "$response" | tail -1)
    local body=$(echo "$response" | sed '$d')

    log_info "Response: $body"

    if [[ "$http_code" != "200" ]]; then
        log_fail "/readyz - HTTP $http_code (expected 200)"
        return 1
    fi

    local status=$(echo "$body" | jq -r '.status // "unknown"' 2>/dev/null || echo "parse_error")
    local migrations=$(echo "$body" | jq -r '.migrations_current // "unknown"' 2>/dev/null || echo "parse_error")

    if [[ "$status" == "ready" ]]; then
        log_pass "/readyz - status=$status"
    else
        log_fail "/readyz - status=$status (expected ready)"
    fi

    if [[ "$migrations" == "true" ]]; then
        log_pass "/readyz - migrations_current=true"
    else
        log_warn "/readyz - migrations_current=$migrations (may need: alembic upgrade head)"
    fi
}

check_database_queries() {
    echo ""
    echo "Checking database queries..."

    # Test basic connectivity
    if compose_cmd exec -T db pg_isready -U postgres 2>/dev/null; then
        log_pass "PostgreSQL is ready"
    else
        log_fail "PostgreSQL is not ready"
        return 1
    fi

    # Test data queries
    local bookings_count
    bookings_count=$(compose_cmd exec -T db psql -U postgres -d cleaning -t -c \
        "SELECT COUNT(*) FROM bookings;" 2>/dev/null | tr -d ' ' || echo "error")

    if [[ "$bookings_count" =~ ^[0-9]+$ ]]; then
        log_pass "SELECT COUNT(*) FROM bookings = $bookings_count"
    else
        log_fail "Could not query bookings table: $bookings_count"
    fi

    local leads_count
    leads_count=$(compose_cmd exec -T db psql -U postgres -d cleaning -t -c \
        "SELECT COUNT(*) FROM leads;" 2>/dev/null | tr -d ' ' || echo "error")

    if [[ "$leads_count" =~ ^[0-9]+$ ]]; then
        log_pass "SELECT COUNT(*) FROM leads = $leads_count"
    else
        log_fail "Could not query leads table: $leads_count"
    fi

    # Check latest data timestamp
    local max_booking_date
    max_booking_date=$(compose_cmd exec -T db psql -U postgres -d cleaning -t -c \
        "SELECT MAX(created_at) FROM bookings;" 2>/dev/null | tr -d ' ' || echo "N/A")

    if [[ -n "$max_booking_date" ]] && [[ "$max_booking_date" != "N/A" ]]; then
        log_info "Latest booking created_at: $max_booking_date"
        log_pass "Data timestamp check completed"
    else
        log_warn "Could not determine latest data timestamp"
    fi
}

check_postgres_recovery_status() {
    echo ""
    echo "Checking PostgreSQL recovery status..."

    # Check if recovery is complete (no recovery.signal)
    local in_recovery
    in_recovery=$(compose_cmd exec -T db psql -U postgres -t -c \
        "SELECT pg_is_in_recovery();" 2>/dev/null | tr -d ' ' || echo "error")

    if [[ "$in_recovery" == "f" ]]; then
        log_pass "PostgreSQL is not in recovery mode (recovery complete)"
    elif [[ "$in_recovery" == "t" ]]; then
        log_warn "PostgreSQL is still in recovery mode"
    else
        log_fail "Could not determine recovery status: $in_recovery"
    fi

    # Check WAL archiving status
    local archive_mode
    archive_mode=$(compose_cmd exec -T db psql -U postgres -t -c \
        "SHOW archive_mode;" 2>/dev/null | tr -d ' ' || echo "error")

    if [[ "$archive_mode" == "on" ]]; then
        log_pass "WAL archiving is enabled (archive_mode=on)"
    else
        log_warn "WAL archiving status: $archive_mode"
    fi
}

check_services_running() {
    echo ""
    echo "Checking Docker services..."

    local services=("db" "api")
    for svc in "${services[@]}"; do
        if compose_cmd ps --status running "$svc" 2>/dev/null | grep -q "$svc"; then
            log_pass "Service '$svc' is running"
        else
            log_fail "Service '$svc' is not running"
        fi
    done

    # Optional services
    local optional_services=("web" "jobs" "redis")
    for svc in "${optional_services[@]}"; do
        if compose_cmd ps --status running "$svc" 2>/dev/null | grep -q "$svc"; then
            log_pass "Service '$svc' is running"
        else
            log_warn "Service '$svc' is not running (may be optional)"
        fi
    done
}

# =============================================================================
# Main Execution
# =============================================================================

echo "============================================================"
echo "  PITR Restore Verification"
echo "============================================================"
echo "API URL:    $API_BASE_URL"
echo "ENV_FILE:   $ENV_FILE"
echo "============================================================"

# Run all checks
check_services_running
check_postgres_recovery_status
check_healthz
check_readyz
check_database_queries

# Summary
echo ""
echo "============================================================"
echo "  Verification Summary"
echo "============================================================"
echo -e "  ${GREEN}Passed:${NC}  $checks_passed"
echo -e "  ${RED}Failed:${NC}  $checks_failed"
echo -e "  ${YELLOW}Warned:${NC}  $checks_warned"
echo "============================================================"

if [[ $checks_failed -eq 0 ]]; then
    echo ""
    echo -e "${GREEN}All critical checks passed. PITR restore verified successfully.${NC}"
    exit 0
else
    echo ""
    echo -e "${RED}$checks_failed check(s) failed. Review the output above.${NC}"
    echo ""
    echo "Troubleshooting steps:"
    echo "  1. Check PostgreSQL logs: docker compose logs db"
    echo "  2. Check API logs: docker compose logs api"
    echo "  3. Run migrations if needed: docker compose exec api alembic upgrade head"
    echo "  4. Verify recovery configuration was applied correctly"
    exit 1
fi
