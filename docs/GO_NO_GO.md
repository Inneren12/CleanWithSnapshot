# Go/No-Go Deployment Checklist

This checklist provides a comprehensive set of readiness gates before deploying CleanWithSnapshot to production or staging environments.

## Pre-Deployment Checklist

### 1. Infrastructure Readiness

#### 1.1 Server Requirements
- [ ] Docker Engine installed (version 20.10+)
- [ ] Docker Compose plugin installed (version 2.0+)
- [ ] Sufficient disk space (minimum 20GB free)
- [ ] Sufficient RAM (minimum 2GB, recommended 4GB+)
- [ ] Firewall configured (ports 80, 443 open)
- [ ] Domain DNS configured (A records for apex and api subdomain)

#### 1.2 Directory Structure
- [ ] Repository cloned to `/opt/cleaning` (or deployment directory)
- [ ] Git origin configured and accessible
- [ ] `.env` file created in repository root
- [ ] Backup directory exists: `/opt/backups/postgres/`
- [ ] Log directory exists and is writable: `logs/`
- [ ] Runtime directories exist: `var/`, `tmp/`

#### 1.3 SSL/TLS
- [ ] Caddy can obtain Let's Encrypt certificates
- [ ] Ports 80 and 443 are accessible from internet
- [ ] Domain resolves correctly (`dig panidobro.com`, `dig api.panidobro.com`)

### 2. Environment Configuration

#### 2.1 Database Settings
- [ ] `DATABASE_URL` configured (PostgreSQL 16+)
- [ ] `POSTGRES_DB` set
- [ ] `POSTGRES_USER` set
- [ ] `POSTGRES_PASSWORD` set (strong password, 16+ chars)
- [ ] Database connection tested

#### 2.2 Authentication & Secrets
- [ ] `AUTH_SECRET_KEY` set (32+ chars, not default value)
- [ ] `CLIENT_PORTAL_SECRET` set (32+ chars, not default value)
- [ ] `WORKER_PORTAL_SECRET` set (32+ chars, not default value)
- [ ] At least one admin credential pair configured:
  - [ ] `ADMIN_BASIC_USERNAME` / `ADMIN_BASIC_PASSWORD`
  - [ ] OR `OWNER_BASIC_USERNAME` / `OWNER_BASIC_PASSWORD`
- [ ] Admin passwords are strong (12+ chars, not placeholder values)
- [ ] `LEGACY_BASIC_AUTH_ENABLED=true` in production (only if needed)

#### 2.3 Stripe Integration
- [ ] `STRIPE_SECRET_KEY` configured (production key, starts with `sk_live_` or `sk_test_`)
- [ ] `STRIPE_WEBHOOK_SECRET` configured (starts with `whsec_`)
- [ ] Stripe webhook endpoint configured in Stripe dashboard:
  - [ ] URL: `https://api.panidobro.com/v1/payments/stripe/webhook`
  - [ ] Events: `checkout.session.completed`, `checkout.session.expired`, `payment_intent.succeeded`, `payment_intent.payment_failed`, `customer.subscription.*`
- [ ] `STRIPE_SUCCESS_URL` configured
- [ ] `STRIPE_CANCEL_URL` configured
- [ ] Test deposit flow verified in Stripe test mode

