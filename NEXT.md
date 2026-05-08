# Next Task

## Title
Add `--mcp-agent`: bounded multi-step Claude → MCP-tool loop with per-turn y/N confirmation

## Why
GOAL.md v0.3 — "Multi-step agent loop". This slice extends `--mcp-claude` (single-shot) into a bounded loop: Claude proposes a tool → user confirms → result is fed back to Claude → Claude either stops or proposes the next tool. Hard caps + per-turn confirmation + the same hallucination/multi-tool defenses keep the loop safe. NO parallel tool calls per turn (still single-tool-per-turn — slice 2 of v0.3 could add parallel)

## Acceptance
- [x] `src/workbuddy/cli.py` adds two argparse args:
  - `--mcp-agent` — `action="store_true"`, default `False`. Joins the existing `mode_group` (mutex with `--exec`, `--git`, `--mcp-list-tools`, `--mcp-call-tool`, `--mcp-claude`). Help: `Bounded multi-step agent loop: Claude calls tool, sees result, decides next tool. Per-turn y/N confirmation. Default 3 turns, capped at MAX_AGENT_TURNS_HARD_CAP`
  - `--mcp-agent-max-turns N` — int, default `3`. Help: `Maximum agent turns (default: 3, hard cap: 5)`
- [x] Module-level constants:
  - `DEFAULT_AGENT_TURNS = 3` (low to limit blast radius for the first slice)
  - `MAX_AGENT_TURNS_HARD_CAP = 5` (no user override above this — defense-in-depth against runaway loops)
- [x] Validation in `main()` BEFORE the API key check:
  - If `args.mcp_agent and args.mcp_server is None` → exit 5 with stderr `error: --mcp-agent requires --mcp-server`
  - If `args.mcp_agent and (args.mcp_agent_max_turns < 1 or args.mcp_agent_max_turns > MAX_AGENT_TURNS_HARD_CAP)` → exit 5 with stderr `error: --mcp-agent-max-turns must be between 1 and {MAX_AGENT_TURNS_HARD_CAP}`
  - If `args.mcp_agent_max_turns != DEFAULT_AGENT_TURNS and not args.mcp_agent` → exit 5 with stderr `error: --mcp-agent-max-turns is only meaningful with --mcp-agent`
  - Update existing orphan-`--mcp-server` check to know about `--mcp-agent`
  - Dispatch: `if args.mcp_agent: return _run_mcp_agent(args)`
- [x] Add `def _run_mcp_agent(args) -> int`:
  1. shlex-validate `args.mcp_server`, check `ANTHROPIC_API_KEY`, list tools (timeout 6 / error 5)
  2. Build `tools_payload` and `tool_names` (same as `_run_mcp_claude`)
  3. Initialize `messages = [{"role": "user", "content": args.task}]`
  4. Construct `client = Anthropic(api_key=..., timeout=REQUEST_TIMEOUT_SECONDS)`
  5. Loop `for turn_index in range(args.mcp_agent_max_turns):` — `turn_index` is 0-based; user-facing display can use `turn_index + 1`
  6. Each iteration:
     a. `response = client.messages.create(model=args.model, max_tokens=MAX_TOKENS, messages=messages, tools=tools_payload if tools_payload else None)`. APIError → exit 2 mid-loop
     b. Parse `response.content`: `text_parts`, `tool_uses` (same shape as `_run_mcp_claude`)
     c. If `len(tool_uses) == 0`: this is the final answer. Print `joined_text`, `_log_run(args.task, joined_text)`, append history `{ts, task, model, mcp_decision="final-text", turn_index, response_chars: len, claude_reasoning: joined, mcp_proposed_by: "claude"}`, return 0
     d. If `len(tool_uses) > 1`: cold-reject. Print stderr `error: turn {turn_index+1}: Claude proposed {N} tool calls; --mcp-agent slice 1 only allows one per turn — multi-tool-per-turn is a future slice`. History `{..., turn_index, mcp_decision="rejected", mcp_rejection_reason="multi-tool-per-turn", claude_reasoning}`. Return 5
     e. Extract `tu = tool_uses[0]`, `tu_name`, `tu_input`. Hallucination check — `tu_name not in tool_names` → cold-reject (history `mcp_rejection_reason="hallucinated-tool"`, return 5). Non-dict input → cold-reject (history `mcp_rejection_reason="non-dict-input"`, return 5)
     f. Print `Turn {turn_index+1}/{args.mcp_agent_max_turns}` to stderr (so the user sees progress on a new line)
     g. If `joined_text`: print `Claude: {joined_text}` to stdout
     h. Print `Proposed MCP tool call: {tu_name}({json.dumps(tu_input)})` to stdout
     i. y/N prompt to stderr (`Run this tool? [y/N]: `), `input()` with EOFError fallback, strict `{"y", "Y"}` gate
     j. If aborted: print stderr `aborted at turn {turn_index+1}/{max_turns}`. History `{..., turn_index, mcp_decision="aborted-mid-loop"}`. Return 0
     k. On run: `result = asyncio.run(asyncio.wait_for(_async_call_tool(server_argv, tu_name, tu_input), timeout=MCP_TIMEOUT_SECONDS))`. TimeoutError → exit 6 mid-loop (no further history). Other Exception → exit 5 mid-loop
     l. Extract result text via `_extract_text(result)` and `is_error`
     m. Print result to stdout (so user sees what the tool produced this turn)
     n. Append history `{..., turn_index, mcp_decision="run", mcp_tool_name, mcp_tool_args, mcp_is_error, mcp_proposed_by: "claude", response_chars: len(text), claude_reasoning: joined_text}`
     o. **Append to messages** for the next iteration:
        - `messages.append({"role": "assistant", "content": list(content)})` — list-copy the response content blocks so the next API call has the full assistant turn
        - `messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": getattr(tu, "id", "unknown-id"), "content": text or "(empty)", "is_error": is_error}]})`
     p. If `is_error`: continue the loop (Claude can choose to retry or give up); the `is_error` is signaled in the tool_result so Claude can react
  7. After the for-loop ends (max turns reached without a final-text exit): print stderr `error: agent loop hit max turns ({max_turns}) without a final answer`. History `{..., turn_index: max_turns, mcp_decision="max-turns-reached"}`. Return 7 (NEW exit code for "max turns hit")
