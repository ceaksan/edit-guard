#!/usr/bin/env python3
"""
Edit Guard - Claude Code Plugin

Enforces safe file editing practices for AI agents.
Runs as a PostToolUse hook after Read/Edit/Write operations.

Features:
  F1: Sequential Edit counter - warns after N consecutive Edits on same file
  F2: Post-Write line count verification - detects unexpected line drops
  F3: Lost in the middle detection - catches content truncation

Exit 0 = pass, Exit 2 = warning (feedback to Claude via stderr).

Configuration (environment variables):
  EDIT_GUARD_WARN       - Sequential edit warning threshold (default: 3)
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
LINE_DROP_THRESHOLD = float(os.environ.get("EDIT_GUARD_LINE_DROP", "0.2"))
MIN_LINES_LOST = int(os.environ.get("EDIT_GUARD_MIN_LINES", "10"))


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


def handle_read(state: dict, file_path: str) -> list[str]:
    """On Read: record line count, no warnings."""
    line_count = count_file_lines(file_path)
    if line_count is not None:
        entry = get_file_entry(state, file_path)
        entry["known_lines"] = line_count
    return []


def handle_edit(state: dict, file_path: str) -> list[str]:
    """On Edit: increment counter, check threshold."""
    warnings = []
    entry = get_file_entry(state, file_path)

    # Record current line count if not known
    if entry["known_lines"] is None:
        line_count = count_file_lines(file_path)
        if line_count is not None:
            entry["known_lines"] = line_count

    entry["consecutive_edits"] += 1
    count = entry["consecutive_edits"]

    if count >= WARN_THRESHOLD + 2:
        warnings.append(
            f"ALERT: {count} consecutive Edits on {file_path}\n"
            f"  This is well above the safe limit. Use a single Write or generate a script instead.\n"
            f"  Sequential Edits cause line drift, match failures, and wasted tokens."
        )
    elif count >= WARN_THRESHOLD:
        warnings.append(
            f"WARNING: {count} consecutive Edits on {file_path}\n"
            f"  Consider switching to a single Write (for files < 500 lines)\n"
            f"  or generating a Python/sed script (for larger files)."
        )

    return warnings


def handle_write(state: dict, file_path: str, tool_input: dict) -> list[str]:
    """On Write: verify line counts, detect content loss."""
    warnings = []
    entry = get_file_entry(state, file_path)

    # Reset edit counter
    entry["consecutive_edits"] = 0

    # Get the content that was written
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
            warnings.append(
                f"ALERT: Write reduced {file_path} from {known} to {written_lines} lines "
                f"(-{lines_lost} lines, -{drop_pct:.0%})\n"
                f'  This may indicate content loss ("lost in the middle").\n'
                f"  Please verify the complete file content was preserved."
            )

    # F3: Verify written content matches disk
    disk_lines = count_file_lines(file_path)
    if disk_lines is not None and abs(disk_lines - written_lines) > 5:
        warnings.append(
            f"WARNING: Write content ({written_lines} lines) differs from "
            f"file on disk ({disk_lines} lines) for {file_path}\n"
            f"  A formatter or hook may have modified the file after writing."
        )

    # Update known lines to new value
    entry["known_lines"] = disk_lines if disk_lines is not None else written_lines

    return warnings


def main() -> int:
    # Read hook input from stdin
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return 0

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})
    tool_response = hook_input.get("tool_response", {})
    session_id = hook_input.get("session_id")

    # Only process successful operations
    if isinstance(tool_response, dict) and not tool_response.get("success", True):
        return 0

    # Get file path
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return 0

    # Skip binary/non-text files
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
        return 0

    # Load state
    state = load_state()

    # Reset state on session change
    if session_id and state.get("session_id") != session_id:
        state = {"session_id": session_id, "files": {}}

    # Dispatch by tool
    warnings = []
    if tool_name == "Read":
        warnings = handle_read(state, file_path)
    elif tool_name == "Edit":
        warnings = handle_edit(state, file_path)
    elif tool_name == "Write":
        warnings = handle_write(state, file_path, tool_input)

    # Save state
    save_state(state)

    # Output warnings
    if warnings:
        for w in warnings:
            print(f"[edit-guard] {w}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
