#!/usr/bin/env python3
"""Analyze Alembic migration structure."""

import os
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Optional, Tuple

class Migration:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.revision: Optional[str] = None
        self.down_revision: Optional[str] = None
        self.branch_labels: Optional[str] = None
        self.depends_on: Optional[str] = None
        self.description: str = ""

        self._parse()

    def _parse(self):
        """Extract metadata from migration file."""
        with open(self.filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract revision (handle both formats: revision = "..." and revision: str = "...")
        revision_match = re.search(r'^revision\s*(?::\s*str)?\s*=\s*[\'"]([^\'"]+)[\'"]', content, re.MULTILINE)
        if revision_match:
            self.revision = revision_match.group(1)

        # Extract down_revision (handle both formats)
        down_match = re.search(r'^down_revision\s*(?::\s*Union\[str,\s*None\])?\s*=\s*[\'"]([^\'"]+)[\'"]', content, re.MULTILINE)
        if down_match:
            self.down_revision = down_match.group(1) if down_match.group(1) != 'None' else None
        else:
            # Check for None value
            down_none = re.search(r'^down_revision\s*(?::\s*Union\[str,\s*None\])?\s*=\s*None', content, re.MULTILINE)
            if down_none:
                self.down_revision = None

        # Extract branch_labels
        branch_match = re.search(r'^branch_labels\s*=\s*[\'"]([^\'"]+)[\'"]', content, re.MULTILINE)
        if branch_match:
            self.branch_labels = branch_match.group(1)

        # Extract depends_on (tuple format)
        depends_match = re.search(r'^depends_on\s*=\s*\(([^)]+)\)', content, re.MULTILINE)
        if depends_match:
            deps = depends_match.group(1)
            # Extract strings from tuple
            dep_revisions = re.findall(r'[\'"]([^\'"]+)[\'"]', deps)
            if dep_revisions:
                self.depends_on = dep_revisions

        # Extract description from docstring or filename
        doc_match = re.search(r'"""(.+?)"""', content, re.DOTALL)
        if doc_match:
            self.description = doc_match.group(1).strip().split('\n')[0][:80]
        else:
            # Use filename as description
            parts = self.filename.replace('.py', '').split('_', 1)
            if len(parts) > 1:
                self.description = parts[1].replace('_', ' ')

    def __repr__(self):
        return f"Migration({self.revision}, down={self.down_revision}, file={self.filename})"


class MigrationGraph:
    def __init__(self, migrations: List[Migration]):
        self.migrations = {m.revision: m for m in migrations if m.revision}
        self.children: Dict[str, List[str]] = defaultdict(list)
        self.parents: Dict[str, List[str]] = defaultdict(list)

        self._build_graph()

    def _build_graph(self):
        """Build parent-child relationships."""
        for revision, migration in self.migrations.items():
            # Handle down_revision
            if migration.down_revision and migration.down_revision in self.migrations:
                self.children[migration.down_revision].append(revision)
                self.parents[revision].append(migration.down_revision)

            # Handle depends_on (for merge migrations)
            if migration.depends_on:
                for dep in migration.depends_on:
                    if dep in self.migrations:
                        self.children[dep].append(revision)
                        if migration.down_revision != dep:  # Avoid duplicates
                            self.parents[revision].append(dep)

    def find_heads(self) -> List[str]:
        """Find migrations with no children (heads)."""
        heads = []
        for revision in self.migrations.keys():
            if revision not in self.children or len(self.children[revision]) == 0:
                heads.append(revision)
        return sorted(heads)

    def find_roots(self) -> List[str]:
        """Find migrations with no parents (roots)."""
        roots = []
        for revision in self.migrations.keys():
            migration = self.migrations[revision]
            if not migration.down_revision and not migration.depends_on:
                roots.append(revision)
        return sorted(roots)

    def find_branches(self) -> Dict[str, List[str]]:
        """Find migrations with multiple children (branching points)."""
        branches = {}
        for parent, children_list in self.children.items():
            if len(children_list) > 1:
                branches[parent] = sorted(children_list)
        return branches

    def detect_cycles(self) -> List[List[str]]:
        """Detect circular dependencies."""
        visited = set()
        rec_stack = set()
        cycles = []

        def visit(node, path):
            if node in rec_stack:
                # Found a cycle
                cycle_start = path.index(node)
                cycles.append(path[cycle_start:] + [node])
                return

            if node in visited:
                return

            visited.add(node)
            rec_stack.add(node)

            for child in self.children.get(node, []):
                visit(child, path + [child])

            rec_stack.remove(node)

        for revision in self.migrations.keys():
            if revision not in visited:
                visit(revision, [revision])

        return cycles

    def find_broken_chains(self) -> List[Tuple[str, str]]:
        """Find references to non-existent revisions."""
        broken = []
        for revision, migration in self.migrations.items():
            if migration.down_revision and migration.down_revision not in self.migrations:
                broken.append((revision, migration.down_revision))
            if migration.depends_on:
                for dep in migration.depends_on:
                    if dep not in self.migrations:
                        broken.append((revision, dep))
        return broken

    def get_path_to_root(self, revision: str, visited: Optional[Set[str]] = None) -> List[str]:
        """Get path from revision to root."""
        if visited is None:
            visited = set()

        if revision in visited:
            return []  # Avoid infinite loops

        visited.add(revision)
        migration = self.migrations.get(revision)
        if not migration:
            return [revision]

        if not migration.down_revision and not migration.depends_on:
            return [revision]

        # Follow down_revision primarily
        if migration.down_revision:
            parent_path = self.get_path_to_root(migration.down_revision, visited)
            return parent_path + [revision]

        return [revision]

    def visualize_tree(self, max_display: int = 50) -> str:
        """Create a tree visualization of migrations."""
        output = []
        roots = self.find_roots()

        def print_tree(revision: str, indent: int = 0, prefix: str = "", visited: Optional[Set[str]] = None):
            if visited is None:
                visited = set()

            if revision in visited:
                output.append(f"{prefix}{'  ' * indent}⚠️  CYCLE: {revision[:12]}")
                return

            visited.add(revision)
            migration = self.migrations.get(revision)

            if not migration:
                output.append(f"{prefix}{'  ' * indent}❌ MISSING: {revision[:12]}")
                return

            # Format the node
            children_list = self.children.get(revision, [])
            is_branch = len(children_list) > 1
            is_head = len(children_list) == 0

            marker = "🔴" if is_head else "🔀" if is_branch else "●"

            desc = migration.description[:50] if migration.description else migration.filename[:50]
            output.append(f"{prefix}{'  ' * indent}{marker} {revision[:12]} - {desc}")

            # Print children
            for i, child in enumerate(sorted(children_list)):
                is_last = i == len(children_list) - 1
                child_prefix = prefix + ('  ' * indent) + ("└─ " if is_last else "├─ ")
                print_tree(child, indent + 1, child_prefix, visited.copy())

        # Print from each root
        for root in roots:
            output.append(f"\n=== Root: {root[:12]} ===")
            print_tree(root)

        # Limit output if too large
        if len(output) > max_display:
            return '\n'.join(output[:max_display]) + f"\n\n... ({len(output) - max_display} more lines)"

        return '\n'.join(output)


def main():
    # Find all migration files
    migrations_dir = Path("backend/alembic/versions")
    migration_files = sorted(migrations_dir.glob("*.py"))

    print(f"Found {len(migration_files)} migration files\n")

    # Parse all migrations
    migrations = []
    for filepath in migration_files:
        try:
            migration = Migration(str(filepath))
            if migration.revision:
                migrations.append(migration)
        except Exception as e:
            print(f"Error parsing {filepath.name}: {e}")

    print(f"Successfully parsed {len(migrations)} migrations\n")

    # Build graph
    graph = MigrationGraph(migrations)

    # Analysis
    print("=" * 80)
    print("MIGRATION STRUCTURE ANALYSIS")
    print("=" * 80)

    # 1. Heads
    heads = graph.find_heads()
    print(f"\n📍 HEADS (migrations with no children): {len(heads)}")
    for head in heads:
        migration = graph.migrations[head]
        print(f"   - {head[:12]} ({migration.filename})")

    # 2. Roots
    roots = graph.find_roots()
    print(f"\n🌱 ROOTS (migrations with no parents): {len(roots)}")
    for root in roots:
        migration = graph.migrations[root]
        print(f"   - {root[:12]} ({migration.filename})")

    # 3. Branches
    branches = graph.find_branches()
    print(f"\n🔀 BRANCHES (migrations with multiple children): {len(branches)}")
    for parent, children in branches.items():
        parent_migration = graph.migrations[parent]
        print(f"   - {parent[:12]} ({parent_migration.filename}) -> {len(children)} children:")
        for child in children:
            child_migration = graph.migrations[child]
            print(f"      → {child[:12]} ({child_migration.filename})")

    # 4. Cycles
    cycles = graph.detect_cycles()
    print(f"\n🔄 CYCLES: {len(cycles)}")
    if cycles:
        for cycle in cycles:
            print(f"   - {' -> '.join([c[:12] for c in cycle])}")
    else:
        print("   ✓ No cycles detected")

    # 5. Broken chains
    broken = graph.find_broken_chains()
    print(f"\n❌ BROKEN CHAINS (references to missing revisions): {len(broken)}")
    if broken:
        for rev, missing in broken:
            migration = graph.migrations[rev]
            print(f"   - {rev[:12]} ({migration.filename}) references missing: {missing[:12]}")
    else:
        print("   ✓ No broken chains")

    # 6. Tree visualization
    print("\n" + "=" * 80)
    print("MIGRATION TREE STRUCTURE")
    print("=" * 80)
    print(graph.visualize_tree(max_display=100))

    # 7. Recommendations
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)

    if len(heads) > 1:
        print("\n⚠️  CRITICAL: Multiple heads detected!")
        print(f"   Found {len(heads)} heads. This will cause issues with migrations.")
        print("\n   SOLUTION: Create a merge migration using:")
        print(f"   alembic merge -m 'merge multiple heads' {' '.join([h[:12] for h in heads])}")
        print("\n   Or use the full revision IDs:")
        for head in heads:
            print(f"   - {head}")
    else:
        print("\n✓ Single head detected - migration chain is clean")

    if branches:
        print(f"\n⚠️  WARNING: {len(branches)} branching point(s) detected")
        print("   This is normal if merge migrations were created properly.")

    if cycles:
        print(f"\n❌ ERROR: {len(cycles)} circular dependency detected!")
        print("   This should never happen and needs immediate attention.")

    if broken:
        print(f"\n❌ ERROR: {len(broken)} broken reference(s) detected!")
        print("   Some migrations reference non-existent parent revisions.")


if __name__ == "__main__":
    main()
