# Next Task

## Title
Send the task to the Claude API via the Anthropic SDK and print the response

## Why
GOAL.md v0 — "Calls Claude API (`anthropic` SDK), prints response"; reads `ANTHROPIC_API_KEY` from env; default model `claude-sonnet-4-6`

## Acceptance
- [ ] `pyproject.toml` adds `anthropic>=0.40` to `[project] dependencies` (use the latest stable major; pin only the lower bound)
- [ ] `src/workbuddy/cli.py`: when invoked with a `<task>`, calls `anthropic.Anthropic().messages.create(model="claude-sonnet-4-6", max_tokens=1024, messages=[{"role":"user","content":<task>}])` and prints the response's text content to stdout, then exits 0
- [ ] If `ANTHROPIC_API_KEY` is missing/empty, print a clear one-line error to stderr (e.g. `error: ANTHROPIC_API_KEY environment variable is not set`) and exit non-zero — do NOT raise an unhandled exception
- [ ] Existing missing-`<task>`-arg behaviour preserved (argparse usage on stderr, non-zero exit)
- [ ] `tests/test_cli.py` is updated so the happy-path test stubs out the SDK (`monkeypatch.setattr` on `workbuddy.cli` to inject a fake `Anthropic` class whose `.messages.create()` returns an object with `content=[type("X",(),{"text":"hi"})()]`) and asserts that the stub's text appears on stdout. Tests MUST NOT make a real network call and MUST pass without `ANTHROPIC_API_KEY` set
- [ ] Add a missing-key test: with `ANTHROPIC_API_KEY` unset (use `monkeypatch.delenv(..., raising=False)`) and a task arg, `main` exits non-zero and prints to stderr
- [ ] Keep the module-invocation subprocess test, but stub the SDK at the `workbuddy.cli` module level (e.g. via a `WORKBUDDY_FAKE_SDK=1` env flag wired in cli.py, OR drop this test if stubbing through subprocess is awkward — at the Coder's discretion)
- [ ] `python -m pytest` passes locally with no network and no `ANTHROPIC_API_KEY`
- [ ] Total project LOC remains well under the 500-LOC v0 ceiling from GOAL.md

## Files likely involved
- pyproject.toml
- src/workbuddy/cli.py
- tests/test_cli.py
