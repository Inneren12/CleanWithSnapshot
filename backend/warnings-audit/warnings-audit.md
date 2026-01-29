# Warnings Audit Report

Generated: 2026-01-29T09:01:24.772552+00:00

## Summary

| Metric | Count |
|--------|-------|
| Total warnings | 2 |
| Unique signatures | 1 |
| Our warnings | 0 |
| Third-party warnings | 2 |
| High-risk warnings | 0 |
| Filtered noise | 0 |

## Warning Categories

| Category | Count |
|----------|-------|
| ResourceWarning | 2 |

## Top Warning Sources (by file)

| File | Count |
|------|-------|
| /root/.pyenv/versions/3.11.14/lib/python3.11/asyncio/base_events.py | 2 |

## Third-Party Warnings (Top 20)

| Module | Category | Message | Count |
|--------|----------|---------|-------|
| base_events | ResourceWarning | unclosed event loop <_UnixSelectorEventL... | 2 |

## CI Gate Status

- PytestRemovedIn9Warning: 0 PASS
- RuntimeWarning (unawaited coroutine): 0 PASS
- SQLAlchemy warnings (our code): 0 PASS
