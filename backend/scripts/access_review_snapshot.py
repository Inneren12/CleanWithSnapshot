#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.access_review import service as access_review
from app.settings import settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate quarterly access review snapshots.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL to connect to. Defaults to DATABASE_URL or app.settings.",
    )
    parser.add_argument(
        "--scope",
        choices=("org", "global"),
        default="org",
        help="Review scope: org or global.",
    )
    parser.add_argument(
        "--org-id",
        default=None,
        help="Organization UUID (required for org scope unless default org configured).",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="ISO-8601 timestamp used as the snapshot time (defaults to now UTC).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional JSON file for anomaly rule configuration overrides.",
    )
    parser.add_argument(
        "--inactive-days",
        type=int,
        default=None,
        help="Override inactive account threshold in days.",
    )
    parser.add_argument(
        "--break-glass-days",
        type=int,
        default=None,
        help="Override break-glass lookback days.",
    )
    parser.add_argument(
        "--role-change-days",
        type=int,
        default=None,
        help="Override role-change lookback days.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write JSON and Markdown output files.",
    )
    parser.add_argument(
        "--store-run",
        action="store_true",
        help="Persist run metadata (hash, scope, generated_by) to the database.",
    )
    parser.add_argument(
        "--generated-by",
        default=None,
        help="Operator name or identifier (required when --store-run is set).",
    )
    return parser.parse_args()


def _resolve_database_url(cli_value: str | None) -> str:
    if cli_value:
        return cli_value
    env_value = os.getenv("DATABASE_URL")
    if env_value:
        return env_value
    return settings.database_url


def _parse_as_of(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_config(path: str | None) -> access_review.AccessReviewConfig:
    if not path:
        return access_review.AccessReviewConfig()
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return access_review.AccessReviewConfig.from_payload(payload)


def _apply_cli_overrides(
    config: access_review.AccessReviewConfig,
    *,
    inactive_days: int | None,
    break_glass_days: int | None,
    role_change_days: int | None,
) -> access_review.AccessReviewConfig:
    return access_review.AccessReviewConfig(
        inactive_days=inactive_days or config.inactive_days,
        break_glass_lookback_days=break_glass_days or config.break_glass_lookback_days,
        role_change_lookback_days=role_change_days or config.role_change_lookback_days,
        owner_admin_allowlist=config.owner_admin_allowlist,
        owner_admin_allowlist_by_org=config.owner_admin_allowlist_by_org,
        mfa_required=config.mfa_required,
        mfa_required_roles=config.mfa_required_roles,
    )


def _write_output(output_dir: str | None, basename: str, json_text: str, markdown_text: str) -> None:
    if not output_dir:
        print(json_text)
        print("\n")
        print(markdown_text)
        return
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    json_path = output_path / f"{basename}.json"
    md_path = output_path / f"{basename}.md"
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(markdown_text, encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


async def _run() -> int:
    args = _parse_args()
    scope = access_review.AccessReviewScope(args.scope)
    org_id = uuid.UUID(args.org_id) if args.org_id else None
    if scope == access_review.AccessReviewScope.GLOBAL:
        org_id = None
    as_of = _parse_as_of(args.as_of)
    config = _load_config(args.config)
    config = _apply_cli_overrides(
        config,
        inactive_days=args.inactive_days,
        break_glass_days=args.break_glass_days,
        role_change_days=args.role_change_days,
    )

    if args.store_run and not args.generated_by:
        raise ValueError("--generated-by is required when --store-run is set")

    database_url = _resolve_database_url(args.database_url)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        snapshot = await access_review.build_access_review_snapshot(
            session,
            scope=scope,
            org_id=org_id,
            as_of=as_of,
            config=config,
            generated_by=args.generated_by,
        )
        if args.store_run:
            await access_review.store_access_review_run(
                session,
                org_id=org_id,
                scope=scope,
                generated_by=args.generated_by,
                artifact_hash=snapshot.get("artifact_hash"),
            )

    await engine.dispose()

    json_text = access_review.render_json(snapshot)
    markdown_text = access_review.render_markdown(snapshot)
    timestamp = as_of.strftime("%Y%m%dT%H%M%SZ")
    scope_label = scope.value
    org_label = str(org_id) if org_id else "global"
    basename = f"access_review_{scope_label}_{org_label}_{timestamp}"
    _write_output(args.output_dir, basename, json_text, markdown_text)
    return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
