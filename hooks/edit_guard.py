#!/usr/bin/env python3
"""
Edit Guard - Claude Code Plugin

Enforces safe file editing practices for AI agents.
Runs as a PostToolUse hook after Read/Edit/Write operations.

Features:
  F1: Sequential Edit counter - warns after N consecutive Edits on same file
  F2: Post-Write line count verification - detects unexpected line drops
  F3: Lost in the middle detection - catches content truncation

Exit codes:
  0 = pass (warnings may be printed to stderr as non-blocking feedback)
  2 = blocking alert (hard stop, agent must change approach)

Configuration (environment variables):
  EDIT_GUARD_WARN       - Sequential edit warning threshold (default: 3)
  EDIT_GUARD_ALERT      - Sequential edit alert/block threshold (default: 5)
  EDIT_GUARD_LINE_DROP  - Line drop percentage threshold (default: 0.2 = 20%)
  EDIT_GUARD_MIN_LINES  - Minimum lines lost to trigger warning (default: 10)
"""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(SCRIPT_DIR, ".state")
STATE_FILE = os.path.join(STATE_DIR, "edit-state.json")

WARN_THRESHOLD = int(os.environ.get("EDIT_GUARD_WARN", "3"))
ALERT_THRESHOLD = int(os.environ.get("EDIT_GUARD_ALERT", "5"))
if ALERT_THRESHOLD <= WARN_THRESHOLD:
    ALERT_THRESHOLD = WARN_THRESHOLD + 2
LINE_DROP_THRESHOLD = float(os.environ.get("EDIT_GUARD_LINE_DROP", "0.2"))
MIN_LINES_LOST = int(os.environ.get("EDIT_GUARD_MIN_LINES", "10"))

# Exit codes
EXIT_OK = 0
EXIT_BLOCK = 2


def load_state() -> dict:
    """Load persisted state from disk."""
    if not os.path.isfile(STATE_FILE):
        return {"session_id": None, "files": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"session_id": None, "files": {}}


def save_state(state: dict) -> None:
    """Persist state to disk."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def count_file_lines(file_path: str) -> int | None:
    """Count lines in a file on disk. Returns None if file doesn't exist."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except (OSError, UnicodeDecodeError):
        return None


def get_file_entry(state: dict, file_path: str) -> dict:
    """Get or create a file entry in state."""
    if file_path not in state["files"]:
        state["files"][file_path] = {
            "consecutive_edits": 0,
            "known_lines": None,
        }
    return state["files"][file_path]


def recommend_approach(line_count: int | None, edit_count: int) -> str:
    """Return a context-aware recommendation based on file size and edit count."""
    if line_count is None:
        if edit_count <= 5:
            return (
                "Consider switching to a single Write (for files < 500 lines)\n"
                "  or generating a Python/sed script (for larger files)."
            )
        return (
            f"{edit_count} edits is excessive. Generate a Python script "
            f"to apply all changes in one pass."
        )

    if line_count < 300:
        return (
            f"File is {line_count} lines. Use a single Write "
            f"(Read + Write) to apply all {edit_count} changes at once."
        )
    elif line_count < 500:
        if edit_count <= 5:
            return (
                f"File is {line_count} lines. Use bottom-up Edit ordering "
                f"or a single Write to apply {edit_count} changes."
            )
        return (
            f"File is {line_count} lines with {edit_count} changes. "
            f"Generate a Python script to apply all changes in one pass."
        )
    elif line_count < 1000:
        return (
            f"File is {line_count} lines with {edit_count} changes. "
            f"Generate a Python script to apply all changes in one pass."
        )
    else:
        if edit_count <= 5:
            return (
                f"File is {line_count} lines with {edit_count} changes. "
                f"Generate a Python script or use unified diff/patch."
            )
        return (
            f"File is {line_count} lines with {edit_count} changes. "
            f"Use unified diff/patch for best reliability on large files."
        )


def handle_read(state: dict, file_path: str) -> tuple[list[str], list[str]]:
    """On Read: record line count, no warnings."""
    line_count = count_file_lines(file_path)
    if line_count is not None:
        entry = get_file_entry(state, file_path)
        entry["known_lines"] = line_count
    return [], []


