# Next Task

## Title
Add `--mcp-claude`: Claude reads the MCP server's tool list, proposes ONE tool call, user confirms, workbuddy executes

## Why
GOAL.md v0.2 — "MCP integration", final slice. Single-shot Claude-in-the-loop: list tools → ask Claude to pick at most one for the user's task → show proposed call + Claude's reasoning → strict y/N gate → execute via `_async_call_tool`. **NO agent loop / NO multi-step in this slice** — if Claude proposes more than one tool call we error out, telling the user a future slice will add multi-step. The tool name MUST be one Claude actually saw in the list (rejects hallucinations cold)

## Acceptance
- [x] `src/workbuddy/cli.py` adds `--mcp-claude` to the existing `mode_group` (mutex with `--exec`, `--git`, `--mcp-list-tools`, `--mcp-call-tool`). Help: `Ask Claude to pick ONE MCP tool for the task and execute it after y/N confirmation. Reads tools from --mcp-server. Single-shot (no agent loop)`
- [x] Validation in `main()` BEFORE the API key check:
  - If `args.mcp_claude and args.mcp_server is None` → exit 5 with stderr `error: --mcp-claude requires --mcp-server`
  - Dispatch: `if args.mcp_claude: return _run_mcp_claude(args)`
  - The API key check still runs implicitly (slice 3 DOES need Claude). Move the dispatch AFTER the api_key check OR re-check inside `_run_mcp_claude`. Pick one — recommend re-check inside to keep `main` linear
- [x] Add `def _run_mcp_claude(args) -> int`:
  1. Validate `args.mcp_server` via shlex.split (same pattern as `_run_mcp_call_tool`); empty → exit 5
  2. Validate `ANTHROPIC_API_KEY` is set; missing → exit 1 (matches existing missing-key contract)
  3. List server tools via `asyncio.run(asyncio.wait_for(_async_list_tools(server_argv), timeout=MCP_TIMEOUT_SECONDS))`. Wrap in `try/except` → on `(asyncio.TimeoutError, TimeoutError)` exit 6, on other `Exception` exit 5 (`MCP error: <Class>: <msg>`)
  4. Build `tools_payload = [{"name": t.name, "description": getattr(t, "description", "") or "", "input_schema": getattr(t, "inputSchema", None) or getattr(t, "input_schema", {}) or {}} for t in tools]`. Defensive — handle both MCP camelCase and Python snake_case shapes
  5. If `not tools_payload`: print stderr `note: server advertised no tools; passing task to Claude as text only`; proceed without `tools=` parameter
  6. Build `client = Anthropic(api_key=..., timeout=REQUEST_TIMEOUT_SECONDS)` (reuse existing constants)
  7. Call `client.messages.create(model=args.model, max_tokens=MAX_TOKENS, messages=[{"role": "user", "content": args.task}], tools=tools_payload if tools_payload else None)` — wrap in `try/except APIError` → exit 2 on API error (parallel to existing handling)
  8. Iterate `response.content` blocks. Collect:
     - `text_parts = [b.text for b in content if getattr(b, "type", None) == "text" and getattr(b, "text", None)]`
     - `tool_uses = [b for b in content if getattr(b, "type", None) == "tool_use"]`
  9. If `len(tool_uses) == 0`: print joined text to stdout (this is a normal Claude response with no tool call); call `_log_run(args.task, joined_text)` and `_append_history({...response_chars: len(joined_text), mcp_decision: "text-only"})`; return 0
  10. If `len(tool_uses) > 1`: print stderr `error: Claude proposed {N} tool calls; --mcp-claude (slice 1) only supports one — multi-step is a future slice`; return 5. Append history with `mcp_decision="rejected", mcp_rejection_reason="multi-tool"` (audit signal)
  11. If `len(tool_uses) == 1`: extract `tu.name` and `tu.input` (dict). **VALIDATE** `tu.name` is in `[t.name for t in tools]` (lookup against the list we got from the server). If not in list → cold-reject: print stderr `error: Claude proposed tool {tu.name!r} which is not in the server's advertised tools (likely hallucination)`; return 5; history with `mcp_decision="rejected", mcp_rejection_reason="hallucinated-tool"`. NO y/N prompt
  12. **VALIDATE** `tu.input` is a dict (defensive — SDK should give us a dict but check). Non-dict → cold-reject similarly with `mcp_rejection_reason="non-dict-input"`
  13. Print Claude's reasoning (the joined `text_parts`) to stdout, prefixed `Claude:` so the user sees it as commentary
  14. Print proposed call: `Proposed MCP tool call: {tu.name}({json.dumps(tu.input)})`
  15. y/N prompt to stderr (`Run this tool? [y/N]: `), `input()` with EOFError fallback, strict `{"y", "Y"}` gate. Same UX as slice 2
  16. Build base record `{ts, task, model, mcp_tool_name: tu.name, mcp_tool_args: tu.input, mcp_proposed_by: "claude", claude_reasoning: <joined text>, response_chars: 0}`
  17. Abort: stderr `aborted`, history with `mcp_decision="aborted"`, return 0
  18. Run: `_async_call_tool(...)` wrapped in `asyncio.run(asyncio.wait_for(..., timeout=MCP_TIMEOUT_SECONDS))`. TimeoutError → exit 6, NO history. Other Exception → exit 5 `MCP error:`, NO history
  19. Extract `is_error`, print result text via `_extract_text`, history with `mcp_decision="run", mcp_is_error=is_error, response_chars=len(text)`. Return `5 if is_error else 0`
