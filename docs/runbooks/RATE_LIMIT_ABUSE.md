# Runbook: Rate Limit Abuse

**Alert signal:** `OrgRateLimitBlocksHigh` or `Sustained429Rate`.

## Quick diagnosis

**Prometheus queries:**

```promql
sum by (bucket) (increase(org_rate_limit_blocks_total[5m]))
sum by (bucket) (rate(http_429_total[10m]))
```

Check for global impact vs a single bucket.

## Identify the offending org/client

**Logs (Loki):**

```
{app="api"} | json | message="rate_limit_blocked"
```

Filter by bucket:

```
{app="api"} | json | message="rate_limit_blocked" | bucket="auth"
```

The log payload includes `request_id`, `org_id` (when available), and `limit_per_minute`.
Use `request_id` to correlate upstream requests in access logs.

## Likely causes

- Burst traffic from automated clients or integration loops.
- Legitimate spikes (campaigns, bulk imports).
- Broken client retry logic causing tight retry loops.
- Abuse / credential stuffing in `/v1/auth` or `/v1/admin`.

## Safe mitigation steps

1. **Confirm client behavior** via logs and recent deploys.
2. **Short-term relief (legitimate spike):**
   - Increase `RATE_LIMIT_PER_MINUTE` or `ADMIN_ACTION_RATE_LIMIT_PER_MINUTE` temporarily.
3. **Mitigation (abuse):**
   - Block abusive client at the edge (IP or token) if identified.
   - Keep or tighten rate limits for impacted bucket.
4. **Communicate with affected orgs** if legitimate traffic was throttled.

## Post-incident follow-up

- Add org notes and incident record.
- Review client retry policies or integration rate limits.
- Consider per-org throttling enhancements if recurring.

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Backend lead
- **Tertiary:** Security/Compliance
