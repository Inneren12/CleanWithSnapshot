from __future__ import annotations

from typing import Final, Iterable

LEAD_STATUS_NEW: Final[str] = "NEW"
LEAD_STATUS_CONTACTED: Final[str] = "CONTACTED"
LEAD_STATUS_QUOTED: Final[str] = "QUOTED"
LEAD_STATUS_WON: Final[str] = "WON"
LEAD_STATUS_LOST: Final[str] = "LOST"

LEAD_STATUSES: Final[tuple[str, ...]] = (
    LEAD_STATUS_NEW,
    LEAD_STATUS_CONTACTED,
    LEAD_STATUS_QUOTED,
    LEAD_STATUS_WON,
    LEAD_STATUS_LOST,
)

QUOTE_STATUS_DRAFT: Final[str] = "DRAFT"
QUOTE_STATUS_SENT: Final[str] = "SENT"
QUOTE_STATUS_EXPIRED: Final[str] = "EXPIRED"
QUOTE_STATUS_ACCEPTED: Final[str] = "ACCEPTED"
QUOTE_STATUS_DECLINED: Final[str] = "DECLINED"

QUOTE_STATUSES: Final[tuple[str, ...]] = (
    QUOTE_STATUS_DRAFT,
    QUOTE_STATUS_SENT,
    QUOTE_STATUS_EXPIRED,
    QUOTE_STATUS_ACCEPTED,
    QUOTE_STATUS_DECLINED,
)

_ALLOWED_TRANSITIONS: Final[dict[str, set[str]]] = {
    LEAD_STATUS_NEW: {LEAD_STATUS_CONTACTED, LEAD_STATUS_QUOTED, LEAD_STATUS_LOST},
    LEAD_STATUS_CONTACTED: {LEAD_STATUS_QUOTED, LEAD_STATUS_WON, LEAD_STATUS_LOST},
    LEAD_STATUS_QUOTED: {LEAD_STATUS_WON, LEAD_STATUS_LOST},
    LEAD_STATUS_WON: set(),
    LEAD_STATUS_LOST: set(),
}


def is_valid_status(value: str) -> bool:
    return value in LEAD_STATUSES


def allowed_next_statuses(current: str) -> set[str]:
    return _ALLOWED_TRANSITIONS.get(current, set())


def assert_valid_transition(current: str, target: str) -> None:
    if not is_valid_status(target):
        raise ValueError(f"Unknown lead status: {target}")
    if current == target:
        return
    allowed = allowed_next_statuses(current)
    if not allowed:
        raise ValueError(f"Lead is already in terminal status: {current}")
    if target not in allowed:
        raise ValueError(f"Cannot transition lead from {current} to {target}")


def default_lead_status() -> str:
    return LEAD_STATUS_NEW


def is_valid_quote_status(value: str) -> bool:
    return value in QUOTE_STATUSES


def statuses_for_filter() -> Iterable[str]:
    return LEAD_STATUSES
