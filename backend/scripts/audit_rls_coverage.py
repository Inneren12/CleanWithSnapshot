#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORE_TABLE_ALIASES: dict[str, tuple[str, ...]] = {
    "bookings": ("bookings",),
    "invoices": ("invoices",),
    "leads": ("leads",),
    "clients": ("client_users",),
    "workers": ("workers",),
}

MODEL_IMPORTS = (
    "app.domain.bookings.db_models",
    "app.domain.addons.db_models",
    "app.domain.checklists.db_models",
    "app.domain.export_events.db_models",
    "app.domain.leads.db_models",
    "app.domain.invoices.db_models",
    "app.domain.reason_logs.db_models",
    "app.domain.time_tracking.db_models",
    "app.domain.nps.db_models",
    "app.domain.clients.db_models",
    "app.domain.quality.db_models",
    "app.domain.subscriptions.db_models",
    "app.domain.notifications_center.db_models",
    "app.domain.notifications_digests.db_models",
    "app.domain.marketing.db_models",
    "app.domain.analytics.db_models",
    "app.domain.training.db_models",
    "app.domain.inventory.db_models",
    "app.domain.finance.db_models",
    "app.domain.integrations.db_models",
    "app.domain.rules.db_models",
    "app.domain.leads_nurture.db_models",
    "app.domain.leads_scoring.db_models",
)


@dataclass(frozen=True)
class RlsInfo:
    enabled: bool
    policy_count: int


@dataclass(frozen=True)
class TableData:
    all_tables: list[tuple[str, str]]
    org_id_tables: list[tuple[str, str]]
    rls_info: dict[tuple[str, str], RlsInfo]


@dataclass(frozen=True)
class CoreRow:
    core_label: str
    table_name: str
    schema: str | None
    org_id_present: bool
    rls_enabled: bool | None
    policy_count: int | None
    status: str
    notes: str


@dataclass(frozen=True)
class NonCoreRow:
    table_name: str
    schema: str
    rls_enabled: bool | None
    policy_count: int | None
    status: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit RLS coverage for org-scoped tables.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL to connect to. Defaults to DATABASE_URL or app.settings.",
    )
    parser.add_argument(
        "--source",
        choices=("database", "metadata"),
        default="database",
        help="Source for table metadata: live database or SQLAlchemy metadata.",
    )
    parser.add_argument(
        "--fallback-to-metadata",
        action="store_true",
        help="Fallback to SQLAlchemy metadata if database connection fails.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional file path to write the markdown report.",
    )
    parser.add_argument(
        "--fail-on-core-missing",
        action="store_true",
        help="Exit non-zero if any core table lacks RLS coverage.",
    )
    return parser.parse_args()


def _resolve_database_url(cli_value: str | None) -> str:
    if cli_value:
        return cli_value
    env_value = os.getenv("DATABASE_URL")
    if env_value:
        return env_value
    from app.settings import settings

    return settings.database_url


