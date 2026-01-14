from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.message_templates.db_models import MessageTemplate


async def list_templates(session: AsyncSession, *, org_id: uuid.UUID) -> list[MessageTemplate]:
    return (
        (
            await session.execute(
                sa.select(MessageTemplate)
                .where(MessageTemplate.org_id == org_id)
                .order_by(MessageTemplate.name.asc())
            )
        )
        .scalars()
        .all()
    )


async def get_template(
    session: AsyncSession, *, org_id: uuid.UUID, template_id: int
) -> MessageTemplate | None:
    return await session.scalar(
        sa.select(MessageTemplate).where(
            MessageTemplate.org_id == org_id, MessageTemplate.template_id == template_id
        )
    )


async def create_template(
    session: AsyncSession, *, org_id: uuid.UUID, name: str, body: str
) -> MessageTemplate:
    template = MessageTemplate(org_id=org_id, name=name, body=body)
    session.add(template)
    await session.flush()
    return template


async def update_template(
    session: AsyncSession, *, org_id: uuid.UUID, template_id: int, name: str, body: str
) -> MessageTemplate | None:
    template = await get_template(session, org_id=org_id, template_id=template_id)
    if template is None:
        return None
    template.name = name
    template.body = body
    session.add(template)
    await session.flush()
    return template


async def delete_template(
    session: AsyncSession, *, org_id: uuid.UUID, template_id: int
) -> bool:
    template = await get_template(session, org_id=org_id, template_id=template_id)
    if template is None:
        return False
    await session.delete(template)
    await session.flush()
    return True