#### 2.4 Email Configuration
- [ ] `EMAIL_MODE` set (`sendgrid` or `smtp` or `off`)
- [ ] If SendGrid: `SENDGRID_API_KEY` configured
- [ ] If SMTP: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` configured
- [ ] `EMAIL_FROM` set (valid sender email)
- [ ] `EMAIL_FROM_NAME` set
- [ ] Test email sent successfully

#### 2.5 Storage Backend
- [ ] `ORDER_STORAGE_BACKEND` set (`local`, `r2`, `cloudflare_images`)
- [ ] If local: `ORDER_UPLOAD_ROOT` configured and writable
- [ ] If R2: `R2_BUCKET`, `R2_ACCESS_KEY`, `R2_SECRET_KEY` configured
- [ ] If Cloudflare Images: `CF_IMAGES_ACCOUNT_ID`, `CF_IMAGES_API_TOKEN`, `CF_IMAGES_SIGNING_KEY` configured
- [ ] Storage backend tested (upload/download)

#### 2.6 CORS & Proxy Settings
- [ ] `APP_ENV=prod` set
- [ ] `CORS_ORIGINS` configured (comma-separated list of allowed origins)
- [ ] `STRICT_CORS=true` in production
- [ ] If behind proxy: `TRUST_PROXY_HEADERS=true`
- [ ] If behind proxy: `TRUSTED_PROXY_IPS` or `TRUSTED_PROXY_CIDRS` configured

#### 2.7 Security Settings
- [ ] `ADMIN_IP_ALLOWLIST_CIDRS` configured (if restricting admin access by IP)
- [ ] `ADMIN_MFA_REQUIRED=true` recommended for production
- [ ] `CAPTCHA_MODE` and `TURNSTILE_SECRET_KEY` configured (if using Turnstile)
- [ ] Rate limiting configured: `RATE_LIMIT_PER_MINUTE`
- [ ] `REDIS_URL` configured for distributed rate limiting (if multi-instance)

#### 2.8 Monitoring & Observability
- [ ] `METRICS_ENABLED=true` recommended
- [ ] `METRICS_TOKEN` set (16+ chars)
- [ ] `JOB_HEARTBEAT_REQUIRED=true` if job runner is deployed
- [ ] `JOB_HEARTBEAT_TTL_SECONDS` configured (default 300)

### 3. Build & Migration Readiness

#### 3.1 Docker Images
- [ ] API image builds successfully: `docker compose build api`
- [ ] Web image builds successfully: `docker compose build web`
- [ ] No build errors or warnings
- [ ] Images are reasonably sized (< 1GB each)

#### 3.2 Database Migrations
- [ ] Migrations run successfully: `docker compose exec api alembic upgrade head`
- [ ] Current revision matches expected head: `docker compose exec api alembic current`
- [ ] No migration errors in logs
- [ ] Database schema validated

### 4. Service Health Checks

#### 4.1 Docker Services
- [ ] All services running: `docker compose ps`
  - [ ] `db` service: healthy
  - [ ] `api` service: running
  - [ ] `web` service: running
  - [ ] `caddy` service: running
- [ ] No restart loops in `docker compose ps`
- [ ] Database health check passing: `docker compose exec db pg_isready`

#### 4.2 API Health
- [ ] Liveness check: `curl https://api.panidobro.com/healthz` returns 200
- [ ] Readiness check: `curl https://api.panidobro.com/readyz` returns 200
  - [ ] Database connectivity: OK
  - [ ] Migrations current: true
  - [ ] Job heartbeat: OK (if `JOB_HEARTBEAT_REQUIRED=true`)
- [ ] OpenAPI docs accessible: `https://api.panidobro.com/docs`

#### 4.3 Web Application
- [ ] Web root accessible: `curl https://panidobro.com/` returns 200
- [ ] Static assets loading
- [ ] No console errors in browser
- [ ] Page renders correctly

#### 4.4 Reverse Proxy (Caddy)
- [ ] HTTP redirects to HTTPS
- [ ] SSL certificate valid (not self-signed)
- [ ] Certificate auto-renewal configured
- [ ] Security headers present:
  - [ ] `X-Content-Type-Options: nosniff`
  - [ ] `X-Frame-Options: DENY`
  - [ ] `Referrer-Policy: no-referrer`
- [ ] Access logs being written to `logs/`

### 5. Functional Testing

#### 5.1 API Endpoints
- [ ] Estimate pricing works: `POST /v1/estimate`
- [ ] Lead creation works: `POST /v1/leads`
- [ ] Admin authentication works: `GET /v1/admin/profile`
- [ ] Unauthorized access returns 401
- [ ] Invalid requests return proper error messages (ProblemDetails format)

#### 5.2 Stripe Integration
- [ ] Stripe webhook endpoint reachable
- [ ] Webhook signature validation working
- [ ] Test checkout session creation (test mode)
- [ ] Deposit flow complete (if deposits enabled)
- [ ] Payment intent handling verified

#### 5.3 Email System
- [ ] Test email sends successfully
- [ ] Email templates render correctly
- [ ] Outbox delivery working
- [ ] Dead letter queue handling verified

#### 5.4 Storage System
- [ ] Photo upload works
- [ ] Photo retrieval works
- [ ] Signed URLs generate correctly
- [ ] Signed URLs expire as configured
- [ ] Storage backend accessible

### 6. Background Jobs & Cron

#### 6.1 Job Runner
- [ ] Job runner starts: `python -m app.jobs.run --once`
- [ ] All jobs execute without errors
- [ ] Job heartbeat recorded in database
- [ ] Jobs scheduled via cron or Cloudflare Scheduler

