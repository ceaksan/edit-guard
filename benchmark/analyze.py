#!/usr/bin/env python3
"""
Benchmark Analysis Script

Aggregates all result JSON files and produces summary tables.

Usage:
  python analyze.py [--format table|csv|json|markdown]

Output:
  - Summary table: approach x (file_size, change_count) -> metrics
  - Failure mode catalog
  - Decision matrix derivation
"""

import argparse
import json
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")
SCENARIOS_FILE = os.path.join(SCRIPT_DIR, "scenarios.json")

APPROACH_LABELS = {
    "sequential_edit": "Sequential Edit",
    "atomic_write": "Atomic Write",
    "bottom_up_edit": "Bottom-up Edit",
    "script_generation": "Script Generation",
    "unified_diff": "Unified Diff",
}

FIXTURE_LABELS = {
    "small": "~300 lines",
    "large": "~1000 lines",
}

CHANGE_SET_LABELS = {
    "small_5": "5 changes",
    "small_10": "10 changes",
    "large_5": "5 changes",
    "large_10": "10 changes",
}


def load_all_results() -> dict:
    """Load all result JSON files and merge with scenario metadata."""
    with open(SCENARIOS_FILE, "r", encoding="utf-8") as f:
        scenarios_data = json.load(f)

    scenario_map = {}
    for s in scenarios_data["scenarios"]:
        scenario_map[s["id"]] = s

    results = {}
    if not os.path.isdir(RESULTS_DIR):
        return results

    for fname in sorted(os.listdir(RESULTS_DIR)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(RESULTS_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        sid = data["scenario_id"]
        if sid in scenario_map:
            data["scenario"] = scenario_map[sid]
        results[sid] = data

    return results


def compute_summary(results: dict) -> list[dict]:
    """Compute per-scenario summary metrics."""
    summaries = []
    for sid, data in sorted(results.items()):
        runs = data.get("runs", [])
        if not runs:
            continue

        scenario = data.get("scenario", {})
        n = len(runs)
        success_count = sum(1 for r in runs if r["success"])
        total_tokens = [r["tokens_total"] for r in runs]
        durations = [r["duration_s"] for r in runs]
        tool_calls_list = [r["tool_calls"] for r in runs]
        retries = [r.get("retries", 0) for r in runs]

        failure_modes = [r["failure_mode"] for r in runs if r.get("failure_mode")]

        summaries.append(
            {
                "scenario_id": sid,
                "approach": scenario.get("approach", "unknown"),
                "approach_label": APPROACH_LABELS.get(
                    scenario.get("approach", ""), "?"
                ),
                "fixture": scenario.get("fixture", "unknown"),
                "fixture_label": FIXTURE_LABELS.get(scenario.get("fixture", ""), "?"),
                "change_set": scenario.get("change_set", "unknown"),
                "changes_label": CHANGE_SET_LABELS.get(
                    scenario.get("change_set", ""), "?"
                ),
                "runs": n,
                "success_rate": success_count / n if n > 0 else 0,
                "avg_tokens": sum(total_tokens) / n if n > 0 else 0,
                "avg_duration_s": sum(durations) / n if n > 0 else 0,
                "avg_tool_calls": sum(tool_calls_list) / n if n > 0 else 0,
                "avg_retries": sum(retries) / n if n > 0 else 0,
                "failure_modes": failure_modes,
            }
        )

    return summaries


def print_markdown_table(summaries: list[dict]) -> None:
    """Print summary as markdown table."""
    print("\n## Benchmark Results\n")
    print(
        "| Scenario | Approach | File Size | Changes | Success | Avg Tokens | Avg Time (s) | Avg Tool Calls |"
    )
    print(
        "|----------|----------|-----------|---------|---------|------------|--------------|----------------|"
    )

    for s in summaries:
        success_pct = f"{s['success_rate']:.0%}"
        print(
            f"| {s['scenario_id']} "
            f"| {s['approach_label']} "
            f"| {s['fixture_label']} "
            f"| {s['changes_label']} "
            f"| {success_pct} "
            f"| {s['avg_tokens']:.0f} "
            f"| {s['avg_duration_s']:.1f} "
            f"| {s['avg_tool_calls']:.1f} |"
        )

    # Approach summary
    print("\n## Approach Summary\n")
    approach_groups = defaultdict(list)
    for s in summaries:
        approach_groups[s["approach"]].append(s)

    print("| Approach | Avg Success | Avg Tokens | Avg Time (s) | Failure Modes |")
    print("|----------|-------------|------------|--------------|---------------|")

    for approach, group in approach_groups.items():
        avg_success = sum(s["success_rate"] for s in group) / len(group)
        avg_tokens = sum(s["avg_tokens"] for s in group) / len(group)
        avg_time = sum(s["avg_duration_s"] for s in group) / len(group)
        all_failures = []
        for s in group:
            all_failures.extend(s["failure_modes"])
        unique_failures = list(set(all_failures)) if all_failures else ["-"]

        print(
            f"| {APPROACH_LABELS.get(approach, approach)} "
            f"| {avg_success:.0%} "
            f"| {avg_tokens:.0f} "
            f"| {avg_time:.1f} "
            f"| {', '.join(unique_failures[:3])} |"
        )

    # Decision matrix
    print("\n## Decision Matrix (derived from data)\n")
    print("| File Size | Changes | Best Approach | Success Rate | Reasoning |")
    print("|-----------|---------|---------------|--------------|-----------|")

    for fixture in ["small", "large"]:
        for changes in ["5", "10"]:
            change_key = f"{fixture}_{changes}"
            candidates = [s for s in summaries if s["change_set"] == change_key]
            if not candidates:
                continue

            best = max(candidates, key=lambda x: (x["success_rate"], -x["avg_tokens"]))
            print(
                f"| {FIXTURE_LABELS.get(fixture, fixture)} "
                f"| {changes} changes "
                f"| {best['approach_label']} "
                f"| {best['success_rate']:.0%} "
                f"| Lowest tokens at highest success |"
            )

    # Failure mode catalog
    all_failures = []
    for s in summaries:
        for fm in s["failure_modes"]:
            all_failures.append(
                {
                    "scenario": s["scenario_id"],
                    "approach": s["approach_label"],
                    "mode": fm,
                }
            )

    if all_failures:
        print("\n## Failure Mode Catalog\n")
        print("| Scenario | Approach | Failure Mode |")
        print("|----------|----------|--------------|")
        for fm in all_failures:
            print(f"| {fm['scenario']} | {fm['approach']} | {fm['mode']} |")


def print_json(summaries: list[dict]) -> None:
    # Remove non-serializable items
    clean = []
    for s in summaries:
        c = dict(s)
        clean.append(c)
    print(json.dumps(clean, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Analyze benchmark results")
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format",
    )
    args = parser.parse_args()

    results = load_all_results()
    if not results:
        print("No results found in results/ directory.")
        print("Run scenarios first, then use record.py to save results.")
        return 1

    summaries = compute_summary(results)

    if args.format == "json":
        print_json(summaries)
    else:
        print_markdown_table(summaries)

    return 0


if __name__ == "__main__":
    sys.exit(main())
