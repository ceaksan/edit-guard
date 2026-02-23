#!/usr/bin/env python3
"""
Benchmark Result Recorder

Records the result of a benchmark run. Called after each scenario test.

Usage:
  python record.py <scenario_id> --run <run_number> \
    --success <true|false> \
    --tool_calls <N> \
    --tokens_in <N> --tokens_out <N> \
    --duration_s <seconds> \
    [--failure_mode <description>] \
    [--retries <N>] \
    [--notes <text>]

Example:
  python record.py S01 --run 1 --success true --tool_calls 6 \
    --tokens_in 15000 --tokens_out 3000 --duration_s 45.2

Results are appended to results/<scenario_id>.json
"""

import argparse
import json
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")


def record_result(args) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)

    result_file = os.path.join(RESULTS_DIR, f"{args.scenario_id}.json")

    # Load existing results or create new
    if os.path.isfile(result_file):
        with open(result_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"scenario_id": args.scenario_id, "runs": []}

    run = {
        "run": args.run,
        "timestamp": datetime.now().isoformat(),
        "success": args.success == "true",
        "tool_calls": args.tool_calls,
        "tokens_in": args.tokens_in,
        "tokens_out": args.tokens_out,
        "tokens_total": args.tokens_in + args.tokens_out,
        "duration_s": args.duration_s,
        "retries": args.retries or 0,
        "failure_mode": args.failure_mode or None,
        "notes": args.notes or None,
    }

    data["runs"].append(run)

    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Recorded run {args.run} for {args.scenario_id} -> {result_file}")


def main():
    parser = argparse.ArgumentParser(description="Record benchmark result")
    parser.add_argument("scenario_id", help="Scenario ID (e.g., S01)")
    parser.add_argument("--run", type=int, required=True, help="Run number (1, 2, 3)")
    parser.add_argument("--success", required=True, choices=["true", "false"])
    parser.add_argument("--tool_calls", type=int, required=True)
    parser.add_argument("--tokens_in", type=int, required=True)
    parser.add_argument("--tokens_out", type=int, required=True)
    parser.add_argument("--duration_s", type=float, required=True)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--failure_mode", type=str, default=None)
    parser.add_argument("--notes", type=str, default=None)
    args = parser.parse_args()

    record_result(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
