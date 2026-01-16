from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain.bookings.db_models import Booking
from app.domain.clients.db_models import ClientFeedback, ClientUser
from app.domain.quality import service as quality_service
from tests.conftest import DEFAULT_ORG_ID


@pytest.mark.anyio
async def test_rating_distribution_counts(async_session_maker):
    async with async_session_maker() as session:
        client = ClientUser(
            org_id=DEFAULT_ORG_ID,
            email="client@example.com",
            name="Client Example",
        )
        session.add(client)
        await session.flush()

        base_time = datetime(2024, 4, 10, 10, tzinfo=timezone.utc)
        ratings = [5, 4, 2]
        for offset, rating in enumerate(ratings):
            booking = Booking(
                org_id=DEFAULT_ORG_ID,
                client_id=client.client_id,
                team_id=1,
                starts_at=base_time + timedelta(days=offset),
                duration_minutes=90,
                status="DONE",
            )
            session.add(booking)
            await session.flush()
            feedback = ClientFeedback(
                org_id=DEFAULT_ORG_ID,
                client_id=client.client_id,
                booking_id=booking.booking_id,
                rating=rating,
                comment=None,
                created_at=base_time + timedelta(days=offset),
            )
            session.add(feedback)

        await session.commit()

        distribution, total, average = await quality_service.get_rating_distribution(
            session,
            org_id=DEFAULT_ORG_ID,
            from_date=date(2024, 4, 10),
            to_date=date(2024, 4, 11),
        )
        counts = {stars: count for stars, count in distribution}
        assert total == 2
        assert average == pytest.approx(4.5)
        assert counts.get(5) == 1
        assert counts.get(4) == 1
        assert 2 not in counts
