#!/usr/bin/env bash
#
# Blue/Green Deployment Script
#
# This script implements zero-downtime blue/green deployments for API and Web services.
# It deploys to the inactive color, health checks the new stack, switches traffic via Caddy,
# and keeps the old stack running until the new one is verified healthy.
#
# Usage:
#   ./ops/blue-green-deploy.sh              # Deploy to inactive color
#   ./ops/blue-green-deploy.sh --rollback   # Rollback to previous color
#   ./ops/blue-green-deploy.sh --status     # Show current deployment status
#   ./ops/blue-green-deploy.sh --cleanup    # Remove inactive color containers
#
# Environment Variables:
#   SKIP_BUILD=1          Skip image build (use existing images)
#   SKIP_MIGRATIONS=1     Skip database migrations
#   HEALTH_TIMEOUT=300    Health check timeout in seconds (default: 300)
#   KEEP_OLD_STACK=1      Keep old stack running after switch (default: true)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Configuration
STATE_DIR="$REPO_ROOT/ops/state"
ACTIVE_COLOR_FILE="$STATE_DIR/active_color"
LAST_GOOD_FILE="$STATE_DIR/last_good.env"
DEPLOY_STATE_FILE="${DEPLOY_STATE_FILE:-/opt/cleaning/.deploy_state.json}"
CADDY_UPSTREAM_DIR="$REPO_ROOT/config/caddy"
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.blue-green.yml"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-300}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
  echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
  echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $1" >&2
}

# Get current active color
get_active_color() {
  if [[ -f "$ACTIVE_COLOR_FILE" ]]; then
    cat "$ACTIVE_COLOR_FILE" | tr -d '[:space:]'
  else
    echo "blue"
  fi
}

# Get inactive color (opposite of active)
get_inactive_color() {
  local active
  active=$(get_active_color)
  if [[ "$active" == "blue" ]]; then
    echo "green"
  else
    echo "blue"
  fi
}

# Set active color
set_active_color() {
  local color="$1"
  mkdir -p "$STATE_DIR"
  echo "$color" > "$ACTIVE_COLOR_FILE"
  log_info "Active color set to: $color"
}

record_last_good() {
  local sha="$1"
  local mode="$2"
  local color="$3"
  local timestamp
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  mkdir -p "$STATE_DIR"
  cat > "$LAST_GOOD_FILE" <<EOF
LAST_GOOD_SHA=$sha
LAST_GOOD_MODE=$mode
LAST_GOOD_COLOR=$color
LAST_GOOD_TIMESTAMP=$timestamp
EOF
  log_info "Recorded last known good deploy: $sha ($color)"
}

get_db_revision() {
  docker compose $COMPOSE_FILES exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select version_num from alembic_version"' \
    2>/dev/null | tr -d '[:space:]'
}

get_expected_heads() {
  local color="$1"
  docker compose $COMPOSE_FILES run --rm --no-deps "api-${color}" python - <<'PY'
from alembic.config import Config
from alembic.script import ScriptDirectory

cfg = Config("alembic.ini")
script = ScriptDirectory.from_config(cfg)
heads = script.get_heads()
print(" ".join(heads))
PY
}

record_deploy_state() {
  local sha="$1"
  local mode="$2"
  local color="$3"
  local timestamp="$4"
  local db_revision="$5"
  local expected_heads="$6"

  mkdir -p "$(dirname "$DEPLOY_STATE_FILE")"
  python3 - <<PY
import json
from pathlib import Path

data = {
    "last_good_sha": "${sha}",
    "last_good_timestamp": "${timestamp}",
    "deploy_mode": "${mode}",
    "deploy_color": "${color}",
    "db_revision": "${db_revision}",
    "expected_heads": "${expected_heads}".split() if "${expected_heads}" else [],
}

Path("${DEPLOY_STATE_FILE}").write_text(json.dumps(data, indent=2) + "\n")
PY
  log_info "Recorded deploy state: $DEPLOY_STATE_FILE"
}

# Update Caddy upstream configuration
update_caddy_upstream() {
  local color="$1"
  local upstream_file="$CADDY_UPSTREAM_DIR/upstream-${color}.caddy"
  local active_file="$CADDY_UPSTREAM_DIR/active-upstream.caddy"

  if [[ ! -f "$upstream_file" ]]; then
    log_error "Upstream config not found: $upstream_file"
    return 1
  fi

  # Add header comment and copy content
  {
    echo "# Active upstream configuration"
    echo "# This file is managed by ops/blue-green-deploy.sh"
    echo "# DO NOT EDIT MANUALLY - changes will be overwritten during deployment"
    echo "#"
    echo "# Current active color: $color"
    echo "# Updated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo ""
    tail -n +5 "$upstream_file"
  } > "$active_file"

  log_info "Updated Caddy upstream configuration to: $color"
}

