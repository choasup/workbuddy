# Next Task

## Title
Append per-run history to `~/.workbuddy/history.jsonl` and soften the config.json schema

## Why
GOAL.md v0.1 — "Persistent local state (config, history)". Slice 1 shipped config.json (`021fc0b`); this slice closes the BACKLOG line by adding history persistence. Bundles the prior REVIEW carryover: relax `_load_config_default_model` so a config.json that omits `default_model` is silent (forward-compat for future keys like history toggles)

## Acceptance
- [x] `src/workbuddy/cli.py` adds:
  - constant `MAX_HISTORY_ROWS = 1000`
  - helper `_history_path() -> Path` returning `_log_path().parent / "history.jsonl"`
  - helper `_append_history(record: dict) -> None` that creates the parent dir, opens in `"a"` mode, writes `json.dumps(record, ensure_ascii=False) + "\n"`, and after writing rotates the file to the last `MAX_HISTORY_ROWS` lines (read all lines, keep the trailing slice, rewrite). All filesystem failures caught as `OSError` → one-line stderr `warning: failed to append run to history: <exc>` (parallel to `_log_run`)
- [x] On the successful-run path in `main()`, after `_log_run(...)`, call `_append_history({"ts": "<UTC ISO8601>", "task": args.task, "model": args.model, "response_chars": len(text)})`. Do NOT store the full response in history — `log.md` already keeps it; history exists for indexed scanning, not full text
- [x] On the API-error path AND the missing-key path, history is NOT written (parallel to `log.md` skip)
- [x] **Soften config schema**: in `_load_config_default_model`, when the file exists, parses as a `dict`, but the `default_model` key is **absent** (key missing) — return `DEFAULT_MODEL` SILENTLY (no warning). Wrong-type values for `default_model` (non-string, empty string) still warn. Invalid JSON / non-dict top-level still warn. Update inline reasoning if any helper comments exist
- [x] `tests/test_cli.py` adds:
  - `test_successful_run_appends_history`: with stub SDK, `main(["task"])` returns 0 and `(tmp_path / "history.jsonl")` exists with exactly one line that JSON-parses to a dict containing keys `ts`, `task`, `model`, `response_chars`. Sanity: `task == "task"`, `model == "claude-sonnet-4-6"` (default), `response_chars == len("stubbed-claude-reply")`
  - `test_history_appends_across_runs`: two successful runs → two JSONL lines in order; the second line's `task` is the second invocation's task
  - `test_api_error_does_not_create_history`: stub raises `_FakeAPIError`; assert non-zero exit, stderr contains `API call failed`, AND `(tmp_path / "history.jsonl")` does NOT exist
  - `test_history_rotation_caps_at_max`: pre-write `MAX_HISTORY_ROWS` (i.e. 1000) lines of distinguishable JSONL (e.g. `{"i": 0}`, `{"i": 1}`, ...) to `(tmp_path / "history.jsonl")`, run `main(["new task"])` once, then read the file, assert exactly `MAX_HISTORY_ROWS` lines remain AND the last line is the new `{"ts": ..., "task": "new task", ...}` row. (Use `from workbuddy.cli import MAX_HISTORY_ROWS` so the test follows the constant if it ever changes)
  - `test_config_silent_when_default_model_absent`: write `(tmp_path / "config.json").write_text('{"unrelated_key": 7}')`, run `main(["task"])` with stub, assert it returns 0, the stub's recorded `model == "claude-sonnet-4-6"`, AND **stderr is empty** (no warning)
- [x] All 19 existing tests still pass unchanged. The existing `test_main_malformed_config_falls_back_and_warns` still fires for the invalid-JSON path
- [x] `README.md` "Usage" section gains one terse paragraph after the existing `~/.workbuddy/log.md` sentence: explain that `~/.workbuddy/history.jsonl` records one compact JSON record per successful run (`ts`, `task`, `model`, `response_chars`) and rotates to the last 1000 entries
- [x] `python -m pytest` passes (no network, no `ANTHROPIC_API_KEY`)
- [x] **LOC ceiling**: GOAL.md's 500-LOC ceiling applied to v0; v0 is shipped, so v0.1 is no longer bound by it. Aim to stay tight — target under ~600 LOC total — but it's not a hard fail criterion

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
