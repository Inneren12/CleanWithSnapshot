#!/usr/bin/env bash
# Canary Deployment Script
# Deploys a canary version of the API with percentage-based traffic routing.
#
# Usage:
#   ./deploy_canary.sh start [--weight PERCENT] [--auto-advance]
#   ./deploy_canary.sh set-weight PERCENT
#   ./deploy_canary.sh promote
#   ./deploy_canary.sh rollback
#   ./deploy_canary.sh status
#
# Options:
#   --weight PERCENT    Initial traffic percentage for canary (default: 10)
#   --auto-advance      Automatically advance through traffic stages if SLOs are met
#   --skip-build        Skip building the canary image (use existing)
#   --force             Skip confirmation prompts
#
# Environment Variables:
#   CANARY_IMAGE_TAG    Docker image tag for canary (default: canary)
#   PROMETHEUS_URL      Prometheus endpoint for SLO checks (default: http://prometheus:9090)
#
# Examples:
#   ./deploy_canary.sh start --weight 10
#   ./deploy_canary.sh set-weight 25
#   ./deploy_canary.sh status
#   ./deploy_canary.sh promote
#   ./deploy_canary.sh rollback

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Load canary configuration
CANARY_CONF="${REPO_ROOT}/config/canary/canary.conf"
if [[ -f "$CANARY_CONF" ]]; then
  # shellcheck source=/dev/null
  source "$CANARY_CONF"
fi

# Defaults
CANARY_WEIGHT="${CANARY_WEIGHT:-0}"
CANARY_IMAGE_TAG="${CANARY_IMAGE_TAG:-canary}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://prometheus:9090}"
CANARY_OBSERVATION_TIME="${CANARY_OBSERVATION_TIME:-300}"
CANARY_TRAFFIC_STAGES="${CANARY_TRAFFIC_STAGES:-10,25,50,100}"
CANARY_ERROR_RATE_THRESHOLD="${CANARY_ERROR_RATE_THRESHOLD:-1.0}"
CANARY_LATENCY_P95_THRESHOLD="${CANARY_LATENCY_P95_THRESHOLD:-300}"
CANARY_AVAILABILITY_THRESHOLD="${CANARY_AVAILABILITY_THRESHOLD:-99.0}"
CANARY_AUTO_ROLLBACK="${CANARY_AUTO_ROLLBACK:-true}"

# State file for tracking canary deployment
STATE_FILE="${REPO_ROOT}/.canary_state"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Save canary state
save_state() {
  cat > "$STATE_FILE" << EOF
CANARY_ENABLED=true
CANARY_WEIGHT=$CANARY_WEIGHT
CANARY_START_TIME=$(date +%s)
CANARY_VERSION=${CANARY_VERSION:-$(git rev-parse --short HEAD)}
STABLE_VERSION=${STABLE_VERSION:-stable}
LAST_UPDATE=$(date -Iseconds)
EOF
  log_info "State saved: weight=${CANARY_WEIGHT}%"
}

