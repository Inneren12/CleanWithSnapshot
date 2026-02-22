# Booking concurrency control

To prevent double-booking under concurrent requests for the same team and start time,
booking creation now uses a database-enforced uniqueness guarantee for active bookings.

## Strategy

- Keep the existing application-level availability check (`is_slot_available`) for UX-friendly pre-validation.
- Add a **partial unique index** on `(org_id, team_id, starts_at)` for rows where `status IN ('PENDING', 'CONFIRMED')`.
- On insert race, the database rejects the second+ insert. The service catches that
  specific integrity error and maps it to the existing domain conflict message,
  so the API continues to return **409 Conflict**.

## Why this is safe

- The uniqueness check happens atomically inside the DB engine and is race-safe.
- It works with PostgreSQL (production target) and SQLite (test suite) via dialect-specific
  filtered-index support in SQLAlchemy/Alembic.

## Test coverage

`tests/test_slots.py::test_booking_endpoint_prevents_double_booking_under_concurrency`
issues 5 concurrent booking requests for the same slot and asserts exactly:

- 1 request returns `201 Created`
- 4 requests return `409 Conflict`