def _db_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def _fetch_all_tables(engine: Engine) -> list[tuple[str, str]]:
    query = text(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name
        """
    )
    with engine.connect() as conn:
        return [(row[0], row[1]) for row in conn.execute(query)]


def _fetch_org_id_tables(engine: Engine) -> list[tuple[str, str]]:
    query = text(
        """
        SELECT table_schema, table_name
        FROM information_schema.columns
        WHERE column_name = 'org_id'
          AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name
        """
    )
    with engine.connect() as conn:
        return [(row[0], row[1]) for row in conn.execute(query)]


def _fetch_rls_info(engine: Engine) -> dict[tuple[str, str], RlsInfo]:
    rls_query = text(
        """
        SELECT n.nspname AS table_schema,
               c.relname AS table_name,
               c.relrowsecurity AS rls_enabled
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r'
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
        """
    )
    policy_query = text(
        """
        SELECT schemaname AS table_schema,
               tablename AS table_name,
               COUNT(*) AS policy_count
        FROM pg_policies
        GROUP BY schemaname, tablename
        """
    )
    rls_map: dict[tuple[str, str], RlsInfo] = {}
    with engine.connect() as conn:
        rls_rows = conn.execute(rls_query).fetchall()
        policy_rows = conn.execute(policy_query).fetchall()
    policy_map = {(row[0], row[1]): int(row[2]) for row in policy_rows}
    for row in rls_rows:
        key = (row[0], row[1])
        rls_map[key] = RlsInfo(enabled=bool(row[2]), policy_count=policy_map.get(key, 0))
    return rls_map


def _load_database_tables(database_url: str) -> TableData:
    engine = _db_engine(database_url)
    try:
        all_tables = _fetch_all_tables(engine)
        org_id_tables = _fetch_org_id_tables(engine)
        rls_info = _fetch_rls_info(engine)
    finally:
        engine.dispose()
    return TableData(all_tables=all_tables, org_id_tables=org_id_tables, rls_info=rls_info)


def _load_rls_tables_from_migrations() -> set[str]:
    migration_names = (
        "0044_postgres_rls_org_isolation.py",
        "1b9c3d4e5f6a_checklist_rls_policies.py",
        "2f3a4b5c6d7e_training_rls_policies.py",
        "ff1a2b3c4d5e_client_users_rls_org_isolation.py",
    )
    tables: set[str] = set()
    for migration_name in migration_names:
        migration_path = ROOT / "alembic" / "versions" / migration_name
        if not migration_path.exists():
            continue
        spec = importlib.util.spec_from_file_location(
            f"rls_migration_{migration_name}", migration_path
        )
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        table_list = getattr(module, "TABLES", ())
        if isinstance(table_list, str):
            tables.add(table_list)
        else:
            tables.update(table_list)
        table_single = getattr(module, "TABLE", None)
        if table_single:
            tables.add(table_single)
    return tables


def _load_metadata_tables() -> TableData:
    for module_name in MODEL_IMPORTS:
        importlib.import_module(module_name)
    from app.infra.db import Base

    all_tables: list[tuple[str, str]] = []
    org_id_tables: list[tuple[str, str]] = []
    for table in Base.metadata.sorted_tables:
        schema = table.schema or "public"
        key = (schema, table.name)
        all_tables.append(key)
        if "org_id" in table.c:
            org_id_tables.append(key)
    rls_tables = _load_rls_tables_from_migrations()
    rls_info = {
        key: RlsInfo(enabled=key[1] in rls_tables, policy_count=1 if key[1] in rls_tables else 0)
        for key in all_tables
    }
    return TableData(all_tables=all_tables, org_id_tables=org_id_tables, rls_info=rls_info)


def _build_core_rows(data: TableData) -> tuple[list[CoreRow], list[str]]:
    core_failures: list[str] = []
    core_rows: list[CoreRow] = []
    all_tables_by_name = {name: schema for schema, name in data.all_tables}
    org_id_set = set(data.org_id_tables)

    for core_label, aliases in CORE_TABLE_ALIASES.items():
        for table_name in aliases:
            schema = all_tables_by_name.get(table_name)
            key = (schema, table_name) if schema else None
            org_id_present = key in org_id_set if key else False
            rls_info = data.rls_info.get(key) if key else None
            rls_enabled = rls_info.enabled if rls_info else None
            policy_count = rls_info.policy_count if rls_info else None

            if not key:
                status = "warn"
                notes = "table missing"
            elif not org_id_present:
                status = "warn"
                notes = "org_id column missing"
            elif not rls_info or not rls_info.enabled or rls_info.policy_count == 0:
                status = "fail"
                notes = "RLS policy missing"
                core_failures.append(table_name)
            else:
                status = "ok"
                notes = ""

            core_rows.append(
                CoreRow(
                    core_label=core_label,
                    table_name=table_name,
                    schema=schema,
                    org_id_present=org_id_present,
                    rls_enabled=rls_enabled,
                    policy_count=policy_count,
                    status=status,
                    notes=notes,
                )
            )
    return core_rows, core_failures


def _build_non_core_rows(data: TableData) -> tuple[list[NonCoreRow], list[str]]:
    core_tables = {name for aliases in CORE_TABLE_ALIASES.values() for name in aliases}
    org_id_tables = [key for key in data.org_id_tables if key[1] not in core_tables]
    missing_rls: list[str] = []
    rows: list[NonCoreRow] = []
    for schema, table_name in org_id_tables:
        rls_info = data.rls_info.get((schema, table_name))
        if not rls_info or not rls_info.enabled or rls_info.policy_count == 0:
            status = "warn"
            missing_rls.append(table_name)
        else:
            status = "ok"
        rows.append(
            NonCoreRow(
                table_name=table_name,
                schema=schema,
                rls_enabled=rls_info.enabled if rls_info else None,
                policy_count=rls_info.policy_count if rls_info else None,
                status=status,
            )
        )
    return rows, missing_rls


def _markdown_table(headers: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    header_list = list(headers)
    header_line = "| " + " | ".join(header_list) + " |"
    separator_line = "| " + " | ".join(["---"] * len(header_list)) + " |"
    row_lines = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header_line, separator_line, *row_lines])


def _format_bool(value: bool | None) -> str:
    if value is None:
        return "-"
    return "yes" if value else "no"


def _format_int(value: int | None) -> str:
    return "-" if value is None else str(value)


def _build_report(
    *,
    data: TableData,
    source: str,
    database_url: str | None,
    core_rows: list[CoreRow],
    non_core_rows: list[NonCoreRow],
    core_failures: list[str],
    non_core_missing: list[str],
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = ["# RLS Coverage Audit Report", "", f"Generated: {timestamp}"]

    if source == "database" and database_url:
        safe_url = make_url(database_url).render_as_string(hide_password=True)
        lines.append(f"Source: database ({safe_url})")
    else:
        lines.append("Source: SQLAlchemy metadata + migration list")
    lines.append("")

    core_headers = [
        "Core group",
        "Table",
        "Schema",
        "org_id column",
        "RLS enabled",
        "Policies",
        "Status",
        "Notes",
    ]
    core_rows_md = [
        [
            row.core_label,
            row.table_name,
            row.schema or "-",
            _format_bool(row.org_id_present),
            _format_bool(row.rls_enabled),
            _format_int(row.policy_count),
            row.status,
            row.notes or "-",
        ]
        for row in core_rows
    ]
    lines.append("## Core tables")
    lines.append("")
    lines.append(_markdown_table(core_headers, core_rows_md))
    lines.append("")

    non_core_headers = ["Table", "Schema", "RLS enabled", "Policies", "Status"]
    non_core_rows_md = [
        [
            row.table_name,
            row.schema,
            _format_bool(row.rls_enabled),
            _format_int(row.policy_count),
            row.status,
        ]
        for row in non_core_rows
    ]
    lines.append("## Non-core tables with org_id")
    lines.append("")
    lines.append(_markdown_table(non_core_headers, non_core_rows_md) if non_core_rows_md else "No non-core tables detected.")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total org_id tables: {len(data.org_id_tables)}")
    lines.append(f"- Core tables missing RLS: {len(core_failures)}")
    lines.append(f"- Non-core tables missing RLS (warn only): {len(non_core_missing)}")
    if core_failures:
        lines.append(f"- Core failures: {', '.join(sorted(set(core_failures)))}")
    if non_core_missing:
        lines.append(f"- Non-core warnings: {', '.join(sorted(set(non_core_missing)))}")
    lines.append("")
    lines.append("### Core table mapping")
    lines.append("")
    lines.append(
        "- bookings → bookings\n"
        "- invoices → invoices\n"
        "- leads → leads\n"
        "- clients → client_users\n"
        "- workers → workers"
    )

    if source != "database":
        lines.append("")
        lines.append(
            "_Metadata mode uses SQLAlchemy models plus the RLS table list from "
            "`0044_postgres_rls_org_isolation.py` and "
            "`ff1a2b3c4d5e_client_users_rls_org_isolation.py`."
        )

    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    database_url = _resolve_database_url(args.database_url)

    if args.source == "database":
        try:
            data = _load_database_tables(database_url)
        except Exception as exc:
            if not args.fallback_to_metadata:
                raise
            print(f"Database connection failed ({exc}); falling back to metadata.")
            data = _load_metadata_tables()
            database_url = None
            source = "metadata"
        else:
            source = "database"
    else:
        data = _load_metadata_tables()
        source = "metadata"
        database_url = None

    core_rows, core_failures = _build_core_rows(data)
    non_core_rows, non_core_missing = _build_non_core_rows(data)

    report = _build_report(
        data=data,
        source=source,
        database_url=database_url,
        core_rows=core_rows,
        non_core_rows=non_core_rows,
        core_failures=core_failures,
        non_core_missing=non_core_missing,
    )
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(report)
    print(report)

    if args.fail_on_core_missing and core_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
