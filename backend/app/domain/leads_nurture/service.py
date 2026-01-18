from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.leads.db_models import Lead
from app.domain.leads_nurture import schemas
from app.domain.leads_nurture.db_models import (
    NurtureCampaign,
    NurtureEnrollment,
    NurtureStep,
    NurtureStepLog,
)
from app.domain.leads_nurture.statuses import NurtureEnrollmentStatus, NurtureStepLogStatus


def build_idempotency_key(enrollment_id: uuid.UUID, step_index: int) -> str:
    return f"{enrollment_id}:{step_index}"


async def list_campaigns(session: AsyncSession, org_id: uuid.UUID) -> list[NurtureCampaign]:
    result = await session.execute(
        sa.select(NurtureCampaign)
        .where(NurtureCampaign.org_id == org_id)
        .order_by(NurtureCampaign.created_at.desc())
    )
    return list(result.scalars())


async def get_campaign(
    session: AsyncSession, org_id: uuid.UUID, campaign_id: uuid.UUID
) -> NurtureCampaign | None:
    return await session.scalar(
        sa.select(NurtureCampaign).where(
            NurtureCampaign.org_id == org_id,
            NurtureCampaign.campaign_id == campaign_id,
        )
    )


async def get_campaign_by_key(
    session: AsyncSession, org_id: uuid.UUID, key: str
) -> NurtureCampaign | None:
    return await session.scalar(
        sa.select(NurtureCampaign).where(
            NurtureCampaign.org_id == org_id,
            NurtureCampaign.key == key,
        )
    )


async def create_campaign(
    session: AsyncSession, org_id: uuid.UUID, payload: schemas.NurtureCampaignCreateRequest
) -> NurtureCampaign:
    model = NurtureCampaign(
        org_id=org_id,
        key=payload.key,
        name=payload.name,
        enabled=payload.enabled,
    )
    session.add(model)
    await session.flush()
    return model


async def update_campaign(
    session: AsyncSession,
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    payload: schemas.NurtureCampaignUpdateRequest,
) -> NurtureCampaign | None:
    model = await get_campaign(session, org_id, campaign_id)
    if not model:
        return None
    if payload.key is not None:
        model.key = payload.key
    if payload.name is not None:
        model.name = payload.name
    if payload.enabled is not None:
        model.enabled = payload.enabled
    await session.flush()
    return model


async def delete_campaign(
    session: AsyncSession, org_id: uuid.UUID, campaign_id: uuid.UUID
) -> bool:
    model = await get_campaign(session, org_id, campaign_id)
    if not model:
        return False
    await session.delete(model)
    return True


