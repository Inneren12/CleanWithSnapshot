#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STRING_LITERAL_RE = re.compile(r"(E'?)(?:''|[^'])*'")
DOLLAR_QUOTED_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
NUMERIC_LITERAL_RE = re.compile(r"\b-?\d+(?:\.\d+)?\b")
BIND_PARAM_RE = re.compile(r"\$\d+")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a slow query report from pg_stat_statements (masked output)."
        )
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL to connect to. Defaults to DATABASE_URL or app.settings.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Number of queries to show per section.",
    )
    parser.add_argument(
        "--format",
        choices=("md", "json"),
        default="md",
        help="Output format: md or json.",
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


def _ensure_postgres(database_url: str) -> None:
    driver = make_url(database_url).drivername
    if not driver.startswith("postgres"):
        raise ValueError(
            f"pg_stat_statements is Postgres-only. Got driver '{driver}'."
        )


def _db_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def _extension_enabled(engine: Engine) -> bool:
    query = text("SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'")
    with engine.connect() as conn:
        return conn.execute(query).first() is not None


def _mask_literals(query: str) -> str:
    masked = DOLLAR_QUOTED_RE.sub("$$?$$", query)
    masked = STRING_LITERAL_RE.sub("'?'", masked)
    masked = NUMERIC_LITERAL_RE.sub("?", masked)
    masked = BIND_PARAM_RE.sub("$?", masked)
    return masked


def _fetch_stats(engine: Engine, order_by: str, limit: int) -> list[dict[str, object]]:
    base_query = """
        SELECT queryid,
               query,
               calls,
               total_exec_time AS total_time_ms,
               mean_exec_time AS mean_time_ms,
               rows
        FROM pg_stat_statements
        WHERE dbid = (
            SELECT oid
            FROM pg_database
            WHERE datname = current_database()
        )
    """
    legacy_query = """
        SELECT queryid,
               query,
               calls,
               total_time AS total_time_ms,
               mean_time AS mean_time_ms,
               rows
        FROM pg_stat_statements
        WHERE dbid = (
            SELECT oid
            FROM pg_database
            WHERE datname = current_database()
        )
    """
    order_clause = (
        "ORDER BY total_time_ms DESC" if order_by == "total_time" else "ORDER BY mean_time_ms DESC"
    )
    query_text = f"{base_query} {order_clause} LIMIT :limit"
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(query_text), {"limit": limit}).mappings().all()
    except SQLAlchemyError:
        query_text = f"{legacy_query} {order_clause} LIMIT :limit"
        with engine.connect() as conn:
            rows = conn.execute(text(query_text), {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def _format_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    formatted: list[dict[str, object]] = []
    for idx, row in enumerate(rows, start=1):
        formatted.append(
            {
                "rank": idx,
                "calls": int(row["calls"]),
                "total_time_ms": float(row["total_time_ms"]),
                "mean_time_ms": float(row["mean_time_ms"]),
                "rows": int(row["rows"]),
                "query": _mask_literals(str(row["query"])),
            }
        )
    return formatted


def _print_markdown(section_title: str, rows: list[dict[str, object]]) -> None:
    print(f"## {section_title}")
    if not rows:
        print("No pg_stat_statements data available yet.")
        print()
        return
    print("| Rank | Calls | Total ms | Mean ms | Rows | Query |")
    print("| ---: | ---: | ---: | ---: | ---: | :--- |")
    for row in rows:
        print(
            "| {rank} | {calls} | {total_time_ms:.2f} | {mean_time_ms:.2f} | {rows} | {query} |".format(
                **row
            )
        )
    print()


def _print_report(format_type: str, total_rows: list[dict[str, object]], mean_rows: list[dict[str, object]]) -> None:
    if format_type == "json":
        payload = {
            "total_time": total_rows,
            "mean_time": mean_rows,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    print("# Slow query report")
    print()
    _print_markdown("Top queries by total time", total_rows)
    _print_markdown("Top queries by mean time", mean_rows)


def main() -> int:
    args = _parse_args()
    database_url = _resolve_database_url(args.database_url)
    try:
        _ensure_postgres(database_url)
    except ValueError as exc:
        print(str(exc))
        return 0

    engine = _db_engine(database_url)
    if not _extension_enabled(engine):
        print(
            "pg_stat_statements extension is not enabled. Run "
            "`CREATE EXTENSION IF NOT EXISTS pg_stat_statements;` first."
        )
        return 1

    total_rows = _format_rows(_fetch_stats(engine, "total_time", args.limit))
    mean_rows = _format_rows(_fetch_stats(engine, "mean_time", args.limit))
    _print_report(args.format, total_rows, mean_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
