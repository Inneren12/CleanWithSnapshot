# Runbook: Email/SMS Provider Failing

**Alert signal:** Spike in delivery failures, queue backlog, or provider status alert.

## Quick diagnosis

```bash
# Check outbox/dlq counts
curl -fsS -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \
  "https://api.panidobro.com/v1/admin/queue/dlq?kind=all&limit=1"

# Review recent outbox logs
cd /opt/cleaning

docker compose logs --tail=200 api | grep -i "outbox\|email\|sms\|twilio\|sendgrid"
```

```bash
# Verify provider config
cat /opt/cleaning/.env | grep -E "EMAIL_MODE|SENDGRID|SMS_MODE|TWILIO"
```

## Likely causes

- Provider outage or degraded status.
- Invalid API keys or rotated credentials.
- Rate limiting or quota exhaustion.
- Misconfigured sender domain/number.

## Safe remediation steps

1. **Confirm provider status:** check SendGrid/Twilio dashboards.
2. **Validate credentials:** compare `.env` with secret store.
3. **Temporarily disable sending if needed:**
   - Set `EMAIL_MODE=off` or `SMS_MODE=off` in `.env`.
   - Restart API container:
     ```bash
     docker compose restart api
     ```
4. **Clear DLQ entries only after root cause fixed.**

## Rollback / restore pointers

- For misconfigured env, revert to last known good `.env` from secret store.
- If code change introduced failures, rollback deploy:
  ```bash
  cd /opt/cleaning
  git reset --hard <good_sha>
  ./ops/deploy.sh
  ```

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Customer support lead (to communicate delays)
- **Tertiary:** Vendor contact (SendGrid/Twilio)
