#!/usr/bin/env python3
"""Detect redundant merge parents in Alembic merge revisions."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def _normalize_parents(revision) -> list[str]:
    down_revision = revision.down_revision
    if down_revision is None:
        return []
    if isinstance(down_revision, (list, tuple)):
        return list(down_revision)
    return [down_revision]


def _is_ancestor(ancestor: str, descendant: str, revision_map: dict[str, object]) -> bool:
    if ancestor == descendant:
        return False
    stack = [descendant]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        if current == ancestor:
            return True
        revision = revision_map.get(current)
        if revision is None:
            continue
        for parent in _normalize_parents(revision):
            if parent not in seen:
                stack.append(parent)
    return False


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    config_path = repo_root / "backend" / "alembic.ini"
    config = Config(str(config_path))
    script = ScriptDirectory.from_config(config)

    revision_map = {rev.revision: rev for rev in script.walk_revisions()}
    problems = []

    for revision in revision_map.values():
        parents = _normalize_parents(revision)
        if len(parents) < 2:
            continue
        redundant = []
        for parent in parents:
            for other in parents:
                if parent == other:
                    continue
                if _is_ancestor(parent, other, revision_map):
                    redundant.append(parent)
                    break
        if redundant:
            remaining = [parent for parent in parents if parent not in set(redundant)]
            problems.append(
                {
                    "revision": revision.revision,
                    "path": revision.path,
                    "parents": parents,
                    "redundant": redundant,
                    "suggested": remaining,
                }
            )

    if problems:
        print("Redundant Alembic merge parents detected:")
        for problem in problems:
            print(f"- Merge revision: {problem['revision']}")
            print(f"  File: {problem['path']}")
            print(f"  Parents: {problem['parents']}")
            print(f"  Redundant parents: {problem['redundant']}")
            print(f"  Suggested down_revision: {tuple(problem['suggested'])}")
        return 2

    print("No redundant merge parents found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
