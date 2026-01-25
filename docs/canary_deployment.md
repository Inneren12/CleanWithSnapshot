# Canary Deployment Guide

This document describes how to use the canary deployment system for gradual rollouts with percentage-based traffic routing.

## Overview

Canary deployment allows you to deploy a new version of the API alongside the stable version and gradually shift traffic to validate the new release before full promotion.

**Key Features:**
- Percentage-based traffic routing (0-100%)
- SLO-based automatic rollback
- Progressive traffic advancement
- Full observability via Prometheus/Grafana
- One-command rollback

## Quick Start

### Start a Canary Deployment

```bash
# Start canary with 10% traffic
./ops/deploy_canary.sh start --weight 10

# Start with auto-advancement through stages
./ops/deploy_canary.sh start --weight 10 --auto-advance
```

### Monitor and Advance Traffic

```bash
# Check current status and SLO metrics
./ops/deploy_canary.sh status

# Increase traffic to 25%
./ops/deploy_canary.sh set-weight 25

# Continue advancing: 50% -> 75% -> 100%
./ops/deploy_canary.sh set-weight 50
./ops/deploy_canary.sh set-weight 100
```

### Promote or Rollback

```bash
# Promote canary to stable (after successful validation)
./ops/deploy_canary.sh promote

# Rollback to stable (if issues detected)
./ops/deploy_canary.sh rollback

# Emergency rollback (standalone script)
./ops/canary_rollback.sh --force
```

## Architecture

### Traffic Flow

```
                    ┌─────────────────┐
                    │     Caddy       │
                    │  (Load Balancer)│
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
    ┌─────────────────┐          ┌─────────────────┐
    │   api (stable)  │          │   api-canary    │
    │                 │          │                 │
    │  90% traffic    │          │  10% traffic    │
    └─────────────────┘          └─────────────────┘
              │                             │
              └──────────────┬──────────────┘
                             │
                    ┌────────▼────────┐
                    │    Database     │
                    │    (shared)     │
                    └─────────────────┘
```

### Components

| File | Purpose |
|------|---------|
| `ops/deploy_canary.sh` | Main deployment script |
| `ops/canary_rollback.sh` | Emergency rollback script |
| `ops/generate_canary_caddyfile.sh` | Generates Caddyfile with traffic split |
| `docker-compose.canary.yml` | Docker Compose override for canary service |
| `config/canary/canary.conf` | Canary configuration settings |
| `config/canary/Caddyfile.template` | Caddyfile template for traffic routing |
| `prometheus/rules/canary_alerts.yml` | Canary-specific alerting rules |

## Configuration

### Canary Settings

Edit `config/canary/canary.conf` to customize:

```bash
# Traffic weight (0-100%)
CANARY_WEIGHT=0

# Observation time at each stage (seconds)
CANARY_OBSERVATION_TIME=300

# Traffic stages for auto-advance
CANARY_TRAFFIC_STAGES=10,25,50,100

# SLO thresholds for automatic rollback
CANARY_ERROR_RATE_THRESHOLD=2.0      # Percentage
CANARY_LATENCY_P95_THRESHOLD=500     # Milliseconds

# Enable automatic rollback on SLO violation
CANARY_AUTO_ROLLBACK=true
```

### Traffic Stages

The default progression is:
1. **10%** - Initial canary traffic for smoke testing
2. **25%** - Low-risk validation with broader traffic
3. **50%** - Equal split for comprehensive testing
4. **100%** - Full traffic before promotion

## Commands Reference

### `deploy_canary.sh start`

Starts a new canary deployment.

```bash
./ops/deploy_canary.sh start [options]

Options:
  --weight PERCENT    Initial traffic percentage (default: 10)
  --auto-advance      Automatically advance through stages if SLOs are met
  --skip-build        Use existing canary image (don't rebuild)
  --force             Start even if canary is already active
```

### `deploy_canary.sh set-weight`

Adjusts traffic percentage to the canary.

```bash
./ops/deploy_canary.sh set-weight PERCENT
```

### `deploy_canary.sh status`

Shows current canary deployment status and SLO metrics.

```bash
./ops/deploy_canary.sh status
```

Output includes:
- Deployment state (active/inactive)
- Current traffic split
- Service health status
- Error rate and latency metrics
- Comparison to SLO thresholds

### `deploy_canary.sh promote`

Promotes the canary to stable after successful validation.

```bash
./ops/deploy_canary.sh promote
```

This will:
1. Check SLOs (with option to override)
2. Route 100% traffic to canary
3. Tag canary image as stable
4. Restart with standard configuration
5. Remove canary service

