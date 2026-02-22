# Cursor Pagination

The data-rights export list endpoint uses seek pagination with a stable `(created_at, id)` sort key.

## Endpoint

`GET /v1/data-rights/exports`

### Query params

- `page_size` (default `50`, max `200`)
- `cursor` (opaque, optional)
- `offset` (deprecated; accepted for backward compatibility and ignored)

### Ordering

Rows are ordered by:

1. `created_at DESC`
2. `export_id DESC`

This deterministic ordering prevents duplicates/skips while paging.

### Response fields

- `items`: page of exports
- `total`: filtered total count
- `next_cursor`: cursor for the next page, or `null` if no more rows
- `prev_cursor`: optional cursor representing the first item in the current page

## Why cursor pagination

- avoids deep-page `OFFSET` scans
- stable page traversal under concurrent inserts
- supports efficient index-backed seeks
