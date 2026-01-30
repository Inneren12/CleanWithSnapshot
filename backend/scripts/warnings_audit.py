#!/usr/bin/env python3
"""
Warnings Audit Script

Parses pytest output to capture, categorize, and report warnings.
Generates structured reports for iterative warning cleanup.

Usage:
    # Parse from log file:
    python scripts/warnings_audit.py --log pytest-warnings.log --out warnings-audit/

    # Run pytest internally and capture:
    python scripts/warnings_audit.py --run-pytest --out warnings-audit/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Warning categories we consider high-risk
HIGH_RISK_CATEGORIES = {
    "PytestRemovedIn9Warning",
    "PytestDeprecationWarning",
    "SAWarning",
    "RemovedIn20Warning",  # SQLAlchemy 2.0
    "RuntimeWarning",  # includes "coroutine never awaited"
}

# Patterns for "our code" - warnings from these paths are ours
OUR_CODE_PATTERNS = [
    r"backend/app/",
    r"backend/tests/",
    r"app/",  # When PYTHONPATH=backend
    r"tests/",
]

# Regex patterns to normalize variable parts in warning messages
NORMALIZATION_PATTERNS = [
    # UUIDs
    (r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "<UUID>"),
    # Memory addresses
    (r"0x[0-9a-fA-F]+", "<ADDR>"),
    # Timestamps ISO format
    (r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?", "<TIMESTAMP>"),
    # Unix timestamps
    (r"\b\d{10,13}\b", "<UNIX_TS>"),
    # File paths with line numbers (normalize line numbers)
    (r":\d+:", ":<LINE>:"),
    # Port numbers in URLs
    (r"localhost:\d+", "localhost:<PORT>"),
    # Numeric IDs
    (r"#\d+", "#<ID>"),
    # Object IDs in angle brackets
    (r"<\w+ object at 0x[0-9a-fA-F]+>", "<OBJECT>"),
]


def is_unclosed_event_loop_message(message: str) -> bool:
    return "unclosed event loop" in message.lower()


@dataclass
class Warning:
    """Represents a single warning instance."""

    category: str
    message: str
    source_file: str
    source_line: int
    source_module: str
    origin: str  # "our" or "third_party"
    raw_text: str
    test_context: str = ""


@dataclass
class WarningSignature:
    """Aggregated warning with count."""

    signature_id: str
    category: str
    message: str  # First line, normalized
    message_full: str  # Full message, truncated
    source_file: str
    source_line: int
    source_module: str
    origin: str
    count: int = 0
    first_seen_example: str = ""
    test_contexts: list[str] = field(default_factory=list)


@dataclass
class AuditResult:
    """Complete audit result."""

    timestamp: str
    total_warnings: int
    unique_signatures: int
    our_warnings_count: int
    third_party_warnings_count: int
    high_risk_count: int
    categories: dict[str, int]
    origins: dict[str, int]
    signatures: list[dict[str, Any]]
    high_risk_signatures: list[dict[str, Any]]
    top_files: list[tuple[str, int]]
    filtered_noise_count: int = 0


def load_noise_allowlist() -> list[dict[str, str]]:
    """Load noise allowlist from JSON file if it exists."""
    allowlist_path = ROOT / "scripts" / "noise_allowlist.json"
    if not allowlist_path.exists():
        return []
    try:
        with open(allowlist_path) as f:
            data = json.load(f)
        return data.get("patterns", [])
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Failed to load noise_allowlist.json: {e}", file=sys.stderr)
        return []


def normalize_message(message: str) -> str:
    """Normalize variable parts of a warning message for stable grouping."""
    result = message
    for pattern, replacement in NORMALIZATION_PATTERNS:
        result = re.sub(pattern, replacement, result)
    return result


def compute_signature_id(category: str, message: str, source_file: str, source_line: int) -> str:
    """Compute a stable hash for warning deduplication."""
    normalized_msg = normalize_message(message)
    key = f"{category}|{normalized_msg}|{source_file}|{source_line}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def determine_origin(source_file: str) -> str:
    """Determine if a warning is from our code or third-party."""
    if not source_file:
        return "third_party"

    # Check for site-packages
    if "site-packages" in source_file:
        return "third_party"

    # Check for our code patterns
    for pattern in OUR_CODE_PATTERNS:
        if re.search(pattern, source_file):
            return "our"

    # Default to third-party for unknown paths
    return "third_party"


def extract_module(source_file: str) -> str:
    """Extract module name from source file path."""
    if not source_file:
        return "unknown"

    # Try to extract package name from site-packages
    match = re.search(r"site-packages/([^/]+)", source_file)
    if match:
        pkg = match.group(1)
        # Clean up .dist-info, .egg-info, etc.
        pkg = re.sub(r"\.dist-info.*|\.egg-info.*|-\d+.*", "", pkg)
        return pkg

    # For our code, extract app/tests module
    match = re.search(r"(app|tests)/([^/]+)", source_file)
    if match:
        return f"{match.group(1)}.{match.group(2)}"

    # Fallback to filename
    return Path(source_file).stem


def parse_warnings_from_log(log_content: str) -> list[Warning]:
    """Parse warnings from pytest log output."""
    warnings_list: list[Warning] = []

    # Pattern for standard Python warnings format
    # /path/to/file.py:123: WarningCategory: message
    warning_pattern = re.compile(
        r"^(?P<file>[^\s:]+):(?P<line>\d+):\s*(?P<category>\w+Warning):\s*(?P<message>.+)$",
        re.MULTILINE
    )

    # Pattern for pytest warnings summary section
    pytest_warning_pattern = re.compile(
        r"^\s*(?P<file>[^\s:]+):(?P<line>\d+):\s*(?P<category>\w+Warning):\s*(?P<message>.+?)(?=\n\s*[^\s:]|$)",
        re.MULTILINE | re.DOTALL
    )

    # Pattern for "warnings summary" block in pytest output
    warnings_summary_pattern = re.compile(
        r"={5,}\s*warnings summary\s*={5,}(.*?)(?:={5,}|$)",
        re.DOTALL | re.IGNORECASE
    )

    # Extract warnings summary section if present
    summary_match = warnings_summary_pattern.search(log_content)
    if summary_match:
        summary_content = summary_match.group(1)

        # Parse individual warnings from summary
        current_file = ""
        current_line = 0
        current_category = ""
        current_message_lines: list[str] = []
        current_test = ""

        for line in summary_content.split("\n"):
            # Skip empty lines and separators
            if not line.strip() or line.strip().startswith("--"):
                continue

            # Check for test context line (e.g., "tests/test_foo.py::test_bar")
            test_match = re.match(r"^\s*(tests/[^\s:]+::\w+)", line)
            if test_match:
                current_test = test_match.group(1)
                continue

            # Check for new warning line
            warn_match = re.match(
                r"^\s*(?P<file>[^\s:]+):(?P<line>\d+):\s*(?P<category>\w+Warning):\s*(?P<message>.*)$",
                line
            )
            if warn_match:
                # Save previous warning if exists
                if current_file and current_category:
                    full_message = "\n".join(current_message_lines).strip()
                    warnings_list.append(Warning(
                        category=current_category,
                        message=current_message_lines[0] if current_message_lines else "",
                        source_file=current_file,
                        source_line=current_line,
                        source_module=extract_module(current_file),
                        origin=determine_origin(current_file),
                        raw_text=full_message,
                        test_context=current_test,
                    ))

                # Start new warning
                current_file = warn_match.group("file")
                current_line = int(warn_match.group("line"))
                current_category = warn_match.group("category")
                current_message_lines = [warn_match.group("message").strip()]
            elif current_category and line.strip():
                # Continuation of message
                current_message_lines.append(line.strip())

        # Don't forget last warning
        if current_file and current_category:
            full_message = "\n".join(current_message_lines).strip()
            warnings_list.append(Warning(
                category=current_category,
                message=current_message_lines[0] if current_message_lines else "",
                source_file=current_file,
                source_line=current_line,
                source_module=extract_module(current_file),
                origin=determine_origin(current_file),
                raw_text=full_message,
                test_context=current_test,
            ))

    # Also scan for inline warnings outside summary section
    for match in warning_pattern.finditer(log_content):
        # Skip if this is inside the warnings summary (already parsed)
        if summary_match and summary_match.start() <= match.start() <= summary_match.end():
            continue

        file_path = match.group("file")
        line_num = int(match.group("line"))
        category = match.group("category")
        message = match.group("message").strip()

        warnings_list.append(Warning(
            category=category,
            message=message,
            source_file=file_path,
            source_line=line_num,
            source_module=extract_module(file_path),
            origin=determine_origin(file_path),
            raw_text=message,
            test_context="",
        ))

    return warnings_list


def aggregate_warnings(warnings: list[Warning]) -> dict[str, WarningSignature]:
    """Aggregate warnings by signature."""
    signatures: dict[str, WarningSignature] = {}

    for warning in warnings:
        sig_id = compute_signature_id(
            warning.category,
            warning.message,
            warning.source_file,
            warning.source_line,
        )

        if sig_id not in signatures:
            signatures[sig_id] = WarningSignature(
                signature_id=sig_id,
                category=warning.category,
                message=normalize_message(warning.message)[:200],
                message_full=warning.raw_text[:1000],
                source_file=warning.source_file,
                source_line=warning.source_line,
                source_module=warning.source_module,
                origin=warning.origin,
                count=0,
                first_seen_example=warning.raw_text[:500],
                test_contexts=[],
            )

        signatures[sig_id].count += 1
        if warning.test_context and warning.test_context not in signatures[sig_id].test_contexts:
            if len(signatures[sig_id].test_contexts) < 5:  # Limit to 5 examples
                signatures[sig_id].test_contexts.append(warning.test_context)

    return signatures


def apply_noise_filter(
    signatures: dict[str, WarningSignature],
    allowlist: list[dict[str, str]],
) -> tuple[dict[str, WarningSignature], int]:
    """
    Apply noise filtering to third-party warnings.

    Returns filtered signatures and count of filtered warnings.
    """
    if not allowlist:
        return signatures, 0

    filtered: dict[str, WarningSignature] = {}
    filtered_count = 0

    for sig_id, sig in signatures.items():
        if is_unclosed_event_loop_message(sig.message):
            filtered[sig_id] = sig
            continue

        # Never filter our warnings
        if sig.origin == "our":
            filtered[sig_id] = sig
            continue

        # Never filter high-risk categories even from third-party
        if sig.category in HIGH_RISK_CATEGORIES:
            # Check for special case: RuntimeWarning "coroutine never awaited"
            if sig.category == "RuntimeWarning" and "coroutine" not in sig.message.lower():
                pass  # May be filtered
            else:
                filtered[sig_id] = sig
                continue

        # Check allowlist patterns
        should_filter = False
        for entry in allowlist:
            pattern = entry.get("pattern", "")
            if not pattern:
                continue
            try:
                if re.search(pattern, sig.message, re.IGNORECASE):
                    should_filter = True
                    break
                if re.search(pattern, sig.source_module, re.IGNORECASE):
                    should_filter = True
                    break
            except re.error:
                continue

        if should_filter:
            filtered_count += sig.count
        else:
            filtered[sig_id] = sig

    return filtered, filtered_count


def is_high_risk(sig: WarningSignature) -> bool:
    """Check if a warning signature is high-risk."""
    if is_unclosed_event_loop_message(sig.message):
        return True
    if sig.category in HIGH_RISK_CATEGORIES:
        # Special case for RuntimeWarning - only high-risk if coroutine-related
        if sig.category == "RuntimeWarning":
            return "coroutine" in sig.message.lower() or "never awaited" in sig.message.lower()
        return True
    return False


def build_audit_result(
    signatures: dict[str, WarningSignature],
    filtered_noise_count: int,
) -> AuditResult:
    """Build the final audit result from aggregated signatures."""
    # Count totals
    total_warnings = sum(s.count for s in signatures.values())
    our_count = sum(s.count for s in signatures.values() if s.origin == "our")
    third_party_count = sum(s.count for s in signatures.values() if s.origin == "third_party")

    # Count by category
    categories: dict[str, int] = defaultdict(int)
    for sig in signatures.values():
        categories[sig.category] += sig.count

    # Count by origin
    origins = {"our": our_count, "third_party": third_party_count}

    # High risk warnings
    high_risk_sigs = [sig for sig in signatures.values() if is_high_risk(sig)]
    high_risk_count = sum(s.count for s in high_risk_sigs)

    # Top files by warning count
    file_counts: dict[str, int] = defaultdict(int)
    for sig in signatures.values():
        file_counts[sig.source_file] += sig.count
    top_files = sorted(file_counts.items(), key=lambda x: -x[1])[:20]

    # Sort signatures by count descending
    sorted_sigs = sorted(signatures.values(), key=lambda x: -x.count)

    return AuditResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_warnings=total_warnings,
        unique_signatures=len(signatures),
        our_warnings_count=our_count,
        third_party_warnings_count=third_party_count,
        high_risk_count=high_risk_count,
        categories=dict(sorted(categories.items(), key=lambda x: -x[1])),
        origins=origins,
        signatures=[
            {
                "signature_id": s.signature_id,
                "category": s.category,
                "message": s.message,
                "message_full": s.message_full,
                "source_file": s.source_file,
                "source_line": s.source_line,
                "source_module": s.source_module,
                "origin": s.origin,
                "count": s.count,
                "first_seen_example": s.first_seen_example,
                "test_contexts": s.test_contexts,
            }
            for s in sorted_sigs
        ],
        high_risk_signatures=[
            {
                "signature_id": s.signature_id,
                "category": s.category,
                "message": s.message,
                "source_file": s.source_file,
                "origin": s.origin,
                "count": s.count,
            }
            for s in sorted(high_risk_sigs, key=lambda x: -x.count)
        ],
        top_files=top_files,
        filtered_noise_count=filtered_noise_count,
    )


def generate_markdown_report(result: AuditResult) -> str:
    """Generate human-readable markdown report."""
    lines = [
        "# Warnings Audit Report",
        "",
        f"Generated: {result.timestamp}",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total warnings | {result.total_warnings} |",
        f"| Unique signatures | {result.unique_signatures} |",
        f"| Our warnings | {result.our_warnings_count} |",
        f"| Third-party warnings | {result.third_party_warnings_count} |",
        f"| High-risk warnings | {result.high_risk_count} |",
        f"| Filtered noise | {result.filtered_noise_count} |",
        "",
    ]

    # Categories breakdown
    lines.extend([
        "## Warning Categories",
        "",
        "| Category | Count |",
        "|----------|-------|",
    ])
    for cat, count in result.categories.items():
        risk_marker = " **[HIGH-RISK]**" if cat in HIGH_RISK_CATEGORIES else ""
        lines.append(f"| {cat}{risk_marker} | {count} |")
    lines.append("")

    # High-risk warnings (most important)
    if result.high_risk_signatures:
        lines.extend([
            "## High-Risk Warnings (Action Required)",
            "",
            "These warnings indicate potential issues that should be addressed:",
            "",
            "| Category | Message | File | Origin | Count |",
            "|----------|---------|------|--------|-------|",
        ])
        for sig in result.high_risk_signatures[:20]:
            msg_short = sig["message"][:60] + "..." if len(sig["message"]) > 60 else sig["message"]
            msg_short = msg_short.replace("|", "\\|")
            lines.append(
                f"| {sig['category']} | {msg_short} | {sig['source_file']} | {sig['origin']} | {sig['count']} |"
            )
        lines.append("")

    # Our warnings (prioritize these)
    our_sigs = [s for s in result.signatures if s["origin"] == "our"]
    if our_sigs:
        lines.extend([
            "## Our Code Warnings",
            "",
            "Warnings originating from `backend/app/` and `backend/tests/`:",
            "",
            "| Category | Message | File:Line | Count |",
            "|----------|---------|-----------|-------|",
        ])
        for sig in our_sigs[:30]:
            msg_short = sig["message"][:50] + "..." if len(sig["message"]) > 50 else sig["message"]
            msg_short = msg_short.replace("|", "\\|")
            location = f"{sig['source_file']}:{sig['source_line']}"
            lines.append(f"| {sig['category']} | {msg_short} | {location} | {sig['count']} |")
        if len(our_sigs) > 30:
            lines.append(f"| ... | ({len(our_sigs) - 30} more) | | |")
        lines.append("")

    # Top warning sources
    if result.top_files:
        lines.extend([
            "## Top Warning Sources (by file)",
            "",
            "| File | Count |",
            "|------|-------|",
        ])
        for file_path, count in result.top_files[:15]:
            lines.append(f"| {file_path} | {count} |")
        lines.append("")

    # Third-party summary (less important)
    third_party_sigs = [s for s in result.signatures if s["origin"] == "third_party"]
    if third_party_sigs:
        lines.extend([
            "## Third-Party Warnings (Top 20)",
            "",
            "| Module | Category | Message | Count |",
            "|--------|----------|---------|-------|",
        ])
        for sig in third_party_sigs[:20]:
            msg_short = sig["message"][:40] + "..." if len(sig["message"]) > 40 else sig["message"]
            msg_short = msg_short.replace("|", "\\|")
            lines.append(f"| {sig['source_module']} | {sig['category']} | {msg_short} | {sig['count']} |")
        lines.append("")

    # Gate status
    lines.extend([
        "## CI Gate Status",
        "",
    ])

    pytest_removed_count = sum(
        s["count"] for s in result.signatures
        if s["category"] in ("PytestRemovedIn9Warning", "PytestDeprecationWarning")
    )
    unawaited_count = sum(
        s["count"] for s in result.signatures
        if s["category"] == "RuntimeWarning" and "coroutine" in s["message"].lower()
    )
    sa_our_count = sum(
        s["count"] for s in result.signatures
        if s["category"] in ("SAWarning", "RemovedIn20Warning") and s["origin"] == "our"
    )

    lines.append(f"- PytestRemovedIn9Warning: {pytest_removed_count} {'FAIL' if pytest_removed_count > 0 else 'PASS'}")
    lines.append(f"- RuntimeWarning (unawaited coroutine): {unawaited_count} {'FAIL' if unawaited_count > 0 else 'PASS'}")
    lines.append(f"- SQLAlchemy warnings (our code): {sa_our_count} {'FAIL' if sa_our_count > 0 else 'PASS'}")
    lines.append("")

    return "\n".join(lines)


def generate_top_warnings(result: AuditResult, limit: int = 50) -> str:
    """Generate plain text list of top warnings by count."""
    lines = [
        f"Top {limit} Warnings by Count",
        "=" * 40,
        "",
    ]

    for i, sig in enumerate(result.signatures[:limit], 1):
        lines.append(f"{i:3d}. [{sig['count']:4d}x] {sig['category']}")
        lines.append(f"     {sig['message'][:80]}")
        lines.append(f"     {sig['source_file']}:{sig['source_line']} ({sig['origin']})")
        lines.append("")

    return "\n".join(lines)


def run_pytest_with_warnings(pytest_args: list[str] | None = None) -> str:
    """Run pytest and capture output including warnings."""
    cmd = [
        sys.executable, "-m", "pytest",
        "-v",
        "-W", "default",
        "-m", "not smoke and not postgres",
        "--ignore=tests/smoke",
        "--tb=short",
    ]
    if pytest_args:
        cmd.extend(pytest_args)

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    # Combine stdout and stderr
    return result.stdout + "\n" + result.stderr


def check_gate_conditions(result: AuditResult) -> tuple[bool, list[str]]:
    """
    Check CI gate conditions.

    Returns (passed, list of failure reasons).
    """
    failures: list[str] = []

    # Check PytestRemovedIn9Warning
    pytest_removed_count = sum(
        s["count"] for s in result.signatures
        if s["category"] in ("PytestRemovedIn9Warning", "PytestDeprecationWarning")
    )
    if pytest_removed_count > 0:
        failures.append(f"PytestRemovedIn9Warning/PytestDeprecationWarning: {pytest_removed_count} warnings")

    # Check unawaited coroutine
    unawaited_count = sum(
        s["count"] for s in result.signatures
        if s["category"] == "RuntimeWarning" and "coroutine" in s["message"].lower()
    )
    if unawaited_count > 0:
        failures.append(f"RuntimeWarning (coroutine never awaited): {unawaited_count} warnings")

    # Check SQLAlchemy warnings from our code
    sa_our_count = sum(
        s["count"] for s in result.signatures
        if s["category"] in ("SAWarning", "RemovedIn20Warning") and s["origin"] == "our"
    )
    if sa_our_count > 0:
        failures.append(f"SQLAlchemy warnings in our code: {sa_our_count} warnings")

    return len(failures) == 0, failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit pytest warnings and generate reports."
    )
    parser.add_argument(
        "--log",
        help="Path to pytest log file to parse.",
    )
    parser.add_argument(
        "--run-pytest",
        action="store_true",
        help="Run pytest internally and capture warnings.",
    )
    parser.add_argument(
        "--out",
        default="warnings-audit",
        help="Output directory for reports (default: warnings-audit).",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Disable noise filtering (include all warnings).",
    )
    parser.add_argument(
        "--gate",
        choices=["off", "warn", "fail"],
        default="warn",
        help="CI gate mode: off (no gate), warn (print warnings), fail (exit non-zero).",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Only output JSON to stdout (for programmatic use).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Get log content
    if args.log:
        log_path = Path(args.log)
        if not log_path.exists():
            print(f"Error: Log file not found: {args.log}", file=sys.stderr)
            return 1
        log_content = log_path.read_text()
    elif args.run_pytest:
        log_content = run_pytest_with_warnings()
    else:
        print("Error: Must specify --log or --run-pytest", file=sys.stderr)
        return 1

    # Parse warnings
    warnings = parse_warnings_from_log(log_content)
    print(f"Parsed {len(warnings)} raw warnings", file=sys.stderr)

    # Aggregate by signature
    signatures = aggregate_warnings(warnings)
    print(f"Aggregated to {len(signatures)} unique signatures", file=sys.stderr)

    # Apply noise filter
    filtered_count = 0
    if not args.no_filter:
        allowlist = load_noise_allowlist()
        signatures, filtered_count = apply_noise_filter(signatures, allowlist)
        if filtered_count > 0:
            print(f"Filtered {filtered_count} noise warnings", file=sys.stderr)

    # Build result
    result = build_audit_result(signatures, filtered_count)

    if args.json_only:
        print(json.dumps(asdict(result), indent=2, default=str))
        return 0

    # Create output directory
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write JSON report
    json_path = out_dir / "warnings-audit.json"
    with open(json_path, "w") as f:
        json.dump(asdict(result), f, indent=2, default=str)
    print(f"Wrote {json_path}", file=sys.stderr)

    # Write markdown report
    md_report = generate_markdown_report(result)
    md_path = out_dir / "warnings-audit.md"
    md_path.write_text(md_report)
    print(f"Wrote {md_path}", file=sys.stderr)

    # Write top warnings
    top_report = generate_top_warnings(result)
    top_path = out_dir / "warnings-audit-top.txt"
    top_path.write_text(top_report)
    print(f"Wrote {top_path}", file=sys.stderr)

    # Print summary
    print("\n" + "=" * 60, file=sys.stderr)
    print("WARNINGS AUDIT SUMMARY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"Total warnings:     {result.total_warnings}", file=sys.stderr)
    print(f"Unique signatures:  {result.unique_signatures}", file=sys.stderr)
    print(f"Our code warnings:  {result.our_warnings_count}", file=sys.stderr)
    print(f"Third-party:        {result.third_party_warnings_count}", file=sys.stderr)
    print(f"High-risk:          {result.high_risk_count}", file=sys.stderr)
    print(f"Filtered noise:     {result.filtered_noise_count}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Check gate conditions
    if args.gate != "off":
        passed, failures = check_gate_conditions(result)
        if not passed:
            print("\nCI GATE CONDITIONS:", file=sys.stderr)
            for failure in failures:
                print(f"  - {failure}", file=sys.stderr)

            if args.gate == "fail":
                print("\nGate mode is 'fail' - exiting with error.", file=sys.stderr)
                return 1
            else:
                print("\nGate mode is 'warn' - continuing despite warnings.", file=sys.stderr)
        else:
            print("\nAll CI gate conditions passed.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
