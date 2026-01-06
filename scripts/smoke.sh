#!/usr/bin/env bash
# Comprehensive smoke test pack for CleanWithSnapshot
# Usage: ./scripts/smoke.sh [BASE_URL]
# Environment variables:
#   API_BASE_URL - API base URL (default: https://api.panidobro.com)
#   WEB_BASE_URL - Web base URL (default: https://panidobro.com)
#   ADMIN_USER - Admin username for authenticated tests (optional)
#   ADMIN_PASS - Admin password for authenticated tests (optional)
#   SMOKE_SKIP_AUTH - Skip authenticated tests (default: false)
#   SMOKE_SKIP_WEB - Skip web tests (default: false)
#   SMOKE_SKIP_BACKUP - Skip backup health check (default: false)

set -euo pipefail

# Default configuration
API_BASE_URL=${API_BASE_URL:-https://api.panidobro.com}
WEB_BASE_URL=${WEB_BASE_URL:-https://panidobro.com}
ADMIN_USER=${ADMIN_USER:-}
ADMIN_PASS=${ADMIN_PASS:-}
SMOKE_SKIP_AUTH=${SMOKE_SKIP_AUTH:-false}
SMOKE_SKIP_WEB=${SMOKE_SKIP_WEB:-false}
SMOKE_SKIP_BACKUP=${SMOKE_SKIP_BACKUP:-false}

# Override with positional argument if provided
if [[ $# -gt 0 ]]; then
  if [[ "$1" =~ ^https?:// ]]; then
    API_BASE_URL="$1"
    # Infer web URL from API URL
    WEB_BASE_URL="${API_BASE_URL/api./}"
  fi
fi

# Results tracking
declare -a RESULTS
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0
SKIPPED_TESTS=0

# Colors for output (disabled if not a tty)
if [[ -t 1 ]]; then
  GREEN='\033[0;32m'
  RED='\033[0;31m'
  YELLOW='\033[1;33m'
  BLUE='\033[0;34m'
  GRAY='\033[0;90m'
  NC='\033[0m' # No Color
else
  GREEN=''
  RED=''
  YELLOW=''
  BLUE=''
  GRAY=''
  NC=''
fi

# Utility functions
log_section() {
  echo -e "\n${BLUE}=== $1 ===${NC}"
}

log_test() {
  echo -ne "${GRAY}[TEST]${NC} $1... "
}

log_pass() {
  echo -e "${GREEN}✓ PASS${NC}"
  RESULTS+=("✓ $1")
  ((PASSED_TESTS++))
  ((TOTAL_TESTS++))
}

log_fail() {
  local msg="${2:-}"
  echo -e "${RED}✗ FAIL${NC}${msg:+ ($msg)}"
  RESULTS+=("✗ $1${msg:+ - $msg}")
  ((FAILED_TESTS++))
  ((TOTAL_TESTS++))
}

log_skip() {
  echo -e "${YELLOW}⊘ SKIP${NC} ${2:-}"
  RESULTS+=("⊘ $1 (skipped)")
  ((SKIPPED_TESTS++))
  ((TOTAL_TESTS++))
}

# Test function: check HTTP endpoint
# Args: name, url, expected_status, [max_attempts], [retry_delay]
check_endpoint() {
  local name="$1"
  local url="$2"
  local expected_status="${3:-200}"
  local max_attempts="${4:-5}"
  local retry_delay="${5:-2}"

  log_test "$name"

  local attempts=0
  local status=""

  while [[ $attempts -lt $max_attempts ]]; do
    attempts=$((attempts + 1))
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null) || status="000"

    if [[ "$status" == "$expected_status" ]]; then
      log_pass "$name"
      return 0
    fi

    if [[ $attempts -lt $max_attempts ]]; then
      sleep "$retry_delay"
    fi
  done

  log_fail "$name" "HTTP $status (expected $expected_status)"
  return 1
}

# Test function: check HTTP endpoint with auth
# Args: name, url, username, password, expected_status
check_endpoint_auth() {
  local name="$1"
  local url="$2"
  local username="$3"
  local password="$4"
  local expected_status="${5:-200}"

  log_test "$name"

  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -u "$username:$password" "$url" 2>/dev/null) || status="000"

  if [[ "$status" == "$expected_status" ]]; then
    log_pass "$name"
    return 0
  fi

  log_fail "$name" "HTTP $status (expected $expected_status)"
  return 1
}

# Test function: check JSON response field
# Args: name, url, jq_filter, expected_value
check_json_field() {
  local name="$1"
  local url="$2"
  local jq_filter="$3"
  local expected="$4"

  log_test "$name"

  if ! command -v jq >/dev/null 2>&1; then
    log_skip "$name" "jq not available"
    return 0
  fi

  local value
  value=$(curl -fsS --max-time 5 "$url" 2>/dev/null | jq -r "$jq_filter" 2>/dev/null) || {
    log_fail "$name" "failed to fetch or parse JSON"
    return 1
  }

  if [[ "$value" == "$expected" ]]; then
    log_pass "$name"
    return 0
  fi

  log_fail "$name" "got '$value', expected '$expected'"
  return 1
}

# Test function: check HTTP method
# Args: name, method, url, expected_status
check_http_method() {
  local name="$1"
  local method="$2"
  local url="$3"
  local expected_status="${4:-200}"

  log_test "$name"

  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 -X "$method" "$url" 2>/dev/null) || status="000"

  if [[ "$status" == "$expected_status" ]]; then
    log_pass "$name"
    return 0
  fi

  log_fail "$name" "HTTP $status (expected $expected_status)"
  return 1
}

# Test function: check POST with JSON payload
# Args: name, url, json_payload, expected_status
check_post_json() {
  local name="$1"
  local url="$2"
  local payload="$3"
  local expected_status="${4:-200}"

  log_test "$name"

  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -X POST -H "Content-Type: application/json" \
    -d "$payload" "$url" 2>/dev/null) || status="000"

  if [[ "$status" == "$expected_status" ]]; then
    log_pass "$name"
    return 0
  fi

  log_fail "$name" "HTTP $status (expected $expected_status)"
  return 1
}

# Main smoke test execution
main() {
  echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BLUE}║           CleanWithSnapshot Smoke Test Pack               ║${NC}"
  echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo "API URL: $API_BASE_URL"
  echo "Web URL: $WEB_BASE_URL"
  echo ""

  # Section 1: Core Health Checks
  log_section "1. Core Health & Readiness"
  check_endpoint "API liveness (GET /healthz)" "$API_BASE_URL/healthz" 200
  check_http_method "API liveness (HEAD /healthz)" HEAD "$API_BASE_URL/healthz" 200
  check_endpoint "API readiness (GET /readyz)" "$API_BASE_URL/readyz" 200

  if [[ "$SMOKE_SKIP_BACKUP" == "false" ]]; then
    # Backup health check - allow 503 as it may not be configured in all environments
    log_test "Backup health check"
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$API_BASE_URL/healthz/backup" 2>/dev/null) || status="000"
    if [[ "$status" == "200" ]]; then
      log_pass "Backup health check"
    elif [[ "$status" == "503" ]]; then
      log_skip "Backup health check" "not configured or outdated"
    else
      log_fail "Backup health check" "HTTP $status"
    fi
  else
    log_skip "Backup health check" "SMOKE_SKIP_BACKUP=true"
  fi

  # Section 2: Web Application
  if [[ "$SMOKE_SKIP_WEB" == "false" ]]; then
    log_section "2. Web Application"
    check_endpoint "Web root" "$WEB_BASE_URL/" 200
  else
    log_section "2. Web Application"
    log_skip "Web root" "SMOKE_SKIP_WEB=true"
  fi

  # Section 3: API Core Endpoints
  log_section "3. API Core Endpoints"
  check_endpoint "OpenAPI docs" "$API_BASE_URL/docs" 200 1
  check_endpoint "OpenAPI schema" "$API_BASE_URL/openapi.json" 200 1

  # Test estimate endpoint with valid payload
  check_post_json "Estimate pricing endpoint" "$API_BASE_URL/v1/estimate" \
    '{"beds":2,"baths":1,"cleaning_type":"standard","frequency":"weekly"}' 200

  # Section 4: Authentication
  log_section "4. Authentication & Authorization"

  # Test unauthenticated access is rejected
  check_endpoint "Admin endpoint without auth (expect 401)" "$API_BASE_URL/v1/admin/profile" 401 1

  # Test authenticated access if credentials provided
  if [[ "$SMOKE_SKIP_AUTH" == "false" && -n "$ADMIN_USER" && -n "$ADMIN_PASS" ]]; then
    check_endpoint_auth "Admin auth (Basic)" "$API_BASE_URL/v1/admin/profile" \
      "$ADMIN_USER" "$ADMIN_PASS" 200
  else
    if [[ "$SMOKE_SKIP_AUTH" == "true" ]]; then
      log_skip "Admin auth (Basic)" "SMOKE_SKIP_AUTH=true"
    else
      log_skip "Admin auth (Basic)" "ADMIN_USER/ADMIN_PASS not set"
    fi
  fi

  # Section 5: Stripe Integration
  log_section "5. Stripe Webhook Endpoint"

  # Stripe webhook should reject invalid signatures (400 or 503 if not configured)
  log_test "Stripe webhook endpoint availability"
  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -X POST -H "Content-Type: application/json" \
    -H "Stripe-Signature: t=invalid" \
    -d '{}' "$API_BASE_URL/v1/payments/stripe/webhook" 2>/dev/null) || status="000"

  if [[ "$status" == "400" ]]; then
    log_pass "Stripe webhook endpoint availability"
  elif [[ "$status" == "503" ]]; then
    log_skip "Stripe webhook endpoint availability" "webhook secret not configured"
  else
    log_fail "Stripe webhook endpoint availability" "HTTP $status (expected 400 or 503)"
  fi

  # Section 6: Security Headers
  log_section "6. Security & Headers"

  log_test "Security headers (X-Content-Type-Options)"
  if curl -fsS -I --max-time 5 "$API_BASE_URL/healthz" 2>/dev/null | grep -qi "x-content-type-options: nosniff"; then
    log_pass "Security headers (X-Content-Type-Options)"
  else
    log_fail "Security headers (X-Content-Type-Options)" "header not found"
  fi

  log_test "Security headers (X-Frame-Options)"
  if curl -fsS -I --max-time 5 "$API_BASE_URL/healthz" 2>/dev/null | grep -qi "x-frame-options: deny"; then
    log_pass "Security headers (X-Frame-Options)"
  else
    log_fail "Security headers (X-Frame-Options)" "header not found"
  fi

  # Section 7: JSON Response Validation (if jq available)
  if command -v jq >/dev/null 2>&1; then
    log_section "7. Response Validation"
    check_json_field "Health status field" "$API_BASE_URL/healthz" '.status' 'ok'
    check_json_field "Readiness database.ok" "$API_BASE_URL/readyz" '.database.ok' 'true'
  else
    log_section "7. Response Validation"
    log_skip "JSON validation tests" "jq not installed"
  fi

  # Print summary
  echo ""
  echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BLUE}║                     Test Summary                          ║${NC}"
  echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo "Total tests:   $TOTAL_TESTS"
  echo -e "${GREEN}Passed:        $PASSED_TESTS${NC}"

  if [[ $FAILED_TESTS -gt 0 ]]; then
    echo -e "${RED}Failed:        $FAILED_TESTS${NC}"
  else
    echo "Failed:        $FAILED_TESTS"
  fi

  if [[ $SKIPPED_TESTS -gt 0 ]]; then
    echo -e "${YELLOW}Skipped:       $SKIPPED_TESTS${NC}"
  else
    echo "Skipped:       $SKIPPED_TESTS"
  fi

  echo ""
  echo "Detailed results:"
  for result in "${RESULTS[@]}"; do
    echo "  $result"
  done
  echo ""

  # Exit with appropriate code
  if [[ $FAILED_TESTS -gt 0 ]]; then
    echo -e "${RED}✗ SMOKE TESTS FAILED${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  - Check service status: docker compose ps"
    echo "  - Review logs: docker compose logs api web"
    echo "  - Check readiness details: curl $API_BASE_URL/readyz | jq ."
    echo "  - Verify environment variables in .env"
    echo ""
    exit 1
  elif [[ $PASSED_TESTS -eq 0 ]]; then
    echo -e "${YELLOW}⚠ NO TESTS PASSED${NC}"
    exit 1
  else
    echo -e "${GREEN}✓ ALL SMOKE TESTS PASSED${NC}"
    if [[ $SKIPPED_TESTS -gt 0 ]]; then
      echo -e "${YELLOW}  ($SKIPPED_TESTS tests skipped)${NC}"
    fi
    echo ""
    exit 0
  fi
}

# Run main function
main "$@"
