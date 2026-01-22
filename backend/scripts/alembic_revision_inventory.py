#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class MigrationInfo:
    revision: str
    down_revisions: tuple[str, ...]
    path: Path


def _parse_assignments(source: str) -> tuple[str | None, tuple[str, ...]]:
    tree = ast.parse(source)
    revision: str | None = None
    down_revisions: tuple[str, ...] = tuple()
    for node in ast.walk(tree):
        target_id = None
        value_node = None
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            target_id = node.targets[0].id
            value_node = node.value
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name):
                continue
            target_id = node.target.id
            value_node = node.value
        else:
            continue

        if target_id == "revision" and value_node is not None:
            revision = ast.literal_eval(value_node)
        elif target_id == "down_revision" and value_node is not None:
            parsed = ast.literal_eval(value_node)
            if parsed is None:
                down_revisions = tuple()
            elif isinstance(parsed, (tuple, list)):
                down_revisions = tuple(parsed)
            else:
                down_revisions = (parsed,)
    return revision, down_revisions


def _load_migrations(directory: Path) -> list[MigrationInfo]:
    migrations: list[MigrationInfo] = []
    for path in sorted(directory.glob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        revision, down_revisions = _parse_assignments(source)
        if not revision:
            continue
        migrations.append(MigrationInfo(revision=revision, down_revisions=down_revisions, path=path))
    return migrations


def _build_map(migrations: list[MigrationInfo]) -> dict[str, Path]:
    return {migration.revision: migration.path for migration in migrations}


def _compute_heads(migrations: list[MigrationInfo]) -> list[str]:
    revisions = {migration.revision for migration in migrations}
    referenced: set[str] = set()
    for migration in migrations:
        for down in migration.down_revisions:
            if down:
                referenced.add(down)
    return sorted(revisions - referenced)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory Alembic revisions across canonical/noncanonical trees.")
    parser.add_argument("--canon", required=True, help="Canonical migrations directory.")
    parser.add_argument("--noncanon", required=True, help="Non-canonical migrations directory.")
    parser.add_argument("--output", help="Optional JSON output path. Defaults to stdout.")
    args = parser.parse_args()

    canon_dir = Path(args.canon)
    noncanon_dir = Path(args.noncanon)

    canon_migrations = _load_migrations(canon_dir)
    noncanon_migrations = _load_migrations(noncanon_dir)

    canon_map = _build_map(canon_migrations)
    noncanon_map = _build_map(noncanon_migrations)

    all_migrations = canon_migrations + noncanon_migrations
    all_map: dict[str, list[Path]] = {}
    for migration in all_migrations:
        all_map.setdefault(migration.revision, []).append(migration.path)

    duplicates_in_repo = {rev: [str(path) for path in paths] for rev, paths in all_map.items() if len(paths) > 1}

    missing_in_canon = sorted(set(noncanon_map.keys()) - set(canon_map.keys()))

    known_revisions = set(canon_map.keys()) | set(noncanon_map.keys())
    missing_in_repo_references: set[str] = set()
    for migration in all_migrations:
        for down in migration.down_revisions:
            if down and down not in known_revisions:
                missing_in_repo_references.add(down)

    canon_rev_paths: dict[str, list[Path]] = {}
    for migration in canon_migrations:
        canon_rev_paths.setdefault(migration.revision, []).append(migration.path)
    duplicates_in_canon = sorted(rev for rev, paths in canon_rev_paths.items() if len(paths) > 1)

    report = {
        "canon": {rev: str(path) for rev, path in canon_map.items()},
        "noncanon": {rev: str(path) for rev, path in noncanon_map.items()},
        "duplicates_in_repo": duplicates_in_repo,
        "duplicates_in_canon": duplicates_in_canon,
        "missing_in_canon": missing_in_canon,
        "missing_in_repo_references": sorted(missing_in_repo_references),
        "head_candidates": _compute_heads(canon_migrations),
    }

    output = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)

    if missing_in_repo_references or duplicates_in_canon:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
