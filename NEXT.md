# Next Task

## Title
Add `--mcp-list-tools --mcp-server "<cmd>"` mode: connect to a stdio MCP server and print its tools

## Why
GOAL.md v0.2 — "MCP integration". Smallest useful slice: spawn an MCP server, perform the standard initialize / list-tools handshake, print tool names + descriptions. NO tool execution, NO resources, NO prompts integration in this round — those follow in separate slices. This slice proves the wire works and gives users visibility into what an MCP server offers without any execution risk

## Acceptance
- [ ] `pyproject.toml` adds `mcp>=1.0` to `[project] dependencies`. Existing `anthropic>=0.40` and the dev extra stay as-is
- [ ] `src/workbuddy/cli.py` adds two argparse args:
  - `--mcp-list-tools` — `action="store_true"`, default `False`. Help: `Connect to the MCP server given by --mcp-server, print its advertised tools, then exit. Does NOT call Claude or execute any tool`
  - `--mcp-server CMD` — string, default `None`. Help: `Shell command (parsed via shlex.split) that spawns an MCP server speaking stdio JSON-RPC. Required when --mcp-list-tools is set`
- [ ] Add `--mcp-list-tools` to the existing `mode_group` so it is mutually exclusive with `--exec` and `--git`
- [ ] After argparse parses but before the API call: if `args.mcp_list_tools` is True and `args.mcp_server` is None → exit 5 with stderr `error: --mcp-list-tools requires --mcp-server`. If `args.mcp_server` is set but `args.mcp_list_tools` is False → exit 5 with stderr `error: --mcp-server is only meaningful with --mcp-list-tools`
- [ ] Add an async helper `async def _async_list_tools(server_argv: list[str]) -> list` that:
  - Uses `mcp.client.stdio.stdio_client` and `mcp.ClientSession` (or whatever the current public API surface is — pin to whatever `mcp>=1.0` ships)
  - Constructs `StdioServerParameters(command=server_argv[0], args=server_argv[1:])`
  - Opens `stdio_client(...)` then `ClientSession(read, write)`, calls `await session.initialize()`, calls `await session.list_tools()`, and returns the resulting `tools` list (each item exposes `.name` and `.description`)
- [ ] Add a sync wrapper `def _run_mcp_list_tools(args) -> int` that:
  1. `shlex.split(args.mcp_server)` → server_argv. Empty / `ValueError` → exit 5 with stderr `error: invalid --mcp-server: <reason>`
  2. Wrap with `asyncio.run(asyncio.wait_for(_async_list_tools(server_argv), timeout=30))`
  3. On `asyncio.TimeoutError` (or `TimeoutError` in 3.11+) → exit 6 with stderr `error: MCP server did not respond within 30s`
  4. On any other `Exception` (catch broadly — MCP can raise many flavours) → exit 5 with stderr `error: MCP error: <ExcClass>: <msg>`. NO unhandled stack traces
  5. Print one line per tool: `{tool.name}: {tool.description or ""}` to stdout. Use `getattr(tool, "name", "")` / `getattr(tool, "description", None) or ""` defensively in case the SDK's tool object shape changes
  6. Return 0
