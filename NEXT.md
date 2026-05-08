# Next Task

## Title
Add `--model` flag to override the default Claude model

## Why
GOAL.md v0 — "Default model: `claude-sonnet-4-6`"; BACKLOG explicitly lists `--model` flag with that default

## Acceptance
- [ ] `src/workbuddy/cli.py` adds an argparse option `--model` accepting a string, with `default=DEFAULT_MODEL` (so `--model` is optional and defaults to `claude-sonnet-4-6`)
- [ ] `messages.create(...)` is called with `model=args.model` (not the hardcoded `DEFAULT_MODEL`); the global `DEFAULT_MODEL` constant remains as the default source
- [ ] The argparse `help=` string for `--model` mentions the default (e.g. `f"Claude model id (default: {DEFAULT_MODEL})"`)
- [ ] Existing happy-path test (`test_main_calls_anthropic_and_prints_response`) continues to pass unchanged — it already asserts `sent["model"] == "claude-sonnet-4-6"`, which will still be the default
- [ ] New test: invoking `main(["--model", "claude-opus-4-7", "task"])` with the stub SDK records `model="claude-opus-4-7"` in the stub's last_kwargs and exits 0
- [ ] `python -m pytest` passes locally with no network and no `ANTHROPIC_API_KEY`
- [ ] Total project Python LOC stays under 500

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