# Load canary state
load_state() {
  if [[ -f "$STATE_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$STATE_FILE"
    return 0
  fi
  return 1
}

# Clear canary state
clear_state() {
  rm -f "$STATE_FILE"
  log_info "Canary state cleared"
}

# Check if canary is currently active
is_canary_active() {
  if load_state && [[ "${CANARY_ENABLED:-false}" == "true" ]]; then
    return 0
  fi
  return 1
}

# Query Prometheus for canary error rate
check_canary_error_rate() {
  local query='sum(rate(http_requests_total{service="api-canary",status_class="5xx"}[5m])) / sum(rate(http_requests_total{service="api-canary"}[5m])) * 100'
  local result

  result=$(curl -s --fail "${PROMETHEUS_URL}/api/v1/query" \
    --data-urlencode "query=${query}" 2>/dev/null | \
    jq -r '.data.result[0].value[1] // "0"' 2>/dev/null) || result="N/A"

  echo "$result"
}

# Query Prometheus for canary availability (success rate)
check_canary_availability() {
  local query='sum(rate(http_requests_total{service="api-canary",status_class=~"2xx|3xx"}[5m])) / sum(rate(http_requests_total{service="api-canary"}[5m])) * 100'
  local result

  result=$(curl -s --fail "${PROMETHEUS_URL}/api/v1/query" \
    --data-urlencode "query=${query}" 2>/dev/null | \
    jq -r '.data.result[0].value[1] // "0"' 2>/dev/null) || result="N/A"

  echo "$result"
}

# Query Prometheus for canary p95 latency
check_canary_latency_p95() {
  local query='histogram_quantile(0.95, sum(rate(http_request_latency_seconds_bucket{service="api-canary"}[5m])) by (le)) * 1000'
  local result

  result=$(curl -s --fail "${PROMETHEUS_URL}/api/v1/query" \
    --data-urlencode "query=${query}" 2>/dev/null | \
    jq -r '.data.result[0].value[1] // "0"' 2>/dev/null) || result="N/A"

  echo "$result"
}

# Check if canary SLOs are within thresholds
check_canary_slos() {
  log_info "Checking canary SLOs..."

  local error_rate
  local availability
  local latency_p95

  error_rate=$(check_canary_error_rate)
  availability=$(check_canary_availability)
  latency_p95=$(check_canary_latency_p95)

  log_info "Canary error rate: ${error_rate}% (threshold: ${CANARY_ERROR_RATE_THRESHOLD}%)"
  log_info "Canary availability: ${availability}% (threshold: ${CANARY_AVAILABILITY_THRESHOLD}%)"
  log_info "Canary p95 latency: ${latency_p95}ms (threshold: ${CANARY_LATENCY_P95_THRESHOLD}ms)"

  # Check if we have valid metrics
  if [[ "$error_rate" == "N/A" ]] || [[ "$availability" == "N/A" ]] || [[ "$latency_p95" == "N/A" ]]; then
    log_warn "Unable to retrieve canary metrics - Prometheus may not be available"
    return 2  # Unknown state
  fi

  # Compare against thresholds
  local error_ok availability_ok latency_ok
  error_ok=$(echo "$error_rate <= $CANARY_ERROR_RATE_THRESHOLD" | bc -l 2>/dev/null) || error_ok=1
  availability_ok=$(echo "$availability >= $CANARY_AVAILABILITY_THRESHOLD" | bc -l 2>/dev/null) || availability_ok=1
  latency_ok=$(echo "$latency_p95 <= $CANARY_LATENCY_P95_THRESHOLD" | bc -l 2>/dev/null) || latency_ok=1

  if [[ "$error_ok" -eq 1 ]] && [[ "$availability_ok" -eq 1 ]] && [[ "$latency_ok" -eq 1 ]]; then
    log_success "Canary SLOs are within thresholds"
    return 0
  else
    log_error "Canary SLOs exceeded thresholds!"
    [[ "$error_ok" -eq 0 ]] && log_error "  Error rate ${error_rate}% > ${CANARY_ERROR_RATE_THRESHOLD}%"
    [[ "$availability_ok" -eq 0 ]] && log_error "  Availability ${availability}% < ${CANARY_AVAILABILITY_THRESHOLD}%"
    [[ "$latency_ok" -eq 0 ]] && log_error "  Latency p95 ${latency_p95}ms > ${CANARY_LATENCY_P95_THRESHOLD}ms"
    return 1
  fi
}

# Update traffic weight
update_traffic_weight() {
  local new_weight="$1"

  if [[ "$new_weight" -lt 0 ]] || [[ "$new_weight" -gt 100 ]]; then
    log_error "Weight must be between 0 and 100"
    return 1
  fi

  CANARY_WEIGHT="$new_weight"
  log_info "Setting canary traffic weight to ${new_weight}%"

  # Generate new Caddyfile
  "${SCRIPT_DIR}/generate_canary_caddyfile.sh" "$new_weight"

  # Reload Caddy configuration
  log_info "Reloading Caddy configuration..."
  if docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null; then
    log_success "Caddy configuration reloaded"
  else
    log_warn "Caddy reload failed, restarting container..."
    docker compose restart caddy
  fi

  save_state
  log_success "Traffic weight updated to ${new_weight}%"
}

# Start canary deployment
cmd_start() {
  local initial_weight=10
  local auto_advance=false
  local skip_build=false
  local force=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --weight)
        initial_weight="$2"
        shift 2
        ;;
      --auto-advance)
        auto_advance=true
        shift
        ;;
      --skip-build)
        skip_build=true
        shift
        ;;
      --force)
        force=true
        shift
        ;;
      *)
        log_error "Unknown option: $1"
        exit 1
        ;;
    esac
  done

  if is_canary_active && [[ "$force" != "true" ]]; then
    log_warn "Canary deployment is already active (weight: ${CANARY_WEIGHT}%)"
    log_warn "Use 'set-weight', 'promote', or 'rollback' to manage the deployment"
    log_warn "Or use --force to start a new canary deployment"
    exit 1
  fi

  log_info "Starting canary deployment..."
  CANARY_VERSION="${CANARY_VERSION:-$(git rev-parse --short HEAD)}"
  STABLE_VERSION="${STABLE_VERSION:-stable}"

  # Build canary image
  if [[ "$skip_build" != "true" ]]; then
    log_info "Building canary image..."
    CANARY_IMAGE_TAG="${CANARY_IMAGE_TAG}" docker compose -f docker-compose.yml build api
    docker tag cleanwithsnapshot-api:ci "cleanwithsnapshot-api:${CANARY_IMAGE_TAG}"
    log_success "Canary image built: cleanwithsnapshot-api:${CANARY_IMAGE_TAG}"
  else
    log_info "Skipping canary build (using existing image)"
  fi

  # Generate Caddyfile with initial weight
  log_info "Generating Caddyfile with ${initial_weight}% canary traffic..."
  "${SCRIPT_DIR}/generate_canary_caddyfile.sh" "$initial_weight"

  # Export canary image for docker-compose
  export CANARY_IMAGE="cleanwithsnapshot-api:${CANARY_IMAGE_TAG}"
  export CANARY_VERSION
  export STABLE_VERSION

  # Start services with canary override
  log_info "Starting services with canary configuration..."
  docker compose -f docker-compose.yml -f docker-compose.canary.yml up -d --remove-orphans

  # Wait for canary to be healthy
  log_info "Waiting for canary service to become healthy..."
  local attempts=0
  local max_attempts=30
  while [[ $attempts -lt $max_attempts ]]; do
    attempts=$((attempts + 1))
    if docker compose -f docker-compose.yml -f docker-compose.canary.yml exec -T api-canary \
       python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()" 2>/dev/null; then
      log_success "Canary service is healthy"
      break
    fi
    if [[ $attempts -eq $max_attempts ]]; then
      log_error "Canary service failed to become healthy"
      log_error "Rolling back..."
      cmd_rollback
      exit 1
    fi
    sleep 2
  done

  # Run smoke tests against canary
  log_info "Running smoke tests against canary..."
  if docker compose -f docker-compose.yml -f docker-compose.canary.yml exec -T api-canary \
     python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/healthz').read().decode())" 2>/dev/null; then
    log_success "Canary smoke tests passed"
  else
    log_error "Canary smoke tests failed"
    log_error "Rolling back..."
    cmd_rollback
    exit 1
  fi

  CANARY_WEIGHT="$initial_weight"
  save_state

  log_success "Canary deployment started successfully!"
  log_info "Current traffic split: stable=$((100 - initial_weight))%, canary=${initial_weight}%"
  log_info ""
  log_info "Next steps:"
  log_info "  - Monitor canary metrics in Grafana"
  log_info "  - Check SLOs: ./deploy_canary.sh status"
  log_info "  - Increase traffic: ./deploy_canary.sh set-weight 25"
  log_info "  - Promote to 100%: ./deploy_canary.sh promote"
  log_info "  - Rollback: ./deploy_canary.sh rollback"

  if [[ "$auto_advance" == "true" ]]; then
    log_info ""
    log_info "Auto-advance mode enabled. Monitoring and advancing traffic automatically..."
    cmd_auto_advance
  fi
}

