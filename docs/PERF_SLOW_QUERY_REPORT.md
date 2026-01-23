# Slow query report (pg_stat_statements)

This report surfaces the most expensive queries by total execution time and mean execution time using `pg_stat_statements`. Output is masked to avoid leaking secrets or PII (string literals, numeric literals, and bind parameter placeholders are replaced).

## Prerequisites

1. Ensure `pg_stat_statements` is installed and enabled:
   ```sql
   CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
   ```
2. Ensure your database URL is available via `DATABASE_URL`, or pass it explicitly.

## Usage

```bash
python backend/scripts/slow_query_report.py --help
```

### Markdown output (default)

```bash
python backend/scripts/slow_query_report.py --limit 20 --format md
```

### JSON output

```bash
python backend/scripts/slow_query_report.py --limit 20 --format json
```

### Custom database URL

```bash
python backend/scripts/slow_query_report.py \
  --database-url "postgresql+psycopg://user:pass@host:5432/dbname" \
  --format md
```

## Output safety

The report masks the query text by:

- Replacing string literals with `'?'`.
- Replacing numeric literals with `?`.
- Replacing dollar-quoted literals with `$$?$$`.
- Replacing bind parameter placeholders (e.g., `$1`) with `$?`.

This ensures the report does not reveal secrets, PII, or runtime parameters.
