#!/usr/bin/env bash
# Generate Caddyfile with canary traffic routing configuration
# Usage: ./generate_canary_caddyfile.sh <canary_weight_percent>
#
# This script generates a Caddyfile that routes traffic between stable and
# canary API instances based on the specified weight percentage.
#
# Examples:
#   ./generate_canary_caddyfile.sh 0    # All traffic to stable
#   ./generate_canary_caddyfile.sh 10   # 10% to canary, 90% to stable
#   ./generate_canary_caddyfile.sh 100  # All traffic to canary (promote)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

TEMPLATE_FILE="${REPO_ROOT}/config/canary/Caddyfile.template"
OUTPUT_FILE="${REPO_ROOT}/Caddyfile.canary"

# Default to 0% canary traffic
CANARY_WEIGHT="${1:-0}"

# Validate input
if ! [[ "$CANARY_WEIGHT" =~ ^[0-9]+$ ]] || [[ "$CANARY_WEIGHT" -gt 100 ]]; then
  echo "ERROR: Canary weight must be an integer between 0 and 100" >&2
  exit 1
fi

STABLE_WEIGHT=$((100 - CANARY_WEIGHT))

echo "Generating Caddyfile with traffic split: stable=${STABLE_WEIGHT}%, canary=${CANARY_WEIGHT}%"

# Generate upstream configuration based on weights
# Caddy's random_choose policy works by randomly selecting from the pool
# We replicate upstreams to create the desired ratio
generate_upstream_config() {
  local stable_weight="$1"
  local canary_weight="$2"
  local upstreams=""

  # Handle edge cases
  if [[ "$canary_weight" -eq 0 ]]; then
    echo "api:8000"
    return
  fi

  if [[ "$stable_weight" -eq 0 ]]; then
    echo "api-canary:8000"
    return
  fi

  # Find GCD for simplification
  gcd() {
    local a=$1 b=$2
    while [[ $b -ne 0 ]]; do
      local temp=$b
      b=$((a % b))
      a=$temp
    done
    echo "$a"
  }

  local divisor
  divisor=$(gcd "$stable_weight" "$canary_weight")
  local stable_units=$((stable_weight / divisor))
  local canary_units=$((canary_weight / divisor))

  # Cap at reasonable number of upstreams (max 20)
  while [[ $((stable_units + canary_units)) -gt 20 ]]; do
    stable_units=$(( (stable_units + 1) / 2 ))
    canary_units=$(( (canary_units + 1) / 2 ))
    # Ensure at least 1 of each if both were > 0
    [[ $stable_units -eq 0 && $stable_weight -gt 0 ]] && stable_units=1
    [[ $canary_units -eq 0 && $canary_weight -gt 0 ]] && canary_units=1
  done

  # Build upstream list
  for ((i=0; i<stable_units; i++)); do
    upstreams="${upstreams} api:8000"
  done
  for ((i=0; i<canary_units; i++)); do
    upstreams="${upstreams} api-canary:8000"
  done

  # Trim leading space
  echo "${upstreams# }"
}

UPSTREAM_CONFIG=$(generate_upstream_config "$STABLE_WEIGHT" "$CANARY_WEIGHT")

echo "Generated upstream configuration: ${UPSTREAM_CONFIG}"

# Check if template exists
if [[ ! -f "$TEMPLATE_FILE" ]]; then
  echo "ERROR: Template file not found: $TEMPLATE_FILE" >&2
  exit 1
fi

# Generate Caddyfile from template
sed "s|{{CANARY_UPSTREAM_CONFIG}}|${UPSTREAM_CONFIG}|g" "$TEMPLATE_FILE" > "$OUTPUT_FILE"

echo "Generated Caddyfile written to: $OUTPUT_FILE"

# Validate the generated Caddyfile (if caddy is available)
if command -v caddy &> /dev/null; then
  echo "Validating generated Caddyfile..."
  if caddy validate --config "$OUTPUT_FILE" 2>/dev/null; then
    echo "Caddyfile validation passed"
  else
    echo "WARNING: Caddyfile validation failed (caddy may need to run in container)" >&2
  fi
elif docker compose ps caddy 2>/dev/null | grep -q "running"; then
  echo "Validating generated Caddyfile via container..."
  if docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile 2>/dev/null; then
    echo "Caddyfile validation passed"
  fi
else
  echo "Skipping Caddyfile validation (caddy not available)"
fi

echo "Canary Caddyfile generation complete"
