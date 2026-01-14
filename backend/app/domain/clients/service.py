import base64
import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.clients.db_models import ClientUser
from app.settings import settings

logger = logging.getLogger(__name__)


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


@dataclass
class TokenResult:
    email: str
    client_id: str
    issued_at: datetime
    expires_at: datetime
    org_id: uuid.UUID


@dataclass
class ChurnAssessment:
    risk_band: str
    score: int
    reasons: list[str]


def evaluate_churn(
    *,
    days_since_last_completed: int | None,
    avg_gap_days: float | None,
    complaint_count: int,
    avg_rating: float | None,
    low_rating_count: int,
) -> ChurnAssessment:
    reasons: list[str] = []
    score = 0

    if days_since_last_completed is not None:
        if days_since_last_completed >= settings.client_churn_days_since_last_high:
            score += 3
            reasons.append(f"No booking in {days_since_last_completed}d")
        elif days_since_last_completed >= settings.client_churn_days_since_last_medium:
            score += 1
            reasons.append(f"No booking in {days_since_last_completed}d")

        if avg_gap_days is not None and avg_gap_days > 0:
            if days_since_last_completed >= avg_gap_days * settings.client_churn_avg_gap_multiplier_high:
                score += 2
                reasons.append(
                    "Booking gap {gap}d vs avg {avg:.1f}d".format(
                        gap=days_since_last_completed,
                        avg=avg_gap_days,
                    )
                )
            elif days_since_last_completed >= avg_gap_days * settings.client_churn_avg_gap_multiplier_medium:
                score += 1
                reasons.append(
                    "Booking gap {gap}d vs avg {avg:.1f}d".format(
                        gap=days_since_last_completed,
                        avg=avg_gap_days,
                    )
                )

    if complaint_count >= settings.client_risk_complaints_threshold:
        score += 1
        reasons.append(
            f"Complaints last {settings.client_risk_complaints_window_days}d"
        )

    low_rating_flag = (
        avg_rating is not None and avg_rating <= settings.client_risk_avg_rating_threshold
    ) or (low_rating_count >= settings.client_risk_low_rating_count_threshold)
    if low_rating_flag:
        score += 1
        reasons.append(f"Low ratings last {settings.client_risk_feedback_window_days}d")

    if score >= settings.client_churn_score_high:
        band = "HIGH"
    elif score >= settings.client_churn_score_medium:
        band = "MEDIUM"
    else:
        band = "LOW"

    return ChurnAssessment(risk_band=band, score=score, reasons=reasons)


def issue_magic_token(
    email: str,
    client_id: str,
    *,
    secret: str,
    ttl_minutes: int,
    issued_at: datetime | None = None,
    org_id: uuid.UUID | None = None,
) -> str:
    now = issued_at or datetime.now(timezone.utc)
    org = org_id or settings.default_org_id
    payload = {
        "email": email.lower(),
        "client_id": client_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
        "org_id": str(org),
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return f"{_b64_encode(body)}.{_b64_encode(signature)}"


def verify_magic_token(token: str, *, secret: str) -> TokenResult:
    try:
        body_b64, sig_b64 = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("invalid_token_format") from exc

    body = _b64_decode(body_b64)
    expected_sig = _b64_encode(hmac.new(secret.encode(), body, hashlib.sha256).digest())
    if not hmac.compare_digest(expected_sig, sig_b64):
        raise ValueError("invalid_token_signature")

    payload = json.loads(body.decode())
    issued_at = datetime.fromtimestamp(payload.get("iat", 0), tz=timezone.utc)
    expires_at = datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise ValueError("token_expired")

    try:
        org_id = uuid.UUID(payload.get("org_id"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("token_invalid_org") from exc

    return TokenResult(
        email=payload["email"],
        client_id=payload["client_id"],
        issued_at=issued_at,
        expires_at=expires_at,
        org_id=org_id,
    )


async def get_or_create_client(
    session: AsyncSession, email: str, name: str | None = None, commit: bool = True
) -> ClientUser:
    normalized = email.lower().strip()
    stmt = select(ClientUser).where(func.lower(ClientUser.email) == normalized)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        return user

    user = ClientUser(email=normalized, name=name)
    session.add(user)
    if commit:
        await session.commit()
        await session.refresh(user)
    else:
        await session.flush()
    return user


async def attach_client_to_orders(session: AsyncSession, client: ClientUser) -> None:
    from app.domain.bookings.db_models import Booking  # Imported lazily to avoid cycle
    from app.domain.leads.db_models import Lead

    stmt = (
        update(Booking)
        .where(Booking.client_id.is_(None))
        .where(Booking.lead_id.is_not(None))
        .where(
            Booking.lead_id.in_(
                select(Lead.lead_id).where(func.lower(Lead.email) == client.email.lower())
            )
        )
        .values(client_id=client.client_id)
    )
    await session.execute(stmt)
    await session.commit()