# Reload Caddy configuration
reload_caddy() {
  log_info "Reloading Caddy configuration..."
  if docker compose $COMPOSE_FILES exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null; then
    log_success "Caddy configuration reloaded"
  else
    # Try restart if reload fails
    log_warn "Caddy reload failed, restarting container..."
    docker compose $COMPOSE_FILES restart caddy
    sleep 5
  fi
}

# Wait for service to be healthy
wait_for_healthy() {
  local service="$1"
  local timeout="$2"
  local start_time
  start_time=$(date +%s)

  log_info "Waiting for $service to become healthy (timeout: ${timeout}s)..."

  while true; do
    local current_time
    current_time=$(date +%s)
    local elapsed=$((current_time - start_time))

    if [[ $elapsed -ge $timeout ]]; then
      log_error "Timeout waiting for $service to become healthy"
      return 1
    fi

    # Check Docker health status
    local health_status
    health_status=$(docker compose $COMPOSE_FILES ps --format json "$service" 2>/dev/null | jq -r '.Health // "unknown"' 2>/dev/null || echo "unknown")

    if [[ "$health_status" == "healthy" ]]; then
      log_success "$service is healthy (took ${elapsed}s)"
      return 0
    fi

    # Also check if container is running
    local state
    state=$(docker compose $COMPOSE_FILES ps --format json "$service" 2>/dev/null | jq -r '.State // "unknown"' 2>/dev/null || echo "unknown")

    if [[ "$state" == "exited" ]] || [[ "$state" == "dead" ]]; then
      log_error "$service container is not running (state: $state)"
      docker compose $COMPOSE_FILES logs --tail=50 "$service"
      return 1
    fi

    echo -n "."
    sleep 5
  done
}

# Health check a service via HTTP
http_health_check() {
  local service="$1"
  local port="$2"
  local endpoint="${3:-/healthz}"
  local max_attempts="${4:-10}"
  local attempt=1

  log_info "Running HTTP health check for $service..."

  while [[ $attempt -le $max_attempts ]]; do
    # Get container IP
    local container_ip
    container_ip=$(docker compose $COMPOSE_FILES exec -T "$service" hostname -i 2>/dev/null | tr -d '[:space:]' || echo "")

    if [[ -z "$container_ip" ]]; then
      log_warn "Could not get container IP for $service (attempt $attempt/$max_attempts)"
      sleep 5
      ((attempt++))
      continue
    fi

    # Make HTTP request from within the network
    if docker compose $COMPOSE_FILES exec -T caddy wget -q --spider --timeout=5 "http://${service}:${port}${endpoint}" 2>/dev/null; then
      log_success "HTTP health check passed for $service"
      return 0
    fi

    log_warn "HTTP health check failed for $service (attempt $attempt/$max_attempts)"
    sleep 5
    ((attempt++))
  done

  log_error "HTTP health check failed for $service after $max_attempts attempts"
  return 1
}

# Run database migrations on the new API container
run_migrations() {
  local api_service="$1"

  if [[ "${SKIP_MIGRATIONS:-}" == "1" ]]; then
    log_warn "Skipping migrations (SKIP_MIGRATIONS=1)"
    return 0
  fi

  log_info "Running database migrations on $api_service..."

  if docker compose $COMPOSE_FILES exec -T "$api_service" alembic upgrade head; then
    log_success "Migrations completed successfully"
  else
    log_error "Migrations failed"
    return 1
  fi
}

# Build images for a color
build_images() {
  local color="$1"

  if [[ "${SKIP_BUILD:-}" == "1" ]]; then
    log_warn "Skipping build (SKIP_BUILD=1)"
    return 0
  fi

  log_info "Building images for $color stack..."

  # Build with specific tags
  docker compose $COMPOSE_FILES build "api-${color}" "web-${color}"

  log_success "Images built for $color stack"
}

# Start services for a color
start_services() {
  local color="$1"

  log_info "Starting $color stack..."

  docker compose $COMPOSE_FILES up -d --no-deps "api-${color}" "web-${color}"

  log_success "Started $color stack"
}

# Stop services for a color
stop_services() {
  local color="$1"

  log_info "Stopping $color stack..."

  docker compose $COMPOSE_FILES stop "api-${color}" "web-${color}" 2>/dev/null || true
  docker compose $COMPOSE_FILES rm -f "api-${color}" "web-${color}" 2>/dev/null || true

  log_success "Stopped $color stack"
}

