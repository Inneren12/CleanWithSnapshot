#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL=${API_BASE_URL:-https://api.panidobro.com}
WEB_BASE_URL=${WEB_BASE_URL:-https://panidobro.com}

report=()

check_endpoint() {
  local name="$1"
  local url="$2"
  local attempts=0
  local max_attempts=5
  local status=""

  while [[ $attempts -lt $max_attempts ]]; do
    attempts=$((attempts + 1))
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url") || status="000"
    if [[ "$status" =~ ^[23][0-9]{2}$ ]]; then
      echo "[OK] $name ($status)"
      report+=("$name: OK ($status)")
      return 0
    fi
    echo "[wait] $name not ready (status: $status). attempt $attempts/$max_attempts"
    sleep 2
  done

  echo "[FAIL] $name failed after $max_attempts attempts (last status: $status)" >&2
  report+=("$name: FAIL ($status)")
  return 1
}

api_status=0
web_status=0

check_endpoint "API /healthz" "$API_BASE_URL/healthz" || api_status=$?
check_endpoint "Web root" "$WEB_BASE_URL/" || web_status=$?

printf '\nSmoke summary:\n'
for line in "${report[@]}"; do
  printf "- %s\n" "$line"
done

if [[ $api_status -ne 0 || $web_status -ne 0 ]]; then
  exit 1
fi

exit 0
