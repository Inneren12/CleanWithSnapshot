import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.bookings.service import is_active_slot_conflict, is_booking_overlap_integrity_error


class _Diag:
    def __init__(self, constraint_name: str | None):
        self.constraint_name = constraint_name


class _PgError:
    def __init__(
        self,
        constraint_name: str | None,
        sqlstate: str | None = None,
        message: str = "",
    ):
        self.diag = _Diag(constraint_name)
        self.sqlstate = sqlstate
        self.message = message

    def __str__(self) -> str:
        return self.message


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


def test_is_active_slot_conflict_detects_postgres_duplicate_key_column_fallback():
    message = (
        'duplicate key value violates unique constraint "some_other_name" '
        "Key (org_id, team_id, starts_at)=(org_1, team_1, 2026-02-22 09:00:00+00) already exists."
    )
    exc = IntegrityError("insert", {}, _PgError(constraint_name=None, sqlstate="23505", message=message))

    assert is_active_slot_conflict(exc) is True


def test_is_active_slot_conflict_does_not_match_unrelated_postgres_unique_violation():
    message = (
        'duplicate key value violates unique constraint "uq_users_email" '
        "Key (email)=(demo@example.com) already exists."
    )
    exc = IntegrityError("insert", {}, _PgError(constraint_name=None, sqlstate="23505", message=message))

    assert is_active_slot_conflict(exc) is False
