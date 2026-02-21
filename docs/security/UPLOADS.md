# Upload Security — Streaming, Size Limits, and Content-Type Enforcement

This document describes how the API handles file uploads securely to prevent
Denial-of-Service attacks and unwanted file types.

---

## Overview

All file uploads (e.g., order photos via `POST /v1/orders/{order_id}/photos`) are
processed using **streaming I/O**.  No endpoint loads an entire upload payload into
server memory before validation and persistence.

---

## Threat: Unbuffered Full-Body Reads (DoS)

Without streaming, a single request containing a multi-gigabyte payload can exhaust
server memory and crash the process.  The previous implementation called
`await file.read()` before saving — this loaded the complete body into RAM.

**Fixed in:** Epic 1 / PR-01.

---

## How Uploads Are Handled

### 1. Early Content-Type Validation (before any I/O)

The declared `Content-Type` of the uploaded file is checked against the allow-list
**before any bytes are read from the network**.  Disallowed types are rejected with
`415 Unsupported Media Type`.

**Allow-list (default):** `image/jpeg`, `image/png`, `image/webp`

Configurable via:

```
ORDER_PHOTO_ALLOWED_MIMES=image/jpeg,image/png,image/webp
```

### 2. Early Size Rejection via Content-Length Header

If the client sends a `Content-Length` header (all standard HTTP/1.1 clients do), its
value is compared against `MAX_UPLOAD_BYTES` **before reading any body data**.  Requests
where `Content-Length` exceeds the limit are rejected immediately with
`413 Request Entity Too Large`.

> **Note:** `Content-Length` for a multipart request represents the total body size
> (including boundaries and form fields), not just the file payload.  It therefore
> acts as a conservative upper-bound check.  The per-chunk enforcement below provides
> accurate byte-level gating regardless.

It is **not** used as the file-size value for storage-quota accounting. Quota is
finalized from the actual streamed file bytes written.

### 3. Per-Chunk Streaming Enforcement

The upload body is consumed in **64 KB chunks**.  A running byte counter is maintained
during streaming; if it exceeds `MAX_UPLOAD_BYTES` at any point the upload is aborted
with `413 Request Entity Too Large` and any partially written file is deleted.

This enforcement applies even when no `Content-Length` header is present (e.g.,
chunked transfer encoding).

### 4. Partial File Cleanup

On any failure (size exceeded, storage error, database error), the partially-written
file is deleted from the storage backend and any pending storage-quota reservation is
released before the HTTP error response is returned.

---

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `ORDER_PHOTO_MAX_BYTES` | `10485760` (10 MiB) | Maximum allowed upload size in bytes |
| `ORDER_PHOTO_ALLOWED_MIMES` | `image/jpeg,image/png,image/webp` | Comma-separated allow-list of MIME types |
| `ORDER_STORAGE_BACKEND` | `local` | Storage destination (`local`, `r2`, `cloudflare_images`) |

---

## HTTP Error Responses

| Status | Condition |
|---|---|
| `413 Request Entity Too Large` | Upload body exceeds `ORDER_PHOTO_MAX_BYTES` |
| `415 Unsupported Media Type` | Declared `Content-Type` is not in the allow-list |
| `403 Forbidden` | Photo consent not granted or admin permission missing |
| `409 Conflict` | Organisation storage quota exceeded |

---

## Storage Backends

### Local Disk (`ORDER_STORAGE_BACKEND=local`)

Files are written to `ORDER_UPLOAD_ROOT/<org_id>/<order_id>/<photo_id><ext>`.
Temporary state is never used; the file is written directly to its final path in
chunks.  On failure, the file is unlinked.

### Cloudflare R2 / S3 (`r2`, `s3`)

The upload body is streamed via the S3 `put_object` API.  A secondary hard limit
(`max_payload_bytes`) is enforced inside the storage backend as a defence-in-depth
measure.

### Cloudflare Images (`cloudflare_images`, `cf_images`)

The upload body is buffered internally by the Cloudflare Images backend before being
forwarded to the Cloudflare API.  The `max_payload_bytes` limit is enforced before
any network call is made.

---

## Testing

The security behaviour is covered by `backend/tests/test_upload_streaming.py`:

| Test | Purpose |
|---|---|
| `test_upload_valid_small_image_returns_201` | Happy path — valid upload succeeds |
| `test_upload_oversized_file_returns_413` | Size limit enforced via Content-Length |
| `test_upload_invalid_content_type_returns_415` | Non-image MIME type rejected |
| `test_upload_pdf_content_type_returns_415` | PDF MIME type rejected |
| `test_upload_does_not_full_read_file` | **Streaming guard** — asserts `file.read()` is never called without an explicit chunk size; catches any regression that re-introduces a full-buffer read |
| `test_upload_png_allowed` | PNG MIME type accepted |
| `test_upload_webp_allowed` | WebP MIME type accepted |

Run with:

```bash
cd backend
pytest tests/test_upload_streaming.py -v
```
