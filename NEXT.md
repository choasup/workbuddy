# Next Task

## Title
Append every successful run to `~/.workbuddy/log.md` with a UTC timestamp

## Why
GOAL.md v0 — "Logs every run to `~/.workbuddy/log.md` with timestamp"

## Acceptance
- [x] After a successful API response, `cli.py` appends a markdown entry to `~/.workbuddy/log.md` containing: an ISO8601 UTC timestamp, the task input, and the printed response. Truncate the logged response to at most 4000 characters and append `... [truncated]` if it was longer
- [x] Entry format (suggested, Coder may tweak slightly): a `## <UTC timestamp>` header, a `**Task:**` line with the task, and the response in a fenced block. Each entry separated by a blank line. Use `>>>` instead of triple-backticks to avoid escaping headaches if needed — Coder's call
- [x] The log directory and parent directories are created if missing (`Path.mkdir(parents=True, exist_ok=True)`)
- [x] Logging failures (permission denied, disk full, etc.) MUST NOT crash the CLI — catch `OSError`, print a one-line warning to stderr, still exit 0 because the user already got their response
- [x] An env override `WORKBUDDY_HOME` is supported: when set, the log path is `$WORKBUDDY_HOME/log.md` instead of `~/.workbuddy/log.md`. This is the hook tests use; do NOT touch `$HOME` in tests
- [x] The missing-`ANTHROPIC_API_KEY` path does NOT write to the log
- [x] `tests/test_cli.py` adds: with stubbed SDK and `monkeypatch.setenv("WORKBUDDY_HOME", str(tmp_path))`, after `main(["hello"])` returns 0, `tmp_path / "log.md"` exists and contains both `"hello"` and the stubbed response text
- [x] `tests/test_cli.py` adds: calling `main` twice with the stubbed SDK appends — the resulting `log.md` contains two timestamped entries (count occurrences of the response text or of `## ` headers)
- [x] `tests/test_cli.py` adds: when `ANTHROPIC_API_KEY` is unset, `tmp_path / "log.md"` is NOT created
- [x] `python -m pytest` passes (no network, no real key)
- [x] Total project Python LOC stays under 500

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
