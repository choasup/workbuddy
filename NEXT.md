# Next Task

## Title
Add `--mcp-agent-dry-run`: simulate the agent loop without executing any tool

## Why
Slice 1 + 2 of v0.3 ship a real agent loop with confirmation gates; this slice ships an inspection mode that lets users see what Claude WOULD propose at each turn without any side effects. Useful for: debugging an agent's plan before running it for real, demonstrating workflows safely, building trust with Claude's tool-use behaviour. ZERO new execution paths — `_async_call_tool` is never invoked in dry-run mode

## Acceptance
- [ ] `src/workbuddy/cli.py` adds a new argparse arg `--mcp-agent-dry-run` (boolean, default False). Help: `When combined with --mcp-agent: simulate the loop without executing any tool. Each turn prints "DRY RUN: would call ..." and feeds Claude a synthetic success result so the plan continues. No y/N prompts, no real tool invocations`
- [ ] Validation in `main()` BEFORE the existing dispatch:
  - If `args.mcp_agent_dry_run and not args.mcp_agent` → exit 5 with stderr `error: --mcp-agent-dry-run is only meaningful with --mcp-agent`
- [ ] In `_run_mcp_agent`, after the cold-rejection checks (multi-tool / hallucination / non-dict input still fire per turn — DRY-RUN MUST NOT BYPASS THEM) but at the point where the live mode would do `print(f"Turn {turn_index + 1}/{max_turns}", ...)` plus the y/N prompt:
  - If `args.mcp_agent_dry_run`:
    1. Print `Turn {turn_index + 1}/{max_turns} (DRY RUN)` to stderr (so user sees turn progress with the mode marker)
    2. If `joined_text`: print `Claude: {joined_text}` to stdout (same as live mode — Claude's reasoning is shown)
    3. Print `DRY RUN: would call tool {tu_name}({json.dumps(tu_input)})` to stdout (replaces both the live mode's `Proposed MCP tool call:` line AND the actual execution)
    4. Skip `input()` ENTIRELY — no prompt
    5. Set `result_text = "(dry-run: tool not actually invoked; assuming success)"` and `is_error = False`
    6. Append history record `{...base_record, mcp_decision: "dry-run-skipped", mcp_dry_run: True, mcp_tool_name, mcp_tool_args, response_chars: len(result_text), claude_reasoning, mcp_is_error: False}`
    7. Append to messages: `assistant` with the response content, then `user` with synthetic tool_result containing `result_text` and `is_error: False`. SAME structure as the live-success path so Claude can continue planning
  - The consecutive-error-counter logic does NOT apply in dry-run (synthetic results are always success). Skip the counter update path entirely when dry-run is set
- [ ] DRY-RUN MUST NOT BYPASS any cold-rejection. Multi-tool / hallucination / non-dict-input rejections still happen with the same exit codes (5) and history records (`mcp_rejection_reason` still recorded). The dry-run ONLY changes what happens AFTER the proposed call passes those checks
- [ ] DRY-RUN does NOT change `final-text` exit semantics — if Claude returns text-only, dry-run still prints it and exits 0
- [ ] DRY-RUN does NOT change `max-turns-reached` semantics — if the loop hits `max_turns` of synthetic-success turns without a final-text, exit 7 with `max-turns-reached` history record
- [ ] `tests/test_cli.py` adds these tests:
  - `test_mcp_agent_dry_run_skips_execution` — server has `echo` tool. Turn 1: tool_use(`echo`, `{"x":1}`). Turn 2: text-only "done". `_async_call_tool` MUST NOT be called (use the must-not-be-called sentinel from earlier). Input MUST NOT be called (no prompt in dry-run). Assert main returns 0; stdout contains "DRY RUN: would call tool echo" and "done" and "Claude: ..." reasoning if any; history has 2 rows: turn 0 with `mcp_decision="dry-run-skipped"` and `mcp_dry_run=True`, turn 1 with `mcp_decision="final-text"`
  - `test_mcp_agent_dry_run_synthetic_result_passed_to_next_turn` — scripted Anthropic returns 2 tool_use turns then a final-text. In dry-run, capture the messages list passed on the second create() call. Assert it contains a `tool_result` block whose `content` includes `(dry-run:` (the synthetic text) — proves Claude is fed a placeholder result for chaining
  - `test_mcp_agent_dry_run_no_y_n_prompt_appears` — verify the prompt string `Run this tool? [y/N]:` does NOT appear in stderr in dry-run mode
  - `test_mcp_agent_dry_run_still_cold_rejects_hallucination` — turn 1: tool_use with hallucinated name `rm`. Even in dry-run, hallucination check fires → exit 5, stderr "hallucination", history `mcp_rejection_reason="hallucinated-tool"`. NO `_async_call_tool` invocation, NO "DRY RUN: would call" line in stdout
  - `test_mcp_agent_dry_run_still_cold_rejects_multi_tool` — turn 1: 2 tool_use blocks. Exit 5, `mcp_rejection_reason="multi-tool-per-turn"`. NO "DRY RUN" output
  - `test_mcp_agent_dry_run_alone_rejected` — `--mcp-agent-dry-run` without `--mcp-agent` → exit 5, stderr "only meaningful with --mcp-agent". Existing tests for `--mcp-agent` (without dry-run) MUST still pass — verify by running the full suite
  - `test_mcp_agent_dry_run_max_turns_reached` — set `--mcp-agent-max-turns 2`; both turns return tool_use (never text-only). Dry-run skips execution. Loop hits max-turns, exits 7. History has 3 rows: 2 dry-run-skipped, 1 max-turns-reached
- [ ] All 94 existing tests must continue to pass unchanged. The slice 1+2 tests do NOT use dry-run, so their behaviour is byte-identical
- [ ] `python -m pytest -W error` passes
- [ ] `README.md` `--mcp-agent` paragraph: append a final sentence (or new paragraph) — `Use --mcp-agent-dry-run to inspect the plan without executing: each turn prints "DRY RUN: would call ..." and Claude is fed a synthetic success result so the plan can continue. No y/N prompts, no real tool invocations.`
- [ ] BACKLOG: extend the v0.3 annotation to `*(slice 1: --mcp-agent + per-turn y/N + hard cap; slice 2: consecutive-error abort; slice 3: --mcp-agent-dry-run; parallel tool calls and self-reflection deferred)*`
- [ ] Total project Python LOC stays under ~3100

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
- BACKLOG.md
