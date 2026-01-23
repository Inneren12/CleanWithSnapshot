# Performance baseline & regression checks

This repo stores a k6 baseline in `load-tests/baseline.json` and a comparison script in
`load-tests/compare_baseline.py`. The baseline captures expected p95/p99 latency, error rate,
and request throughput (RPS) per scenario.

## Baseline format

```json
{
  "version": 1,
  "scenarios": {
    "healthz": {
      "p95_ms": 500,
      "p99_ms": 800,
      "error_rate": 0.01,
      "rps": 1.0
    }
  }
}
```

- `p95_ms` / `p99_ms`: latency budget in milliseconds.
- `error_rate`: allowed failed request ratio (0.02 = 2%).
- `rps`: minimum acceptable requests-per-second.

## Running a comparison locally

1. Run a load test and export a summary JSON:

   ```bash
   k6 run --summary-export /tmp/healthz-summary.json load-tests/k6/healthz.js
   ```

2. Compare against the baseline:

   ```bash
   python load-tests/compare_baseline.py \
     --scenario healthz \
     --results /tmp/healthz-summary.json
   ```

The script prints a PASS/WARN/FAIL summary along with per-metric deltas. Use `--mode fail`
if you want regressions to exit non-zero.

## Updating the baseline

- Re-run k6 against your target environment.
- Review the summary JSON for p95/p99, error rate, and RPS.
- Update `load-tests/baseline.json` and keep a short note in the PR about the environment
  the baseline represents (staging, prod, etc.).
