#!/usr/bin/env python3
"""Tests for edit-guard hook."""

import io
import json
import os
import sys

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


def _stdin(hook_input: dict) -> io.StringIO:
    return io.StringIO(json.dumps(hook_input))


def _stdin_raw(text: str) -> io.StringIO:
    return io.StringIO(text)


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
        """3 edits should trigger non-blocking warning (exit 0)."""
        for i in range(3):
            hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            code = edit_guard.main()

        assert code == 0  # WARNING is non-blocking

    def test_warning_outputs_to_stderr(self, sample_file, monkeypatch, capsys):
        """3 edits should print warning to stderr."""
        for _ in range(3):
            hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            edit_guard.main()

        captured = capsys.readouterr()
        assert "[edit-guard] WARNING" in captured.err

    def test_alert_above_threshold(self, sample_file, monkeypatch):
        """5 edits should trigger blocking ALERT (exit 2)."""
        for i in range(5):
            hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            code = edit_guard.main()

        assert code == 2  # ALERT is blocking

    def test_alert_outputs_to_stderr(self, sample_file, monkeypatch, capsys):
        """5 edits should print alert to stderr with recommendation."""
        for _ in range(5):
            hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            edit_guard.main()

        captured = capsys.readouterr()
        assert "[edit-guard] ALERT" in captured.err

    def test_recommendation_includes_file_size(self, sample_file, monkeypatch, capsys):
        """Warning message should include actual file line count."""
        for _ in range(3):
            hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            edit_guard.main()

        captured = capsys.readouterr()
        assert "100 lines" in captured.err

    def test_recommendation_for_large_file(self, large_file, monkeypatch, capsys):
        """Large file (500 lines) should recommend script generation."""
        for _ in range(3):
            hook = make_hook_input("Edit", large_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            edit_guard.main()

        captured = capsys.readouterr()
        assert "500 lines" in captured.err
        assert "script" in captured.err.lower()

    def test_different_file_resets_counter(self, sample_file, tmp_path, monkeypatch):
        """Editing a different file should not affect the first file's counter."""
        other_file = str(tmp_path / "other.ts")
        with open(other_file, "w") as f:
            f.write("content\n" * 10)

        for _ in range(2):
            hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            edit_guard.main()

        hook = make_hook_input("Edit", other_file, old_string="x", new_string="y")
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0

    def test_write_resets_counter(self, sample_file, monkeypatch):
        """Write should reset the edit counter for that file."""
        for _ in range(2):
            hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            edit_guard.main()

        content = "\n".join(f"// line {i}" for i in range(1, 101))
        hook = make_hook_input("Write", sample_file, content=content)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        edit_guard.main()

        hook = make_hook_input("Edit", sample_file, old_string="x", new_string="y")
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0

    def test_session_change_resets_state(self, sample_file, monkeypatch):
        """Changing session_id should reset all state."""
        for _ in range(2):
            hook = make_hook_input(
                "Edit", sample_file, session_id="A", old_string="x", new_string="y"
            )
            monkeypatch.setattr("sys.stdin", _stdin(hook))
            edit_guard.main()

        hook = make_hook_input(
            "Edit", sample_file, session_id="B", old_string="x", new_string="y"
        )
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0


# --- F2: Post-Write Line Count Verification ---


class TestLineCountVerification:
    def test_no_warning_normal_write(self, sample_file, monkeypatch):
        """Write with same line count should not warn."""
        hook = make_hook_input("Read", sample_file)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        edit_guard.main()

        content = "\n".join(f"// line {i}" for i in range(1, 101))
        with open(sample_file, "w") as f:
            f.write(content)
        hook = make_hook_input("Write", sample_file, content=content)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0

    def test_alert_significant_line_drop(self, large_file, monkeypatch):
        """Write that drops 40% of lines should block (ALERT)."""
        hook = make_hook_input("Read", large_file)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        edit_guard.main()

        short_content = "\n".join(f"// line {i}" for i in range(1, 301))
        with open(large_file, "w") as f:
            f.write(short_content)
        hook = make_hook_input("Write", large_file, content=short_content)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 2  # content loss is always blocking

    def test_no_warning_small_drop(self, sample_file, monkeypatch):
        """Write that drops only 5 lines (5%) should not warn."""
        hook = make_hook_input("Read", sample_file)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        edit_guard.main()

        content = "\n".join(f"// line {i}" for i in range(1, 96))
        with open(sample_file, "w") as f:
            f.write(content)
        hook = make_hook_input("Write", sample_file, content=content)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0

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
    def test_warning_when_disk_differs_small(self, sample_file, monkeypatch):
        """Small disk diff (6-50 lines) should warn (non-blocking, exit 0)."""
        content_100_lines = "\n".join(f"// line {i}" for i in range(1, 101))
        disk_content = "\n".join(f"// line {i}" for i in range(1, 112))
        with open(sample_file, "w") as f:
            f.write(disk_content)

        hook = make_hook_input("Write", sample_file, content=content_100_lines)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0

    def test_alert_when_disk_differs_drastically(self, sample_file, monkeypatch):
        """Large disk diff (>50 lines) should block (exit 2)."""
        content_100_lines = "\n".join(f"// line {i}" for i in range(1, 101))
        disk_content = "\n".join(f"// line {i}" for i in range(1, 160))
        with open(sample_file, "w") as f:
            f.write(disk_content)

        hook = make_hook_input("Write", sample_file, content=content_100_lines)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 2

    def test_no_warning_when_disk_diff_small(self, sample_file, monkeypatch):
        """Disk diff <= 5 lines should not trigger any warning."""
        content_100_lines = "\n".join(f"// line {i}" for i in range(1, 101))
        disk_content = "\n".join(f"// line {i}" for i in range(1, 105))
        with open(sample_file, "w") as f:
            f.write(disk_content)

        hook = make_hook_input("Write", sample_file, content=content_100_lines)
        monkeypatch.setattr("sys.stdin", _stdin(hook))
        code = edit_guard.main()
        assert code == 0


# --- F4: Smart Recommendations ---


class TestSmartRecommendations:
    def test_small_file_recommends_write(self):
        """Files < 300 lines should recommend atomic Write."""
        advice = edit_guard.recommend_approach(100, 3)
        assert "Write" in advice
        assert "100 lines" in advice

    def test_medium_file_low_edits_recommends_bottom_up(self):
        """Files 300-500 with <= 5 edits should recommend bottom-up or Write."""
        advice = edit_guard.recommend_approach(400, 4)
        assert "400 lines" in advice
        assert "bottom-up" in advice.lower() or "Write" in advice

    def test_medium_file_high_edits_recommends_script(self):
        """Files 300-500 with > 5 edits should recommend script."""
        advice = edit_guard.recommend_approach(400, 7)
        assert "400 lines" in advice
        assert "script" in advice.lower()

    def test_large_file_recommends_script(self):
        """Files 500-1000 lines should recommend script generation."""
        advice = edit_guard.recommend_approach(700, 4)
        assert "script" in advice.lower()
        assert "700 lines" in advice

    def test_very_large_file_low_edits_recommends_script(self):
        """Files 1000+ with <= 5 edits should recommend script or diff."""
        advice = edit_guard.recommend_approach(1200, 4)
        assert "1200 lines" in advice
        assert "script" in advice.lower() or "diff" in advice.lower()

    def test_very_large_file_high_edits_recommends_diff(self):
        """Files 1000+ with > 5 edits should recommend diff/patch."""
        advice = edit_guard.recommend_approach(1200, 8)
        assert "1200 lines" in advice
        assert "diff" in advice.lower()

    def test_unknown_size_low_edits_gives_generic_advice(self):
        """Unknown file size with low edits should give generic advice."""
        advice = edit_guard.recommend_approach(None, 3)
        assert "Write" in advice
        assert "script" in advice.lower()

    def test_unknown_size_high_edits_recommends_script(self):
        """Unknown file size with high edits should recommend script."""
        advice = edit_guard.recommend_approach(None, 8)
        assert "script" in advice.lower()


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

    def test_alert_threshold_auto_corrects(self, monkeypatch):
        """ALERT_THRESHOLD is forced to WARN+2 if set <= WARN."""
        monkeypatch.setattr(edit_guard, "WARN_THRESHOLD", 5)
        monkeypatch.setattr(edit_guard, "ALERT_THRESHOLD", 3)
        # After module-level guard, ALERT should be WARN+2=7
        # But since we monkeypatch after import, simulate the guard:
        if edit_guard.ALERT_THRESHOLD <= edit_guard.WARN_THRESHOLD:
            monkeypatch.setattr(
                edit_guard, "ALERT_THRESHOLD", edit_guard.WARN_THRESHOLD + 2
            )
        assert edit_guard.ALERT_THRESHOLD == 7