# Set traffic weight
cmd_set_weight() {
  local new_weight="${1:-}"

  if [[ -z "$new_weight" ]]; then
    log_error "Usage: deploy_canary.sh set-weight PERCENT"
    exit 1
  fi

  if ! is_canary_active; then
    log_error "No active canary deployment. Use 'start' first."
    exit 1
  fi

  update_traffic_weight "$new_weight"
}

# Promote canary to stable (100% traffic)
cmd_promote() {
  if ! is_canary_active; then
    log_error "No active canary deployment to promote"
    exit 1
  fi

  log_info "Promoting canary to stable..."

  # Check SLOs before promotion
  if ! check_canary_slos; then
    log_warn "Canary SLOs are not within thresholds"
    read -r -p "Continue with promotion anyway? [y/N] " response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
      log_info "Promotion cancelled"
      exit 1
    fi
  fi

  # Set traffic to 100% canary
  update_traffic_weight 100

  log_info "Waiting for traffic to stabilize..."
  sleep 10

  # Swap canary to stable
  log_info "Swapping canary image to stable..."
  docker tag "cleanwithsnapshot-api:${CANARY_IMAGE_TAG}" "cleanwithsnapshot-api:ci"

  # Restart with standard configuration (no canary)
  log_info "Restarting with standard configuration..."
  docker compose -f docker-compose.yml up -d --remove-orphans

  # Restore original Caddyfile
  log_info "Restoring original Caddyfile..."
  docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null || true

  clear_state
  log_success "Canary promoted to stable successfully!"
}

