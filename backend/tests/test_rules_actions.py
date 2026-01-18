import asyncio

import sqlalchemy as sa

from app.domain.notifications_center.db_models import NotificationEvent
from app.domain.rules import service as rules_service
from app.settings import settings


class StubEmailAdapter:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_email(self, recipient: str, subject: str, body: str, headers=None) -> bool:
        self.sent.append(
            {
                "recipient": recipient,
                "subject": subject,
                "body": body,
            }
        )
        return True


class StubCommunicationAdapter:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_sms(self, *, to_number: str, body: str):
        self.sent.append({"to_number": to_number, "body": body})

        class Result:
            status = "sent"
            error_code = None

        return Result()


def test_rules_actions_dry_run_no_external(async_session_maker):
    async def _run() -> None:
        original_email_mode = settings.email_mode
        original_sms_mode = settings.sms_mode
        settings.email_mode = "sendgrid"
        settings.sms_mode = "twilio"
        try:
            async with async_session_maker() as session:
                rule = await rules_service.create_rule(
                    session,
                    settings.default_org_id,
                    {
                        "name": "Dry Run Rule",
                        "enabled": True,
                        "dry_run": True,
                        "trigger_type": "payment_failed",
                        "conditions_json": {"status": "failed"},
                        "actions_json": [
                            {
                                "type": "create_notification_event",
                                "priority": "HIGH",
                                "event_type": "payment_failed",
                                "title": "Payment failed",
                                "body": "Invoice failed.",
                            },
                            {
                                "type": "send_email",
                                "to": "owner@example.com",
                                "subject": "Payment failed",
                                "body": "Invoice failed.",
                            },
                            {"type": "send_sms", "to": "+15551234567", "body": "Invoice failed."},
                        ],
                    },
                )
                await session.commit()

            email_adapter = StubEmailAdapter()
            sms_adapter = StubCommunicationAdapter()

            async with async_session_maker() as session:
                await rules_service.evaluate_rules_for_trigger(
                    session,
                    org_id=settings.default_org_id,
                    trigger_type=rule.trigger_type,
                    payload={"status": "failed"},
                    occurred_at=None,
                    entity_type=None,
                    entity_id=None,
                    idempotency_key=None,
                    execute_actions=True,
                    email_adapter=email_adapter,
                    communication_adapter=sms_adapter,
                )
                await session.commit()

                events = await session.scalars(sa.select(NotificationEvent))
                assert email_adapter.sent == []
                assert sms_adapter.sent == []
                assert events.all() == []
        finally:
            settings.email_mode = original_email_mode
            settings.sms_mode = original_sms_mode

    asyncio.run(_run())


def test_rules_actions_create_notification_event_once(async_session_maker):
    async def _run() -> None:
        async with async_session_maker() as session:
            rule = await rules_service.create_rule(
                session,
                settings.default_org_id,
                {
                    "name": "Notification Event Rule",
                    "enabled": True,
                    "dry_run": False,
                    "trigger_type": "payment_failed",
                    "conditions_json": {"status": "failed"},
                    "actions_json": [
                        {
                            "type": "create_notification_event",
                            "priority": "HIGH",
                            "event_type": "payment_failed",
                            "title": "Payment failed",
                            "body": "Invoice failed.",
                        }
                    ],
                },
            )
            await session.commit()

        async with async_session_maker() as session:
            await rules_service.evaluate_rules_for_trigger(
                session,
                org_id=settings.default_org_id,
                trigger_type=rule.trigger_type,
                payload={"status": "failed"},
                occurred_at=None,
                entity_type="invoice",
                entity_id="inv_1",
                idempotency_key=None,
                execute_actions=True,
            )
            await session.commit()

            events = await session.scalars(sa.select(NotificationEvent))
            assert len(events.all()) == 1

    asyncio.run(_run())


def test_rules_actions_idempotency_prevents_duplicate_events(async_session_maker):
    async def _run() -> None:
        async with async_session_maker() as session:
            rule = await rules_service.create_rule(
                session,
                settings.default_org_id,
                {
                    "name": "Idempotent Action Rule",
                    "enabled": True,
                    "dry_run": False,
                    "trigger_type": "payment_failed",
                    "conditions_json": {"status": "failed"},
                    "actions_json": [
                        {
                            "type": "create_notification_event",
                            "priority": "HIGH",
                            "event_type": "payment_failed",
                            "title": "Payment failed",
                            "body": "Invoice failed.",
                        }
                    ],
                },
            )
            await session.commit()

        async with async_session_maker() as session:
            for _ in range(2):
                await rules_service.evaluate_rules_for_trigger(
                    session,
                    org_id=settings.default_org_id,
                    trigger_type=rule.trigger_type,
                    payload={"status": "failed"},
                    occurred_at=None,
                    entity_type="invoice",
                    entity_id="inv_2",
                    idempotency_key="evt_123",
                    execute_actions=True,
                )
            await session.commit()

            events = await session.scalars(sa.select(NotificationEvent))
            assert len(events.all()) == 1

    asyncio.run(_run())


def test_rules_actions_escalation_cooldown_blocks_repeat(async_session_maker):
    async def _run() -> None:
        original_email_mode = settings.email_mode
        original_sms_mode = settings.sms_mode
        settings.email_mode = "sendgrid"
        settings.sms_mode = "twilio"
        try:
            async with async_session_maker() as session:
                rule = await rules_service.create_rule(
                    session,
                    settings.default_org_id,
                    {
                        "name": "Escalation Cooldown Rule",
                        "enabled": True,
                        "dry_run": False,
                        "trigger_type": "payment_failed",
                        "conditions_json": {"status": "failed"},
                        "actions_json": [{"type": "escalate"}],
                        "escalation_cooldown_minutes": 60,
                        "escalation_policy": {
                            "level1_email": {
                                "to": "owner@example.com",
                                "subject": "Payment failed",
                                "body": "Invoice failed.",
                            },
                            "level2_sms": {
                                "to_number": "+15551234567",
                                "body": "Invoice failed.",
                            },
                        },
                    },
                )
                await session.commit()

            email_adapter = StubEmailAdapter()
            sms_adapter = StubCommunicationAdapter()

            async with async_session_maker() as session:
                for _ in range(2):
                    await rules_service.evaluate_rules_for_trigger(
                        session,
                        org_id=settings.default_org_id,
                        trigger_type=rule.trigger_type,
                        payload={"status": "failed"},
                        occurred_at=None,
                        entity_type="invoice",
                        entity_id="inv_3",
                        idempotency_key=None,
                        execute_actions=True,
                        email_adapter=email_adapter,
                        communication_adapter=sms_adapter,
                    )
                await session.commit()

            assert len(email_adapter.sent) == 1
            assert len(sms_adapter.sent) == 1
        finally:
            settings.email_mode = original_email_mode
            settings.sms_mode = original_sms_mode

    asyncio.run(_run())