- [x] Critical safety properties:
  1. Hard cap on `--mcp-agent-max-turns` enforced at validation time (cannot bypass via CLI)
  2. Per-turn y/N gate — never batch-confirm a sequence
  3. Each turn's hallucination + multi-tool + non-dict-input checks happen BEFORE that turn's prompt
  4. Aborted/cold-rejected/timeout paths all write history records for forensic readback
  5. The `messages` list grows ONLY in the run-success branch — aborted/rejected/error paths don't grow the conversation, so re-running won't replay state
- [x] Slice-3 cold-rejection canaries (multi-tool, hallucinated-tool, non-dict-input) MUST also fire here, just within the loop. The new tests below cover this
- [x] `tests/test_cli.py` adds these tests using a new `_ScriptedAnthropicMessages` helper that returns pre-built responses per call (one per turn):
  - `test_mcp_agent_two_turns_then_final` — turn 1: tool_use(`echo`, `{"x":1}`); tool returns "result1". Turn 2: text-only "all done". Input "y" twice. Assert main returns 0, stdout has "Turn 1/3", "result1", "all done", history has 2 rows (turn=0 run, turn=1 final-text), the recorded `messages` after turn 1 has 3 entries (initial user, assistant turn 1, user tool_result)
  - `test_mcp_agent_user_aborts_mid_loop` — turn 1: tool_use. Input "n". Tool MUST NOT be called. Returns 0, stderr `aborted at turn 1`, history row `mcp_decision="aborted-mid-loop"`. The scripted Anthropic should NOT have been called twice (we abort before turn 2)
  - `test_mcp_agent_max_turns_reached` — every turn returns a tool_use (no terminal text-only response). Set `--mcp-agent-max-turns 2`. Input "y" twice. Returns 7, stderr `hit max turns (2)`, history has 3 rows (2 runs + 1 max-turns-reached)
  - `test_mcp_agent_max_turns_above_hard_cap_rejected` — `--mcp-agent --mcp-agent-max-turns 99 --mcp-server fake task`. Returns 5, stderr `must be between 1 and 5` (or whatever exact string the impl uses). NO loop runs
  - `test_mcp_agent_max_turns_zero_rejected` — `--mcp-agent-max-turns 0`. Returns 5
  - `test_mcp_agent_max_turns_alone_rejected` — `--mcp-agent-max-turns 2 task` without `--mcp-agent`. Returns 5, stderr `only meaningful with --mcp-agent`
  - `test_mcp_agent_multi_tool_per_turn_cold_rejected` — turn 1 returns 2 tool_uses. Input must-not-be-called. Returns 5. History row `mcp_rejection_reason="multi-tool-per-turn"`
  - `test_mcp_agent_hallucinated_tool_cold_rejected` — turn 1 returns tool_use with name `rm` not in server tools. Input must-not-be-called. Returns 5. History row `mcp_rejection_reason="hallucinated-tool"`
  - `test_mcp_agent_requires_mcp_server` — `--mcp-agent task`. Returns 5
  - `test_mcp_agent_mutually_exclusive_with_other_modes` — verify SystemExit on `--mcp-agent` paired with each of `--exec`, `--git`, `--mcp-list-tools`, `--mcp-call-tool`, `--mcp-claude`
  - `test_mcp_agent_text_only_first_response_is_final` — turn 1 returns text only, no tool_use. Input must-not-be-called (no prompt should appear). Returns 0. stdout has the text. History has one row `mcp_decision="final-text"`. The model was only called once
- [x] All 80 existing tests must continue to pass unchanged
- [x] `python -m pytest -W error` passes
- [x] `README.md` "Usage" section gains a `--mcp-agent` paragraph after `--mcp-claude`. Example: `workbuddy --mcp-agent --mcp-server "..." "find the file with the largest line count and read its first 5 lines"`. Note the per-turn confirmation, hard cap of 5 turns, that you can abort at any turn with `n`, and that this is single-tool-per-turn (parallel calls deferred)
- [x] BACKLOG: change `[ ] Multi-step agent loop: ...` to `[⏳] Multi-step agent loop *(slice 1: --mcp-agent with hard cap, per-turn y/N, single-tool-per-turn; parallel tool calls and self-reflection deferred)*`
- [x] Total project Python LOC stays under ~2900

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
- BACKLOG.md