# Rollback canary deployment
cmd_rollback() {
  log_info "Rolling back canary deployment..."

  # Restore original Caddyfile (0% canary traffic)
  log_info "Restoring original Caddyfile..."
  cp "${REPO_ROOT}/Caddyfile" "${REPO_ROOT}/Caddyfile.canary"

  # Restart with standard configuration (no canary)
  log_info "Stopping canary and restarting with stable configuration..."
  docker compose -f docker-compose.yml up -d --remove-orphans

  # Force Caddy to reload original config
  docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null || \
    docker compose restart caddy

  clear_state
  log_success "Canary rollback completed. All traffic now goes to stable."
}

# Show canary status
cmd_status() {
  echo "=== Canary Deployment Status ==="
  echo ""

  if ! is_canary_active; then
    echo "Status: ${YELLOW}INACTIVE${NC}"
    echo "No active canary deployment"
    return
  fi

  load_state

  echo -e "Status: ${GREEN}ACTIVE${NC}"
  echo "Canary version: ${CANARY_VERSION:-unknown}"
  echo "Stable version: ${STABLE_VERSION:-unknown}"
  echo "Traffic split: stable=$((100 - CANARY_WEIGHT))%, canary=${CANARY_WEIGHT}%"
  echo "Started: ${LAST_UPDATE:-unknown}"
  echo ""

  echo "=== Service Health ==="
  echo "Stable API:"
  if docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()" 2>/dev/null; then
    echo -e "  Health: ${GREEN}HEALTHY${NC}"
  else
    echo -e "  Health: ${RED}UNHEALTHY${NC}"
  fi

  echo "Canary API:"
  if docker compose -f docker-compose.yml -f docker-compose.canary.yml exec -T api-canary \
     python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()" 2>/dev/null; then
    echo -e "  Health: ${GREEN}HEALTHY${NC}"
  else
    echo -e "  Health: ${RED}UNHEALTHY${NC}"
  fi

  echo ""
  echo "=== SLO Metrics ==="
  local error_rate availability latency_p95
  error_rate=$(check_canary_error_rate)
  availability=$(check_canary_availability)
  latency_p95=$(check_canary_latency_p95)

  if [[ "$error_rate" != "N/A" ]]; then
    local error_status="${GREEN}OK${NC}"
    if (( $(echo "$error_rate > $CANARY_ERROR_RATE_THRESHOLD" | bc -l 2>/dev/null || echo 0) )); then
      error_status="${RED}EXCEEDED${NC}"
    fi
    echo -e "Error rate: ${error_rate}% (threshold: ${CANARY_ERROR_RATE_THRESHOLD}%) - ${error_status}"
  else
    echo "Error rate: N/A (metrics unavailable)"
  fi

  if [[ "$availability" != "N/A" ]]; then
    local availability_status="${GREEN}OK${NC}"
    if (( $(echo "$availability < $CANARY_AVAILABILITY_THRESHOLD" | bc -l 2>/dev/null || echo 0) )); then
      availability_status="${RED}EXCEEDED${NC}"
    fi
    echo -e "Availability: ${availability}% (threshold: ${CANARY_AVAILABILITY_THRESHOLD}%) - ${availability_status}"
  else
    echo "Availability: N/A (metrics unavailable)"
  fi

  if [[ "$latency_p95" != "N/A" ]]; then
    local latency_status="${GREEN}OK${NC}"
    if (( $(echo "$latency_p95 > $CANARY_LATENCY_P95_THRESHOLD" | bc -l 2>/dev/null || echo 0) )); then
      latency_status="${RED}EXCEEDED${NC}"
    fi
    echo -e "P95 latency: ${latency_p95}ms (threshold: ${CANARY_LATENCY_P95_THRESHOLD}ms) - ${latency_status}"
  else
    echo "P95 latency: N/A (metrics unavailable)"
  fi

  echo ""
  echo "=== Next Steps ==="
  echo "  Increase traffic: ./deploy_canary.sh set-weight <percent>"
  echo "  Promote canary:   ./deploy_canary.sh promote"
  echo "  Rollback:         ./deploy_canary.sh rollback"
}

