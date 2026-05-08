# Next Task

## Title
Persist a preferred default model in `~/.workbuddy/config.json`

## Why
GOAL.md v0.1 — "Persistent local state (config, history) under `~/.workbuddy/`". This is the smallest useful slice: a config file with a single `default_model` key, so users don't have to type `--model X` on every invocation. History (jsonl) is intentionally deferred to a follow-up round to keep this Coder pass small

## Acceptance
- [ ] `src/workbuddy/cli.py` adds a helper `_load_config_default_model() -> str` that returns the model id to use as the argparse default. Resolution order:
  1. Read JSON from `_log_path().parent / "config.json"` (i.e. `$WORKBUDDY_HOME/config.json` if set, else `~/.workbuddy/config.json`)
  2. If the file does not exist → return `DEFAULT_MODEL` silently
  3. If the file exists and parses and `data["default_model"]` is a non-empty string → return that string
  4. If the file exists but is invalid JSON OR `default_model` is missing/wrong type → print a one-line warning to stderr (e.g. `warning: ignoring malformed config.json: <reason>`) and return `DEFAULT_MODEL`
- [ ] Use **stdlib only** (`json` module). Do NOT add `tomli`/`tomllib` — staying on JSON keeps Python 3.10 support intact
- [ ] `_build_parser()` calls `_load_config_default_model()` to compute the `--model` argparse default. The help text continues to read `Claude model id (default: <effective-default>)` — i.e. it reflects the config-resolved default, not the hardcoded `DEFAULT_MODEL`. (Implementation hint: capture the resolved value once, reuse in both `default=` and `help=`)
- [ ] Explicit `--model X` on the command line still wins over the config file (argparse precedence — should be automatic if `default=` is set correctly)
- [ ] `tests/test_cli.py` adds three tests:
  - **config_default_model is honored**: with `(tmp_path / "config.json").write_text('{"default_model": "claude-opus-4-7"}')` and the stub SDK, calling `main(["task"])` (no `--model` flag) records `model="claude-opus-4-7"` in the stub
  - **explicit --model overrides config**: with the same config.json present, calling `main(["--model", "claude-haiku-4-5", "task"])` records `model="claude-haiku-4-5"`
  - **malformed config falls back to default and warns**: write `(tmp_path / "config.json").write_text("not json {")` and assert `main(["task"])` records `model="claude-sonnet-4-6"` AND stderr contains `warning`
- [ ] All 16 existing tests still pass unchanged. The autouse `_isolate_workbuddy_home` fixture redirects to `tmp_path`; existing tests do NOT create a config.json, so they still observe `DEFAULT_MODEL` as before
- [ ] `README.md` "Usage" section gains a one-line note immediately after the `--model` example: explaining that a default can be persisted in `~/.workbuddy/config.json` with shape `{"default_model": "<model-id>"}`. Keep it terse — one paragraph or one fenced JSON block, not both
- [ ] `python -m pytest` passes (no network, no `ANTHROPIC_API_KEY`)
- [ ] Total project Python LOC stays under 500

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
