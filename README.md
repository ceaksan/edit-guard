# edit-guard

A Claude Code plugin that enforces safe file editing practices for AI agents.

Tracks sequential edits, verifies line counts after writes, and detects content loss ("lost in the middle").

## Problem

AI coding agents (Claude Code, Cursor, Copilot) break in predictable ways when editing files:

| Failure Mode           | When It Happens                  | Impact                             |
| ---------------------- | -------------------------------- | ---------------------------------- |
| **Line drift**         | 3+ sequential Edits on same file | Edit tool can't find target string |
| **Lost in the middle** | Write on 500+ line files         | LLM truncates middle content       |
| **Formatter mismatch** | Edit after linter/prettier runs  | Exact string match fails           |

edit-guard catches these before they cause problems.

## What happens without it

A typical failure on a 400-line React component:

1. Claude makes Edit #1 (line 50). Works.
2. A formatter runs, reformats the file. Line numbers shift.
3. Claude makes Edit #2 (line 120). The exact string match fails because the formatter changed whitespace.
4. Claude retries with a slightly different match. Works, but now the internal line map is stale.
5. Claude makes Edit #3 (line 200). Targets a string that no longer exists at that position. Fails.
6. Claude falls back to a full Write. Regenerates the entire file. Middle 80 lines are silently dropped.
7. Build passes. Tests pass. Content is gone. You find out in production.

edit-guard stops this at step 3 with a warning and at step 5 with a block, before content loss happens.

## Installation

```bash
# Clone the repo
git clone https://github.com/ceaksan/edit-guard.git

# Install as Claude Code plugin
claude plugin install /path/to/edit-guard
```

Or add manually to your project's `.claude/settings.json`:

```json
{
  "plugins": ["/path/to/edit-guard"]
}
```

## Features

### F1: Sequential Edit Counter

Tracks consecutive Edit tool calls on the same file. Issues a **non-blocking warning** after 3 edits (configurable) and a **blocking alert** after 5.

**Warning (non-blocking, exit 0):** The agent sees the feedback but continues working.

```
[edit-guard] WARNING: 3 consecutive Edits on /src/components/App.tsx
  File is 180 lines. Use a single Write (single Read + single Write) for 3+ changes on small files.
```

**Alert (blocking, exit 2):** The edit is blocked, forcing the agent to change approach.

```
[edit-guard] ALERT: 5 consecutive Edits on /src/components/App.tsx
  This is well above the safe limit. File is 180 lines. Use a single Write (single Read + single Write) for 5+ changes on small files.
  Sequential Edits cause line drift, match failures, and wasted tokens.
```

Recommendations are context-aware based on actual file size:

| File Size     | Recommendation                           |
| ------------- | ---------------------------------------- |
| < 300 lines   | Atomic Write (single Read + single Write)|
| 300-500 lines | Bottom-up Edit or Python script          |
| 500-1000      | Python script generation                 |
| 1000+ lines   | Python script or unified diff/patch      |

### F2: Post-Write Line Count Verification

Compares written content against the file's previously known line count. Detects significant drops that indicate content loss. This is always a **blocking alert**.

```
[edit-guard] ALERT: Write reduced /src/pages/index.astro from 500 to 280 lines (-220 lines, -44%)
  This may indicate content loss ("lost in the middle").
  Please verify the complete file content was preserved.
```

### F3: Disk Mismatch Detection

After Write, compares the intended content with what's actually on disk. Catches cases where formatters or hooks modify the file. This is a **non-blocking warning**.

```
[edit-guard] WARNING: Write content (100 lines) differs from file on disk (111 lines)
  A formatter or hook may have modified the file after writing.
```

## Exit Code Behavior

| Severity | Exit Code | Effect                                    | When                          |
| -------- | --------- | ----------------------------------------- | ----------------------------- |
| WARNING  | 0         | Feedback to agent, does not block          | Sequential edits at threshold |
| ALERT    | 2         | Blocks the operation, agent must adapt     | Sequential edits well above threshold, content loss detected |

## Configuration

Environment variables:

| Variable               | Default | Description                                |
| ---------------------- | ------- | ------------------------------------------ |
| `EDIT_GUARD_WARN`      | `3`     | Sequential edit warning threshold          |
| `EDIT_GUARD_ALERT`     | `5`     | Sequential edit blocking threshold         |
| `EDIT_GUARD_LINE_DROP` | `0.2`   | Line drop percentage threshold (0.2 = 20%) |
| `EDIT_GUARD_MIN_LINES` | `10`    | Minimum lines lost to trigger warning      |

## How It Works

- Runs as a `PostToolUse` hook on `Read`, `Edit`, and `Write` operations
- Persists state to `.state/edit-state.json` (gitignored)
- State resets on session change
- Tracks per-file: consecutive edit count, known line count
- Binary files are automatically skipped

## Decision Matrix

When should you use which editing approach?

| File Size     | Changes | Recommended                          |
| ------------- | ------- | ------------------------------------ |
| Any           | 1-2     | Sequential Edit                      |
| < 300 lines   | 3+      | Atomic Write (single Read + single Write) |
| 300-500 lines | 3+      | Bottom-up Edit or Script Generation  |
| 500+ lines    | 3+      | Script Generation                    |
| 1000+ lines   | Any 3+  | Script Generation or Diff/Patch      |

## Testing

```bash
python3 -m pytest tests/ -v
```

31 tests covering all features, smart recommendations, and edge cases.

## Related

- [turkish-diacritics](https://github.com/ceaksan/turkish-diacritics) - Claude Code plugin for Turkish character validation
- [Claude Code Hooks Documentation](https://docs.anthropic.com/en/docs/claude-code/hooks)

## License

MIT
