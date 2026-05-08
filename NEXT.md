# Next Task

## Title
Cover remaining helper edge cases with direct unit tests for `_extract_text` and `_log_run`

## Why
GOAL.md v0 — BACKLOG line "Unit tests for CLI parsing and log writer". The 9 existing tests already cover argparse parsing, the SDK happy path, `--model`, missing-key, API errors, and log append/skip behaviour. Remaining gaps live inside the helpers — close them so v0 lands with full coverage of the small surface

## Acceptance
- [x] Import the helpers directly: `from workbuddy.cli import _extract_text, _log_run, MAX_LOGGED_RESPONSE_CHARS`
- [x] Add a test for `_extract_text` covering at minimum these shapes (use `types.SimpleNamespace` to fake the response and content blocks):
  - response with multiple text blocks → concatenated string
  - response where one block lacks a `.text` attribute (or `.text is None`) → that block is silently skipped, others kept
  - response with empty content list → returns `""`
  - response whose `.content` is `None` (defensively) → returns `""`
- [x] Add a test for `_log_run` truncation: write a string of length `MAX_LOGGED_RESPONSE_CHARS + 100`, call `_log_run("t", that_string)`, and assert the resulting `log.md` contains `"... [truncated]"` and does NOT contain the final 100 chars of the input
- [x] Add a test for `_log_run` nested-directory creation: set `WORKBUDDY_HOME` to `tmp_path / "deep" / "nested" / "wb"` (parent dirs do NOT exist), call `_log_run`, and assert the file at `<that path>/log.md` exists with the entry written
- [x] Add a test for `_log_run` OSError tolerance: set `WORKBUDDY_HOME` to a path that already exists as a regular file (so the implicit `mkdir` will raise `FileExistsError`, a subclass of `OSError`); assert `_log_run` returns `None` (does NOT raise), prints `warning:` to stderr, and the CLI as a whole would still continue (test the helper in isolation here)
- [x] No production-code changes to `src/workbuddy/cli.py`. If a test reveals a real bug, the Coder may fix it but MUST call it out explicitly in `LOG.md`
- [x] All existing 9 tests still pass; new tests added bring the total upward without modifying old tests
- [x] `python -m pytest` passes with no network and no `ANTHROPIC_API_KEY`
- [x] Total project Python LOC stays under 500

## Files likely involved
- tests/test_cli.py