- [x] **Critical safety properties**:
  1. Hallucinated tool names are cold-rejected (no prompt, no execution)
  2. Multi-tool proposals are cold-rejected (single-shot only)
  3. Non-dict tool args are cold-rejected
  4. Strict y/N gate (same as slice 2)
  5. Hallucination/multi-tool rejections write audit history with `mcp_rejection_reason` for forensics
- [x] Slice 2's history records gain a `mcp_proposed_by: "user"` field (so future analytics can distinguish human-typed vs Claude-proposed calls). One-line change: add the key to the record dict in `_run_mcp_call_tool`. Existing slice-2 tests must be updated to assert `row["mcp_proposed_by"] == "user"`
- [x] `tests/test_cli.py` adds these tests. Define a `_make_anthropic_with_tool_use(...)` helper that returns a `_StubClient`-shaped class whose `messages.create()` returns content blocks with `type="text"` and/or `type="tool_use"` per parameters:
  - `test_mcp_claude_runs_tool_after_yes` — fake list_tools returns `[SimpleNamespace(name="echo", description="echo", inputSchema={})]`. Anthropic stub returns one tool_use block (`name="echo", input={"x": 1}`) plus a text block ("I'll echo that"). Fake call_tool returns content with text "echoed: 1". Input "y". Assert main returns 0, stdout contains both "Claude: I'll echo that" and "echoed: 1", history row has `mcp_decision="run"`, `mcp_proposed_by="claude"`, `claude_reasoning` containing "echo"
  - `test_mcp_claude_no_tool_use_prints_text_only` — Anthropic stub returns text only, no tool_use. Fake call_tool MUST NOT be called (use the must-not-be-called sentinel). Assert main returns 0, stdout contains the text, history has `mcp_decision="text-only"`. Also assert log.md has the entry
  - `test_mcp_claude_multi_tool_use_is_cold_rejected` — Anthropic stub returns 2 tool_use blocks (configure `multi_count=2`). Input must-not-be-called sentinel. Assert main returns 5, stderr contains "Claude proposed 2 tool calls", history has `mcp_decision="rejected"` and `mcp_rejection_reason="multi-tool"`
  - `test_mcp_claude_hallucinated_tool_is_cold_rejected` — list_tools returns `[name="echo"]`. Anthropic stub proposes `tool_use(name="rm", input={...})`. Input must-not-be-called. Returns 5, stderr contains "hallucination", history has `mcp_rejection_reason="hallucinated-tool"`
  - `test_mcp_claude_aborts_on_n` — same setup as happy path but input "n". call_tool must-not-be-called. Returns 0, history row has `mcp_decision="aborted"`, `mcp_proposed_by="claude"`
  - `test_mcp_claude_requires_mcp_server` — `--mcp-claude task` without `--mcp-server`. Returns 5, stderr "requires --mcp-server"
  - `test_mcp_claude_requires_api_key` — `--mcp-claude --mcp-server "fake" task` with `ANTHROPIC_API_KEY` unset. Returns 1, stderr "ANTHROPIC_API_KEY"
  - `test_mcp_claude_mutually_exclusive_with_other_modes` — verify SystemExit on `--mcp-claude` with each of `--exec`, `--git`, `--mcp-list-tools`, `--mcp-call-tool`
  - `test_mcp_claude_tool_isError_returns_5` — happy path setup but call_tool returns isError=True with text "tool failed". Input "y". Returns 5, stdout has "tool failed", history has `mcp_is_error=True`
  - `test_mcp_call_tool_history_now_has_proposed_by_user` — happy path of slice 2 (`--mcp-call-tool`). Assert history row has `mcp_proposed_by == "user"` (forward-compat for slice 3 audit queries)
- [x] All 70 existing tests must continue to pass. The slice-2 tests asserting history shape will need ONE-LINE updates to also assert `mcp_proposed_by == "user"` if they read the row's `mcp_decision` — audit them and update only the necessary tests
- [x] `python -m pytest -W error` passes (no resource warnings)
- [x] `README.md` "Usage" section gains a `--mcp-claude` paragraph after the `--mcp-call-tool` paragraph: example `workbuddy --mcp-claude --mcp-server "python -m my_server" "echo hi"`. Explain that Claude reads the tools, proposes ONE call (single-shot, no multi-step), workbuddy shows reasoning + proposed call, y/N confirms. Note hallucination defense (tool name must match listed tools), and that multi-step / agent loop is a future slice
- [x] Update BACKLOG: change `[⏳] MCP integration *(slice 1+2 ...)*` to `[x] MCP integration *(--mcp-list-tools, --mcp-call-tool, --mcp-claude shipped; agent loop / multi-step deferred to v0.3)*`. With this round merging, the v0.2 BACKLOG line is finally `[x]` and ALL declared scope tiers (v0/v0.1/v0.2) ship complete
- [x] Add a new BACKLOG section `## v0.3 (post-MCP)` with one entry: `[ ] Multi-step agent loop: Claude calls tool, sees result, decides next tool — with per-call y/N gates`. This codifies that the autobuddy run did NOT ship full agent loops; humans should design that
- [x] Total project Python LOC stays under ~2200

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
- BACKLOG.md
