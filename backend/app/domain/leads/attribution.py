from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.leads.db_models import LeadTouchpoint

ATTRIBUTION_FIRST_WEIGHT = 0.4
ATTRIBUTION_MIDDLE_WEIGHT = 0.3
ATTRIBUTION_LAST_WEIGHT = 0.3


@dataclass(frozen=True)
class AttributionWeights:
    first: float
    middle: float
    last: float


@dataclass(frozen=True)
class AttributionSplit:
    touchpoint: LeadTouchpoint
    label: str
    weight: float
    bucket: str


def normalize_occurred_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(tz=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def touchpoint_label(touchpoint: LeadTouchpoint) -> str:
    for candidate in (
        touchpoint.channel,
        touchpoint.source,
        touchpoint.medium,
        touchpoint.campaign,
        touchpoint.landing_page,
    ):
        if candidate:
            normalized = candidate.strip()
            if normalized:
                return normalized
    return "Unknown"


def build_path(touchpoints: list[LeadTouchpoint]) -> str:
    if not touchpoints:
        return ""
    labels = [touchpoint_label(tp) for tp in touchpoints]
    return " > ".join(labels)


def attribution_weights() -> AttributionWeights:
    return AttributionWeights(
        first=ATTRIBUTION_FIRST_WEIGHT,
        middle=ATTRIBUTION_MIDDLE_WEIGHT,
        last=ATTRIBUTION_LAST_WEIGHT,
    )


def build_split(touchpoints: list[LeadTouchpoint]) -> list[AttributionSplit]:
    if not touchpoints:
        return []
    if len(touchpoints) == 1:
        return [
            AttributionSplit(
                touchpoint=touchpoints[0],
                label=touchpoint_label(touchpoints[0]),
                weight=1.0,
                bucket="first",
            )
        ]
    if len(touchpoints) == 2:
        first, last = touchpoints
        return [
            AttributionSplit(
                touchpoint=first,
                label=touchpoint_label(first),
                weight=ATTRIBUTION_FIRST_WEIGHT,
                bucket="first",
            ),
            AttributionSplit(
                touchpoint=last,
                label=touchpoint_label(last),
                weight=ATTRIBUTION_MIDDLE_WEIGHT + ATTRIBUTION_LAST_WEIGHT,
                bucket="last",
            ),
        ]

    middle_count = max(len(touchpoints) - 2, 1)
    middle_weight = ATTRIBUTION_MIDDLE_WEIGHT / middle_count
    splits: list[AttributionSplit] = [
        AttributionSplit(
            touchpoint=touchpoints[0],
            label=touchpoint_label(touchpoints[0]),
            weight=ATTRIBUTION_FIRST_WEIGHT,
            bucket="first",
        )
    ]
    for touchpoint in touchpoints[1:-1]:
        splits.append(
            AttributionSplit(
                touchpoint=touchpoint,
                label=touchpoint_label(touchpoint),
                weight=middle_weight,
                bucket="middle",
            )
        )
    splits.append(
        AttributionSplit(
            touchpoint=touchpoints[-1],
            label=touchpoint_label(touchpoints[-1]),
            weight=ATTRIBUTION_LAST_WEIGHT,
            bucket="last",
        )
    )
    return splits
