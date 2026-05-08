# Review of 0b0b8b7

## Verdict
PASS

## Safety property check (the critical one)
The slice-2 contract was: **all argument-validation errors must short-circuit BEFORE the y/N prompt is shown — a malformed call cannot be confirmed**. Reading `_run_mcp_call_tool` line by line:

| Line | Check | On failure |
|---|---|---|
| 244–252 | `--mcp-server` is non-empty (shlex parses) | `return 5` ✓ |
| 254–261 | `args.mcp_tool_args` is valid JSON | `return 5` ✓ |
| 262–267 | parsed JSON is `isinstance(..., dict)` (rejects arrays, strings, numbers, null) | `return 5` ✓ |
| 277 | `print("Proposed MCP tool call: ...")` | (only reached after all three validations pass) |
| 278–283 | y/N prompt | (only after validations) |

The `_input_must_not_be_called` sentinel installed in `test_mcp_call_tool_invalid_json_args_is_cold_rejected` and `test_mcp_call_tool_args_must_be_dict_not_array` would `AssertionError` if any of the three validation paths fell through to `input()`. Both tests pass — the sentinel proves cold-rejection ordering is correct.

The y/N gate is strict (`answer.strip() not in {"y", "Y"}`). Empty input, EOF (caught), `yes`/`Yes` all abort. Same posture as `--exec` and `--git`.

## Findings
- All 14 acceptance criteria met. `pytest -W error` → 70 passed (58 prior + 12 new) with no resource warnings or async cleanup leaks.
- `_async_call_tool` mirrors `_async_list_tools` exactly except for the call line (`return await session.call_tool(tool_name, tool_args)`). Lazy-import inside the function preserves the slice-1 startup-speed and test-mockability properties.
- Defensive `isError` extraction: `getattr(result, "isError", None) or getattr(result, "is_error", False)` handles both MCP-spec camelCase and Python-SDK snake_case shapes. The `bool(...)` wrap ensures the history record stores a clean `true`/`false` JSON value.
- Reuses `_extract_text(result)` for the tool result content — `_extract_text` was already defensive (`getattr(block, "text", None)`), so `CallToolResult.content` blocks lacking `.text` (e.g. image / resource blocks) are silently skipped. Acceptable for slice 2.
- History records (timeout/exception paths) are intentionally NOT written — `_append_history(record)` lives AFTER the `try/except` block in the run path and is unreachable on those exits. Asserted by `test_mcp_call_tool_timeout` / `test_mcp_call_tool_protocol_error` which both `assert not (tmp_path / "history.jsonl").exists()`.
- The `record["response_chars"]` is correctly recomputed AFTER `_extract_text` to match the actual printed length, not the placeholder `0` from the initial record dict.
- Three new mutex tests confirm `--mcp-call-tool` is exclusive with `--mcp-list-tools`, `--exec`, and `--git`. argparse handles all combinations.
- The orphan-args check (`args.mcp_tool_args != "{}"` AND no `--mcp-call-tool`) uses string-equality on the default value `"{}"`. Edge case: if a user explicitly passes `--mcp-tool-args "{}"` without `--mcp-call-tool`, it's indistinguishable from the default and the orphan check doesn't fire. This is a minor UX papercut (user gets no error for a meaningless flag combination) but not a safety issue.
- LOC = 1702 — 2 over the planner's `~1700` soft target. Within rounding error; the bulk is the `_FAKE_LAST_CALL` recording fake and the 12 named test bodies. Not worth trimming.
- The recording fake `_fake_async_call_tool_recording` uses a module-global dict (`_FAKE_LAST_CALL`) which must be `.clear()`-ed in tests that use it. The two tests that touch it (`test_mcp_call_tool_runs_after_yes`, `test_mcp_call_tool_default_args_is_empty_dict`) both clear at start. A future cleanup could move this into a fixture, but it's tractable as-is.

## Non-blocking observations (carry-forward for slice 3)
- **Slice 3 is the riskiest unbuilt piece**: Claude-driven tool selection. Claude reads the list-tools output, decides which tool to call with which args, and proposes that as a structured response. workbuddy must:
  - Show the user EVERYTHING Claude is proposing (tool name + JSON args + Claude's stated rationale)
  - Apply the same y/N gate per tool call
  - For multi-step plans (Claude calls tool A, sees the result, decides tool B), every call needs an independent gate — never batch-confirm a chain
  - Audit log must distinguish "human-typed" calls (slice 2) from "Claude-proposed" calls (slice 3) — extend the `mcp_*` keys with a `mcp_proposed_by: "user" | "claude"` field
- The `--mcp-tool-args` orphan-check edge case (literal `"{}"` indistinguishable from default) could be tightened: use `argparse`'s `default=None` and explicitly require non-None when `--mcp-call-tool` is set. Cosmetic.
- Image / resource content blocks in `CallToolResult.content` are silently dropped by `_extract_text`. Slice 3 might want a richer printer that says e.g. `[image content omitted: <bytes>]`.
- The y/N prompt for `--mcp-call-tool` is the third copy of essentially the same prompt code (also in `_run_exec` and `_run_git`). Slice 3 could refactor to a shared `_confirm(proposed_text) -> bool` helper. Not worth doing now — the duplication is small and refactor risks correctness regressions.

## Suggestions for next round
- BACKLOG `MCP integration` stays `[⏳]` for slice 3.
- Slice 3 (Claude-driven tool selection) has multiple design knobs that materially benefit from human input:
  - How does Claude communicate its tool choice? Structured tool-use blocks via the Anthropic SDK's existing tool-use API, OR a JSON-in-text protocol?
  - Multi-step plans: do we hand each tool result back to Claude for the next step (full agent loop) or do one-shot?
  - Plan audit: should the Planner pre-show the user a "Claude wants to call N tools" plan and gate at the plan level too?
- **At this point — 12 commits into v0.2 with no human checkpoint** — pausing the cron is the most aligned move with the user's stated "commercial-grade stable OS app" goal. Stable systems are designed at the human level for these kinds of agent-loop decisions. Run `CronDelete bbee383b` to stop.
- If the cron continues, slice 3 should be the smallest possible Claude-in-the-loop slice: one tool call per `workbuddy --mcp-claude --mcp-server "..."` invocation (no multi-step), Claude returns a `tool_use` block, workbuddy shows the proposed call + Claude's reasoning, y/N confirm, run, print result, exit. Multi-step / agent-loop comes in a separate slice.
