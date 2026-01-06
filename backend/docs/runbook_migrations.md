# Database Migrations Runbook

This runbook covers the automated database migration process, preflight checks, and rollback procedures for the CleanWithSnapshot application.

## Overview

The application uses Alembic for database schema migrations. All migrations are automated as part of the standard deployment process and validated through health checks before the deployment is considered successful.

## Migration Automation

### Standard Deploy Process

The standard deployment automatically handles migrations in the following order:

1. **Build** - Docker images are built from the latest code
2. **Start Services** - Database and API containers are started
3. **Wait for Database** - Deployment waits for PostgreSQL to be ready
4. **Run Migrations** - `alembic upgrade head` executes all pending migrations
5. **Health Check** - `/readyz` endpoint validates migrations are current
6. **Smoke Tests** - Basic endpoint checks confirm the deploy succeeded

### Running Migrations

Migrations run automatically during deployment via:

```bash
docker compose exec -T api alembic upgrade head
```

For manual migration execution:

```bash
# Using Makefile (recommended)
make migrate

# Or directly via docker compose
docker compose exec -T api alembic upgrade head
```

### Creating New Migrations

When schema changes are needed:

```bash
# Auto-generate migration from model changes
make revision msg="description_of_change"

# Or manually
docker compose exec -T api alembic revision --autogenerate -m "description_of_change"
```

Review the generated migration file in `backend/alembic/versions/` before committing.

## Preflight Checks

### Automated Health Checks

The `/readyz` endpoint provides comprehensive readiness checks including migration status:

```bash
curl https://api.panidobro.com/readyz
```

Response structure:
```json
{
  "ok": true,
  "checks": [
    {
      "name": "db",
      "ok": true,
      "ms": 12.34,
      "detail": {"message": "database reachable"}
    },
    {
      "name": "migrations",
      "ok": true,
      "ms": 23.45,
      "detail": {
        "message": "migrations in sync",
        "migrations_current": true,
        "current_version": "0052_stripe_events_processed",
        "expected_head": "0052_stripe_events_processed",
        "expected_heads": ["0052_stripe_events_processed"],
        "migrations_check": "ok"
      }
    },
    {
      "name": "jobs",
      "ok": true,
      "ms": 8.90,
      "detail": {
        "enabled": true,
        "last_heartbeat": "2026-01-06T12:34:56Z",
        "runner_id": "jobs-runner",
        "age_seconds": 45.2,
        "threshold_seconds": 180,
        "jobs_enabled": true
      }
    }
  ]
}
```

**Migration Check Behavior:**
- Returns `503 Service Unavailable` if migrations are pending
- Compares database `alembic_version` table against expected Alembic heads
- Caches Alembic metadata for 60 seconds to reduce filesystem overhead
- Skips check gracefully if Alembic files are unavailable (packaged deployments)

### Manual Migration Status

Check current migration version:

```bash
# Via docker compose
docker compose exec -T db psql -U postgres -d cleaning -c "SELECT version_num FROM alembic_version;"

# Or via Alembic
docker compose exec -T api alembic current
```

Show migration history:

```bash
docker compose exec -T api alembic history
```

Show pending migrations:

```bash
docker compose exec -T api alembic heads
docker compose exec -T api alembic current
```

## Migration Best Practices

### Forward-Only Migrations (Preferred)

**Always prefer forward-fix migrations over rollbacks.**

When a migration causes issues:

1. **Don't** immediately roll back the database
2. **Do** create a new migration that fixes the problem
3. Deploy the fix using the standard process

Benefits:
- Preserves data integrity
- Maintains audit trail
- Avoids risky downgrade operations
- Supports zero-downtime deployments

### Writing Safe Migrations

**Additive changes** (safe for zero-downtime):
- Adding new tables
- Adding new columns with defaults or nullable
- Adding indexes (use `CONCURRENTLY` in Postgres)
- Adding new constraints that don't affect existing data

**Breaking changes** (require coordination):
- Dropping columns or tables
- Adding NOT NULL without default
- Changing column types
- Renaming columns (appears as drop + add)

For breaking changes, use a multi-phase approach:

**Phase 1: Add new schema**
```python
def upgrade():
    # Add new column
    op.add_column('users', sa.Column('email_new', sa.String(255), nullable=True))

    # Backfill data
    op.execute("UPDATE users SET email_new = email WHERE email IS NOT NULL")
```

**Phase 2: Switch application code**
- Deploy code that uses `email_new` but falls back to `email`
- Verify in production

**Phase 3: Remove old schema**
```python
def upgrade():
    # Remove old column
    op.drop_column('users', 'email')
```

### Downgrade Functions

**Rule: Implement `downgrade()` for every migration, even if you never use it.**

Reasons:
- Required for Alembic to track revision chain
- Enables emergency rollbacks if absolutely necessary
- Documents the inverse operation for future reference

