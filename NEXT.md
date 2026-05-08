# Next Task

## Title
Handle Anthropic SDK network and API errors gracefully (no stack traces to the user)

## Why
GOAL.md v0 stability requires the CLI to fail cleanly on transient network or API issues. The `ANTHROPIC_API_KEY` half of BACKLOG's "Error handling" task already shipped; this round covers the network/API half so the same backlog line can finally be marked done

## Acceptance
- [ ] `src/workbuddy/cli.py` wraps `client.messages.create(...)` in a `try` / `except anthropic.APIError` (the umbrella class — covers `APIConnectionError`, `APITimeoutError`, `APIStatusError`, etc.). On error: print a one-line message to stderr like `error: API call failed: <ExcClassName>: <message>` and return a non-zero exit code (use `2`)
- [ ] Pass `timeout=60.0` when constructing `Anthropic(...)` so a hung connection cannot stall the CLI forever
- [ ] On an API-error path, the `~/.workbuddy/log.md` file MUST NOT be created or appended (logging is success-only)
- [ ] `tests/test_cli.py` adds a test that injects a stub whose `messages.create(...)` raises a fake `APIError` subclass (e.g. `class _FakeAPIError(anthropic.APIError):  def __init__(self, msg="boom"): Exception.__init__(self, msg)` — this avoids the real SDK's required `request`/`body` kwargs). Assert: `main(["task"])` returns non-zero, stderr contains `API call failed`, and the log file is NOT created
- [ ] Existing 8 tests continue to pass unchanged
- [ ] `python -m pytest` passes locally with no network and no `ANTHROPIC_API_KEY` set
- [ ] Total project Python LOC stays under 500

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
