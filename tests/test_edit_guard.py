#!/usr/bin/env python3
"""Tests for edit-guard hook."""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks"))
import edit_guard


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    """Use a temp directory for state file."""
    state_dir = str(tmp_path / ".state")
    state_file = str(tmp_path / ".state" / "edit-state.json")
    monkeypatch.setattr(edit_guard, "STATE_DIR", state_dir)
    monkeypatch.setattr(edit_guard, "STATE_FILE", state_file)
    yield


@pytest.fixture
def sample_file(tmp_path):
    """Create a sample file with 100 lines."""
    f = tmp_path / "sample.ts"
    content = "\n".join(f"// line {i}" for i in range(1, 101))
    f.write_text(content, encoding="utf-8")
    return str(f)


@pytest.fixture
def large_file(tmp_path):
    """Create a sample file with 500 lines."""
    f = tmp_path / "large.ts"
    content = "\n".join(f"// line {i}" for i in range(1, 501))
    f.write_text(content, encoding="utf-8")
    return str(f)


def make_hook_input(tool_name, file_path, session_id="test-session", **extra_input):
    """Build a hook input dict."""
    tool_input = {"file_path": file_path, **extra_input}
    return {
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": {"filePath": file_path, "success": True},
    }


def run_hook(hook_input, monkeypatch, capsys=None):
    """Simulate running the hook with given input on stdin."""
    monkeypatch.setattr(
        "sys.stdin", type(sys.stdin)(initial_value=json.dumps(hook_input))
    )
    return edit_guard.main()


# --- F1: Sequential Edit Counter ---


class TestSequentialEditCounter:
    def test_no_warning_under_threshold(self, sample_file, monkeypatch):
        """2 edits should not warn (threshold is 3)."""
        for _ in range(2):
            hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            code = edit_guard.main()
            assert code == 0

    def test_warning_at_threshold(self, sample_file, monkeypatch):
        """3 edits should trigger warning."""
        for i in range(3):
            hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            code = edit_guard.main()

        assert code == 2  # last one should warn

    def test_strong_warning_above_threshold(self, sample_file, monkeypatch):
        """5 edits should trigger ALERT."""
        for i in range(5):
            hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            code = edit_guard.main()

        assert code == 2

    def test_different_file_resets_counter(self, sample_file, tmp_path, monkeypatch):
        """Editing a different file should not affect the first file's counter."""
        other_file = str(tmp_path / "other.ts")
        with open(other_file, "w") as f:
            f.write("content\n" * 10)

        # 2 edits on sample_file
        for _ in range(2):
            hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            edit_guard.main()

        # 1 edit on other_file
        hook = make_hook_input("Edit", other_file, old_string="x", new_string="y")
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0  # only 1st edit on other_file

    def test_write_resets_counter(self, sample_file, monkeypatch):
        """Write should reset the edit counter for that file."""
        # 2 edits
        for _ in range(2):
            hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            edit_guard.main()

        # Write resets
        content = "\n".join(f"// line {i}" for i in range(1, 101))
        hook = make_hook_input("Write", sample_file, content=content)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        edit_guard.main()

        # Next edit should be count=1
        hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0

    def test_session_change_resets_state(self, sample_file, monkeypatch):
        """Changing session_id should reset all state."""
        # 2 edits in session A
        for _ in range(2):
            hook = make_hook_input(
                "Edit", sample_file, session_id="A", old_string="x", new_string="y"
            )
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            edit_guard.main()

        # Switch to session B, should reset
        hook = make_hook_input(
            "Edit", sample_file, session_id="B", old_string="x", new_string="y"
        )
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0  # count=1 in new session


# --- F2: Post-Write Line Count Verification ---


class TestLineCountVerification:
    def test_no_warning_normal_write(self, sample_file, monkeypatch):
        """Write with same line count should not warn."""
        # Read first to record line count
        hook = make_hook_input("Read", sample_file)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        edit_guard.main()

        # Write with same content
        content = "\n".join(f"// line {i}" for i in range(1, 101))
        with open(sample_file, "w") as f:
            f.write(content)
        hook = make_hook_input("Write", sample_file, content=content)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0

    def test_warning_significant_line_drop(self, large_file, monkeypatch):
        """Write that drops 40% of lines should warn."""
        # Read first to record 500 lines
        hook = make_hook_input("Read", large_file)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        edit_guard.main()

        # Write only 300 lines (40% drop)
        short_content = "\n".join(f"// line {i}" for i in range(1, 301))
        with open(large_file, "w") as f:
            f.write(short_content)
        hook = make_hook_input("Write", large_file, content=short_content)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 2

    def test_no_warning_small_drop(self, sample_file, monkeypatch):
        """Write that drops only 5 lines (5%) should not warn."""
        # Read first
        hook = make_hook_input("Read", sample_file)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        edit_guard.main()

        # Write 95 lines (5% drop, only 5 lines lost)
        content = "\n".join(f"// line {i}" for i in range(1, 96))
        with open(sample_file, "w") as f:
            f.write(content)
        hook = make_hook_input("Write", sample_file, content=content)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0  # 5 lines < MIN_LINES_LOST (10)

    def test_no_warning_without_prior_read(self, tmp_path, monkeypatch):
        """Write without prior Read should not crash or warn about line drop."""
        new_file = str(tmp_path / "new.ts")
        content = "// new file\n" * 10
        with open(new_file, "w") as f:
            f.write(content)
        hook = make_hook_input("Write", new_file, content=content)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0


# --- F3: Disk Mismatch Detection ---


class TestDiskMismatch:
    def test_warning_when_disk_differs(self, sample_file, monkeypatch):
        """If disk content differs significantly from written content, warn."""
        content_100_lines = "\n".join(f"// line {i}" for i in range(1, 101))
        # But disk has been modified by a formatter (say 110 lines)
        disk_content = "\n".join(f"// line {i}" for i in range(1, 112))
        with open(sample_file, "w") as f:
            f.write(disk_content)

        hook = make_hook_input("Write", sample_file, content=content_100_lines)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 2  # disk has 111 lines, content has 100


# --- Edge Cases ---


class TestEdgeCases:
    def test_empty_stdin(self, monkeypatch):
        """Empty stdin should exit cleanly."""
        monkeypatch.setattr("sys.stdin", _stdin_raw(""))
        code = edit_guard.main()
        assert code == 0

    def test_invalid_json(self, monkeypatch):
        """Invalid JSON should exit cleanly."""
        monkeypatch.setattr("sys.stdin", _stdin_raw("{invalid"))
        code = edit_guard.main()
        assert code == 0

    def test_binary_file_skipped(self, tmp_path, monkeypatch):
        """Binary files should be skipped."""
        img = str(tmp_path / "image.png")
        with open(img, "wb") as f:
            f.write(b"\x89PNG")
        hook = make_hook_input("Edit", img, old_string="x", new_string="y")
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0

    def test_failed_tool_response_skipped(self, sample_file, monkeypatch):
        """Failed tool responses should be skipped."""
        hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
        hook["tool_response"] = {"success": False}
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0

    def test_no_file_path(self, monkeypatch):
        """Missing file_path should exit cleanly."""
        hook = {
            "session_id": "test",
            "tool_name": "Edit",
            "tool_input": {},
            "tool_response": {"success": True},
        }
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0


# --- Helpers ---

import io


def _stdin(hook_input: dict) -> io.StringIO:
    return io.StringIO(json.dumps(hook_input))


def _stdin_raw(text: str) -> io.StringIO:
    return io.StringIO(text)