Example:

```python
def upgrade():
    op.add_column('bookings', sa.Column('priority', sa.Integer(), nullable=True))

def downgrade():
    op.drop_column('bookings', 'priority')
```

## Data Migrations

For data transformations that don't fit in schema migrations:

### Option 1: Inline Data Migration

Include data changes in the same migration:

```python
def upgrade():
    # Schema change
    op.add_column('invoices', sa.Column('status_normalized', sa.String(20), nullable=True))

    # Data migration
    connection = op.get_bind()
    connection.execute(
        text("UPDATE invoices SET status_normalized = LOWER(TRIM(status)) WHERE status IS NOT NULL")
    )

    # Apply constraints after data is clean
    op.alter_column('invoices', 'status_normalized', nullable=False)

def downgrade():
    op.drop_column('invoices', 'status_normalized')
```

### Option 2: Separate Admin Endpoint

For large data migrations or backfills:

1. Create migration with new schema (nullable)
2. Deploy code with admin endpoint for backfill
3. Run backfill via admin endpoint
4. Create follow-up migration to add constraints

Benefits:
- Controlled rollout
- Progress monitoring
- Doesn't block migration step
- Can be run during business hours

## Troubleshooting

### Migration Failed During Deploy

If migrations fail during deployment:

1. **Check migration logs:**
   ```bash
   docker compose logs api | grep -i alembic
   ```

2. **Identify the failing migration:**
   ```bash
   docker compose exec -T api alembic current
   ```

3. **Options:**
   - **Fix forward:** Create a new migration that corrects the issue
   - **Emergency rollback:** See "Emergency Migration Rollback" below

### Conflicting Migrations (Multiple Heads)

If multiple branches created migrations simultaneously:

```bash
# Check for multiple heads
docker compose exec -T api alembic heads

# Create merge migration
docker compose exec -T api alembic merge -m "merge migration heads" <head1> <head2>
```

### Emergency Migration Rollback

**Only use in true emergencies when forward-fix is not feasible.**

Prerequisites:
- Downgrade function exists in the migration
- Database backup is recent and tested
- Incident is documented

Steps:

1. **Take immediate backup:**
   ```bash
   ./backend/scripts/backup_pg.sh
   ```

2. **Verify downgrade function exists:**
   ```bash
   docker compose exec -T api cat alembic/versions/<migration_file>.py | grep "def downgrade"
   ```

3. **Execute downgrade:**
   ```bash
   # Downgrade one migration
   docker compose exec -T api alembic downgrade -1

   # Or to specific version
   docker compose exec -T api alembic downgrade <revision>
   ```

4. **Verify migration status:**
   ```bash
   docker compose exec -T api alembic current
   curl https://api.panidobro.com/readyz | jq '.checks[] | select(.name=="migrations")'
   ```

5. **Roll back application version:**
   ```bash
   # See docs/runbook_rollback.md for image rollback
   IMAGE_TAG=<previous-tag> docker compose up -d api
   ```

6. **Document in incident log:**
   - What migration was rolled back
   - Why forward-fix wasn't feasible
   - Plan for re-applying the change

### Migration Timeout

If migrations take too long:

1. **Check for blocking queries:**
   ```bash
   docker compose exec -T db psql -U postgres -d cleaning -c \
     "SELECT pid, now() - pg_stat_activity.query_start AS duration, query
      FROM pg_stat_activity
      WHERE state = 'active' AND query NOT LIKE '%pg_stat_activity%';"
   ```

2. **Consider maintenance window:**
   - For large schema changes, schedule downtime
   - Use `CONCURRENTLY` for index creation (can't run in transaction)

3. **Break into smaller migrations:**
   - Split large data migrations into batches
   - Use multiple migrations for complex changes

### Read-Only Replica Lag

For systems with read replicas:

1. **Monitor replication lag** before migrations:
   ```bash
   # On replica
   docker compose exec -T db_replica psql -U postgres -d cleaning -c \
     "SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;"
   ```

2. **Wait for replica catch-up** after migrations:
   - Automated in deployment scripts
   - Verify via monitoring before routing read traffic

## Monitoring

### Key Metrics

Monitor these metrics during and after migrations:

- **Migration duration** - Track via deploy logs
- **Readiness check status** - `/readyz` endpoint
- **Database connection pool** - Watch for exhaustion
- **Query performance** - Check for slow queries post-migration
- **Error rates** - Monitor 500s and application errors

### Alerts

Set up alerts for:

- `/readyz` returning 503 (migrations pending)
- Migration taking longer than expected (>5 minutes)
- Alembic errors in application logs
- Database lock waits during migration window

## See Also

- `runbook_rollback.md` - Application rollback procedures
- `runbook_backup_restore.md` - Database backup and restore
- `OPERATIONS.md` - Complete operations guide
- `alembic/README` - Alembic configuration details
