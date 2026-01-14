from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.chat_threads.db_models import (
    ChatMessage,
    ChatParticipant,
    ChatThread,
    ChatThreadRead,
)
from app.domain.saas.db_models import Membership, MembershipRole, User
from app.domain.workers.db_models import Worker

ParticipantType = str

PARTICIPANT_ADMIN: ParticipantType = "admin"
PARTICIPANT_WORKER: ParticipantType = "worker"
THREAD_TYPE_DIRECT = "direct"
THREAD_TYPE_GROUP = "group"


@dataclass
class ThreadSummary:
    thread: ChatThread
    last_message: ChatMessage | None
    unread_count: int
    worker_id: int | None
    admin_membership_id: int | None


async def resolve_worker_for_identity(
    session: AsyncSession, *, org_id: uuid.UUID, name: str, team_id: int
) -> Worker:
    worker = await session.scalar(
        sa.select(Worker).where(
            Worker.org_id == org_id,
            Worker.name == name,
            Worker.team_id == team_id,
            Worker.is_active.is_(True),
        )
    )
    if worker is None:
        raise ValueError("Worker not found")
    return worker


async def resolve_admin_membership_id(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    admin_username: str,
    user_id: uuid.UUID | None = None,
) -> int:
    membership = None
    if user_id:
        membership = await session.scalar(
            sa.select(Membership).where(
                Membership.user_id == user_id,
                Membership.org_id == org_id,
                Membership.is_active.is_(True),
            )
        )
        if membership:
            return membership.membership_id

    email = admin_username if "@" in admin_username else f"{admin_username}@local"
    user = await session.scalar(sa.select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        session.add(user)
        await session.flush()
    membership = await session.scalar(
        sa.select(Membership).where(
            Membership.user_id == user.user_id,
            Membership.org_id == org_id,
        )
    )
    if membership is None:
        membership = Membership(
            org_id=org_id,
            user_id=user.user_id,
            role=MembershipRole.ADMIN,
            is_active=True,
        )
        session.add(membership)
        await session.flush()
    return membership.membership_id


async def get_or_create_direct_thread(
    session: AsyncSession, *, org_id: uuid.UUID, worker_id: int, admin_membership_id: int
) -> ChatThread:
    worker_participant = aliased(ChatParticipant)
    admin_participant = aliased(ChatParticipant)
    stmt = (
        sa.select(ChatThread)
        .join(worker_participant, worker_participant.thread_id == ChatThread.thread_id)
        .join(admin_participant, admin_participant.thread_id == ChatThread.thread_id)
        .where(
            ChatThread.org_id == org_id,
            ChatThread.thread_type == THREAD_TYPE_DIRECT,
            worker_participant.participant_type == PARTICIPANT_WORKER,
            worker_participant.worker_id == worker_id,
            admin_participant.participant_type == PARTICIPANT_ADMIN,
            admin_participant.admin_membership_id == admin_membership_id,
        )
    )
    existing = await session.scalar(stmt)
    if existing:
        return existing

    thread = ChatThread(org_id=org_id, thread_type=THREAD_TYPE_DIRECT)
    session.add(thread)
    await session.flush()
    session.add_all(
        [
            ChatParticipant(
                org_id=org_id,
                thread_id=thread.thread_id,
                participant_type=PARTICIPANT_WORKER,
                worker_id=worker_id,
            ),
            ChatParticipant(
                org_id=org_id,
                thread_id=thread.thread_id,
                participant_type=PARTICIPANT_ADMIN,
                admin_membership_id=admin_membership_id,
            ),
        ]
    )
    await session.flush()
    return thread


async def create_group_thread(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    worker_ids: list[int],
    admin_membership_id: int,
) -> ChatThread:
    if not worker_ids:
        raise ValueError("worker_ids required")

    thread = ChatThread(org_id=org_id, thread_type=THREAD_TYPE_GROUP)
    session.add(thread)
    await session.flush()
    participants = [
        ChatParticipant(
            org_id=org_id,
            thread_id=thread.thread_id,
            participant_type=PARTICIPANT_ADMIN,
            admin_membership_id=admin_membership_id,
        ),
        *[
            ChatParticipant(
                org_id=org_id,
                thread_id=thread.thread_id,
                participant_type=PARTICIPANT_WORKER,
                worker_id=worker_id,
            )
            for worker_id in worker_ids
        ],
    ]
    session.add_all(participants)
    await session.flush()
    return thread


async def list_threads(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    participant_type: ParticipantType,
    worker_id: int | None = None,
    admin_membership_id: int | None = None,
) -> list[ThreadSummary]:
    if participant_type == PARTICIPANT_WORKER and worker_id is None:
        raise ValueError("worker_id required")
    if participant_type == PARTICIPANT_ADMIN and admin_membership_id is None:
        raise ValueError("admin_membership_id required")

    participant_filter = (
        ChatParticipant.worker_id == worker_id
        if participant_type == PARTICIPANT_WORKER
        else ChatParticipant.admin_membership_id == admin_membership_id
    )
    stmt = (
        sa.select(ChatThread)
        .join(ChatParticipant, ChatParticipant.thread_id == ChatThread.thread_id)
        .where(
            ChatThread.org_id == org_id,
            ChatParticipant.participant_type == participant_type,
            participant_filter,
        )
        .order_by(ChatThread.updated_at.desc())
    )
    threads = (await session.execute(stmt)).scalars().all()

    summaries: list[ThreadSummary] = []
    for thread in threads:
        last_message = await session.scalar(
            sa.select(ChatMessage)
            .where(ChatMessage.thread_id == thread.thread_id, ChatMessage.org_id == org_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.message_id.desc())
            .limit(1)
        )

        participants = (
            await session.execute(
                sa.select(ChatParticipant).where(ChatParticipant.thread_id == thread.thread_id)
            )
        ).scalars().all()
        if thread.thread_type == THREAD_TYPE_GROUP:
            thread_worker_id = None
        else:
            thread_worker_id = next(
                (
                    participant.worker_id
                    for participant in participants
                    if participant.participant_type == PARTICIPANT_WORKER
                ),
                None,
            )
        thread_admin_id = next(
            (
                participant.admin_membership_id
                for participant in participants
                if participant.participant_type == PARTICIPANT_ADMIN
            ),
            None,
        )

        read_record = await session.scalar(
            sa.select(ChatThreadRead).where(
                ChatThreadRead.thread_id == thread.thread_id,
                ChatThreadRead.participant_type == participant_type,
                ChatThreadRead.worker_id == worker_id if participant_type == PARTICIPANT_WORKER else True,
                ChatThreadRead.admin_membership_id == admin_membership_id
                if participant_type == PARTICIPANT_ADMIN
                else True,
            )
        )
        unread_stmt = sa.select(sa.func.count()).where(
            ChatMessage.thread_id == thread.thread_id,
            ChatMessage.org_id == org_id,
        )
        if read_record and read_record.last_read_at:
            unread_stmt = unread_stmt.where(ChatMessage.created_at > read_record.last_read_at)

        if participant_type == PARTICIPANT_WORKER:
            unread_stmt = unread_stmt.where(
                sa.not_(
                    sa.and_(
                        ChatMessage.sender_type == PARTICIPANT_WORKER,
                        ChatMessage.worker_id == worker_id,
                    )
                )
            )
        else:
            unread_stmt = unread_stmt.where(
                sa.not_(
                    sa.and_(
                        ChatMessage.sender_type == PARTICIPANT_ADMIN,
                        ChatMessage.admin_membership_id == admin_membership_id,
                    )
                )
            )

        unread_count = int((await session.scalar(unread_stmt)) or 0)
        summaries.append(
            ThreadSummary(
                thread=thread,
                last_message=last_message,
                unread_count=unread_count,
                worker_id=thread_worker_id,
                admin_membership_id=thread_admin_id,
            )
        )
    return summaries


async def list_messages(
    session: AsyncSession, *, org_id: uuid.UUID, thread_id: uuid.UUID, limit: int = 200
) -> list[ChatMessage]:
    stmt = (
        sa.select(ChatMessage)
        .where(ChatMessage.thread_id == thread_id, ChatMessage.org_id == org_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.message_id.asc())
        .limit(limit)
    )
    return (await session.execute(stmt)).scalars().all()


async def list_messages_since(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    thread_id: uuid.UUID,
    since: datetime,
    since_message_id: int = 0,
    limit: int = 200,
) -> list[ChatMessage]:
    stmt = (
        sa.select(ChatMessage)
        .where(
            ChatMessage.thread_id == thread_id,
            ChatMessage.org_id == org_id,
            sa.or_(
                ChatMessage.created_at > since,
                sa.and_(ChatMessage.created_at == since, ChatMessage.message_id > since_message_id),
            ),
        )
        .order_by(ChatMessage.created_at.asc(), ChatMessage.message_id.asc())
        .limit(limit)
    )
    return (await session.execute(stmt)).scalars().all()


async def count_unread_messages(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    participant_type: ParticipantType,
    worker_id: int | None = None,
    admin_membership_id: int | None = None,
) -> int:
    summaries = await list_threads(
        session,
        org_id=org_id,
        participant_type=participant_type,
        worker_id=worker_id,
        admin_membership_id=admin_membership_id,
    )
    return sum(summary.unread_count for summary in summaries)


async def ensure_participant(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    thread_id: uuid.UUID,
    participant_type: ParticipantType,
    worker_id: int | None = None,
    admin_membership_id: int | None = None,
) -> ChatThread:
    thread = await session.get(ChatThread, thread_id)
    if thread is None:
        raise LookupError("Thread not found")
    if thread.org_id != org_id:
        raise PermissionError("Cross-org thread access forbidden")

    participant_stmt = sa.select(ChatParticipant).where(
        ChatParticipant.thread_id == thread_id,
        ChatParticipant.participant_type == participant_type,
    )
    if participant_type == PARTICIPANT_WORKER:
        participant_stmt = participant_stmt.where(ChatParticipant.worker_id == worker_id)
    else:
        participant_stmt = participant_stmt.where(ChatParticipant.admin_membership_id == admin_membership_id)
    participant = await session.scalar(participant_stmt)
    if participant is None:
        raise PermissionError("Participant not found")
    return thread


async def send_message(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    thread: ChatThread,
    sender_type: ParticipantType,
    body: str,
    worker_id: int | None = None,
    admin_membership_id: int | None = None,
) -> ChatMessage:
    now = datetime.now(timezone.utc)
    message = ChatMessage(
        org_id=org_id,
        thread_id=thread.thread_id,
        sender_type=sender_type,
        worker_id=worker_id,
        admin_membership_id=admin_membership_id,
        body=body,
    )
    thread.updated_at = now
    session.add(message)
    session.add(thread)
    await session.flush()
    return message


async def mark_thread_read(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    thread_id: uuid.UUID,
    participant_type: ParticipantType,
    worker_id: int | None = None,
    admin_membership_id: int | None = None,
) -> ChatThreadRead:
    now = datetime.now(timezone.utc)
    stmt = sa.select(ChatThreadRead).where(
        ChatThreadRead.thread_id == thread_id,
        ChatThreadRead.participant_type == participant_type,
        ChatThreadRead.worker_id == worker_id if participant_type == PARTICIPANT_WORKER else True,
        ChatThreadRead.admin_membership_id == admin_membership_id
        if participant_type == PARTICIPANT_ADMIN
        else True,
    )
    record = await session.scalar(stmt)
    if record is None:
        record = ChatThreadRead(
            org_id=org_id,
            thread_id=thread_id,
            participant_type=participant_type,
            worker_id=worker_id,
            admin_membership_id=admin_membership_id,
            last_read_at=now,
        )
        session.add(record)
    else:
        record.last_read_at = now
        session.add(record)
    await session.flush()
    return record
