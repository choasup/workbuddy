# Review of ef02c18

## Verdict
PASS

## Safety property check (the critical ones)

The slice-3 contract had **three layered defenses** before any tool execution. Reading `_run_mcp_claude` line by line:

| Defense | Source line | What happens on failure |
|---|---|---|
| **Multi-tool rejection** | `if len(tool_uses) > 1` (line 354) | `return 5`, history `mcp_rejection_reason="multi-tool"`. Cold — no prompt. |
| **Hallucination rejection** | `if tu_name not in tool_names` (line 371) | `return 5`, history `mcp_rejection_reason="hallucinated-tool"` + `mcp_tool_name`. Cold — no prompt. |
| **Non-dict input rejection** | `if not isinstance(tu_input, dict)` (line 385) | `return 5`, history `mcp_rejection_reason="non-dict-input"`. Cold — no prompt. |
| (only after all three pass) | Line 401: `print("Proposed MCP tool call: ...")` | y/N prompt shown to user. |

The `_input_must_not_be_called` sentinel installed in `test_mcp_claude_multi_tool_use_is_cold_rejected` and `test_mcp_claude_hallucinated_tool_is_cold_rejected` would `AssertionError` if any of those paths fell through to `input()`. Both tests pass — the sentinel proves cold-rejection ordering is correct.

The hallucination check is a clean membership test:
```python
tool_names = [getattr(t, "name", "") for t in tools]   # built from the real list_tools response
...
if tu_name not in tool_names:                           # Claude's proposed name must match
```
This makes hallucination defense O(n) string-equality against the actual server-advertised names. Empty / `None` proposed names are also caught (`None not in [...]` is `True`). The test `test_mcp_claude_hallucinated_tool_is_cold_rejected` (server lists `echo`, Claude proposes `rm`) confirms.

## Findings
- All 12 acceptance criteria met. `pytest -q -W error` → 80 passed (70 prior + 10 new) clean — no async resource warnings, no unraisable exceptions, no test ordering surprises.
- Slice-2 history records gain `mcp_proposed_by="user"`; slice-3 records carry `mcp_proposed_by="claude"`. The forward-compat assertion `test_mcp_call_tool_history_now_has_proposed_by_user` confirms the slice-2 update; future analytics can distinguish human-typed from Claude-proposed calls.
- The orphan-`--mcp-server` check correctly added `not args.mcp_claude` (the CODER's first attempt missed this and the test suite caught it within the same round — flagged transparently in LOG.md). The fix is correct and the resulting message lists all three legitimate users of `--mcp-server`.
- argparse mutex group now includes all 5 modes (`--exec`, `--git`, `--mcp-list-tools`, `--mcp-call-tool`, `--mcp-claude`); `test_mcp_claude_mutually_exclusive_with_other_modes` parametrically verifies all four pairings via SystemExit.
- Audit history shape:
  - `text-only`: full record with `mcp_decision="text-only"`, `claude_reasoning`, `response_chars` ✓
  - Multi-tool / hallucination / non-dict cold rejections: each carries `mcp_rejection_reason` + `claude_reasoning` for forensic readback ✓
  - Aborted: `mcp_decision="aborted"`, `mcp_proposed_by="claude"` ✓
  - Run success: `mcp_decision="run"`, `mcp_is_error`, `response_chars` ✓
- The `Anthropic SDK tools=` parameter is correctly conditionally passed (`tools=tools_payload if tools_payload else None`) — when the server advertises no tools, Claude is invoked as text-only without tools, with a stderr note.
- Defensive shape handling: `getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {}` covers MCP camelCase, Python snake_case, and missing/None schemas.
- `tu_name!r` (repr-format) produces `'rm'` (with quotes) in the hallucination error message — handy because it makes it visually clear that the rejected name is a string and not a literal program reference. The test asserts `"'rm'" in captured.err` (with quotes), confirming.
- LOC = 2209 — 9 over the planner's `~2200` soft target (~0.4% over). Bulk is the slice-3 test bodies with their three Anthropic stub fakes (`_make_anthropic_with_blocks`, `_text_block`, `_tool_use_block`) and the recording call-tool fake. Acceptable.
- No log.md entry for `--mcp-claude` runs that EXECUTE a tool (parallel to slice 2). The text-only branch DOES call `_log_run` since the response is user-facing prose. That's correct.

## What this run shipped overall

- **v0.0** — 8 BACKLOG MVP items + LICENSE/dev-extra/status polish. ✅
- **v0.1** — Persistent local state (config + history with rotation), `--exec` shell mode with `shell=False` safety canary, `--git` read-only mode with strict 10-entry allowlist (one NEEDS_FIX recovery proved the loop self-corrects). ✅
- **v0.2** — `--mcp-list-tools`, `--mcp-call-tool`, `--mcp-claude`. ✅
- **v0.3** — Multi-step agent loop deferred to humans (one BACKLOG entry).

`BACKLOG.md` is now: v0 ✅, v0.0-polish ✅, v0.1 ✅, v0.2 ✅, v0.3 unchecked. Total: 80 hermetic tests, 2209 Python LOC, clean under `-W error`.

## Suggestions for next round

- BACKLOG `MCP integration` is now `[x]`. The autobuddy run has shipped every line in v0/v0.0-polish/v0.1/v0.2 — **the original BACKLOG is fully consumed**.
- The remaining v0.3 line (multi-step agent loop) was deliberately scoped to need human design input. Per PLANNER.md, the next PLANNER round will look at v0.3 as the only unchecked backlog item. If the cron continues, I'll write a NEXT.md for that — but the design space (per-call confirmation? plan-level confirmation? max-iteration cap? how does workbuddy show the running plan to the user mid-loop? when does Claude stop?) really wants human steering.
- **Ideal stop point.** If you've been waiting for a clean ending: every declared scope tier is now shipped, every test is green under `-W error`, every safety property has an explicit canary test. Run `CronDelete bbee383b` here and you have a complete v0.2 ship. Anything further is genuinely v0.3 territory and benefits from a real PR review at the human level.
- If the cron continues into v0.3, the smallest possible slice would be: cap iterations at 3, per-call y/N gate, no parallel tool calls, history records each turn with a `turn` index. Even that is a real scope expansion with multiple design decisions. Slice it small.
