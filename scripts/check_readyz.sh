#!/usr/bin/env bash
# Check /readyz endpoint and fail if unhealthy
# Usage: ./scripts/check_readyz.sh [API_BASE_URL]
# Environment variables:
#   API_BASE_URL - API base URL (default: http://localhost:8000)
#   READYZ_TIMEOUT - Request timeout in seconds (default: 5)
#   READYZ_VERBOSE - Print detailed output (default: false)

set -euo pipefail

# Configuration
API_BASE_URL=${API_BASE_URL:-http://localhost:8000}
READYZ_TIMEOUT=${READYZ_TIMEOUT:-5}
READYZ_VERBOSE=${READYZ_VERBOSE:-false}

# Override with positional argument if provided
if [[ $# -gt 0 ]]; then
  API_BASE_URL="$1"
fi

# Colors for output (disabled if not a tty)
if [[ -t 1 ]]; then
  GREEN='\033[0;32m'
  RED='\033[0;31m'
  YELLOW='\033[1;33m'
  GRAY='\033[0;90m'
  NC='\033[0m' # No Color
else
  GREEN=''
  RED=''
  YELLOW=''
  GRAY=''
  NC=''
fi

# Check if jq is available for JSON parsing
HAS_JQ=false
if command -v jq >/dev/null 2>&1; then
  HAS_JQ=true
fi

# Make the request
READYZ_URL="${API_BASE_URL}/readyz"

if [[ "$READYZ_VERBOSE" == "true" ]]; then
  echo -e "${GRAY}Checking readiness: ${READYZ_URL}${NC}"
fi

# Fetch response and status code
HTTP_RESPONSE=$(mktemp)
trap "rm -f $HTTP_RESPONSE" EXIT

HTTP_CODE=$(curl -s -w "%{http_code}" -o "$HTTP_RESPONSE" --max-time "$READYZ_TIMEOUT" "$READYZ_URL" 2>/dev/null) || {
  echo -e "${RED}✗ FAIL: Unable to connect to ${READYZ_URL}${NC}" >&2
  exit 1
}

# Check HTTP status code
if [[ "$HTTP_CODE" == "200" ]]; then
  if [[ "$READYZ_VERBOSE" == "true" || "$HAS_JQ" == "false" ]]; then
    echo -e "${GREEN}✓ PASS: Readiness check succeeded (HTTP ${HTTP_CODE})${NC}"
  fi

  # Validate JSON response if jq is available
  if [[ "$HAS_JQ" == "true" ]]; then
    RESPONSE_BODY=$(cat "$HTTP_RESPONSE")

    # Check if overall ok is true
    OK_VALUE=$(echo "$RESPONSE_BODY" | jq -r '.ok // false' 2>/dev/null)
    if [[ "$OK_VALUE" != "true" ]]; then
      echo -e "${RED}✗ FAIL: Readiness check returned ok: false${NC}" >&2
      if [[ "$READYZ_VERBOSE" == "true" ]]; then
        echo "$RESPONSE_BODY" | jq . >&2
      fi
      exit 1
    fi

    # Check if checks array exists
    CHECKS_COUNT=$(echo "$RESPONSE_BODY" | jq -r '.checks | length' 2>/dev/null)
    if [[ "$CHECKS_COUNT" -eq 0 ]]; then
      echo -e "${RED}✗ FAIL: No health checks found in response${NC}" >&2
      if [[ "$READYZ_VERBOSE" == "true" ]]; then
        echo "$RESPONSE_BODY" | jq . >&2
      fi
      exit 1
    fi

    if [[ "$READYZ_VERBOSE" == "true" ]]; then
      echo -e "${GRAY}Checks:${NC}"
      echo "$RESPONSE_BODY" | jq -r '.checks[] | "  [\(.ok | if . then "✓" else "✗" end)] \(.name): \(.detail) (\(.ms)ms)"'
    else
      # Compact output: just show we're healthy
      echo -e "${GREEN}✓ PASS${NC}: All checks healthy (${CHECKS_COUNT} checks, HTTP ${HTTP_CODE})"
    fi
  fi

  exit 0
elif [[ "$HTTP_CODE" == "503" ]]; then
  echo -e "${RED}✗ FAIL: Service unavailable (HTTP 503)${NC}" >&2

  if [[ "$HAS_JQ" == "true" ]]; then
    RESPONSE_BODY=$(cat "$HTTP_RESPONSE")

    # Show which checks failed
    FAILED_CHECKS=$(echo "$RESPONSE_BODY" | jq -r '.checks[] | select(.ok == false) | "  [\(.name)] \(.detail)"' 2>/dev/null || echo "")
    if [[ -n "$FAILED_CHECKS" ]]; then
      echo -e "${YELLOW}Failed checks:${NC}" >&2
      echo "$FAILED_CHECKS" >&2
    fi

    if [[ "$READYZ_VERBOSE" == "true" ]]; then
      echo -e "${GRAY}Full response:${NC}" >&2
      echo "$RESPONSE_BODY" | jq . >&2
    fi
  else
    echo -e "${GRAY}Response body:${NC}" >&2
    cat "$HTTP_RESPONSE" >&2
  fi

  exit 1
else
  echo -e "${RED}✗ FAIL: Unexpected HTTP status ${HTTP_CODE}${NC}" >&2
  if [[ "$READYZ_VERBOSE" == "true" ]]; then
    echo -e "${GRAY}Response body:${NC}" >&2
    cat "$HTTP_RESPONSE" >&2
  fi
  exit 1
fi