# Auto-advance through traffic stages
cmd_auto_advance() {
  if ! is_canary_active; then
    log_error "No active canary deployment"
    exit 1
  fi

  IFS=',' read -ra stages <<< "$CANARY_TRAFFIC_STAGES"

  for stage in "${stages[@]}"; do
    if [[ "$CANARY_WEIGHT" -ge "$stage" ]]; then
      log_info "Already at or past ${stage}% stage, skipping..."
      continue
    fi

    log_info "Advancing to ${stage}% canary traffic..."
    update_traffic_weight "$stage"

    if [[ "$stage" -eq 100 ]]; then
      log_info "Reached 100% - ready for promotion"
      break
    fi

    log_info "Observing for ${CANARY_OBSERVATION_TIME} seconds..."
    sleep "$CANARY_OBSERVATION_TIME"

    # Check SLOs
    if ! check_canary_slos; then
      if [[ "$CANARY_AUTO_ROLLBACK" == "true" ]]; then
        log_error "SLOs exceeded threshold - auto-rolling back"
        cmd_rollback
        exit 1
      else
        log_warn "SLOs exceeded but auto-rollback is disabled"
        log_warn "Manual intervention required"
        exit 1
      fi
    fi

    log_success "Stage ${stage}% complete, SLOs within thresholds"
  done

  log_success "All traffic stages completed successfully!"
  log_info "Run './deploy_canary.sh promote' to finalize the deployment"
}

# Main command dispatcher
main() {
  local cmd="${1:-}"
  shift || true

  case "$cmd" in
    start)
      cmd_start "$@"
      ;;
    set-weight)
      cmd_set_weight "$@"
      ;;
    promote)
      cmd_promote "$@"
      ;;
    rollback)
      cmd_rollback "$@"
      ;;
    status)
      cmd_status "$@"
      ;;
    auto-advance)
      cmd_auto_advance "$@"
      ;;
    ""|help|-h|--help)
      echo "Canary Deployment Manager"
      echo ""
      echo "Usage: deploy_canary.sh <command> [options]"
      echo ""
      echo "Commands:"
      echo "  start [--weight N] [--auto-advance]  Start canary deployment"
      echo "  set-weight PERCENT                   Set canary traffic percentage"
      echo "  promote                              Promote canary to stable (100%)"
      echo "  rollback                             Rollback to stable, remove canary"
      echo "  status                               Show current canary status"
      echo "  auto-advance                         Auto-advance through traffic stages"
      echo ""
      echo "Options:"
      echo "  --weight PERCENT    Initial traffic percentage (default: 10)"
      echo "  --auto-advance      Automatically advance traffic if SLOs are met"
      echo "  --skip-build        Skip building canary image"
      echo "  --force             Force start even if canary is already active"
      echo ""
      echo "Examples:"
      echo "  ./deploy_canary.sh start --weight 10"
      echo "  ./deploy_canary.sh set-weight 25"
      echo "  ./deploy_canary.sh status"
      echo "  ./deploy_canary.sh promote"
      echo "  ./deploy_canary.sh rollback"
      ;;
    *)
      log_error "Unknown command: $cmd"
      log_error "Run './deploy_canary.sh help' for usage information"
      exit 1
      ;;
  esac
}

main "$@"