# Run smoke tests
run_smoke_tests() {
  log_info "Running smoke tests..."

  if [[ -x "$REPO_ROOT/ops/smoke.sh" ]]; then
    if "$REPO_ROOT/ops/smoke.sh"; then
      log_success "Smoke tests passed"
      return 0
    else
      log_error "Smoke tests failed"
      return 1
    fi
  else
    log_warn "Smoke test script not found or not executable, skipping..."
    return 0
  fi
}

# Show deployment status
show_status() {
  echo ""
  echo "=========================================="
  echo "       Blue/Green Deployment Status       "
  echo "=========================================="
  echo ""

  local active_color
  active_color=$(get_active_color)
  local inactive_color
  inactive_color=$(get_inactive_color)

  echo -e "Active color:   ${GREEN}${active_color}${NC}"
  echo -e "Inactive color: ${YELLOW}${inactive_color}${NC}"
  echo ""

  echo "Service Status:"
  echo "---------------"

  for color in blue green; do
    for service in api web; do
      local full_name="${service}-${color}"
      local status
      status=$(docker compose $COMPOSE_FILES ps --format json "$full_name" 2>/dev/null | jq -r '.State // "not running"' 2>/dev/null || echo "not running")
      local health
      health=$(docker compose $COMPOSE_FILES ps --format json "$full_name" 2>/dev/null | jq -r '.Health // "N/A"' 2>/dev/null || echo "N/A")

      local color_code
      if [[ "$status" == "running" ]] && [[ "$health" == "healthy" ]]; then
        color_code="${GREEN}"
      elif [[ "$status" == "running" ]]; then
        color_code="${YELLOW}"
      else
        color_code="${RED}"
      fi

      local active_marker=""
      if [[ "$color" == "$active_color" ]]; then
        active_marker=" (ACTIVE)"
      fi

      echo -e "  ${full_name}: ${color_code}${status}${NC} [health: ${health}]${active_marker}"
    done
  done

  echo ""
  echo "Infrastructure:"
  echo "---------------"
  for service in db redis caddy; do
    local status
    status=$(docker compose $COMPOSE_FILES ps --format json "$service" 2>/dev/null | jq -r '.State // "not running"' 2>/dev/null || echo "not running")
    local health
    health=$(docker compose $COMPOSE_FILES ps --format json "$service" 2>/dev/null | jq -r '.Health // "N/A"' 2>/dev/null || echo "N/A")
    echo -e "  ${service}: ${status} [health: ${health}]"
  done

  echo ""
}

# Perform deployment
deploy() {
  local current_sha
  local active_color
  local target_color

  echo ""
  echo "=========================================="
  echo "     Blue/Green Deployment Starting       "
  echo "=========================================="
  echo ""

  current_sha="$(git rev-parse HEAD)"
  log_info "Current revision: $current_sha"

  # Determine colors
  active_color=$(get_active_color)
  target_color=$(get_inactive_color)

  log_info "Current active color: $active_color"
  log_info "Target deployment color: $target_color"

  # Check .env file
  if [[ ! -f .env ]]; then
    log_warn ".env file not found. Ensure environment variables are present."
  fi

  # Ensure infrastructure services are running
  log_info "Ensuring infrastructure services are running..."
  docker compose $COMPOSE_FILES up -d db redis caddy

  # Wait for database
  log_info "Waiting for database to become ready..."
  for attempt in $(seq 1 30); do
    if docker compose $COMPOSE_FILES exec -T db sh -c 'pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"' >/dev/null 2>&1; then
      log_success "Database is ready"
      break
    fi
    if [[ "$attempt" -eq 30 ]]; then
      log_error "Database did not become ready in time"
      exit 1
    fi
    sleep 2
  done

  # Build new images
  build_images "$target_color"

  # Start target color services
  start_services "$target_color"

  # Wait for services to be healthy
  if ! wait_for_healthy "api-${target_color}" "$HEALTH_TIMEOUT"; then
    log_error "API service failed health check, aborting deployment"
    stop_services "$target_color"
    exit 1
  fi

  if ! wait_for_healthy "web-${target_color}" "$HEALTH_TIMEOUT"; then
    log_error "Web service failed health check, aborting deployment"
    stop_services "$target_color"
    exit 1
  fi

  # Run migrations on new API
  if ! run_migrations "api-${target_color}"; then
    log_error "Migrations failed, aborting deployment"
    stop_services "$target_color"
    exit 1
  fi

  # Perform HTTP health checks
  if ! http_health_check "api-${target_color}" 8000 "/healthz"; then
    log_error "API HTTP health check failed, aborting deployment"
    stop_services "$target_color"
    exit 1
  fi

  if ! http_health_check "web-${target_color}" 3000 "/healthz"; then
    # Web might not have /healthz, try root
    if ! http_health_check "web-${target_color}" 3000 "/" 5; then
      log_error "Web HTTP health check failed, aborting deployment"
      stop_services "$target_color"
      exit 1
    fi
  fi

  # Switch traffic to new color
  log_info "Switching traffic to $target_color stack..."
  update_caddy_upstream "$target_color"
  reload_caddy

  # Update active color state
  set_active_color "$target_color"

  # Wait a moment and verify the switch
  sleep 5

  # Run smoke tests
  if ! run_smoke_tests; then
    log_error "Smoke tests failed after traffic switch!"
    log_warn "Rolling back to $active_color..."
    update_caddy_upstream "$active_color"
    reload_caddy
    set_active_color "$active_color"
    exit 1
  fi

  # Cleanup old stack (optional)
  if [[ "${KEEP_OLD_STACK:-1}" != "1" ]]; then
    log_info "Cleaning up old $active_color stack..."
    stop_services "$active_color"
  else
    log_info "Keeping old $active_color stack running (KEEP_OLD_STACK=1)"
    log_info "Run './ops/blue-green-deploy.sh --cleanup' to remove it later"
  fi

  echo ""
  echo "=========================================="
  log_success "Deployment completed successfully!"
  echo "=========================================="
  echo ""
  echo "Active color: $target_color"
  echo "Revision: $current_sha"
  echo ""

  deploy_timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  db_revision="$(get_db_revision)"
  expected_heads="$(get_expected_heads "$target_color")"
  record_deploy_state "$current_sha" "blue-green" "$target_color" "$deploy_timestamp" "$db_revision" "$expected_heads"
  record_last_good "$current_sha" "blue-green" "$target_color"

  show_status
}

