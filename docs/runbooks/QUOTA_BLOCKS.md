# Runbook: Quota Blocks

**Alert signal:** `OrgUserQuotaRejectionsSpike`, `OrgBookingQuotaRejectionsSpike`, or `OrgStorageQuotaRejectionsSpike`.

## Quick diagnosis

**Prometheus queries:**

```promql
sum(increase(org_user_quota_rejections_total[15m]))
sum(increase(org_active_bookings_quota_rejections_total[15m]))
sum(increase(org_storage_quota_rejections_total[15m]))
```

## Identify the offending org

**Logs (Loki):**

```
{app="api"} | json | message=~"org_user_quota_rejected|org_booking_quota_rejected|org_storage_quota_rejected"
```

Log fields to capture:
- `org_id`
- `request_id`
- `attempted_action` (user quota)
- `bookings_this_month` / `max_bookings_per_month`
- `storage_bytes_used` / `max_storage_bytes`

**Admin audit logs (SQL):**

```sql
SELECT created_at, org_id, action, resource_type, after
FROM admin_audit_logs
WHERE action IN (
  'org_user_quota_rejected',
  'org_booking_quota_rejected',
  'org_storage_quota_rejected',
  'org_storage_plan_quota_rejected'
)
ORDER BY created_at DESC
LIMIT 50;
```

## Likely causes

- Org reached configured `max_users`.
- Monthly booking limit reached for the org plan.
- Storage cap exceeded (hard limit or plan limit).
- Bulk imports or integrations exceeding plan limits.

## Safe mitigation steps

1. **Confirm legitimacy:** Check org history and recent activity.
2. **Adjust limits (reversible):**
   - Update `organization_settings.max_users`.
   - Update `organization_settings.max_storage_bytes`.
3. **Plan change:** Upgrade plan if monthly booking/storage caps are too low.
4. **Temporary relief:** increase limits for a short period and monitor.

## Manual remediation (SQL, use with care)

```sql
UPDATE organization_settings
SET max_users = 50
WHERE org_id = '<org_uuid>';

UPDATE organization_settings
SET max_storage_bytes = 10737418240 -- 10 GiB
WHERE org_id = '<org_uuid>';
```

## Post-incident follow-up

- Record incident and mitigation.
- Add org notes and adjust long-term plan if needed.

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Backend lead
