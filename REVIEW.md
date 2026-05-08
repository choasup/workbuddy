# Review of 23aa195

## Verdict
PASS

## Findings
- All 9 acceptance criteria met. `pytest -W error` → 94 passed (91 prior + 3 new) clean — no resource warnings.
- 16-LOC diff to `_run_mcp_agent` is correctly placed and minimal:
  - Counter init `consecutive_errors = 0` BEFORE the for-loop (line 330)
  - Increment-or-reset happens AFTER the run-success history record append, BEFORE the `messages.append` calls
  - Cap check `>=` (not `>`) so reaching the cap value `2` triggers, not a value above it
  - Abort path writes its own `consecutive-error-abort` record (separate from the failed-run record from the same turn) — history.jsonl now reads forensically: turn N run with `mcp_is_error=True`, then turn N abort with `consecutive_errors=2`
  - Returns 8 before `messages.append`, so the conversation doesn't grow into a never-reached iteration
- The 3 new tests cover the relevant axis cleanly:
  - `test_mcp_agent_one_error_then_success_continues` — proves a single error doesn't trip the cap; counter resets on success.
  - `test_mcp_agent_two_consecutive_errors_aborts` — proves the cap fires; the assertion `len(scripted.create_calls) == 2` confirms the third Anthropic response is NEVER requested (the abort short-circuited).
  - `test_mcp_agent_error_then_success_then_error_continues` — proves NON-consecutive errors don't trip the cap (counter resets to 0 between).
- The `_make_async_call_tool_scripted([(text, is_error), ...])` test helper is reusable for any future tests that need to control `is_error` across turns. Cleaner than the prior single-call fakes.
- Subtle interaction with `max_turns` is correct:
  - If `max_turns=1` (1 turn allowed), a single error can never trip a *consecutive* cap that requires 2 — the loop just hits max-turns. Semantically right (the user limited the budget).
  - If errors persist past the cap, the abort takes precedence over max-turns-reached, with a more informative exit code (8 vs 7).
- LOC = 2915 — 15 over the planner's `~2900` soft target. Bulk is the new test-helper + 3 named tests; not worth trimming.
- Audit trail: a future analyst reading `history.jsonl` can grep `mcp_decision="consecutive-error-abort"` to find aborted runs, and the `consecutive_errors` field tells them exactly how many failures fired the cap. Forward-compat for slice 3 + analytics.

## Suggestions for next round
- BACKLOG v0.3 stays `[⏳]` — slice 3 candidates remain (parallel tool calls, self-reflection, `--dry-run` mode for the agent loop).
- Strongest-signal candidates if the cron continues:
  - **`--mcp-agent --dry-run`** — show what Claude WOULD do at each turn but don't actually call `_async_call_tool`; feed Claude a synthetic `(dry-run: tool not actually invoked)` tool_result so it can explore a plan without side effects. Useful debugging tool. Doesn't change any execution semantics.
  - **Bounded self-reflection** — at the end of a `--mcp-agent` run, call Claude once more with the full transcript and ask "did this complete the task?" — a single yes/no recap printed for the user. Bounds: one extra non-tool call, doesn't loop.
  - **NOT recommended next**: parallel tool calls. The UX decision (one prompt per call vs. one prompt for N calls) is the kind of choice that produces different products; a human should decide.
- Same standing recommendation: this is still a good place to pause. Each subsequent slice has been smaller and more incremental, which is good — but at some point the agent itself needs review beyond what canary tests can catch. Run `CronDelete bbee383b` when ready.
