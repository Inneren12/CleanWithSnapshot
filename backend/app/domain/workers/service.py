import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking, BookingWorker
from app.domain.workers.db_models import Worker, WorkerReview

logger = logging.getLogger(__name__)


async def record_worker_review(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    booking_id: str,
    worker_id: int,
    rating: int,
    comment: str | None = None,
) -> WorkerReview:
    if rating < 1 or rating > 5:
        raise ValueError("rating_out_of_range")

    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise ValueError("worker_not_found")

    booking_stmt = (
        select(Booking)
        .outerjoin(BookingWorker, BookingWorker.booking_id == Booking.booking_id)
        .where(
            Booking.booking_id == booking_id,
            Booking.org_id == org_id,
            or_(Booking.assigned_worker_id == worker_id, BookingWorker.worker_id == worker_id),
        )
    )
    booking = (await session.execute(booking_stmt)).scalar_one_or_none()
    if booking is None:
        raise ValueError("booking_not_found")

    review = WorkerReview(
        org_id=org_id,
        booking_id=booking.booking_id,
        worker_id=worker.worker_id,
        rating=rating,
        comment=comment,
    )
    session.add(review)

    current_count = worker.rating_count or 0
    current_avg = worker.rating_avg or 0.0
    new_count = current_count + 1
    worker.rating_count = new_count
    worker.rating_avg = (current_avg * current_count + rating) / new_count

    logger.info(
        "worker_review_recorded",
        extra={
            "extra": {
                "org_id": str(org_id),
                "booking_id": booking.booking_id,
                "worker_id": worker.worker_id,
                "rating": rating,
            }
        },
    )
    return review
