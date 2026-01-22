#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report top queries from pg_stat_statements (masked literals)."
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
        help="Number of queries to show.",
    )
    parser.add_argument(
        "--order-by",
        choices=("total_time", "mean_time"),
        default="total_time",
        help="Sort by total execution time or mean execution time.",
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
    order_clause = "ORDER BY total_time_ms DESC" if order_by == "total_time" else "ORDER BY mean_time_ms DESC"
    query_text = f"{base_query} {order_clause} LIMIT :limit"
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(query_text), {"limit": limit}).mappings().all()
    except SQLAlchemyError:
        query_text = f"{legacy_query} {order_clause} LIMIT :limit"
        with engine.connect() as conn:
            rows = conn.execute(text(query_text), {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def _print_report(rows: list[dict[str, object]]) -> None:
    if not rows:
        print("No pg_stat_statements data available yet.")
        return

    header = f"{'Rank':>4}  {'Calls':>8}  {'Total ms':>12}  {'Mean ms':>10}  Query"
    print(header)
    print("-" * len(header))
    for idx, row in enumerate(rows, start=1):
        masked_query = _mask_literals(str(row["query"]))
        print(
            f"{idx:>4}  {int(row['calls']):>8}  {float(row['total_time_ms']):>12.2f}  "
            f"{float(row['mean_time_ms']):>10.2f}  {masked_query}"
        )


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

    rows = _fetch_stats(engine, args.order_by, args.limit)
    _print_report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
