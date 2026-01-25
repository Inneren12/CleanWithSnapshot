# Runbook: Org Abuse Triage

**Alert signal:** Quota rejection spikes, sustained 429s, or auth failure spikes.

## Quick diagnosis

**Prometheus queries (paste into Grafana/Prometheus):**

```promql
sum(increase(org_user_quota_rejections_total[15m]))
sum(increase(org_active_bookings_quota_rejections_total[15m]))
sum(increase(org_storage_quota_rejections_total[15m]))
sum by (bucket) (increase(org_rate_limit_blocks_total[5m]))
sum by (bucket) (rate(http_429_total[10m]))
sum by (source) (increase(auth_failures_total[10m]))
```

## Identify the offending org

**Logs (Loki):** structured logs include `org_id`, `request_id`, and quota fields.

```
{app="api"} | json | level="warning" | message=~"org_.*_quota_rejected|rate_limit_blocked|org_action_rate_limited"
```

Filter by quota type or bucket:

```
{app="api"} | json | quota_type="bookings_per_month"
{app="api"} | json | reason="hard_limit"
{app="api"} | json | bucket="auth"
```

**Admin audit logs (SQL):**

```sql
SELECT created_at, org_id, action, actor, role, resource_type, resource_id, after
FROM admin_audit_logs
WHERE action IN (
  'org_user_quota_rejected',
  'org_booking_quota_rejected',
  'org_storage_quota_rejected',
  'org_storage_plan_quota_rejected',
  'org_action_rate_limit_rejected'
)
ORDER BY created_at DESC
LIMIT 50;
```

## Likely causes

- Legitimate growth (plan limits reached).
- Misconfigured plan or org settings (limits too low).
- Abuse (automated booking attempts, storage flood, auth brute force).
- Broken client retry loops causing rate-limit saturation.

## Safe mitigation steps

1. **Confirm org ownership and intent** via audit/logs and recent support tickets.
2. **Adjust org settings (safe and reversible):**
   - Increase `max_users` or `max_storage_bytes` in `organization_settings` for legit growth.
3. **Plan adjustment:** move org to a higher plan or resume an active plan if paused.
4. **Rate-limit mitigation:** if abuse is confirmed, block offending client/automation and keep limits.
5. **Record action:** add an internal note and reference incident ID.

## Post-incident follow-up

- Document the incident and root cause.
- Add org notes for future on-call context.
- Consider long-term plan/contract updates if limits are regularly exceeded.

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Backend lead
- **Tertiary:** Security/Compliance (if auth abuse)
