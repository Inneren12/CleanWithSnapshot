import uuid

import pytest
from sqlalchemy import select

from app.domain.leads.db_models import Lead
from app.domain.outbox.db_models import OutboxEvent

DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _lead_payload() -> dict:
    return {
        "name": "Org Lead",
        "phone": "555-0101",
        "email": "org@example.com",
        "postal_code": "T5A",
        "address": "1 Test St",
        "preferred_dates": ["Mon"],
        "structured_inputs": {"beds": 1, "baths": 1, "cleaning_type": "standard"},
        "estimate_snapshot": {
            "price_cents": 12000,
            "subtotal_cents": 12000,
            "tax_cents": 0,
            "pricing_config_version": "v1",
            "config_hash": "hash",
            "line_items": [],
        },
        "pricing_config_version": "v1",
        "config_hash": "hash",
    }


@pytest.mark.anyio
async def test_org_id_filters_do_not_error(async_session_maker):
    async with async_session_maker() as session:
        lead = Lead(org_id=DEFAULT_ORG_ID, **_lead_payload())
        session.add(lead)

        outbox = OutboxEvent(
            org_id=DEFAULT_ORG_ID,
            kind="test",
            payload_json={"hello": "world"},
            dedupe_key="org-id-smoke",
            status="pending",
            attempts=0,
        )
        session.add(outbox)
        await session.commit()

        lead_result = await session.execute(
            select(Lead.lead_id).where(Lead.org_id == DEFAULT_ORG_ID)
        )
        outbox_result = await session.execute(
            select(OutboxEvent.event_id).where(OutboxEvent.org_id == DEFAULT_ORG_ID)
        )

        assert lead_result.scalar_one_or_none() is not None
        assert outbox_result.scalar_one_or_none() is not None
