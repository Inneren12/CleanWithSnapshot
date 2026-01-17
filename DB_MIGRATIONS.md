# Database Migrations Guide

This guide covers database schema management using Alembic in the CleanWithSnapshot project.

---

## Table of Contents

1. [Overview](#overview)
2. [How Alembic is Structured](#how-alembic-is-structured)
3. [Creating Migrations](#creating-migrations)
4. [Running Migrations](#running-migrations)
5. [Merging Heads](#merging-heads)
6. [Testing Migrations](#testing-migrations)
7. [Migration Validation](#migration-validation)
8. [Common Migration Tasks](#common-migration-tasks)
9. [Troubleshooting](#troubleshooting)

---

## Overview

**Migration System:** Alembic (SQLAlchemy migration tool)
**Location:** `backend/alembic/`
**Total Migrations:** 90+ (as of 2026-01)
**Policy:** Forward-only (no downgrades in production)
**Validation:** Health endpoint checks migration status

**Recent migrations:** `aa12b3cd45ef_add_marketing_spend_and_email_manual.py` adds `marketing_spend`,
`email_segments`, and `email_campaigns` for marketing analytics and manual campaigns,
`e6b1c2d3f4a5_add_promo_codes.py` adds `promo_codes` + `promo_code_redemptions`,
`d3b7c1a4f8e2_add_lead_quotes_and_loss_reason.py` adds lead quotes + loss reason tracking,
`6ddda2f1b93a_quality_issue_responses.py` adds `quality_issue_responses`,
`9b7c1d2e3f4a_quality_issue_tags.py` adds `quality_issue_tags` + `quality_tag_catalog`,
`1b2c3d4e5f6a_quality_issue_tag_position.py` adds tag ordering via `quality_issue_tags.position`,
`a1b2c3d4e5f6_add_inventory_categories_and_items.py` adds `inventory_categories` and `inventory_items` tables,
`b1c2d3e4f5a6_merge_heads_inventory_and_marketing.py` merges parallel migration heads, and
`cf72c4eb59bc_add_inventory_stock_fields.py` adds stock state fields (`current_qty`, `min_qty`, `location_label`) to `inventory_items`.

---

## How Alembic is Structured

### Directory Layout

```
backend/
├── alembic/
│   ├── env.py                  # Migration environment (imports all models)
│   ├── script.py.mako          # Migration template
│   └── versions/               # Migration files (90+)
│       ├── 0001_initial.py
│       ├── 0002_slots_v1.py
│       ├── ...
│       └── 6a2b1c6f3c2b_availability_blocks.py
├── alembic.ini                 # Alembic configuration
└── app/
    ├── domain/
    │   └── {module}/
    │       └── db_models.py    # SQLAlchemy models
    └── infra/
        └── db.py               # Base class for models
```

### Key Files

| File | Purpose |
|------|---------|
| `alembic.ini` | Alembic configuration (database URL placeholder, logging) |
| `alembic/env.py` | **Migration environment** - Imports all models, sets database URL |
| `alembic/versions/*.py` | **Migration files** - Schema change scripts |

### Migration Environment (`env.py`)

**Critical:** `env.py` imports ALL domain models so Alembic can detect schema changes:

```python
# backend/alembic/env.py
from app.domain.bookings import db_models as booking_db_models
from app.domain.invoices import db_models as invoice_db_models
from app.domain.workers import db_models as worker_db_models
# ... all other domain models
from app.infra.db import Base

target_metadata = Base.metadata  # All models registered here
```

**If you add a new domain module with models:**
1. Add import to `env.py`
2. Otherwise Alembic won't detect your new tables

---

## Creating Migrations

### Auto-Generate Migration

**Recommended for most schema changes:**

```bash
cd backend

# 1. Edit your domain models (e.g., add column to Booking)
# 2. Auto-generate migration
alembic revision --autogenerate -m "add booking priority field"

# 3. Review generated migration in alembic/versions/
# (Alembic file is named: 00XX_add_booking_priority_field.py)

# 4. Edit migration if needed (see below)
# 5. Test migration
alembic upgrade head
```

**Example auto-generated migration:**

```python
# alembic/versions/0087_add_booking_priority.py
"""add booking priority field

Revision ID: 0087
Revises: 0086
Create Date: 2026-01-15 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0087'
down_revision = '0086'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('bookings', sa.Column('priority', sa.String(20), nullable=True))
    op.create_index('ix_bookings_priority', 'bookings', ['priority'])

def downgrade() -> None:
    op.drop_index('ix_bookings_priority', 'bookings')
    op.drop_column('bookings', 'priority')
```

### Manual Migration (Empty)

**For data migrations or complex changes:**

```bash
cd backend

# Create empty migration
alembic revision -m "backfill booking priority"

# Edit migration file manually
# Add custom Python logic in upgrade()/downgrade()
```

**Example manual migration:**

```python
def upgrade() -> None:
    # Custom SQL or Python logic
    op.execute("""
        UPDATE bookings
        SET priority = 'normal'
        WHERE priority IS NULL
    """)

def downgrade() -> None:
    # Revert logic (if possible)
    pass
```

### What Alembic Auto-Detects

**Alembic will detect:**
- New tables
- New columns
- Column type changes
- Column nullability changes
- New indexes
- New foreign keys

**Alembic will NOT detect:**
- Table renames (interprets as drop + create)
- Column renames (interprets as drop + add)
- Constraint changes (sometimes)
- Enum value changes

**Always review auto-generated migrations!**

### SQLite Constraint Changes (Batch Mode)

SQLite cannot `ALTER` constraints directly. When dropping or creating constraints (FKs, unique constraints), wrap the
changes in `op.batch_alter_table()` so Alembic uses the copy-and-move strategy during SQLite tests.

---

## Running Migrations

### Upgrade to Latest

```bash
cd backend

# Upgrade to latest (production)
alembic upgrade head

# Upgrade one step
alembic upgrade +1

# Upgrade to specific revision
alembic upgrade 0087
```

### Check Current Version

```bash
cd backend

# Show current revision
alembic current

# Show migration history
alembic history

# Show pending migrations
alembic history --verbose
```

### Downgrade (NOT RECOMMENDED in Production)

```bash
cd backend

# Downgrade one step (dev only)
alembic downgrade -1

# Downgrade to specific revision
alembic downgrade 0086

# Downgrade all (⚠️ DANGER - drops all tables)
alembic downgrade base
```

**Production policy:** Forward-only migrations. No downgrades.

---

## Merging Heads

### Single-Head Policy

CleanWithSnapshot enforces a **single-head policy** - only one active migration branch.

**Why?** Multiple heads cause deployment issues and test failures.

### Detecting Multiple Heads

```bash
cd backend

# Check for multiple heads
alembic heads

# If multiple heads:
# heads: abc123 (branch1), def456 (branch2)
```

**CI validation:** `tests/test_migrations.py` fails if multiple heads exist.

**Quick check + merge (example):**

```bash
cd backend
alembic heads
# Output: abc123 (branch1), def456 (branch2)

alembic merge -m "merge heads abc123 and def456" abc123 def456
alembic upgrade head
```

**Real-world scenario (parallel feature development):**

When two feature branches independently create migrations from the same parent, you get multiple heads:

```bash
# Scenario: Two PRs both branched from f0b1c2d3e4f5
# PR #1 (inventory): creates migration a1b2c3d4e5f6
# PR #2 (marketing): creates migration aa12b3cd45ef
# Both merged to main → multiple heads!

cd backend
alembic heads
# Output:
# a1b2c3d4e5f6 (add inventory categories and items)
# aa12b3cd45ef (add marketing spend and email manual)

# Create merge migration
alembic merge -m "merge heads a1b2c3d4e5f6 and aa12b3cd45ef" a1b2c3d4e5f6 aa12b3cd45ef
# Creates: b1c2d3e4f5a6_merge_heads_inventory_and_marketing.py

# Verify single head
alembic heads
# Output: b1c2d3e4f5a6 (merge heads...)

# Upgrade to merged head
alembic upgrade head
```

**Prevention tip:** Always pull latest `main` and merge any pending heads BEFORE creating new migrations. Check `alembic heads` first!

### Merging Heads

**When you see multiple heads:**

```bash
cd backend

# Merge heads (creates merge migration)
alembic merge -m "merge migration heads" abc123 def456

# This creates a new migration like:
# alembic/versions/96339be46688_merge_alembic_heads.py

# Example (training head merge):
# alembic merge -m "merge heads b1c2d3e4f5a6 and b7f4d2e9c1a0" b1c2d3e4f5a6 b7f4d2e9c1a0

# If you see more than two heads, merge all heads into one merge revision:
# alembic merge -m "merge heads a1b2c3d4e5f6 b1c2d3e4f5a6 c9f0a1b2c3d4 cf72c4eb59bc" \
#   a1b2c3d4e5f6 b1c2d3e4f5a6 c9f0a1b2c3d4 cf72c4eb59bc
# CI enforces the single-head policy via tests/test_migrations.py.

# Example (no-op merge between two specific heads):
# alembic merge -m "merge heads 9f2b7c4d1a0e and b8e1c2d3f4a5" 9f2b7c4d1a0e b8e1c2d3f4a5
# Ensure the generated migration has down_revision = ("9f2b7c4d1a0e", "b8e1c2d3f4a5") and empty upgrade/downgrade.

# Upgrade to merged head
alembic upgrade head

# Verify single head
alembic heads
# Should show only one head
```

**Example merge migration:**

```python
# alembic/versions/96339be46688_merge_alembic_heads.py
"""merge alembic heads

Revision ID: 96339be46688
Revises: abc123, def456
Create Date: 2026-01-15 10:00:00.000000
"""
revision = '96339be46688'
down_revision = ('abc123', 'def456')  # Two parents
branch_labels = None
depends_on = None

def upgrade() -> None:
    pass  # Empty - just merges branches

def downgrade() -> None:
    pass
```

### Preventing Multiple Heads

**Best practices:**
1. Pull latest `main` before creating migrations
2. Check for pending migrations: `alembic heads`
3. If multiple heads exist, merge BEFORE creating new migrations
4. Run `alembic heads` in CI (enforced by `test_migrations.py`)

---

## Testing Migrations

### Local Testing

```bash
cd backend

# 1. Create test database
createdb cleaning_test

# 2. Set database URL
export DATABASE_URL="postgresql+psycopg://user:pass@localhost/cleaning_test"

# 3. Run migrations
alembic upgrade head

# 4. Verify schema
psql cleaning_test -c "\dt"  # List tables
psql cleaning_test -c "\d bookings"  # Describe table

# 5. Test downgrade (optional)
alembic downgrade -1
alembic upgrade head

# 6. Clean up
dropdb cleaning_test
```

### Migration Test Suite

```bash
cd backend

# Run migration validation tests
pytest tests/test_migration_imports.py -v

# This test validates:
# - All models are imported in env.py
# - Single head policy
# - No migration conflicts
```

### Production-like Testing

**Test migrations on a copy of production data:**

```bash
# 1. Create backup
pg_dump production_db > prod_backup.sql

# 2. Restore to test database
createdb migration_test
psql migration_test < prod_backup.sql

# 3. Test migration
export DATABASE_URL="postgresql+psycopg://user:pass@localhost/migration_test"
alembic upgrade head

# 4. Verify data integrity
psql migration_test -c "SELECT COUNT(*) FROM bookings;"

# 5. Clean up
dropdb migration_test
```

---

## Migration Validation

### Health Endpoint

**Production validation:** The `/healthz` endpoint checks migration status:

```bash
curl https://api.panidobro.com/healthz
```

**Response:**

```json
{
  "status": "ready",
  "db_connected": true,
  "migrations_current": true,
  "current_revision": "0086",
  "expected_revision": "0086"
}
```

**If migrations are out of sync:**

```json
{
  "status": "unhealthy",
  "db_connected": true,
  "migrations_current": false,
  "current_revision": "0085",
  "expected_revision": "0086"
}
```

**API won't start** if migrations are out of sync (enforced at startup).

### CI Validation

**GitHub Actions workflow validates:**
- Migration imports (all models in `env.py`)
- Single head policy
- No migration conflicts

See `.github/workflows/ci.yml` (job: `api`)

---

## Common Migration Tasks

### Add a New Table

```bash
cd backend

# 1. Create model in domain module
# backend/app/domain/reports/db_models.py
class Report(Base):
    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(255))

# 2. Import model in env.py
# backend/alembic/env.py
from app.domain.reports import db_models as report_db_models  # ADD THIS

# 3. Generate migration
alembic revision --autogenerate -m "add reports table"

# 4. Review migration
# alembic/versions/00XX_add_reports_table.py

# 5. Test
alembic upgrade head
```

### Add a Column

```bash
# 1. Edit model
class Booking(Base):
    # ... existing columns
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)

# 2. Generate migration
alembic revision --autogenerate -m "add booking priority column"

# 3. Review and test
alembic upgrade head
```

### Add an Index

```bash
# 1. Edit model __table_args__
class Booking(Base):
    __table_args__ = (
        Index("ix_bookings_priority", "priority"),  # ADD THIS
        # ... existing indexes
    )

# 2. Generate migration
alembic revision --autogenerate -m "add booking priority index"

# 3. Test
alembic upgrade head
```

### Rename a Column (Manual)

**Alembic interprets renames as drop + add (data loss!). Use manual migration:**

```python
# alembic revision -m "rename booking column"

def upgrade() -> None:
    # Rename column (PostgreSQL)
    op.alter_column('bookings', 'old_name', new_column_name='new_name')

    # Or use SQL
    op.execute("ALTER TABLE bookings RENAME COLUMN old_name TO new_name")

def downgrade() -> None:
    op.alter_column('bookings', 'new_name', new_column_name='old_name')
```

### Add Row-Level Security (RLS)

**PostgreSQL RLS policies (see migration 0044):**

```python
def upgrade() -> None:
    # Enable RLS
    op.execute("ALTER TABLE bookings ENABLE ROW LEVEL SECURITY")

    # Create policy
    op.execute("""
        CREATE POLICY bookings_org_isolation ON bookings
        USING (org_id = current_setting('app.current_org_id')::uuid)
    """)

def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS bookings_org_isolation ON bookings")
    op.execute("ALTER TABLE bookings DISABLE ROW LEVEL SECURITY")
```

### Backfill Data

**Data migration pattern:**

```python
def upgrade() -> None:
    # 1. Add column (nullable)
    op.add_column('bookings', sa.Column('priority', sa.String(20), nullable=True))

    # 2. Backfill data
    op.execute("""
        UPDATE bookings
        SET priority = 'normal'
        WHERE priority IS NULL
    """)

    # 3. Make column non-nullable (optional)
    op.alter_column('bookings', 'priority', nullable=False)
```

---

## Troubleshooting

### "Target database is not up to date"

**Error:**
```
Target database is not up to date.
Current: 0085
Expected: 0086
```

**Solution:**

```bash
cd backend
alembic upgrade head
```

### "Multiple heads detected"

**Error:**
```
Multiple heads detected:
  abc123 (branch1)
  def456 (branch2)
```

**Solution:**

```bash
cd backend

# Merge heads
alembic merge -m "merge heads" abc123 def456

# Upgrade to merged head
alembic upgrade head
```

### "Can't locate revision identified by 'XXXX'"

**Error:**
```
Can't locate revision identified by '0087'
```

**Causes:**
1. Migration file missing from `alembic/versions/`
2. Git merge conflict (missing migration)
3. Corrupted `alembic_version` table

**Solution:**

```bash
# Check existing migrations
ls backend/alembic/versions/

# Check database revision
psql -d cleaning -c "SELECT * FROM alembic_version;"

# If mismatch, manually fix:
alembic stamp 0086  # Set to known-good revision
alembic upgrade head
```

### "Autogenerate detected no changes"

**Causes:**
1. Model not imported in `env.py`
2. No actual schema changes
3. Base metadata not updated

**Solution:**

```python
# Check env.py imports
# backend/alembic/env.py

from app.domain.your_module import db_models  # ADD THIS

from app.infra.db import Base
target_metadata = Base.metadata
```

### "Duplicate table name"

**Error:**
```
DuplicateTable: relation "bookings" already exists
```

**Cause:** Migration already applied but not recorded in `alembic_version` table.

**Solution:**

```bash
# Mark migration as applied (without running)
alembic stamp 0087

# Or re-run from scratch
alembic downgrade base
alembic upgrade head
```

### "Foreign key constraint violation"

**Cause:** Migration order issue - referencing table doesn't exist yet.

**Solution:**

Manually edit migration to ensure correct order:

```python
def upgrade() -> None:
    # 1. Create parent table first
    op.create_table('organizations', ...)

    # 2. Then create child table
    op.create_table('bookings',
        sa.Column('org_id', sa.UUID, sa.ForeignKey('organizations.id')),
        ...
    )
```

---

## Migration Best Practices

### DO

✅ **Review auto-generated migrations** - Alembic doesn't catch everything
✅ **Test on local database** - Before committing
✅ **Add indexes for foreign keys** - Performance
✅ **Use nullable columns initially** - For backfill migrations
✅ **Commit migration file to git** - Required for deployment
✅ **Run migrations in CI** - Catch issues early
✅ **Enforce single-head policy** - Merge before creating new migrations

### DON'T

❌ **Don't trust autogenerate blindly** - Review and edit
❌ **Don't rename tables/columns** - Use manual migrations
❌ **Don't skip testing** - Test locally before deploying
❌ **Don't run downgrades in production** - Forward-only policy
❌ **Don't modify committed migrations** - Create new ones instead
❌ **Don't forget to import new models in env.py** - Alembic won't see them

---

## Commands Reference

| Command | Purpose |
|---------|---------|
| `alembic current` | Show current revision |
| `alembic heads` | Show head revisions (should be 1) |
| `alembic history` | Show migration history |
| `alembic upgrade head` | Upgrade to latest |
| `alembic upgrade +1` | Upgrade one step |
| `alembic downgrade -1` | Downgrade one step (dev only) |
| `alembic revision -m "msg"` | Create empty migration |
| `alembic revision --autogenerate -m "msg"` | Auto-generate migration |
| `alembic merge -m "msg" abc123 def456` | Merge two heads |
| `alembic stamp 0087` | Mark migration as applied (no-op) |

---

## Related Documentation

- [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) - High-level architecture
- [CONTENT_GUIDE.md](./CONTENT_GUIDE.md) - Coding conventions
- [FILE_OVERVIEW.md](./FILE_OVERVIEW.md) - Repository structure
- [OPERATIONS.md](./OPERATIONS.md) - Deployment guide
- [docs/ADMIN_GUIDE.md](./docs/ADMIN_GUIDE.md) - Migration troubleshooting