#### 6.2 Job Types Verified
- [ ] `booking-reminders` - sends 24h reminders
- [ ] `invoice-reminders` - sends overdue notifications
- [ ] `nps-send` - sends NPS surveys
- [ ] `email-dlq` - processes failed emails
- [ ] `outbox-delivery` - delivers outbox events
- [ ] `dlq-auto-replay` - auto-replays failed exports
- [ ] `accounting-export` - monthly accounting exports
- [ ] `storage-janitor` - cleans up orphaned storage

#### 6.3 Scheduled Tasks
- [ ] Cleanup job scheduled: `POST /v1/admin/cleanup` (every 5-10 minutes)
- [ ] Email scan scheduled: `POST /v1/admin/email-scan` (every hour)
- [ ] Retention cleanup scheduled: `POST /v1/admin/retention/cleanup` (daily)

### 7. Backup & Recovery

#### 7.1 Database Backups
- [ ] Backup script exists and is executable
- [ ] Backup directory writable: `/opt/backups/postgres/`
- [ ] Backup runs successfully (manual test)
- [ ] Backup scheduled via cron (daily recommended)
- [ ] Backup success marker updated: `/opt/backups/postgres/LAST_SUCCESS.txt`
- [ ] Backup health check passing: `GET /healthz/backup`

#### 7.2 Recovery Plan
- [ ] Restore procedure documented
- [ ] Restore tested on non-production environment
- [ ] Backup retention policy defined
- [ ] Off-site backup copy created

### 8. Security Validation

#### 8.1 Configuration Security
- [ ] No secrets in Git repository
- [ ] `.env` file not committed
- [ ] Strong passwords used (no defaults like `change-me`, `secret`, `password`)
- [ ] Production config validation passes (no startup errors)

#### 8.2 Access Control
- [ ] Admin endpoints require authentication
- [ ] Worker endpoints require authentication
- [ ] Client portal tokens properly scoped
- [ ] Org isolation verified (multi-tenant)
- [ ] Cross-org access returns 403/404

#### 8.3 Input Validation
- [ ] Request validation working (422 for invalid input)
- [ ] SQL injection protected (parameterized queries)
- [ ] XSS protection (CSP headers)
- [ ] File upload validation (MIME type, size)
- [ ] Rate limiting active

### 9. Monitoring & Alerting

#### 9.1 Health Monitoring
- [ ] Uptime monitoring configured (external service)
- [ ] `/healthz` endpoint monitored (every 1-5 minutes)
- [ ] `/readyz` endpoint monitored (every 1-5 minutes)
- [ ] `/healthz/backup` endpoint monitored (every hour)

#### 9.2 Metrics Collection
- [ ] Metrics endpoint accessible: `GET /v1/metrics` (if enabled)
- [ ] Prometheus or compatible scraper configured
- [ ] Key metrics collected:
  - [ ] HTTP request latency (P50, P95, P99)
  - [ ] HTTP 5xx error rate
  - [ ] Job execution success/failure
  - [ ] Database connection pool usage
  - [ ] Rate limit hits

#### 9.3 Log Management
- [ ] Logs being written to `logs/` directory
- [ ] Caddy access logs: `logs/access_api.log`, `logs/access_web.log`
- [ ] Application logs: `docker compose logs api`
- [ ] Log rotation configured (Caddy auto-rotates)
- [ ] No sensitive data in logs (PII redacted)

#### 9.4 Alerting
- [ ] Alerts configured for:
  - [ ] Service down (healthz/readyz failing)
  - [ ] High error rate (5xx > threshold)
  - [ ] High latency (P99 > threshold)
  - [ ] Job failures (consecutive failures > 3)
  - [ ] Backup failures (backup health check fails)
  - [ ] Disk space low (< 10% free)
  - [ ] Database connection failures

### 10. Smoke Tests

#### 10.1 Automated Smoke Tests
- [ ] Smoke script runs successfully: `./scripts/smoke.sh`
- [ ] All critical tests pass
- [ ] No unexpected failures
- [ ] Smoke tests integrated into deployment pipeline

#### 10.2 Manual Smoke Tests
- [ ] Can create a lead via web UI
- [ ] Can get an estimate
- [ ] Can book a time slot
- [ ] Can complete Stripe checkout (test mode)
- [ ] Admin can log in
- [ ] Admin can view leads/bookings/invoices
- [ ] Photos can be uploaded and viewed
- [ ] Emails are sent (check logs or inbox)

