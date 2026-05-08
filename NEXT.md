# Next Task

## Title
Add `--mcp-call-tool NAME --mcp-tool-args JSON`: invoke a specific MCP tool with user-provided args after y/N confirmation

## Why
GOAL.md v0.2 — "MCP integration", slice 2. Slice 1 shipped tool listing. This slice ships the simplest possible execution path: USER-PROVIDED tool name + USER-PROVIDED JSON args. NO Claude in the loop yet (Claude-driven tool selection is slice 3 with separate design). The user is responsible for what they call; workbuddy's job is to (a) parse the args, (b) show the proposed call, (c) gate on y/N, (d) invoke, (e) print the result, (f) audit-log. This keeps slice 2 small, testable, and free of LLM-side surprises

## Acceptance
- [ ] `src/workbuddy/cli.py` adds two argparse args:
  - `--mcp-call-tool NAME` — string, default `None`. Help: `Invoke the named MCP tool on the server given by --mcp-server, after y/N confirmation. Use --mcp-tool-args to pass arguments`
  - `--mcp-tool-args JSON` — string, default `"{}"` (empty object). Help: `JSON object string for the tool arguments. Default: {}`. The default is `"{}"` (literal string) because argparse passes strings through; the helper parses with json.loads
- [ ] Add `--mcp-call-tool` to the existing `mode_group` (mutex with `--exec`, `--git`, `--mcp-list-tools`). Verified by adding two more mutex tests
- [ ] In `main()`, BEFORE the API key check, after the existing `--mcp-list-tools`/`--mcp-server` validation:
  - If `args.mcp_call_tool is not None and args.mcp_server is None` → exit 5 with stderr `error: --mcp-call-tool requires --mcp-server`
  - If `args.mcp_tool_args != "{}"` (i.e. user explicitly set it) AND `args.mcp_call_tool is None` → exit 5 with stderr `error: --mcp-tool-args is only meaningful with --mcp-call-tool`
  - Then dispatch: `if args.mcp_call_tool is not None: return _run_mcp_call_tool(args)`
- [ ] Add async helper `async def _async_call_tool(server_argv, tool_name, tool_args)`:
  - Same `stdio_client` + `ClientSession` pattern as `_async_list_tools`
  - After `await session.initialize()`, call `await session.call_tool(tool_name, tool_args)` — returns a `CallToolResult`-shaped object
  - Return the result object
