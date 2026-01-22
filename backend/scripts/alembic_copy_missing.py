#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import shutil
from pathlib import Path


def _parse_value(source: str) -> str:
    parts = source.split("=", 1)
    if len(parts) != 2:
        return ""
    return parts[1].strip()


def _extract_revision(path: Path) -> str | None:
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if line.strip().startswith("revision"):
            value = _parse_value(line)
            if not value:
                continue
            return ast.literal_eval(value)
    return None


def _build_revision_map(directory: Path) -> dict[str, Path]:
    revision_map: dict[str, Path] = {}
    for path in sorted(directory.glob("*.py")):
        revision = _extract_revision(path)
        if revision:
            revision_map[revision] = path
    return revision_map


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy missing Alembic revisions into canonical tree.")
    parser.add_argument("--canon", required=True, help="Canonical migrations directory.")
    parser.add_argument("--noncanon", required=True, help="Non-canonical migrations directory.")
    parser.add_argument("--dry-run", action="store_true", help="Print files to copy without copying.")
    args = parser.parse_args()

    canon_dir = Path(args.canon)
    noncanon_dir = Path(args.noncanon)

    canon_map = _build_revision_map(canon_dir)
    noncanon_map = _build_revision_map(noncanon_dir)

    missing = sorted(set(noncanon_map.keys()) - set(canon_map.keys()))
    for revision in missing:
        src = noncanon_map[revision]
        dest = canon_dir / src.name
        if args.dry_run:
            print(f"Would copy {src} -> {dest}")
            continue
        shutil.copy2(src, dest)
        print(f"Copied {src} -> {dest}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
