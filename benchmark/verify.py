#!/usr/bin/env python3
"""
Benchmark Verification Script

Checks if all expected changes were applied correctly to a fixture file.
Reads scenarios.json to determine what changes should have been made.

Usage:
  python verify.py <scenario_id> [--fixture-path PATH]

Examples:
  python verify.py S01
  python verify.py S07 --fixture-path /tmp/test/fixture-1000.tsx
"""

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCENARIOS_FILE = os.path.join(SCRIPT_DIR, "scenarios.json")

FIXTURE_MAP = {
    "small": os.path.join(SCRIPT_DIR, "fixtures", "fixture-300.tsx"),
    "large": os.path.join(SCRIPT_DIR, "fixtures", "fixture-1000.tsx"),
}


def load_scenarios() -> dict:
    with open(SCENARIOS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_scenario(scenario_id: str, fixture_path: str | None = None) -> dict:
    """Verify a scenario's changes were applied. Returns result dict."""
    data = load_scenarios()

    scenario = None
    for s in data["scenarios"]:
        if s["id"] == scenario_id:
            scenario = s
            break

    if not scenario:
        return {"success": False, "error": f"Scenario {scenario_id} not found"}

    change_set_key = scenario["change_set"]
    changes = data["changes"][change_set_key]["changes"]

    if fixture_path is None:
        fixture_path = FIXTURE_MAP[scenario["fixture"]]

    if not os.path.isfile(fixture_path):
        return {"success": False, "error": f"File not found: {fixture_path}"}

    with open(fixture_path, "r", encoding="utf-8") as f:
        content = f.read()

    results = []
    all_passed = True

    for change in changes:
        old_present = change["old"] in content
        new_present = change["new"] in content

        if new_present and not old_present:
            status = "PASS"
        elif old_present and not new_present:
            status = "FAIL_NOT_APPLIED"
            all_passed = False
        elif old_present and new_present:
            status = "FAIL_BOTH_PRESENT"
            all_passed = False
        else:
            status = "FAIL_NEITHER_PRESENT"
            all_passed = False

        results.append(
            {
                "change_id": change["id"],
                "description": change["description"],
                "status": status,
            }
        )

    line_count = content.count("\n") + (
        1 if content and not content.endswith("\n") else 0
    )

    return {
        "success": all_passed,
        "scenario_id": scenario_id,
        "approach": scenario["approach"],
        "fixture": scenario["fixture"],
        "change_set": change_set_key,
        "total_changes": len(changes),
        "passed": sum(1 for r in results if r["status"] == "PASS"),
        "failed": sum(1 for r in results if r["status"] != "PASS"),
        "line_count": line_count,
        "details": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Verify benchmark scenario results")
    parser.add_argument("scenario_id", help="Scenario ID (e.g., S01)")
    parser.add_argument("--fixture-path", help="Override fixture file path")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = verify_scenario(args.scenario_id, args.fixture_path)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["success"] else 1

    # Human-readable output
    status = "PASS" if result["success"] else "FAIL"
    print(f"\n{'=' * 60}")
    print(f"Scenario: {result.get('scenario_id', 'N/A')} [{status}]")
    print(f"Approach: {result.get('approach', 'N/A')}")
    print(f"Fixture:  {result.get('fixture', 'N/A')}")
    print(
        f"Changes:  {result.get('passed', 0)}/{result.get('total_changes', 0)} passed"
    )
    print(f"Lines:    {result.get('line_count', 'N/A')}")
    print(f"{'=' * 60}")

    for detail in result.get("details", []):
        icon = "+" if detail["status"] == "PASS" else "x"
        print(
            f"  [{icon}] {detail['change_id']}: {detail['description']} -> {detail['status']}"
        )

    print()
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