- [ ] Add sync wrapper `def _run_mcp_call_tool(args) -> int`:
  1. `shlex.split(args.mcp_server)` → `server_argv`. Empty/`ValueError` → exit 5 with `error: invalid --mcp-server: <reason>`
  2. Parse `args.mcp_tool_args` via `json.loads` → `tool_args`. `JSONDecodeError` → exit 5 with `error: --mcp-tool-args must be a JSON object: <reason>`
  3. If `not isinstance(tool_args, dict)` → exit 5 with `error: --mcp-tool-args must be a JSON object (got: <type>)`
  4. If `args.task` is non-empty, print stderr note `note: --mcp-call-tool mode ignores the task argument`
  5. Print proposed call to **stdout**: `Proposed MCP tool call: {tool_name}({json.dumps(tool_args)})`
  6. Prompt to **stderr**: `Run this tool? [y/N]: ` (trailing newline omitted, flush)
  7. `try: answer = input() / except EOFError: answer = ""`
  8. Build base history record (parallel to exec/git records): `{ts, task, model: args.model, response_chars: 0, mcp_tool_name: tool_name, mcp_tool_args: tool_args}`
  9. If `answer.strip() not in {"y", "Y"}` → print `aborted` to stderr; record `mcp_decision="aborted"`; `_append_history(record)`; return 0
  10. On run: `result = asyncio.run(asyncio.wait_for(_async_call_tool(server_argv, tool_name, tool_args), timeout=MCP_TIMEOUT_SECONDS))`
  11. `(asyncio.TimeoutError, TimeoutError)` → exit 6 `error: MCP server did not respond within {MCP_TIMEOUT_SECONDS}s`. NO history record (we don't know if the server side-effected — same posture as `_run_exec`/`_run_git` with the timeout having no exit-code recorded)
  12. Other `Exception` → exit 5 `error: MCP error: {ExcClass}: {msg}`. NO history record
  13. Extract `is_error = bool(getattr(result, "isError", None) or getattr(result, "is_error", False))` — handle both camelCase (MCP spec) and snake_case (some Python SDKs) defensively
  14. Print result content text via the existing `_extract_text(result)` helper (it already does `getattr(block, "text", None)` per content block — works for `CallToolResult.content` whose blocks expose `.text`). For non-text content (image/resource blocks lacking `.text`), `_extract_text` silently skips — a minor information loss for slice 2, acceptable
  15. Update record: `mcp_decision="run"`, `mcp_is_error=is_error`, `response_chars=len(text)`. `_append_history(record)`
  16. Return `5 if is_error else 0` — non-zero exit signals tool-side failure to the shell
- [ ] CRITICAL safety property: validation errors (bad JSON, missing arg pair, non-dict args) MUST short-circuit BEFORE the y/N prompt is shown. Otherwise the user might confirm a malformed call. Test this with the `_input_must_not_be_called` sentinel
- [ ] CRITICAL UX property: y/N prompt is strict — `{"y", "Y"}` only. Empty input / EOF / `yes` / `Y\n` (the latter handled by `.strip()`) abort. Same posture as `--exec` / `--git`
- [ ] `tests/test_cli.py` adds these tests using `monkeypatch.setattr(cli_mod, "_async_call_tool", _fake)`:
  - `test_mcp_call_tool_runs_after_yes` — fake returns `types.SimpleNamespace(content=[types.SimpleNamespace(text="42")], isError=False)`. Input `"y"`. Server cmd `"fake"`, tool `"echo"`, args `'{"x": 1}'`. Assert `main` returns 0, stdout contains `42`, fake was called once with `(["fake"], "echo", {"x": 1})`. History row has `mcp_tool_name == "echo"`, `mcp_tool_args == {"x": 1}`, `mcp_decision == "run"`, `mcp_is_error is False`
  - `test_mcp_call_tool_aborts_on_n` — input `"n"`. Fake NOT called (use a `_must_not_be_called` async sentinel that raises if invoked). History row has `mcp_decision == "aborted"`. stderr has `aborted`. Returns 0
  - `test_mcp_call_tool_invalid_json_args_is_cold_rejected` — `--mcp-tool-args "not json"`. `_input_must_not_be_called` installed. Returns 5. stderr contains `must be a JSON object`. No history row created
  - `test_mcp_call_tool_args_must_be_dict_not_array` — `--mcp-tool-args "[1,2,3]"`. Cold-rejected, returns 5, stderr contains `must be a JSON object`
  - `test_mcp_call_tool_requires_mcp_server` — `--mcp-call-tool echo` WITHOUT `--mcp-server`. Returns 5. stderr contains `requires --mcp-server`
  - `test_mcp_tool_args_alone_errors` — `--mcp-tool-args '{"x":1}'` WITHOUT `--mcp-call-tool`. Returns 5. stderr contains `only meaningful with --mcp-call-tool`
  - `test_mcp_call_tool_is_error_returns_5` — fake returns `isError=True` with content text `"failed: bad input"`. Input `"y"`. Returns 5 (NOT 0). stdout contains the error text (so user sees it). History row has `mcp_is_error == True`, `mcp_decision == "run"`
  - `test_mcp_call_tool_timeout` — fake is an async function that raises `TimeoutError`. Input `"y"`. Returns 6. stderr contains `did not respond within`. NO history row (the `_append_history` call lives AFTER the asyncio.run line, so it isn't reached)
  - `test_mcp_call_tool_protocol_error` — fake raises `RuntimeError("boom")`. Input `"y"`. Returns 5. stderr contains `MCP error:` and `boom`. NO `Traceback` in stderr. NO history row
  - `test_mcp_call_tool_default_args_is_empty_dict` — no `--mcp-tool-args`. Input `"y"`. Fake invoked with `{}` as third arg
  - `test_mcp_call_tool_mutually_exclusive_with_list_tools` — `--mcp-call-tool x --mcp-list-tools`. SystemExit, code != 0
  - `test_mcp_call_tool_mutually_exclusive_with_exec_and_git` — combined check: `--mcp-call-tool x --exec` and `--mcp-call-tool x --git` both raise SystemExit
- [ ] All 58 existing tests must continue to pass unchanged
- [ ] `python -m pytest -W error` passes (no resource warnings — same standard as slice 1)
- [ ] `README.md` "Usage" section gains a `--mcp-call-tool` paragraph after the `--mcp-list-tools` paragraph: example `workbuddy --mcp-call-tool echo --mcp-tool-args '{"text": "hi"}' --mcp-server "python -m my_server" .`. Note that args must be a JSON object, the call requires y/N confirmation, exit codes match other modes (0 success, 5 error / tool-isError, 6 timeout), and a future slice will add Claude-driven tool selection
- [ ] Update the BACKLOG annotation: change `(slice 1: --mcp-list-tools listing only; tool execution and resource subscription deferred)` to `(slice 1+2 shipped: --mcp-list-tools and --mcp-call-tool with user-provided args; slice 3 will add Claude-driven tool selection)`. Keep the line at `[⏳]` since slice 3 still pending
- [ ] Total project Python LOC stays under ~1700

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
- BACKLOG.md