async def list_steps(
    session: AsyncSession, org_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[NurtureStep]:
    result = await session.execute(
        sa.select(NurtureStep)
        .where(
            NurtureStep.org_id == org_id,
            NurtureStep.campaign_id == campaign_id,
        )
        .order_by(NurtureStep.step_index)
    )
    return list(result.scalars())


async def get_step(
    session: AsyncSession,
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    step_id: uuid.UUID,
) -> NurtureStep | None:
    return await session.scalar(
        sa.select(NurtureStep).where(
            NurtureStep.org_id == org_id,
            NurtureStep.campaign_id == campaign_id,
            NurtureStep.step_id == step_id,
        )
    )


async def create_step(
    session: AsyncSession,
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    payload: schemas.NurtureStepCreateRequest,
) -> NurtureStep | None:
    campaign = await get_campaign(session, org_id, campaign_id)
    if not campaign:
        return None
    model = NurtureStep(
        org_id=org_id,
        campaign_id=campaign_id,
        step_index=payload.step_index,
        delay_hours=payload.delay_hours,
        channel=payload.channel,
        template_key=payload.template_key,
        payload_json=payload.payload_json,
        active=payload.active,
    )
    session.add(model)
    await session.flush()
    return model


async def update_step(
    session: AsyncSession,
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    step_id: uuid.UUID,
    payload: schemas.NurtureStepUpdateRequest,
) -> NurtureStep | None:
    model = await get_step(session, org_id, campaign_id, step_id)
    if not model:
        return None
    if payload.step_index is not None:
        model.step_index = payload.step_index
    if payload.delay_hours is not None:
        model.delay_hours = payload.delay_hours
    if payload.channel is not None:
        model.channel = payload.channel
    if payload.template_key is not None:
        model.template_key = payload.template_key
    if payload.payload_json is not None:
        model.payload_json = payload.payload_json
    if payload.active is not None:
        model.active = payload.active
    await session.flush()
    return model


async def delete_step(
    session: AsyncSession,
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    step_id: uuid.UUID,
) -> bool:
    model = await get_step(session, org_id, campaign_id, step_id)
    if not model:
        return False
    await session.delete(model)
    return True


async def enroll_lead(
    session: AsyncSession,
    org_id: uuid.UUID,
    lead_id: str,
    payload: schemas.NurtureEnrollmentCreateRequest,
) -> tuple[NurtureEnrollment | None, list[NurtureStepLog], str | None]:
    lead = await session.scalar(
        sa.select(Lead).where(Lead.lead_id == lead_id, Lead.org_id == org_id)
    )
    if not lead:
        return None, [], "lead"
    campaign = await get_campaign_by_key(session, org_id, payload.campaign_key)
    if not campaign:
        return None, [], "campaign"

    enrolled_at = datetime.now(timezone.utc)
    enrollment = NurtureEnrollment(
        org_id=org_id,
        lead_id=lead_id,
        campaign_id=campaign.campaign_id,
        enrolled_at=enrolled_at,
        status=NurtureEnrollmentStatus.active,
    )
    session.add(enrollment)
    await session.flush()

    steps = await session.execute(
        sa.select(NurtureStep)
        .where(
            NurtureStep.org_id == org_id,
            NurtureStep.campaign_id == campaign.campaign_id,
            NurtureStep.active.is_(True),
        )
        .order_by(NurtureStep.step_index)
    )
    logs: list[NurtureStepLog] = []
    for step in steps.scalars():
        planned_at = enrolled_at + timedelta(hours=step.delay_hours)
        log = NurtureStepLog(
            org_id=org_id,
            enrollment_id=enrollment.enrollment_id,
            step_index=step.step_index,
            planned_at=planned_at,
            status=NurtureStepLogStatus.planned,
            idempotency_key=build_idempotency_key(enrollment.enrollment_id, step.step_index),
        )
        session.add(log)
        logs.append(log)
    await session.flush()
    return enrollment, logs, None


async def list_enrollments_for_lead(
    session: AsyncSession, org_id: uuid.UUID, lead_id: str
) -> list[NurtureEnrollment]:
    result = await session.execute(
        sa.select(NurtureEnrollment)
        .where(
            NurtureEnrollment.org_id == org_id,
            NurtureEnrollment.lead_id == lead_id,
        )
        .order_by(NurtureEnrollment.enrolled_at.desc())
    )
    return list(result.scalars())


async def list_logs_for_enrollments(
    session: AsyncSession, org_id: uuid.UUID, enrollment_ids: list[uuid.UUID]
) -> list[NurtureStepLog]:
    if not enrollment_ids:
        return []
    result = await session.execute(
        sa.select(NurtureStepLog)
        .where(
            NurtureStepLog.org_id == org_id,
            NurtureStepLog.enrollment_id.in_(enrollment_ids),
        )
        .order_by(NurtureStepLog.planned_at, NurtureStepLog.step_index)
    )
    return list(result.scalars())


async def plan_due_steps(
    session: AsyncSession,
    org_id: uuid.UUID,
    as_of: datetime,
) -> list[tuple[NurtureStepLog, NurtureEnrollment, NurtureCampaign, NurtureStep]]:
    stmt = (
        sa.select(NurtureStepLog, NurtureEnrollment, NurtureCampaign, NurtureStep)
        .join(NurtureEnrollment, NurtureStepLog.enrollment_id == NurtureEnrollment.enrollment_id)
        .join(
            NurtureCampaign,
            sa.and_(
                NurtureEnrollment.campaign_id == NurtureCampaign.campaign_id,
                NurtureCampaign.org_id == org_id,
            ),
        )
        .join(
            NurtureStep,
            sa.and_(
                NurtureStep.campaign_id == NurtureCampaign.campaign_id,
                NurtureStep.step_index == NurtureStepLog.step_index,
                NurtureStep.org_id == org_id,
            ),
        )
        .where(
            NurtureStepLog.org_id == org_id,
            NurtureStepLog.status == NurtureStepLogStatus.planned,
            NurtureStepLog.planned_at <= as_of,
            NurtureEnrollment.status == NurtureEnrollmentStatus.active,
            NurtureStep.active.is_(True),
        )
        .order_by(NurtureStepLog.planned_at, NurtureStepLog.step_index)
    )
    result = await session.execute(stmt)
    return list(result.all())
