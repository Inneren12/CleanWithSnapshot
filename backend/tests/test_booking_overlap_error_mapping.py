import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.bookings.service import is_booking_overlap_integrity_error


class _Diag:
    def __init__(self, constraint_name: str | None):
        self.constraint_name = constraint_name


class _PgError:
    def __init__(self, constraint_name: str | None, sqlstate: str | None = None):
        self.diag = _Diag(constraint_name)
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("constraint", "sqlstate", "expected"),
    [
        ("uq_bookings_active_slot", None, True),
        ("bookings_team_time_no_overlap", "23P01", True),
        ("other_constraint", "23505", False),
    ],
)
def test_is_booking_overlap_integrity_error_uses_pg_diagnostics(
    constraint: str,
    sqlstate: str | None,
    expected: bool,
):
    exc = IntegrityError("insert", {}, _PgError(constraint, sqlstate))
    assert is_booking_overlap_integrity_error(exc) is expected


def test_is_booking_overlap_integrity_error_uses_message_fallback():
    exc = IntegrityError("insert", {}, Exception("violates constraint uq_bookings_active_slot"))
    assert is_booking_overlap_integrity_error(exc) is True


def test_is_booking_overlap_integrity_error_detects_sqlite_unique_fallback():
    exc = IntegrityError(
        "insert",
        {},
        Exception("UNIQUE constraint failed: bookings.org_id, bookings.team_id, bookings.starts_at"),
    )
    assert is_booking_overlap_integrity_error(exc) is True
