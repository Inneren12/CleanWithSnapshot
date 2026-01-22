# Runbook: Payment Webhook Failing

**Alert signal:** Stripe webhook failures or missing payment updates.

## Quick diagnosis

```bash
# Check API logs for webhook errors
cd /opt/cleaning

docker compose logs --tail=200 api | grep -i "stripe\|webhook"
```

```bash
# Validate webhook secret configured
cat /opt/cleaning/.env | grep STRIPE_WEBHOOK_SECRET
```

## Likely causes

- Stripe webhook secret rotated and not updated.
- Webhook endpoint blocked or TLS/cert issues.
- API unavailable during Stripe retries.
- Signature validation failing due to clock drift.

## Safe remediation steps

1. **Confirm endpoint health:**
   ```bash
   curl -fsS https://api.panidobro.com/healthz
   ```
2. **Verify webhook secret:**
   - Compare `.env` with Stripe dashboard webhook secret.
3. **Check for retries in Stripe dashboard** and re-send failed events if available.
4. **Restart API if stuck:**
   ```bash
   docker compose restart api
   ```

## Rollback / restore pointers

- If a deploy broke webhook handling, rollback:
  ```bash
  cd /opt/cleaning
  git reset --hard <good_sha>
  ./ops/deploy.sh
  ```
- If payments were missed, reconcile by reprocessing webhook events or running payment sync.

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Backend lead
- **Tertiary:** Finance owner
