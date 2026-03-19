# edit-guard - Architecture

Claude Code plugin that enforces safe file editing practices for AI agents by monitoring Read/Edit/Write tool operations.

<!--
Living Architecture Template v1.0
Source: https://github.com/ceaksan/living-architecture
Depth: L1 (all sections)
Last verified: 2026-03-19
-->

## Stack & Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| python  | 3.12+   | Runtime (stdlib only, no external deps) |
| pytest  | 9.x     | Test framework |

### Infrastructure

| Layer | Technology | Detail |
|-------|-----------|--------|
| Runtime | Claude Code hooks | PostToolUse hook on Read/Edit/Write |
| State | JSON file | `.state/edit-state.json` (gitignored) |
| Distribution | Claude Code plugin system | `.claude-plugin/plugin.json` manifest |

## Module Map

```
edit-guard/
├── hooks/
│   ├── edit_guard.py       # Main hook script (all detection logic)
│   ├── hooks.json          # Hook configuration (PostToolUse matcher)
│   └── .state/             # Runtime state persistence (gitignored)
├── tests/
│   └── test_edit_guard.py  # 25 tests covering all features + edge cases
├── benchmark/
│   ├── scenarios.json      # 20 benchmark scenarios (5 approaches x 4 change sets)
│   ├── record.py           # CLI to record benchmark run results
│   ├── analyze.py          # Result aggregation and summary tables
│   ├── verify.py           # Scenario change verification
│   ├── fixtures/           # Test files (300-line and 1000-line TSX)
│   ├── scenarios/          # Scenario definitions
│   └── results/            # Benchmark results (1 JSON per scenario)
├── .claude-plugin/
│   └── plugin.json         # Plugin metadata and manifest
├── README.md               # Documentation
├── architecture.md         # This file
└── LICENSE                 # MIT
```

~1,500 lines of code. No external dependencies beyond pytest for testing.

## Data Flow

```
Claude Code Tool Call (Read/Edit/Write)
  |
  v
PostToolUse Hook Trigger (hooks.json matcher: "Read|Edit|Write")
  |
  v
edit_guard.py (stdin: JSON hook input)
  |
  ├── Load state from .state/edit-state.json
  ├── Check session_id (reset on change)
  ├── Dispatch by tool_name:
  │   ├── Read  -> record file line count
  │   ├── Edit  -> increment counter, check thresholds, recommend approach
  │   └── Write -> check line drop, check disk mismatch, reset counter
  ├── Save state
  └── Exit:
      ├── 0 = pass (+ optional non-blocking warning on stderr)
      └── 2 = blocking alert (stderr feedback, operation blocked)
```

## Data Model

| Store | Purpose |
|-------|---------|
| `.state/edit-state.json` | Per-session, per-file tracking of consecutive edits and known line counts |

State schema:

```json
{
  "session_id": "string",
  "files": {
    "/path/to/file": {
      "consecutive_edits": 0,
      "known_lines": 100
    }
  }
}
```

State resets on session change. Gitignored to avoid cross-session contamination.

## Configuration & Environment

| Variable | Default | Purpose | Secret |
|----------|---------|---------|--------|
| `EDIT_GUARD_WARN` | `3` | Sequential edit warning threshold (non-blocking) | No |
| `EDIT_GUARD_ALERT` | `5` | Sequential edit blocking threshold | No |
| `EDIT_GUARD_LINE_DROP` | `0.2` | Line drop percentage to trigger content loss alert | No |
| `EDIT_GUARD_MIN_LINES` | `10` | Minimum lines lost to trigger content loss alert | No |

All values are read at hook invocation time. No secrets.

## Security

- [x] No network access (pure local file operations)
- [x] No user input beyond Claude Code hook stdin (trusted source)
- [x] State file is session-scoped and gitignored
- [x] Binary files skipped by extension allowlist
- [x] Graceful handling of malformed input (exit 0, no crash)

## Constraints & Trade-offs

| Decision | Reason | Trade-off |
|----------|--------|-----------|
| stdlib only (no deps) | Zero install friction, works anywhere Python 3.12+ exists | No rich CLI, no structured logging |
| File-based state | Simple, no daemon process, survives hook restarts | Slight I/O on every tool call |
| Exit code signaling | Claude Code hook contract (0=pass, 2=block) | Limited to binary pass/block per check |
| Separate warn/alert thresholds | Warnings inform without disrupting flow | Agent may ignore non-blocking warnings |
| Tiered disk mismatch (F3) | Small formatter diffs (6-50 lines) are non-blocking, large diffs (50+) block | 50-line threshold is heuristic, not content-aware |
| Edit-count-aware recommendations | High edit counts (>5) escalate to script/diff recommendations | Threshold is fixed, not adaptive to file complexity |
| Line count heuristic for content loss | Simple, no content diffing needed | Cannot detect reordering or subtle truncation |

## Known Tech Debt

- No configurable file extension allowlist (hardcoded binary extensions)
- No per-directory or per-project threshold overrides
- Disk mismatch threshold (50 lines) is a fixed heuristic, not percentage-based
- Benchmark results need more runs for statistical significance (currently 1 run per scenario)
- No integration test that runs the hook as an actual subprocess with stdin piping

## Code Hotspots

| File | Changes | Risk |
|------|---------|------|
| `hooks/edit_guard.py` | High | All detection logic in single file |
| `hooks/hooks.json` | Low | Rarely changes, simple matcher config |
| `tests/test_edit_guard.py` | Medium | Must stay in sync with hook logic |
| `benchmark/scenarios.json` | Low | Stable after initial definition |
