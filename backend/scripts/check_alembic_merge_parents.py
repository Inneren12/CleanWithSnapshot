#!/usr/bin/env python3
"""Detect redundant merge parents in Alembic merge revisions."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RevisionInfo:
    revision: str
    parents: list[str]
    path: Path


def _parse_literal(node: ast.AST) -> object:
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _extract_revision_info(path: Path) -> RevisionInfo | None:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return None

    revision_value: str | None = None
    down_revision_value: object | None = None

    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        for target in statement.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "revision":
                value = _parse_literal(statement.value)
                if isinstance(value, str):
                    revision_value = value
            elif target.id == "down_revision":
                down_revision_value = _parse_literal(statement.value)

    if revision_value is None:
        return None

    parents: list[str] = []
    if down_revision_value is None:
        parents = []
    elif isinstance(down_revision_value, str):
        parents = [down_revision_value]
    elif isinstance(down_revision_value, (list, tuple)):
        parents = [item for item in down_revision_value if isinstance(item, str)]

    return RevisionInfo(revision=revision_value, parents=parents, path=path)


def _is_ancestor(ancestor: str, descendant: str, parents_map: dict[str, list[str]]) -> bool:
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
        for parent in parents_map.get(current, []):
            if parent not in seen:
                stack.append(parent)
    return False


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    versions_dir = repo_root / "backend" / "alembic" / "versions"

    revision_infos = []
    for path in sorted(versions_dir.glob("*.py")):
        info = _extract_revision_info(path)
        if info is not None:
            revision_infos.append(info)

    parents_map = {info.revision: info.parents for info in revision_infos}
    problems = []

    for info in revision_infos:
        if len(info.parents) < 2:
            continue
        redundant = []
        for parent in info.parents:
            for other in info.parents:
                if parent == other:
                    continue
                if _is_ancestor(parent, other, parents_map):
                    redundant.append(parent)
                    break
        if redundant:
            remaining = [parent for parent in info.parents if parent not in set(redundant)]
            problems.append(
                {
                    "revision": info.revision,
                    "path": info.path,
                    "parents": info.parents,
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
