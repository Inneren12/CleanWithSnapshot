#!/usr/bin/env python3
"""Compare k6 summary JSON against a stored performance baseline."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class MetricResult:
    name: str
    baseline: float
    current: float
    delta: float
    status: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare k6 summary against a baseline.")
    parser.add_argument("--baseline", type=Path, default=Path("load-tests/baseline.json"))
    parser.add_argument("--results", type=Path, required=True, help="k6 summary JSON export")
    parser.add_argument("--scenario", required=True, help="scenario key in baseline.json")
    parser.add_argument(
        "--mode",
        choices=("warn", "fail"),
        default="warn",
        help="warn keeps exit code 0 on regressions; fail exits non-zero",
    )
    return parser.parse_args()


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return json.loads(path.read_text())


def percentile_value(
    metric: Dict[str, Any],
    percentile: int,
    *,
    mode: str,
    warnings: List[str],
    fallback_percentiles: List[int] | None = None,
) -> float:
    direct_keys = [f"p({percentile})", f"p({percentile}.0)"]
    for key in direct_keys:
        if key in metric:
            return float(metric[key])
    for key, value in metric.items():
        if key.startswith(f"p({percentile}"):
            return float(value)
    fallback_percentiles = fallback_percentiles or []
    for fallback in fallback_percentiles:
        for key in (f"p({fallback})", f"p({fallback}.0)"):
            if key in metric:
                warnings.append(
                    f"Percentile p({percentile}) missing; falling back to p({fallback})."
                )
                return float(metric[key])
        for key, value in metric.items():
            if key.startswith(f"p({fallback}"):
                warnings.append(
                    f"Percentile p({percentile}) missing; falling back to p({fallback})."
                )
                return float(value)
    if "max" in metric:
        warnings.append(f"Percentile p({percentile}) missing; falling back to max.")
        return float(metric["max"])
    if mode == "warn":
        warnings.append(f"Percentile p({percentile}) missing; using 0.0.")
        return 0.0
    raise KeyError(f"Percentile p({percentile}) missing from metric: {metric.keys()}")


def metric_rate(
    metrics: Dict[str, Any],
    metric_name: str,
    *,
    mode: str,
    warnings: List[str],
) -> float:
    metric = metrics.get(metric_name)
    if metric is None:
        if mode == "warn":
            warnings.append(f"Metric '{metric_name}' missing from summary; using 0.0.")
            return 0.0
        raise KeyError(f"Metric '{metric_name}' missing from summary")
    if "rate" not in metric:
        if mode == "warn":
            warnings.append(f"Metric '{metric_name}' missing rate field; using 0.0.")
            return 0.0
        raise KeyError(f"Metric '{metric_name}' missing rate field")
    return float(metric["rate"])


def compare_metrics(
    baseline: Dict[str, float],
    current: Dict[str, float],
) -> List[MetricResult]:
    results: List[MetricResult] = []

    def add_result(name: str, is_regression: bool) -> None:
        base_value = baseline[name]
        current_value = current[name]
        delta = current_value - base_value
        status = "REGRESSION" if is_regression else "OK"
        results.append(
            MetricResult(
                name=name,
                baseline=base_value,
                current=current_value,
                delta=delta,
                status=status,
            )
        )

    add_result("p95_ms", current["p95_ms"] > baseline["p95_ms"])
    add_result("p99_ms", current["p99_ms"] > baseline["p99_ms"])
    add_result("error_rate", current["error_rate"] > baseline["error_rate"])
    add_result("rps", current["rps"] < baseline["rps"])
    return results


def format_value(metric: str, value: float) -> str:
    if metric in {"p95_ms", "p99_ms"}:
        return f"{value:.2f} ms"
    if metric == "error_rate":
        return f"{value * 100:.2f}%"
    if metric == "rps":
        return f"{value:.2f} rps"
    return f"{value:.2f}"


def format_delta(metric: str, value: float) -> str:
    sign = "+" if value >= 0 else ""
    if metric in {"p95_ms", "p99_ms"}:
        return f"{sign}{value:.2f} ms"
    if metric == "error_rate":
        return f"{sign}{value * 100:.2f}%"
    if metric == "rps":
        return f"{sign}{value:.2f} rps"
    return f"{sign}{value:.2f}"


def main() -> int:
    args = parse_args()
    baseline_data = load_json(args.baseline)
    scenarios = baseline_data.get("scenarios", {})
    if args.scenario not in scenarios:
        available = ", ".join(sorted(scenarios.keys()))
        raise KeyError(f"Scenario '{args.scenario}' not found in baseline. Available: {available}")

    results_data = load_json(args.results)
    metrics = results_data.get("metrics", {})
    warnings: List[str] = []

    duration_metric = metrics.get("http_req_duration", {})
    duration_count = int(duration_metric.get("count") or 0)
    reqs_count = int(metrics.get("http_reqs", {}).get("count") or 0)
    if args.mode == "warn" and (duration_count == 0 or reqs_count == 0):
        print("Perf baseline skipped: no request data recorded in k6 results.")
        return 0

    current = {
        "p95_ms": percentile_value(
            duration_metric,
            95,
            mode=args.mode,
            warnings=warnings,
        ),
        "p99_ms": percentile_value(
            duration_metric,
            99,
            mode=args.mode,
            warnings=warnings,
            fallback_percentiles=[95],
        ),
        "error_rate": metric_rate(metrics, "http_req_failed", mode=args.mode, warnings=warnings),
        "rps": metric_rate(metrics, "http_reqs", mode=args.mode, warnings=warnings),
    }

    baseline = scenarios[args.scenario]
    results = compare_metrics(baseline, current)

    regressions = [result for result in results if result.status == "REGRESSION"]
    if regressions:
        overall = "WARN" if args.mode == "warn" else "FAIL"
    else:
        overall = "PASS"

    print("Performance baseline comparison")
    print(f"Scenario : {args.scenario}")
    print(f"Mode     : {args.mode}")
    print(f"Baseline : {args.baseline}")
    print(f"Results  : {args.results}")
    if warnings:
        print("")
        print("Warnings")
        for warning in warnings:
            print(f"- {warning}")
        print("")

    print("")
    print(f"{'Metric':<12} {'Baseline':>12} {'Current':>12} {'Delta':>12} {'Status':>12}")
    print("-" * 64)
    for result in results:
        print(
            f"{result.name:<12} "
            f"{format_value(result.name, result.baseline):>12} "
            f"{format_value(result.name, result.current):>12} "
            f"{format_delta(result.name, result.delta):>12} "
            f"{result.status:>12}"
        )

    print("")
    print(f"Overall : {overall}")

    if regressions and args.mode == "fail":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