### 11. Performance Validation

#### 11.1 Load Testing
- [ ] API handles expected request volume
- [ ] Response times acceptable (< 500ms P95 for reads)
- [ ] No memory leaks observed
- [ ] Database query performance validated
- [ ] Connection pool sized correctly

#### 11.2 Scalability
- [ ] Horizontal scaling tested (if applicable)
- [ ] Redis rate limiting working (if multi-instance)
- [ ] Database connection pooling configured
- [ ] Static assets cached properly

### 12. Documentation & Runbooks

#### 12.1 Documentation Complete
- [ ] README.md up to date
- [ ] OPERATIONS.md current
- [ ] RUNBOOK.md accurate
- [ ] SMOKE.md comprehensive
- [ ] GO_NO_GO.md (this document) complete

#### 12.2 Runbooks Available
- [ ] Deployment procedure documented: `ops/deploy.sh`
- [ ] Rollback procedure documented
- [ ] Incident response playbook available
- [ ] Monitoring runbook available: `backend/docs/runbook_monitoring.md`
- [ ] Backup/restore drill documented: `backend/docs/runbook_backup_restore_drill.md`

#### 12.3 Team Readiness
- [ ] Team trained on deployment process
- [ ] Team trained on incident response
- [ ] On-call rotation defined
- [ ] Escalation contacts documented

### 13. Compliance & Legal

#### 13.1 Data Protection
- [ ] GDPR compliance reviewed (if applicable)
- [ ] Data retention policy implemented
- [ ] Data deletion procedure tested: `POST /v1/admin/data-deletion/requests`
- [ ] Data export procedure tested: `POST /v1/admin/data/export`

#### 13.2 Terms & Privacy
- [ ] Terms of Service published
- [ ] Privacy Policy published
- [ ] Cookie consent implemented (if applicable)

### 14. Rollout Strategy

#### 14.1 Staged Rollout
- [ ] Staging environment validated first
- [ ] Production deployment during low-traffic window
- [ ] Rollback plan ready
- [ ] Database migrations tested on staging
- [ ] No breaking changes to public APIs

#### 14.2 Post-Deployment
- [ ] Monitor for 30 minutes post-deployment
- [ ] Check error logs for new errors
- [ ] Verify key user flows working
- [ ] Customer support notified of deployment
- [ ] Deployment notes communicated to team

## Go/No-Go Decision

### GO Criteria (all must be true)

✅ **Infrastructure**: Server requirements met, Docker services healthy
✅ **Configuration**: All required environment variables set and validated
✅ **Database**: Migrations current, backups working
✅ **Health Checks**: All health endpoints returning 200
✅ **Smoke Tests**: `./scripts/smoke.sh` passes
✅ **Security**: No default passwords, secrets properly configured
✅ **Monitoring**: Health monitoring and alerting configured
✅ **Documentation**: Runbooks complete and team trained

### NO-GO Criteria (any triggers no-go)

❌ **Critical health check failing** (healthz, readyz, backup)
❌ **Smoke tests failing**
❌ **Default/weak passwords in production**
❌ **Database migrations failing**
❌ **SSL certificate invalid or missing**
❌ **Backup system not working**
❌ **Critical monitoring not configured**
❌ **Team not trained on incident response**

## Sign-Off

**Deployment Lead**: ___________________ Date: ___________

**Infrastructure Owner**: ___________________ Date: ___________

**Security Reviewer**: ___________________ Date: ___________

**Technical Lead**: ___________________ Date: ___________

## Post-Deployment Verification

After deployment, verify within 30 minutes:

- [ ] Health checks passing: `curl https://api.panidobro.com/readyz`
- [ ] Smoke tests passing: `./scripts/smoke.sh`
- [ ] No elevated error rates in logs
- [ ] User flows working (create lead, get estimate, book)
- [ ] Monitoring showing healthy metrics
- [ ] No alerts triggered

**Notes:**

---

## Rollback Procedure

If deployment fails:

1. Check health status: `curl https://api.panidobro.com/readyz`
2. Review recent logs: `docker compose logs --tail=200 api`
3. If critical issue, initiate rollback:
   ```bash
   cd /opt/cleaning
   git fetch origin
   git reset --hard <previous-good-sha>
   ./ops/deploy.sh
   ```
4. Verify rollback successful: `./scripts/smoke.sh`
5. Document issue in incident log
6. Schedule post-mortem

---

**Last Updated**: 2026-01-06
**Version**: 1.0
