# Performance Tuning: Database Pool & Timeouts

This guide documents the Postgres pool/timeout knobs and how to tune them safely using load-test (k6) results and Postgres stats. The application reads these values from environment variables and applies them when creating the SQLAlchemy engine for Postgres.

## Knobs (env/config)

| Knob | Default | Description | Guardrails |
| --- | --- | --- | --- |
| `DATABASE_POOL_SIZE` | `5` | Baseline pool size used for steady-state traffic. | Must be ≥ 1. |
| `DATABASE_MAX_OVERFLOW` | `5` | Extra burst connections allowed over the pool size. | Must be ≥ 0. |
| `DATABASE_POOL_TIMEOUT_SECONDS` | `30` | How long to wait for a connection before timing out. | Must be ≥ 0. |
| `DATABASE_STATEMENT_TIMEOUT_MS` | `5000` | Postgres statement timeout enforced per connection (ms). `0` disables the timeout. | Must be ≥ 0. |

**Total potential connections** = `DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW`. Ensure this stays below the Postgres server limit and any managed database connection caps.

## Symptom → Knob → Expected Impact

| Symptom | Knob(s) to adjust | Expected impact | Cautions |
| --- | --- | --- | --- |
| Frequent `db_pool_timeout` warnings; k6 shows rising error rates at steady throughput. | Increase `DATABASE_POOL_SIZE` first; consider `DATABASE_MAX_OVERFLOW` for bursts. | Reduces timeouts and improves throughput under sustained load. | Raising pool sizes increases total DB connections; confirm Postgres connection limits and CPU headroom. |
| Timeouts only during brief traffic spikes; steady-state load is fine. | Increase `DATABASE_MAX_OVERFLOW`. | Absorbs short bursts without permanently increasing the pool. | Too much overflow can still exhaust DB connections during spikes. |
| Latency spikes but no pool timeouts; pg_stat shows long-running queries. | Lower `DATABASE_STATEMENT_TIMEOUT_MS` to protect latency SLOs. | Fails slow queries sooner, improving tail latency. | Too low may cause legitimate queries to fail under load; use pg_stat to identify slow SQL first. |
| Pool timeouts occur while long queries are running. | Increase `DATABASE_POOL_TIMEOUT_SECONDS` slightly while optimizing slow queries. | Gives requests more time to wait for a connection. | Masking slow queries can increase overall latency; tune queries in parallel. |

## Tuning workflow (pg_stat + k6)

1. **Capture a k6 baseline**
   - Run your k6 scenario at current load targets (p95/p99 latency, error rate, throughput).
   - Record `db_pool_timeout` warnings and application latency during the run.

2. **Inspect Postgres stats during the test**
   - **Connection pressure**:
     ```sql
     SELECT count(*) AS active_conns
     FROM pg_stat_activity
     WHERE state = 'active';
     ```
   - **Long-running queries**:
     ```sql
     SELECT pid, now() - query_start AS runtime, state, wait_event_type, wait_event, query
     FROM pg_stat_activity
     WHERE state = 'active'
     ORDER BY runtime DESC
     LIMIT 20;
     ```
   - **Top queries (if pg_stat_statements is enabled)**:
     ```sql
     SELECT query, calls, mean_exec_time, total_exec_time
     FROM pg_stat_statements
     ORDER BY total_exec_time DESC
     LIMIT 10;
     ```

3. **Tune one knob at a time**
   - Increase `DATABASE_POOL_SIZE` only if active connections stay near the pool size and timeouts appear in the logs during steady-state load.
   - Increase `DATABASE_MAX_OVERFLOW` if spikes (not sustained load) drive timeouts.
   - Adjust `DATABASE_STATEMENT_TIMEOUT_MS` after confirming which queries are slow; if needed, adjust SQL or add indexes before raising the timeout.
   - Adjust `DATABASE_POOL_TIMEOUT_SECONDS` only after verifying that the DB can handle the extra concurrent load; larger values can hide contention.

4. **Re-run k6 and compare**
   - Compare p95/p99 latency and error rates to the baseline.
   - Confirm `db_pool_timeout` warnings decline and Postgres connection counts remain within limits.

## Example tuning checklist

- ✅ k6 p95 latency within target after raising pool size.
- ✅ `db_pool_timeout` warnings drop to near-zero during steady load.
- ✅ Postgres connection count stays under server cap.
- ✅ Slow query list in pg_stat shrinks after indexing or query optimization.
