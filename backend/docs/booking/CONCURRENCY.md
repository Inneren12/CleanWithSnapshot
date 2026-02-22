# Booking concurrency control

To prevent double-booking under concurrent requests for the same team and start time,
booking creation now uses a database-enforced uniqueness guarantee for active bookings.

## Strategy

- Keep the existing application-level availability check (`is_slot_available`) for UX-friendly pre-validation.
- Keep the existing **partial unique index** on `(org_id, team_id, starts_at)` for exact-same-start collisions.
- Add a PostgreSQL-only **exclusion constraint** using `EXCLUDE USING gist` with
  `tstzrange(starts_at, starts_at + duration_minutes * interval '1 minute', '[)')`
  so active bookings for the same `team_id` cannot overlap in time.
- On insert race (exact-match or overlap), the database rejects the second+ insert.
  The service catches the corresponding integrity error and maps it to the existing
  domain conflict message, so the API continues to return **409 Conflict**.

## Why this is safe

- The uniqueness check happens atomically inside the DB engine and is race-safe.
- PostgreSQL gets full overlap prevention via exclusion constraints.
- SQLite test runs remain valid because the migration is guarded to no-op outside PostgreSQL.

## Test coverage

`tests/test_slots.py::test_booking_endpoint_prevents_double_booking_under_concurrency`
issues 5 concurrent booking requests for the same slot and asserts exactly:

- 1 request returns `201 Created`
- 4 requests return `409 Conflict`
