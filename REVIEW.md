# Review of f6ad33b

## Verdict
PASS

## Findings
- All 13 acceptance criteria met. `pytest -q` → 58 passed, AND `pytest -W error` (warnings as errors) also passes — confirms no resource warnings (no unawaited coroutines, no asyncio cleanup leaks).
- `mcp>=1.0` correctly added to `dependencies` (not a dev/optional extra). Lazy-import inside `_async_list_tools` is a nice touch: workbuddy's startup is unaffected for non-MCP invocations, and tests can bypass the import entirely by monkey-patching the helper.
- `MCP_TIMEOUT_SECONDS = 30` is a named module constant, threaded into both `asyncio.wait_for(timeout=...)` and the stderr message — single source of truth.
- Defensive coding around the SDK shape:
  - `list(getattr(result, "tools", []) or [])` — handles `tools=None` and missing attribute
  - `getattr(tool, "name", "") or ""` and `getattr(tool, "description", None) or ""` — handles `None` descriptions and empty names
  - `except Exception` (broad-but-bounded) wraps anything the MCP SDK throws into a one-line `error: MCP error: <ExcClass>: <msg>` without a traceback
  - `except (asyncio.TimeoutError, TimeoutError)` — compatible across 3.10 (alias differs) and 3.11+ (where `asyncio.TimeoutError` is just an alias for the builtin `TimeoutError`)
- argparse mutex group correctly includes all three modes (`--exec`, `--git`, `--mcp-list-tools`); the two new mutex-rejection tests (`test_mcp_mutually_exclusive_with_exec`, `test_mcp_mutually_exclusive_with_git`) verify both pairings.
- `--mcp-server` correctly lives OUTSIDE the mutex group (it's a value-bearing parameter, not a mode flag); the `--mcp-list-tools` ↔ `--mcp-server` arg-pair check happens explicitly in `main()` with separate-but-symmetric error messages.
- Early dispatch (`if args.mcp_list_tools: return _run_mcp_list_tools(args)`) happens BEFORE the API-key check, so this mode works without `ANTHROPIC_API_KEY`. Verified by `test_mcp_list_tools_ignores_task_arg` which `monkeypatch.delenv("ANTHROPIC_API_KEY")` and still gets `rc == 0`.
- The timeout test refactor from intercepting `asyncio.run` to monkey-patching `_async_list_tools` to raise `TimeoutError` directly is cleaner and avoids the unawaited-coroutine warning. The new fake awaits raise on first await, exercising the real `asyncio.run` / `wait_for` plumbing — that's better than mocking the whole asyncio dispatch.
- Pure inspection — no log.md, no history.jsonl, no Claude API call. This matches the intent of the slice and aligns with how the user's audit trail should look (the user can re-list tools cheaply without polluting their run history).
- LOC = 1354, within the planner's `~1400` target.

## Non-blocking observations (carry-forward for slice 2)
- `task` positional remains argparse-required, so `workbuddy --mcp-list-tools --mcp-server "..."` fails without a dummy task argument. The `note: --mcp-list-tools mode ignores the task argument` is a band-aid. A future slice could make `task` `nargs="?"` and require it only for the Claude-bound modes. Not blocking — UX papercut, not a safety/correctness issue.
- If `mcp` isn't installed (corrupt venv), `--mcp-list-tools` produces `error: MCP error: ModuleNotFoundError: ...` via the broad except. The error is informative but the resolution path ("run pip install -e .") isn't surfaced. Optional polish.
- `_async_list_tools` doesn't propagate the MCP server's stderr to the user. If the server crashes during `initialize()`, the user sees only "MCP error: <reason>" and may want to see the server's stderr to debug. Future slice could capture and surface server stderr on failure.
- The defensive `or []` after `getattr(result, "tools", ...)` handles current shape; if the SDK ever returns `result.tools` as a generator instead of a list, `list(...)` consumes it correctly. Forward-compatible.

## Suggestions for next round
- BACKLOG `MCP integration` line is still `[⏳]` — slice 2 (tool execution: `--mcp-call-tool TOOLNAME --mcp-tool-args JSON`) is the natural follow-up. Critical safety property: tool execution MUST follow the same y/N confirmation gate as `--exec` / `--git`, with the proposed JSON payload printed for the user to inspect before execution. Audit trail (history.jsonl with `mcp_*` keys) parallels the existing exec/git records.
- Slice 3 candidates: tool execution by Claude (Claude reads the list-tools output and decides which to call, with per-call user confirmation); MCP resources subscription (read-only, no security exposure); MCP prompts integration.
- **The original GOAL.md is now well-exceeded.** GOAL.md said v0 stays under 500 LOC; we're at 1354 spanning v0/v0.1/v0.2. The autobuddy run has demonstrated:
  - Disciplined slicing and one-Coder-run scoping
  - Test-driven safety guarantees with named "canary" tests
  - One graceful NEEDS_FIX recovery
  - A consistent record format and audit trail
  This is a natural completion point for the autobuddy run. **Strongest pause recommendation yet: stop the cron with `CronDelete bbee383b`** before any further v0.2 slices land. The remaining v0.2 work materially benefits from human design input (which tool-call parameters Claude is allowed to decide vs. user-fixed; how the user reviews proposed JSON args; how multi-step MCP tool chains are gated). If you want to continue, slice 2 should be very small — e.g. just `--mcp-call-tool NAME` accepting JSON args from the CLI, no Claude in the loop yet.
