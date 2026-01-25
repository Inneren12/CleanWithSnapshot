#!/usr/bin/env bash
# Emergency Canary Rollback Script
# This script quickly rolls back a canary deployment to stable.
#
# Usage:
#   ./canary_rollback.sh [--force]
#
# This is a simplified script for emergency use. For normal operations,
# use: ./deploy_canary.sh rollback
#
# Options:
#   --force    Skip confirmation prompt

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "[INFO] $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

FORCE=false
if [[ "${1:-}" == "--force" ]]; then
  FORCE=true
fi

STATE_FILE="${REPO_ROOT}/.canary_state"

echo "========================================"
echo "  CANARY EMERGENCY ROLLBACK"
echo "========================================"
echo ""

# Check if canary is active
if [[ -f "$STATE_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$STATE_FILE"
  log_info "Current canary state:"
  log_info "  Weight: ${CANARY_WEIGHT:-unknown}%"
  log_info "  Version: ${CANARY_VERSION:-unknown}"
  log_info "  Started: ${LAST_UPDATE:-unknown}"
else
  log_warn "No canary state file found"
  log_warn "Canary may not be active, but proceeding with rollback anyway"
fi

echo ""

if [[ "$FORCE" != "true" ]]; then
  read -r -p "Proceed with rollback? This will route all traffic to stable. [y/N] " response
  if [[ ! "$response" =~ ^[Yy]$ ]]; then
    log_info "Rollback cancelled"
    exit 0
  fi
fi

echo ""
log_info "Starting emergency rollback..."

# Step 1: Set canary weight to 0 and reload Caddy
log_info "Step 1/4: Setting canary weight to 0%..."
"${SCRIPT_DIR}/generate_canary_caddyfile.sh" 0
if docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null; then
  log_success "Caddy configuration reloaded with 0% canary traffic"
else
  log_warn "Caddy reload failed, restarting container..."
  docker compose restart caddy
  log_success "Caddy container restarted"
fi

# Step 2: Stop canary service
log_info "Step 2/4: Stopping canary services..."
docker compose -f docker-compose.yml -f docker-compose.canary.yml stop api-canary 2>/dev/null || true
log_success "Canary services stopped"

# Step 3: Restart with standard configuration
log_info "Step 3/4: Restarting with stable configuration..."
docker compose -f docker-compose.yml up -d --remove-orphans
log_success "Services restarted with stable configuration"

# Step 4: Clear canary state
log_info "Step 4/4: Clearing canary state..."
rm -f "$STATE_FILE"
log_success "Canary state cleared"

echo ""
echo "========================================"
echo -e "${GREEN}  ROLLBACK COMPLETE${NC}"
echo "========================================"
echo ""
log_success "All traffic is now routed to stable"
echo ""

# Verify stable is healthy
log_info "Verifying stable API health..."
sleep 2
if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()" 2>/dev/null; then
  log_success "Stable API is healthy"
else
  log_error "Stable API health check failed - investigate immediately!"
  exit 1
fi

echo ""
log_info "Rollback verification complete"
log_info "Monitor the system and investigate the canary failure"
