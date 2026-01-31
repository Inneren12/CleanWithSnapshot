# Row-Level Security (RLS)

## Overview
CleanWithSnapshot relies on Postgres RLS as a defense-in-depth layer for **all org-scoped tables**
(every table with an `org_id` column). The application sets `SET LOCAL app.current_org_id = '<uuid>'`
per transaction; policies enforce `org_id` matches the current org so cross-tenant access is blocked.

## How to add a new org-scoped table safely
Use this checklist whenever you introduce a new table that should be tenant-isolated.

1. **Add `org_id` + FK + index**
   - Add `org_id` (UUID) with `ForeignKey("organizations.org_id")`.
   - Backfill existing rows if needed and then mark `org_id` as `nullable=False`.
   - Add an index on `org_id` (and any common composite filters).
2. **Enable + force RLS**
   - Use an Alembic migration to `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`.
3. **Add CRUD policies**
   - Use a single `FOR ALL` policy scoped to `org_id`.
4. **Ensure tenant context is set**
   - All code paths must run with `SET LOCAL app.current_org_id`.
   - Background jobs and scripts must set org context inside each transaction.
5. **Update the RLS audit expected list**
   - Add the migration to `backend/scripts/audit_rls_coverage.py` so metadata mode tracks coverage.
6. **Add a regression test**
   - Add/extend tests to verify cross-org reads/writes are blocked for the new table.

### Minimal migration snippet (pattern used in this repo)

```python
SCHEMA = "public"
TABLE = "example_table"
TENANT_EXPR = "org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid"

def _policy_sql(table: str) -> str:
    qualified_table = f"{SCHEMA}.{table}"
    policy_name = f"{table}_org_isolation"
    return f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = '{SCHEMA}'
          AND c.relname = '{table}'
          AND c.relrowsecurity
    ) THEN
        EXECUTE 'ALTER TABLE {qualified_table} ENABLE ROW LEVEL SECURITY';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = '{SCHEMA}'
          AND c.relname = '{table}'
          AND c.relforcerowsecurity
    ) THEN
        EXECUTE 'ALTER TABLE {qualified_table} FORCE ROW LEVEL SECURITY';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = '{SCHEMA}'
          AND tablename = '{table}'
          AND policyname = '{policy_name}'
    ) THEN
        EXECUTE $sql$
            CREATE POLICY {policy_name} ON {qualified_table}
            USING ({TENANT_EXPR})
            WITH CHECK ({TENANT_EXPR})
        $sql$;
    END IF;
END
$$;
"""
```

## How to run the RLS audit

### Local (database mode)
```bash
cd backend
python -m alembic -c alembic_rls_audit.ini upgrade head
python scripts/audit_rls_coverage.py --output rls-audit.md --fail-on-core-missing
```

### Local (metadata mode)
```bash
cd backend
python scripts/audit_rls_coverage.py --source metadata --output rls-audit.md
```

### CI
The audit runs in `.github/workflows/ci.yml` under the **Security - RLS Coverage Audit** job. It:
1. Spins up a Postgres service.
2. Runs `python -m alembic -c alembic_rls_audit.ini upgrade head`.
3. Runs `python scripts/audit_rls_coverage.py --output rls-audit.md --fail-on-core-missing`.

The `rls-audit-report` artifact contains the generated markdown report and the logs show the table
summary for debugging.
