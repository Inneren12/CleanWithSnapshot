# Incident Response Runbooks

Quick-reference mini-runbooks for common operational alerts and incidents.

---

## Overview

Each runbook follows a standard structure:
- **Alert signal** - How to detect the issue
- **Quick diagnosis** - Commands to identify the problem
- **Likely causes** - Common root causes
- **Safe remediation steps** - Step-by-step fixes
- **Rollback/restore pointers** - Recovery procedures
- **Escalation roles** - Who to contact if needed

---

## Runbook Index

### Infrastructure & Services

| Runbook | Alert Signal | Severity |
|---------|-------------|----------|
| [API Down](./api-down.md) | Health checks failing, elevated 5xx errors | **Critical** |
| [Database Down](./db-down.md) | `db_connected: false`, Postgres health failing | **Critical** |
| [Redis Down](./redis-down.md) | Cache/session errors, Redis health failing | **High** |
| [Disk Full](./disk-full.md) | Disk usage > 85%, write failures | **High** |

### Application & Jobs

| Runbook | Alert Signal | Severity |
|---------|-------------|----------|
| [Migrations Not Current](./migrations-not-current.md) | `migrations_current: false` | **High** |
| [Job Scheduler Stale](./job-scheduler-stale.md) | Stale job heartbeat, DLQ backlog | **Medium** |
| [High Resource Usage](./high-resource-usage.md) | CPU > 80%, Memory > 85%, OOM kills | **Medium** |

### External Integrations

| Runbook | Alert Signal | Severity |
|---------|-------------|----------|
| [Email/SMS Provider Failing](./email-sms-provider-failing.md) | Delivery failures, queue backlog | **Medium** |
| [Payment Webhook Failing](./payment-webhook-failing.md) | Stripe webhook failures, missing payment updates | **High** |

### Backup & Recovery

| Runbook | Alert Signal | Severity |
|---------|-------------|----------|
| [Backup Stale](./backup-stale.md) | Backup heartbeat > 26 hours old | **High** |

---

## Quick Triage

### Step 1: Identify the Alert

Match your alert to one of the runbooks above using the **Alert Signal** column.

### Step 2: Run Quick Diagnosis

Each runbook starts with **Quick diagnosis** commands. Run these first to confirm the issue.

### Step 3: Follow Remediation Steps

Execute the **Safe remediation steps** in order. These are designed to be safe for production.

### Step 4: Escalate if Needed

If remediation fails or the issue is beyond your scope, follow the **Escalation roles** in the runbook.

---

## Common First Steps

**For any incident:**

1. **Check overall health:**
   ```bash
   curl -fsS https://api.panidobro.com/healthz | jq
   curl -fsS https://api.panidobro.com/readyz | jq
   ```

2. **Check recent deployments:**
   ```bash
   cd /opt/cleaning
   git log --oneline -10
   ```

3. **Review recent logs:**
   ```bash
   docker compose logs --tail=500 api
   docker compose logs --tail=500 db
   docker compose logs --tail=500 redis
   ```

4. **Check container status:**
   ```bash
   docker compose ps
   docker stats --no-stream
   ```

---

## Escalation Matrix

| Role | Scope | Contact When |
|------|-------|-------------|
| **On-call Engineer (Ops)** | First responder for all incidents | Primary contact for all alerts |
| **Backend Lead** | API, migrations, job scheduler | Code-related issues, query optimization |
| **Data/DB Owner** | Database, backups, data integrity | Database corruption, restore operations |
| **Infrastructure Owner** | Docker, networking, capacity | Infrastructure scaling, resource limits |
| **Finance Owner** | Payment webhooks, billing | Payment processing issues |
| **Customer Support Lead** | Communication | When customer-facing impact requires notification |
| **Security/Compliance** | Regulated data, retention | Data deletion, backup retention policy |

---

## Emergency Procedures

### Break-Glass Access

If `ADMIN_READ_ONLY=true` is enabled during an incident:

```bash
# OWNER/ADMIN: Request break-glass token
curl -X POST -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \
  "https://api.panidobro.com/v1/admin/break-glass/start" \
  -H "Content-Type: application/json" \
  -d '{"reason":"<incident summary>","ttl_minutes":60}'

# Use returned token for emergency writes
curl -X POST -H "X-Break-Glass-Token: <token>" ...
```

### Rollback Deploy

```bash
cd /opt/cleaning
git log --oneline -10
git reset --hard <good_sha>
./ops/deploy.sh
```

### Database Restore

See [OPERATIONS.md](../OPERATIONS.md#backup--restore) for full restore procedure.

---

## Related Documentation

- [OPERATIONS.md](../OPERATIONS.md) - Complete operations guide
- [DEPLOY_RUNBOOK.md](../DEPLOY_RUNBOOK.md) - Deployment procedures
- [DISASTER_RECOVERY.md](../DISASTER_RECOVERY.md) - DR procedures
- [DLQ_RUNBOOK.md](../DLQ_RUNBOOK.md) - Dead letter queue management
- [ENV_AUDIT_REPORT.md](../ENV_AUDIT_REPORT.md) - Environment variables reference

---

## Updating These Runbooks

When adding or updating runbooks:

1. Follow the standard structure (alert signal, diagnosis, causes, remediation, rollback, escalation)
2. Use real commands that work in production (test in staging first)
3. Keep remediation steps safe (no destructive operations without confirmation)
4. Update this index when adding new runbooks
5. Link from [OPERATIONS.md](../OPERATIONS.md)