def handle_edit(state: dict, file_path: str) -> tuple[list[str], list[str]]:
    """On Edit: increment counter, check threshold.

    Returns (warnings, alerts) where warnings are non-blocking and alerts block.
    """
    warnings = []
    alerts = []
    entry = get_file_entry(state, file_path)

    if entry["known_lines"] is None:
        line_count = count_file_lines(file_path)
        if line_count is not None:
            entry["known_lines"] = line_count

    entry["consecutive_edits"] += 1
    count = entry["consecutive_edits"]
    line_count = entry.get("known_lines")
    advice = recommend_approach(line_count, count)

    if count >= ALERT_THRESHOLD:
        alerts.append(
            f"ALERT: {count} consecutive Edits on {file_path}\n"
            f"  This is well above the safe limit. {advice}\n"
            f"  Sequential Edits cause line drift, match failures, and wasted tokens."
        )
    elif count >= WARN_THRESHOLD:
        warnings.append(
            f"WARNING: {count} consecutive Edits on {file_path}\n  {advice}"
        )

    return warnings, alerts


def handle_write(
    state: dict, file_path: str, tool_input: dict
) -> tuple[list[str], list[str]]:
    """On Write: verify line counts, detect content loss.

    Returns (warnings, alerts) where warnings are non-blocking and alerts block.
    """
    warnings = []
    alerts = []
    entry = get_file_entry(state, file_path)

    entry["consecutive_edits"] = 0

    content = tool_input.get("content", "")
    written_lines = content.count("\n") + (
        1 if content and not content.endswith("\n") else 0
    )

    # F2: Compare with known line count
    known = entry.get("known_lines")
    if known is not None and known > 0:
        lines_lost = known - written_lines
        drop_pct = lines_lost / known

        if lines_lost >= MIN_LINES_LOST and drop_pct >= LINE_DROP_THRESHOLD:
            alerts.append(
                f"ALERT: Write reduced {file_path} from {known} to {written_lines} lines "
                f"(-{lines_lost} lines, -{drop_pct:.0%})\n"
                f'  This may indicate content loss ("lost in the middle").\n'
                f"  Please verify the complete file content was preserved."
            )

    # F3: Verify written content matches disk (tiered severity)
    disk_lines = count_file_lines(file_path)
    if disk_lines is not None:
        disk_diff = abs(disk_lines - written_lines)
        if disk_diff > 50:
            alerts.append(
                f"ALERT: Write content ({written_lines} lines) differs drastically from "
                f"file on disk ({disk_lines} lines, delta {disk_diff}) for {file_path}\n"
                f"  A formatter or hook has heavily rewritten the file after writing.\n"
                f"  Verify the file content is correct before continuing."
            )
        elif disk_diff > 5:
            warnings.append(
                f"WARNING: Write content ({written_lines} lines) differs from "
                f"file on disk ({disk_lines} lines) for {file_path}\n"
                f"  A formatter or hook may have modified the file after writing."
            )

    entry["known_lines"] = disk_lines if disk_lines is not None else written_lines

    return warnings, alerts


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return EXIT_OK
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return EXIT_OK

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})
    tool_response = hook_input.get("tool_response", {})
    session_id = hook_input.get("session_id")

    if isinstance(tool_response, dict) and not tool_response.get("success", True):
        return EXIT_OK

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return EXIT_OK

    binary_extensions = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".pdf",
        ".zip",
    }
    _, ext = os.path.splitext(file_path)
    if ext.lower() in binary_extensions:
        return EXIT_OK

    state = load_state()

    if session_id and state.get("session_id") != session_id:
        state = {"session_id": session_id, "files": {}}

    warnings = []
    alerts = []

    if tool_name == "Read":
        warnings, alerts = handle_read(state, file_path)
    elif tool_name == "Edit":
        warnings, alerts = handle_edit(state, file_path)
    elif tool_name == "Write":
        warnings, alerts = handle_write(state, file_path, tool_input)

    save_state(state)

    # Alerts block (exit 2), warnings are non-blocking feedback (exit 0)
    if alerts:
        for a in alerts:
            print(f"[edit-guard] {a}", file=sys.stderr)
        return EXIT_BLOCK

    if warnings:
        for w in warnings:
            print(f"[edit-guard] {w}", file=sys.stderr)
        return EXIT_OK

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