### `deploy_canary.sh rollback`

Rolls back to stable, removing the canary.

```bash
./ops/deploy_canary.sh rollback
```

### `canary_rollback.sh`

Emergency rollback script for quick recovery.

```bash
./ops/canary_rollback.sh [--force]
```

Use this when you need the fastest possible rollback without prompts.

## Monitoring

### Prometheus Alerts

The following alerts are configured for canary deployments:

| Alert | Severity | Description |
|-------|----------|-------------|
| `CanaryHighErrorRate` | page | Error rate > 2% for 1 minute |
| `CanaryHighLatency` | warning | p95 latency > 500ms for 2 minutes |
| `CanaryErrorRateHigherThanStable` | warning | Canary errors 1% higher than stable |
| `CanaryLatencyHigherThanStable` | warning | Canary latency 1.5x higher than stable |
| `CanaryServiceUnhealthy` | page | Canary not responding to health checks |
| `CanaryNoTraffic` | warning | Canary receiving no traffic when expected |

### Recording Rules

Pre-computed metrics for dashboards:

- `canary:error_rate:5m` - Canary 5-minute error rate
- `stable:error_rate:5m` - Stable 5-minute error rate
- `canary:latency_p95:5m` - Canary p95 latency
- `stable:latency_p95:5m` - Stable p95 latency
- `canary:traffic_ratio:5m` - Percentage of traffic going to canary

### Grafana Dashboard Queries

Example queries for a canary comparison dashboard:

```promql
# Traffic split visualization
canary:traffic_ratio:5m * 100

# Error rate comparison
canary:error_rate:5m * 100
stable:error_rate:5m * 100

# Latency comparison (milliseconds)
canary:latency_p95:5m * 1000
stable:latency_p95:5m * 1000

# Request rate by variant
sum(rate(http_requests_total{service=~"api|api-canary"}[5m])) by (service)
```

## Workflow Examples

### Standard Canary Deployment

```bash
# 1. Start with 10% traffic
./ops/deploy_canary.sh start --weight 10

# 2. Monitor for 5-10 minutes, check status
./ops/deploy_canary.sh status

# 3. If SLOs are good, advance to 25%
./ops/deploy_canary.sh set-weight 25

# 4. Continue monitoring and advancing
./ops/deploy_canary.sh set-weight 50
./ops/deploy_canary.sh set-weight 100

# 5. Promote to stable
./ops/deploy_canary.sh promote
```

### Automated Canary with Auto-Advance

```bash
# Start and automatically advance through stages
./ops/deploy_canary.sh start --weight 10 --auto-advance

# Script will:
# - Wait CANARY_OBSERVATION_TIME at each stage
# - Check SLOs before advancing
# - Auto-rollback if SLOs are violated
# - Stop at 100% ready for promotion
```

### Handling a Failed Canary

```bash
# Option 1: Standard rollback
./ops/deploy_canary.sh rollback

# Option 2: Emergency rollback (faster, no prompts)
./ops/canary_rollback.sh --force

# Investigate the issue
docker compose logs api-canary --tail 100
./ops/deploy_canary.sh status
```

## Troubleshooting

### Canary Not Receiving Traffic

1. Check Caddyfile configuration:
   ```bash
   cat Caddyfile.canary
   ```

2. Verify canary service is running:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.canary.yml ps
   ```

3. Check Caddy logs:
   ```bash
   docker compose logs caddy --tail 50
   ```

### Metrics Not Available

1. Verify Prometheus is scraping canary:
   ```bash
   curl http://localhost:9090/api/v1/targets
   ```

2. Check if canary is exposing metrics:
   ```bash
   docker compose exec api-canary curl -s http://localhost:8000/metrics
   ```

### Rollback Fails

1. Use emergency rollback:
   ```bash
   ./ops/canary_rollback.sh --force
   ```

2. Manual recovery:
   ```bash
   # Stop all services
   docker compose down

   # Start with standard config only
   docker compose -f docker-compose.yml up -d
   ```

## Best Practices

1. **Start small**: Begin with 10% or less traffic
2. **Monitor actively**: Watch dashboards during the first 5-10 minutes
3. **Use auto-advance for low-risk changes**: Set appropriate observation times
4. **Keep rollback ready**: Know the rollback command before deploying
5. **Test during low-traffic periods**: Minimize blast radius
6. **Review SLO thresholds**: Adjust based on your service's normal variance
7. **Don't skip stages**: Gradual advancement catches more issues