# Rollback to previous color
rollback() {
  local active_color
  local target_color

  active_color=$(get_active_color)
  target_color=$(get_inactive_color)

  echo ""
  echo "=========================================="
  echo "          Rollback Initiated              "
  echo "=========================================="
  echo ""

  log_info "Rolling back from $active_color to $target_color..."

  # Check if target color services are running
  local target_api_status
  target_api_status=$(docker compose $COMPOSE_FILES ps --format json "api-${target_color}" 2>/dev/null | jq -r '.State // "not running"' 2>/dev/null || echo "not running")

  if [[ "$target_api_status" != "running" ]]; then
    log_error "Cannot rollback: $target_color stack is not running"
    log_info "You may need to start the $target_color stack manually or redeploy"
    exit 1
  fi

  # Quick health check
  if ! http_health_check "api-${target_color}" 8000 "/healthz" 3; then
    log_error "Cannot rollback: $target_color API is not healthy"
    exit 1
  fi

  # Switch traffic
  update_caddy_upstream "$target_color"
  reload_caddy
  set_active_color "$target_color"

  log_success "Rollback completed! Active color is now: $target_color"

  show_status
}

# Cleanup inactive color
cleanup() {
  local inactive_color
  inactive_color=$(get_inactive_color)

  echo ""
  log_info "Cleaning up inactive $inactive_color stack..."

  stop_services "$inactive_color"

  # Also remove images if requested
  if [[ "${REMOVE_IMAGES:-}" == "1" ]]; then
    log_info "Removing $inactive_color images..."
    docker rmi "cleanwithsnapshot-api:${inactive_color}" 2>/dev/null || true
    docker rmi "cleanwithsnapshot-web:${inactive_color}" 2>/dev/null || true
  fi

  log_success "Cleanup completed"

  show_status
}

# Main entry point
main() {
  case "${1:-}" in
    --status|-s)
      show_status
      ;;
    --rollback|-r)
      rollback
      ;;
    --cleanup|-c)
      cleanup
      ;;
    --help|-h)
      echo "Blue/Green Deployment Script"
      echo ""
      echo "Usage:"
      echo "  $0              Deploy to inactive color (zero-downtime)"
      echo "  $0 --status     Show current deployment status"
      echo "  $0 --rollback   Rollback to previous color"
      echo "  $0 --cleanup    Remove inactive color containers"
      echo ""
      echo "Environment Variables:"
      echo "  SKIP_BUILD=1        Skip image build"
      echo "  SKIP_MIGRATIONS=1   Skip database migrations"
      echo "  HEALTH_TIMEOUT=N    Health check timeout in seconds (default: 300)"
      echo "  KEEP_OLD_STACK=1    Keep old stack after switch (default: true)"
      echo "  REMOVE_IMAGES=1     Remove images during cleanup"
      echo ""
      ;;
    "")
      deploy
      ;;
    *)
      log_error "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
}

main "$@"
