# Next Task

## Title
Add `--reflect` flag to `--mcp-agent`: one-shot Claude self-evaluation at end of an agent run

## Why
GOAL.md v0.3 — "Multi-step agent loop". This slice adds bounded self-reflection: after the agent loop completes, optionally call Claude ONCE more with the full transcript and the question "did this complete the task?". Pure single-shot — no tools available to Claude on this call, no follow-up turns. Useful as an audit signal: a reflection saying "no, the task is half-done" is information for the user

## Acceptance
- [x] `src/workbuddy/cli.py` adds `--reflect` argparse flag (boolean, default `False`). Help: `When combined with --mcp-agent: after the loop ends, ask Claude in ONE additional API call whether the task was completed. Prints "Reflection: <text>". Single-shot — no tools, no looping`
- [x] Module constant `REFLECTION_PROMPT = "Did this complete the task? Answer briefly (1-2 sentences). Do not call any tool."`
- [x] Validation in `main()`: if `args.reflect and not args.mcp_agent` → exit 5 with stderr `error: --reflect is only meaningful with --mcp-agent`
- [x] Add helper `def _reflect_if_enabled(args, client, messages) -> None`:
  1. Early-return if NOT `args.reflect`. No-op
  2. Early-return if `args.mcp_agent_dry_run` is True. Synthetic tool_results in messages would make reflection misleading. Print stderr `note: --reflect skipped in dry-run mode (synthetic results)` and return
  3. Build a final `reflect_messages = list(messages) + [{"role": "user", "content": REFLECTION_PROMPT}]`
  4. `try: response = client.messages.create(model=args.model, max_tokens=MAX_TOKENS, messages=reflect_messages)` — note: NO `tools=` param so Claude can't propose another tool
  5. On `APIError`: print stderr `warning: --reflect API call failed: <Class>: <msg>`. Do NOT change exit code (the agent run itself already concluded). Return
  6. On any other `Exception`: same warning + return (defensive)
  7. Extract text via the existing `_extract_text(response)` helper. If response contains any `tool_use` blocks (Claude trying to call a tool despite the prompt), print stderr `warning: --reflect: model proposed a tool call; ignored — reflection is single-shot`
  8. Print `Reflection: {text}` to stdout (or `Reflection: (no text)` if `_extract_text` returned empty)
  9. Append a history record `{ts, task: args.task, model: args.model, response_chars: len(text), mcp_proposed_by: "claude", mcp_decision: "reflection", reflection_text: text}`
- [x] In `_run_mcp_agent`, call `_reflect_if_enabled(args, client, messages)` JUST BEFORE the `return` statement at each of these 4 graceful-exit points:
  1. Final-text exit (the `if not tool_uses:` branch — line ~370 of current code)
  2. User-aborted mid-loop (the `if answer.strip() not in {"y", "Y"}:` branch — line ~440)
  3. Max-turns reached (the after-for-loop block — line ~503)
  4. Consecutive-error abort (the `if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:` branch — line ~488)
- [x] DO NOT call `_reflect_if_enabled` from these paths — the agent didn't have a meaningful run to reflect on:
  - Cold-rejections (multi-tool, hallucination, non-dict-input — line ~387, ~405, ~419/431) — task didn't start
  - Timeout / protocol error mid-loop (line ~450, ~456) — no usable transcript
  - API error mid-loop (line ~344) — Claude isn't reachable for reflection
  - The `_run_mcp_agent` early-returns BEFORE the loop (e.g. invalid server, missing API key, list_tools failure) — not in the loop yet
- [x] DO call `_reflect_if_enabled` from dry-run exit paths but the helper itself short-circuits on dry-run (per step 2 above). This keeps the call sites uniform — every graceful exit goes through the helper, and the helper makes the dry-run decision in ONE place
- [x] `tests/test_cli.py` adds these tests using the existing `_make_scripted_anthropic` helper (extend the response list by one for the reflection call):
  - `test_reflect_after_final_text_run` — server has `echo`. Turn 1: tool_use; turn 2: text-only "done"; reflection: text "yes, the task is complete". `--mcp-agent --reflect`. Input "y". Assert main returns 0, stdout contains "done" and "Reflection: yes, the task is complete", `len(scripted.create_calls) == 3` (the reflection IS the third call), and the third call's `messages` includes a final user message containing "Did this complete the task?". History row final-text + reflection (2 rows for the run + 1 for reflection)
  - `test_reflect_after_max_turns` — max_turns=2, both turns tool_use, reflection. Exit 7 (max-turns), reflection still runs, history rows: 2 run + max-turns-reached + reflection (4 rows total)
  - `test_reflect_after_consecutive_errors` — 2 turns of is_error, abort 8, reflection runs anyway. History: 2 run with is_error + abort + reflection (4 rows)
  - `test_reflect_after_user_abort` — turn 1: tool_use; user answers "n"; reflection runs. Exit 0
  - `test_reflect_skipped_in_dry_run` — `--mcp-agent --mcp-agent-dry-run --reflect`. Reflection helper short-circuits, stderr contains `--reflect skipped in dry-run mode`, no third API call (`len(scripted.create_calls) == 2` for a 2-turn dry-run)
  - `test_reflect_alone_rejected` — `--reflect task` without `--mcp-agent` → exit 5, stderr `only meaningful with --mcp-agent`
  - `test_reflect_skipped_after_hallucination` — hallucinated tool → cold-rejection at exit 5; reflection NOT called (only the initial create() happened). `len(scripted.create_calls) == 1`
  - `test_reflect_api_error_does_not_change_exit_code` — agent finishes with exit 7 (max-turns); reflection's API call raises an `APIError`. Stderr contains `warning: --reflect API call failed`. Main still returns 7. To inject the APIError, the third scripted Anthropic response is a sentinel that's checked in `_ScriptedMessages.create` — OR simpler, extend `_ScriptedMessages` to support an `apierror_at_call_index` parameter
  - `test_reflect_handles_tool_use_in_response_gracefully` — reflection response contains a `tool_use` block instead of plain text. Helper warns to stderr but still extracts and prints any text. Main return code unchanged
- [x] All 101 existing tests must continue to pass unchanged. `--reflect` defaults to False, so non-reflect runs are byte-identical
- [x] `python -m pytest -W error` passes
- [x] `README.md` `--mcp-agent` paragraph: append a final paragraph: `Use --reflect to add a single self-evaluation API call at the end of the run. Claude is shown the full transcript (without tools) and asked "did this complete the task?". The verdict is printed as "Reflection: <text>". --reflect is skipped in --mcp-agent-dry-run mode (synthetic results would mislead). It does not change the exit code; if the reflection API call itself fails, a warning is printed and the agent's exit code stands.`
- [x] BACKLOG: extend the v0.3 annotation: `*(slice 1: --mcp-agent + per-turn y/N + hard cap; slice 2: consecutive-error abort with exit 8; slice 3: --mcp-agent-dry-run; slice 4: --reflect; parallel tool calls deferred)*`
- [x] Total project Python LOC stays under ~3500

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
- BACKLOG.md
