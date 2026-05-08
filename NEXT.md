# Next Task

## Title
Add consecutive-error abort to `--mcp-agent`: stop the loop after 2 consecutive `is_error=True` tool results

## Why
Slice 1 of v0.3 lets the agent continue when a tool returns `is_error=True` — Claude sees the error and can retry or change strategy. That's correct behaviour for transient errors, but a misbehaving server could keep returning errors and burn through the entire turn budget without making progress. This slice adds a tight bound: 2 consecutive errors → cold abort with a new exit code 8. Single errors and intermittent error-then-success patterns are unaffected. This was specifically called out as the smallest-scope follow-up in the `ca1cacf` REVIEW

## Acceptance
- [x] Module-level constant `MAX_CONSECUTIVE_ERRORS = 2` in `src/workbuddy/cli.py`
- [x] In `_run_mcp_agent`, initialize `consecutive_errors = 0` BEFORE the for-loop
- [x] On the run-success path (after `_append_history(record)` for the run, BEFORE `messages.append(...)`):
  - If `is_error`: `consecutive_errors += 1`
  - Else: `consecutive_errors = 0` (success resets the streak)
  - If `consecutive_errors >= MAX_CONSECUTIVE_ERRORS`:
    - Print stderr: `error: --mcp-agent aborting at turn {turn_index+1}: {consecutive_errors} consecutive tool errors (limit: {MAX_CONSECUTIVE_ERRORS})`
    - Append a NEW history record `{ts, task, model, response_chars: 0, mcp_proposed_by: "claude", turn_index, mcp_decision: "consecutive-error-abort", consecutive_errors}`
    - Return `8` (new exit code distinct from 0/1/2/5/6/7)
  - Otherwise: continue (append messages and loop)
- [x] The check happens AFTER the run-success history record is appended for the current turn — so the audit trail shows the failed run, then the abort record. This keeps history.jsonl readable forensically: "run with is_error=True at turn N, then consecutive-error-abort at turn N"
- [x] `tests/test_cli.py` adds 3 tests:
  - `test_mcp_agent_one_error_then_success_continues` — turn 1 tool returns `is_error=True`, turn 2 succeeds (also tool_use), turn 3 returns final-text. Confirm `consecutive_errors` reset on turn 2's success: main returns 0, NOT 8. History has 3 rows: turn 0 run with `mcp_is_error=True`, turn 1 run with `mcp_is_error=False`, turn 2 final-text
  - `test_mcp_agent_two_consecutive_errors_aborts` — turn 1 tool returns `is_error=True`, turn 2 tool returns `is_error=True`. Loop aborts at turn 2's run-success path. Main returns 8. Stderr contains `2 consecutive tool errors`. History has 3 rows: turn 0 run is_error, turn 1 run is_error, turn 1 consecutive-error-abort. The third response from the scripted Anthropic should NEVER be requested (assert `len(scripted.create_calls) == 2`)
  - `test_mcp_agent_error_then_success_then_error_continues` — turn 1 error, turn 2 success, turn 3 error → consecutive_errors goes 1→0→1, never hits 2. Loop hits max-turns (3) → exit 7. (Three-error scenario where they're not consecutive.) Use `--mcp-agent-max-turns 3`. Recorder for `_async_call_tool` returns is_error per call based on turn index. History has 3 run rows + 1 max-turns-reached row
- [x] All 91 existing tests must continue to pass unchanged. The `test_mcp_agent_two_turns_then_final` test still works because neither turn errors. The `test_mcp_agent_max_turns_reached` test pre-existed and used non-error responses, so still works
- [x] The `_async_call_tool_returning(text, is_error=False)` test helper from slice 3 of v0.2 may need a small extension — currently the slice-3 fakes return `isError=False` hard-coded. The new tests need a fake that returns DIFFERENT `isError` values per call. Add `_make_async_call_tool_scripted(scripted_outputs)` where each output is `(text, is_error)` and the fake pops one per call
- [x] `python -m pytest -W error` passes (no resource warnings)
- [x] `README.md` "Usage" section: in the `--mcp-agent` paragraph, append one sentence after the "you can abort at any turn" line: `After ${MAX_CONSECUTIVE_ERRORS} consecutive tool errors the loop aborts with exit 8 — single errors and error-then-success are still allowed.` (substitute the actual number)
- [x] BACKLOG annotation update: keep v0.3 line at `[⏳]` (parallel tool calls and self-reflection are still deferred) but extend the parenthetical: `*(slice 1: --mcp-agent + per-turn y/N + hard cap; slice 2: consecutive-error abort; parallel tool calls and self-reflection deferred)*`
- [x] Total project Python LOC stays under ~2900

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
- BACKLOG.md
