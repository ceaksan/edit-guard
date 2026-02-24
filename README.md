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

Tracks consecutive Edit tool calls on the same file. Warns after 3 (configurable) and escalates after 5.

```
[edit-guard] WARNING: 3 consecutive Edits on /src/components/App.tsx
  Consider switching to a single Write (for files < 500 lines)
  or generating a Python/sed script (for larger files).
```

### F2: Post-Write Line Count Verification

Compares written content against the file's previously known line count. Detects significant drops that indicate content loss.

```
[edit-guard] ALERT: Write reduced /src/pages/index.astro from 500 to 280 lines (-220 lines, -44%)
  This may indicate content loss ("lost in the middle").
  Please verify the complete file content was preserved.
```

### F3: Disk Mismatch Detection

After Write, compares the intended content with what's actually on disk. Catches cases where formatters or hooks modify the file.

```
[edit-guard] WARNING: Write content (100 lines) differs from file on disk (111 lines)
  A formatter or hook may have modified the file after writing.
```

## Configuration

Environment variables:

| Variable               | Default | Description                                |
| ---------------------- | ------- | ------------------------------------------ |
| `EDIT_GUARD_WARN`      | `3`     | Sequential edit warning threshold          |
| `EDIT_GUARD_LINE_DROP` | `0.2`   | Line drop percentage threshold (0.2 = 20%) |
| `EDIT_GUARD_MIN_LINES` | `10`    | Minimum lines lost to trigger warning      |

## How It Works

- Runs as a `PostToolUse` hook on `Read`, `Edit`, and `Write` operations
- Persists state to `.state/edit-state.json` (gitignored)
- State resets on session change
- Exit 0 = all checks pass, Exit 2 = warning via stderr

## Decision Matrix

When should you use which editing approach?

| File Size     | Changes | Recommended                          |
| ------------- | ------- | ------------------------------------ |
| Any           | 1-2     | Sequential Edit                      |
| < 300 lines   | 3+      | Atomic Write (Read once, Write once) |
| 300-500 lines | 3+      | Bottom-up Edit or Script Generation  |
| 500+ lines    | 3+      | Script Generation                    |
| 1000+ lines   | Any 3+  | Script Generation or Diff/Patch      |

## Testing

```bash
python3 -m pytest tests/ -v
```

## Related

- [turkish-diacritics](https://github.com/ceaksan/turkish-diacritics) - Claude Code plugin for Turkish character validation
- [Claude Code Hooks Documentation](https://docs.anthropic.com/en/docs/claude-code/hooks)

## License

MIT
