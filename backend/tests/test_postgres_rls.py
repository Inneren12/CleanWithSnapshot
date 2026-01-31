import contextlib
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.settings import settings


@contextlib.contextmanager
def _temporary_postgres_database(base_url: str):
    url = make_url(base_url)
    if url.get_backend_name() != "postgresql":
        pytest.skip("Row-level security checks require PostgreSQL")

    database_name = f"rls_check_{uuid.uuid4().hex}"
    admin_url = url.set(database=url.database or "postgres")
    admin_engine = sa.create_engine(
        admin_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5}
    )

    try:
        with admin_engine.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{database_name}"'))
    except sa.exc.OperationalError as exc:  # pragma: no cover - env specific
        pytest.skip(f"PostgreSQL unavailable for RLS check: {exc}")

    try:
        yield url.set(database=database_name).render_as_string(hide_password=False)
    finally:
        with admin_engine.connect() as conn:
            conn.execute(
                sa.text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :db_name AND pid <> pg_backend_pid()
                    """
                ),
                {"db_name": database_name},
            )
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


def _apply_migrations(temp_url: str) -> None:
    config = Config("alembic.ini")
    original_url = settings.database_url

    try:
        settings.database_url = temp_url
        config.set_main_option("sqlalchemy.url", temp_url)
        command.upgrade(config, "head")
    finally:
        settings.database_url = original_url


def _provision_tenant_engine(temp_url: str) -> sa.Engine:
    base_url = make_url(temp_url)
    admin_engine = sa.create_engine(base_url, future=True)

    with admin_engine.begin() as conn:
        conn.execute(sa.text("DROP ROLE IF EXISTS app_test"))
        conn.execute(
            sa.text(
                "CREATE ROLE app_test LOGIN PASSWORD 'app_test' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
            )
        )
        conn.execute(sa.text("GRANT USAGE ON SCHEMA public TO app_test"))
        conn.execute(
            sa.text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_test"
            )
        )
        conn.execute(sa.text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_test"))
        conn.execute(
            sa.text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE "
                "ON TABLES TO app_test"
            )
        )

    admin_engine.dispose()

    tenant_url = base_url.set(username="app_test", password="app_test").render_as_string(
        hide_password=False
    )
    return sa.create_engine(tenant_url, future=True)


@pytest.mark.postgres
@pytest.mark.migrations
def test_rls_prevents_cross_org_queries():
    with _temporary_postgres_database(settings.database_url) as temp_url:
        _apply_migrations(temp_url)
        engine = _provision_tenant_engine(temp_url)
        org_a = uuid.uuid4()
        org_b = uuid.uuid4()

        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO organizations (org_id, name) VALUES (:org_id, :name), (:org_b, :name_b)"
                ),
                {
                    "org_id": org_a,
                    "name": "RLS Org A",
                    "org_b": org_b,
                    "name_b": "RLS Org B",
                },
            )

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_a}'"))
            conn.execute(
                sa.text("INSERT INTO teams (org_id, name) VALUES (:org_id, :name)"),
                {"org_id": org_a, "name": "Team A"},
            )

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_b}'"))
            conn.execute(
                sa.text("INSERT INTO teams (org_id, name) VALUES (:org_id, :name)"),
                {"org_id": org_b, "name": "Team B"},
            )

        with engine.begin() as conn:
            rows = conn.execute(sa.text("SELECT org_id, name FROM teams ORDER BY name"))
            assert rows.fetchall() == []

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_a}'"))
            rows = conn.execute(sa.text("SELECT org_id, name FROM teams ORDER BY name"))
            assert {row.org_id for row in rows} == {org_a}

        engine.dispose()


@pytest.mark.postgres
@pytest.mark.migrations
def test_rls_isolates_checklists():
    with _temporary_postgres_database(settings.database_url) as temp_url:
        _apply_migrations(temp_url)
        engine = _provision_tenant_engine(temp_url)
        org_a = uuid.uuid4()
        org_b = uuid.uuid4()

        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO organizations (org_id, name) VALUES (:org_id, :name), (:org_b, :name_b)"
                ),
                {
                    "org_id": org_a,
                    "name": "Checklist Org A",
                    "org_b": org_b,
                    "name_b": "Checklist Org B",
                },
            )

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_a}'"))
            conn.execute(
                sa.text("INSERT INTO teams (org_id, name) VALUES (:org_id, :name)"),
                {"org_id": org_a, "name": "Team A"},
            )
            team_a_id = conn.execute(
                sa.text("SELECT team_id FROM teams WHERE name = 'Team A'")
            ).scalar_one()
            conn.execute(
                sa.text(
                    "INSERT INTO bookings (booking_id, org_id, team_id, starts_at, duration_minutes, status) "
                    "VALUES (:booking_id, :org_id, :team_id, NOW(), :duration, :status)"
                ),
                {
                    "booking_id": "booking-a",
                    "org_id": org_a,
                    "team_id": team_a_id,
                    "duration": 60,
                    "status": "scheduled",
                },
            )

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_b}'"))
            conn.execute(
                sa.text("INSERT INTO teams (org_id, name) VALUES (:org_id, :name)"),
                {"org_id": org_b, "name": "Team B"},
            )
            team_b_id = conn.execute(
                sa.text("SELECT team_id FROM teams WHERE name = 'Team B'")
            ).scalar_one()
            conn.execute(
                sa.text(
                    "INSERT INTO bookings (booking_id, org_id, team_id, starts_at, duration_minutes, status) "
                    "VALUES (:booking_id, :org_id, :team_id, NOW(), :duration, :status)"
                ),
                {
                    "booking_id": "booking-b",
                    "org_id": org_b,
                    "team_id": team_b_id,
                    "duration": 60,
                    "status": "scheduled",
                },
            )

        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO checklist_templates (name, service_type, version, is_active) "
                    "VALUES (:name, :service_type, :version, :is_active)"
                ),
                {
                    "name": "Base template",
                    "service_type": "standard",
                    "version": 1,
                    "is_active": True,
                },
            )
            template_id = conn.execute(
                sa.text("SELECT template_id FROM checklist_templates WHERE name = 'Base template'")
            ).scalar_one()
            conn.execute(
                sa.text(
                    "INSERT INTO checklist_template_items (template_id, position, label, phase, required) "
                    "VALUES (:template_id, :position, :label, :phase, :required)"
                ),
                {
                    "template_id": template_id,
                    "position": 1,
                    "label": "Do the thing",
                    "phase": "prep",
                    "required": True,
                },
            )
            template_item_id = conn.execute(
                sa.text(
                    "SELECT item_id FROM checklist_template_items WHERE template_id = :template_id"
                ),
                {"template_id": template_id},
            ).scalar_one()

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_a}'"))
            conn.execute(
                sa.text(
                    "INSERT INTO checklist_runs (run_id, order_id, template_id, status) "
                    "VALUES (:run_id, :order_id, :template_id, :status)"
                ),
                {
                    "run_id": "run-a",
                    "order_id": "booking-a",
                    "template_id": template_id,
                    "status": "in_progress",
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO checklist_run_items (run_item_id, run_id, template_item_id, checked) "
                    "VALUES (:run_item_id, :run_id, :template_item_id, :checked)"
                ),
                {
                    "run_item_id": "item-a",
                    "run_id": "run-a",
                    "template_item_id": template_item_id,
                    "checked": False,
                },
            )

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_b}'"))
            conn.execute(
                sa.text(
                    "INSERT INTO checklist_runs (run_id, order_id, template_id, status) "
                    "VALUES (:run_id, :order_id, :template_id, :status)"
                ),
                {
                    "run_id": "run-b",
                    "order_id": "booking-b",
                    "template_id": template_id,
                    "status": "in_progress",
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO checklist_run_items (run_item_id, run_id, template_item_id, checked) "
                    "VALUES (:run_item_id, :run_id, :template_item_id, :checked)"
                ),
                {
                    "run_item_id": "item-b",
                    "run_id": "run-b",
                    "template_item_id": template_item_id,
                    "checked": False,
                },
            )

        with engine.begin() as conn:
            rows = conn.execute(sa.text("SELECT run_id FROM checklist_runs ORDER BY run_id"))
            assert rows.fetchall() == []
            rows = conn.execute(
                sa.text("SELECT run_item_id FROM checklist_run_items ORDER BY run_item_id")
            )
            assert rows.fetchall() == []

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_a}'"))
            rows = conn.execute(
                sa.text("SELECT run_id, order_id FROM checklist_runs ORDER BY run_id")
            )
            assert {(row.run_id, row.order_id) for row in rows} == {("run-a", "booking-a")}
            rows = conn.execute(
                sa.text(
                    "SELECT run_item_id, run_id FROM checklist_run_items ORDER BY run_item_id"
                )
            )
            assert {(row.run_item_id, row.run_id) for row in rows} == {("item-a", "run-a")}

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_b}'"))
            rows = conn.execute(
                sa.text("SELECT run_id, order_id FROM checklist_runs ORDER BY run_id")
            )
            assert {(row.run_id, row.order_id) for row in rows} == {("run-b", "booking-b")}

            updated = conn.execute(
                sa.text(
                    "UPDATE checklist_runs SET status = :status WHERE run_id = :run_id RETURNING run_id"
                ),
                {"status": "complete", "run_id": "run-a"},
            ).fetchall()
            assert updated == []

            deleted = conn.execute(
                sa.text(
                    "DELETE FROM checklist_run_items WHERE run_item_id = :run_item_id RETURNING run_item_id"
                ),
                {"run_item_id": "item-a"},
            ).fetchall()
            assert deleted == []

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_a}'"))
            rows = conn.execute(
                sa.text(
                    "SELECT runs.run_id, items.run_item_id "
                    "FROM checklist_runs AS runs "
                    "JOIN checklist_run_items AS items ON items.run_id = runs.run_id "
                    "ORDER BY runs.run_id"
                )
            )
            assert {(row.run_id, row.run_item_id) for row in rows} == {("run-a", "item-a")}

        engine.dispose()


@pytest.mark.postgres
@pytest.mark.migrations
def test_rls_isolates_client_users():
    with _temporary_postgres_database(settings.database_url) as temp_url:
        _apply_migrations(temp_url)
        engine = _provision_tenant_engine(temp_url)
        org_a = uuid.uuid4()
        org_b = uuid.uuid4()

        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO organizations (org_id, name) VALUES (:org_id, :name), (:org_b, :name_b)"
                ),
                {
                    "org_id": org_a,
                    "name": "Client Org A",
                    "org_b": org_b,
                    "name_b": "Client Org B",
                },
            )

        client_a = str(uuid.uuid4())
        client_b = str(uuid.uuid4())

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_a}'"))
            conn.execute(
                sa.text(
                    "INSERT INTO client_users (client_id, org_id, email, name) "
                    "VALUES (:client_id, :org_id, :email, :name)"
                ),
                {
                    "client_id": client_a,
                    "org_id": org_a,
                    "email": "rls-client-a@example.com",
                    "name": "Client A",
                },
            )

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_b}'"))
            conn.execute(
                sa.text(
                    "INSERT INTO client_users (client_id, org_id, email, name) "
                    "VALUES (:client_id, :org_id, :email, :name)"
                ),
                {
                    "client_id": client_b,
                    "org_id": org_b,
                    "email": "rls-client-b@example.com",
                    "name": "Client B",
                },
            )

        with engine.begin() as conn:
            rows = conn.execute(sa.text("SELECT client_id FROM client_users ORDER BY client_id"))
            assert rows.fetchall() == []

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_a}'"))
            rows = conn.execute(sa.text("SELECT client_id, org_id FROM client_users ORDER BY client_id"))
            assert {(row.client_id, row.org_id) for row in rows} == {(client_a, org_a)}

        engine.dispose()


@pytest.mark.postgres
@pytest.mark.migrations
def test_rls_rejects_writes_without_org_context():
    with _temporary_postgres_database(settings.database_url) as temp_url:
        _apply_migrations(temp_url)
        engine = _provision_tenant_engine(temp_url)

        org_id = uuid.uuid4()
        lead_id = uuid.uuid4()

        with engine.begin() as conn:
            conn.execute(
                sa.text("INSERT INTO organizations (org_id, name) VALUES (:org_id, :name)"),
                {"org_id": org_id, "name": "RLS Org"},
            )

        with pytest.raises(sa.exc.DatabaseError):
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO leads (lead_id, org_id, name) VALUES (:lead_id, :org_id, :name)"
                    ),
                    {"lead_id": lead_id, "org_id": org_id, "name": "Blocked lead"},
                )

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_id}'"))
            conn.execute(
                sa.text(
                    "INSERT INTO leads (lead_id, org_id, name) VALUES (:lead_id, :org_id, :name)"
                ),
                {"lead_id": lead_id, "org_id": org_id, "name": "Allowed lead"},
            )
            rows = conn.execute(sa.text("SELECT lead_id FROM leads"))
            assert {row.lead_id for row in rows} == {lead_id}

        engine.dispose()


@pytest.mark.postgres
@pytest.mark.migrations
def test_rls_isolates_notifications_center():
    with _temporary_postgres_database(settings.database_url) as temp_url:
        _apply_migrations(temp_url)
        engine = _provision_tenant_engine(temp_url)
        org_a = uuid.uuid4()
        org_b = uuid.uuid4()

        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO organizations (org_id, name) VALUES (:org_id, :name), (:org_b, :name_b)"
                ),
                {
                    "org_id": org_a,
                    "name": "Notifications Org A",
                    "org_b": org_b,
                    "name_b": "Notifications Org B",
                },
            )

        event_a = uuid.uuid4()
        event_b = uuid.uuid4()
        read_a = uuid.uuid4()
        read_b = uuid.uuid4()

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_a}'"))
            conn.execute(
                sa.text(
                    "INSERT INTO notifications_events (id, org_id, priority, type, title, body) "
                    "VALUES (:id, :org_id, :priority, :type, :title, :body)"
                ),
                {
                    "id": event_a,
                    "org_id": org_a,
                    "priority": "normal",
                    "type": "audit",
                    "title": "Org A Event",
                    "body": "A body",
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO notifications_reads (id, org_id, user_id, event_id) "
                    "VALUES (:id, :org_id, :user_id, :event_id)"
                ),
                {
                    "id": read_a,
                    "org_id": org_a,
                    "user_id": "user-a",
                    "event_id": event_a,
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO notifications_rules_presets "
                    "(org_id, preset_key, enabled, notify_roles, notify_user_ids) "
                    "VALUES (:org_id, :preset_key, :enabled, :notify_roles, :notify_user_ids)"
                ),
                {
                    "org_id": org_a,
                    "preset_key": "preset-a",
                    "enabled": True,
                    "notify_roles": "[]",
                    "notify_user_ids": "[]",
                },
            )

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_b}'"))
            conn.execute(
                sa.text(
                    "INSERT INTO notifications_events (id, org_id, priority, type, title, body) "
                    "VALUES (:id, :org_id, :priority, :type, :title, :body)"
                ),
                {
                    "id": event_b,
                    "org_id": org_b,
                    "priority": "normal",
                    "type": "audit",
                    "title": "Org B Event",
                    "body": "B body",
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO notifications_reads (id, org_id, user_id, event_id) "
                    "VALUES (:id, :org_id, :user_id, :event_id)"
                ),
                {
                    "id": read_b,
                    "org_id": org_b,
                    "user_id": "user-b",
                    "event_id": event_b,
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO notifications_rules_presets "
                    "(org_id, preset_key, enabled, notify_roles, notify_user_ids) "
                    "VALUES (:org_id, :preset_key, :enabled, :notify_roles, :notify_user_ids)"
                ),
                {
                    "org_id": org_b,
                    "preset_key": "preset-b",
                    "enabled": False,
                    "notify_roles": "[]",
                    "notify_user_ids": "[]",
                },
            )

        with engine.begin() as conn:
            rows = conn.execute(sa.text("SELECT id FROM notifications_events"))
            assert rows.fetchall() == []
            rows = conn.execute(sa.text("SELECT id FROM notifications_reads"))
            assert rows.fetchall() == []
            rows = conn.execute(sa.text("SELECT preset_key FROM notifications_rules_presets"))
            assert rows.fetchall() == []

        with engine.begin() as conn:
            conn.execute(sa.text(f"SET LOCAL app.current_org_id = '{org_a}'"))
            rows = conn.execute(
                sa.text("SELECT id, org_id FROM notifications_events ORDER BY id")
            )
            assert {(row.id, row.org_id) for row in rows} == {(event_a, org_a)}
            rows = conn.execute(
                sa.text("SELECT id, org_id FROM notifications_reads ORDER BY id")
            )
            assert {(row.id, row.org_id) for row in rows} == {(read_a, org_a)}
            rows = conn.execute(
                sa.text("SELECT preset_key, org_id FROM notifications_rules_presets ORDER BY preset_key")
            )
            assert {(row.preset_key, row.org_id) for row in rows} == {("preset-a", org_a)}

        engine.dispose()