- [ ] Wire `main()`: after argparse and the early `--mcp-list-tools` / `--mcp-server` argument validation, BEFORE the API key check and BEFORE the API call, dispatch: `if args.mcp_list_tools: return _run_mcp_list_tools(args)`. The Anthropic API key is NOT required for this mode (no Claude call). The `task` positional arg is required by argparse but ignored — print a one-line note on stderr `note: --mcp-list-tools mode ignores the task argument` if `args.task` is non-empty
- [ ] No log.md or history.jsonl entries for this mode (it's pure inspection — neither user-facing prose nor a confirmable command)
- [ ] `tests/test_cli.py` adds (use `monkeypatch.setattr(cli_mod, "_async_list_tools", _fake)` to bypass the real MCP SDK; pytest-asyncio is NOT required because the production code's `asyncio.run` resolves the coroutine):
  - `test_mcp_list_tools_happy_path` — fake `_async_list_tools` returns `[types.SimpleNamespace(name="echo", description="echo the input"), types.SimpleNamespace(name="add", description="add two numbers")]`. Assert `main(["--mcp-list-tools", "--mcp-server", "fake-server-cmd", "task"])` returns 0 and stdout contains both `echo: echo the input` and `add: add two numbers`
  - `test_mcp_list_tools_handles_empty_description` — fake returns one tool with `description=None`; assert stdout has `name: ` (empty after the colon) without crashing
  - `test_mcp_list_tools_requires_mcp_server` — `main(["--mcp-list-tools", "task"])` returns 5; stderr contains `requires --mcp-server`. Crucially the fake `_async_list_tools` should NOT be installed; if validation fails to short-circuit, an AttributeError will fire (the real function may not be importable in the test env)
  - `test_mcp_server_alone_requires_list_tools` — `main(["--mcp-server", "fake", "task"])` returns 5; stderr contains `only meaningful with --mcp-list-tools`. Same no-fake-installed sentinel
  - `test_mcp_list_tools_protocol_error` — fake `_async_list_tools` raises a generic `Exception("boom")`; assert main returns 5, stderr contains `MCP error:` and `boom`. NO Python traceback in stderr
  - `test_mcp_list_tools_timeout` — fake is an async function that does `await asyncio.sleep(60)` (would hang) but the test sets the timeout to a very small value via monkeypatching the helper to use a 0.1s timeout (or by patching `asyncio.wait_for` to raise `TimeoutError` directly). Assert main returns 6, stderr contains `did not respond within 30s` (or matches the patched timeout message). Pragmatic: the simplest implementation is to monkeypatch `_run_mcp_list_tools` to call `_async_list_tools` directly (bypassing the production `wait_for(..., timeout=30)`) — but that doesn't test the actual timeout wiring. Cleaner: monkeypatch `cli_mod.asyncio.run` (or `cli_mod.asyncio.wait_for`) to raise `asyncio.TimeoutError`. Pick one approach and document it
  - `test_mcp_mutually_exclusive_with_exec` — `main(["--mcp-list-tools", "--exec", "task"])` raises SystemExit; stderr mentions `not allowed with` or one of the flag names
  - `test_mcp_mutually_exclusive_with_git` — same shape with `--git`
  - `test_mcp_list_tools_ignores_task_arg` — fake returns one tool; main passes `"please summarize"` as task; assert it returns 0 AND stderr contains `ignores the task argument`. Confirms no Anthropic call was made (the `Anthropic` stub should NOT be installed; if production code accidentally calls it, the import will reach the real `anthropic` package which is fine — but the test should additionally assert no API key was required, e.g. by NOT setting `ANTHROPIC_API_KEY` and confirming exit 0)
- [ ] All 49 existing tests must continue to pass unchanged. The new mcp dep should not affect them
- [ ] After the `pyproject.toml` change, the Coder MUST run `pip install -e ".[dev]"` in the venv before pytest, so `mcp` becomes importable. (Note this in LOG.md so the Reviewer knows the venv was updated)
- [ ] `python -m pytest` passes (no real MCP server, no network, no `ANTHROPIC_API_KEY` needed for the new tests)
- [ ] `README.md` "Usage" section gains a brief `--mcp-list-tools` paragraph after the `--git` paragraph: a one-line `workbuddy --mcp-list-tools --mcp-server "python -m my_mcp_server" .` example, and an explicit note that this mode does NOT execute tools or call Claude — it just inspects the server's advertised capabilities. Mention that a future slice will add tool execution
- [ ] Total project Python LOC stays under ~1400. Don't pad
- [ ] Append a dedicated BACKLOG annotation: change `- [ ] MCP integration` to `- [⏳] MCP integration *(slice 1: --mcp-list-tools listing only; tool execution and resource subscription deferred)*`

## Files likely involved
- pyproject.toml
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
- BACKLOG.md
