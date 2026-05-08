import argparse
import asyncio
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from anthropic import Anthropic, APIError

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024
MAX_LOGGED_RESPONSE_CHARS = 4000
REQUEST_TIMEOUT_SECONDS = 60.0
MAX_HISTORY_ROWS = 1000
GIT_CONTEXT_TIMEOUT_SECONDS = 10
MCP_TIMEOUT_SECONDS = 30
READONLY_GIT_SUBCMDS = frozenset(
    {
        "status",
        "log",
        "diff",
        "show",
        "blame",
        "rev-parse",
        "ls-files",
        "describe",
        "shortlog",
        "name-rev",
    }
)


def _config_path() -> Path:
    return _log_path().parent / "config.json"


def _load_config_default_model() -> str:
    path = _config_path()
    if not path.exists():
        return DEFAULT_MODEL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: ignoring malformed config.json: {exc}", file=sys.stderr)
        return DEFAULT_MODEL
    if not isinstance(data, dict):
        print(
            "warning: ignoring malformed config.json: top-level must be an object",
            file=sys.stderr,
        )
        return DEFAULT_MODEL
    if "default_model" not in data:
        return DEFAULT_MODEL
    value = data["default_model"]
    if isinstance(value, str) and value:
        return value
    print(
        "warning: ignoring malformed config.json: default_model must be a non-empty string",
        file=sys.stderr,
    )
    return DEFAULT_MODEL


def _build_parser() -> argparse.ArgumentParser:
    effective_default = _load_config_default_model()
    parser = argparse.ArgumentParser(
        prog="workbuddy",
        description="Minimal Python CLI agent assistant backed by the Claude API.",
    )
    parser.add_argument("task", help="Natural-language task for the agent to run.")
    parser.add_argument(
        "--model",
        default=effective_default,
        help=f"Claude model id (default: {effective_default})",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--exec",
        action="store_true",
        default=False,
        help="Ask Claude for a single shell command and execute it after y/N confirmation",
    )
    mode_group.add_argument(
        "--git",
        action="store_true",
        default=False,
        help=(
            "Read-only git helper: loads repo context, runs a Claude-proposed git read "
            "command after y/N confirmation. Write subcommands are blocked"
        ),
    )
    mode_group.add_argument(
        "--mcp-list-tools",
        action="store_true",
        default=False,
        help=(
            "Connect to the MCP server given by --mcp-server, print its advertised tools, "
            "then exit. Does NOT call Claude or execute any tool"
        ),
    )
    mode_group.add_argument(
        "--mcp-call-tool",
        default=None,
        help=(
            "Invoke the named MCP tool on the server given by --mcp-server, after y/N "
            "confirmation. Use --mcp-tool-args to pass arguments"
        ),
    )
    mode_group.add_argument(
        "--mcp-claude",
        action="store_true",
        default=False,
        help=(
            "Ask Claude to pick ONE MCP tool for the task and execute it after y/N "
            "confirmation. Reads tools from --mcp-server. Single-shot (no agent loop)"
        ),
    )
    parser.add_argument(
        "--mcp-server",
        default=None,
        help=(
            "Shell command (parsed via shlex.split) that spawns an MCP server speaking "
            "stdio JSON-RPC. Required when --mcp-list-tools or --mcp-call-tool is set"
        ),
    )
    parser.add_argument(
        "--mcp-tool-args",
        default="{}",
        help="JSON object string for the tool arguments. Default: {}",
    )
    return parser


def _extract_text(response) -> str:
    parts = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts)


def _log_path() -> Path:
    home_override = os.environ.get("WORKBUDDY_HOME")
    base = Path(home_override) if home_override else Path.home() / ".workbuddy"
    return base / "log.md"


def _history_path() -> Path:
    return _log_path().parent / "history.jsonl"


def _append_history(record: dict) -> None:
    try:
        path = _history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > MAX_HISTORY_ROWS:
            with path.open("w", encoding="utf-8") as f:
                f.writelines(lines[-MAX_HISTORY_ROWS:])
    except OSError as exc:
        print(f"warning: failed to append run to history: {exc}", file=sys.stderr)


def _log_run(task: str, response_text: str) -> None:
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = response_text
        if len(body) > MAX_LOGGED_RESPONSE_CHARS:
            body = body[:MAX_LOGGED_RESPONSE_CHARS] + "... [truncated]"
        entry = (
            f"## {timestamp}\n"
            f"**Task:** {task}\n\n"
            f"**Response:**\n\n"
            f"{body}\n\n"
        )
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        print(f"warning: failed to append run to log: {exc}", file=sys.stderr)


_GIT_CONTEXT_UNAVAILABLE = (
    "[Branch: (unknown — not a git repository or git unavailable)]"
)


def _load_git_context() -> str:
    cmds = [
        ("Branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        ("Status", ["git", "status", "--porcelain=v1"]),
        ("Recent commits", ["git", "log", "--oneline", "-10"]),
    ]
    parts = []
    for label, cmd in cmds:
        try:
            result = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
                timeout=GIT_CONTEXT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"warning: git context unavailable: {exc}", file=sys.stderr)
            return _GIT_CONTEXT_UNAVAILABLE
        if result.returncode != 0:
            print(
                f"warning: git context unavailable: {label} query failed",
                file=sys.stderr,
            )
            return _GIT_CONTEXT_UNAVAILABLE
        parts.append(f"[{label}: {result.stdout.strip()}]")
    return "\n".join(parts)


async def _async_list_tools(server_argv: list[str]):
    from mcp import StdioServerParameters
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=server_argv[0], args=server_argv[1:])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return list(getattr(result, "tools", []) or [])


async def _async_call_tool(server_argv: list[str], tool_name: str, tool_args: dict):
    from mcp import StdioServerParameters
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=server_argv[0], args=server_argv[1:])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool_name, tool_args)


def _run_mcp_claude(args) -> int:
    raw = args.mcp_server or ""
    try:
        server_argv = shlex.split(raw)
    except ValueError as exc:
        print(f"error: invalid --mcp-server: {exc}", file=sys.stderr)
        return 5
    if not server_argv:
        print("error: invalid --mcp-server: empty command", file=sys.stderr)
        return 5

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "error: ANTHROPIC_API_KEY environment variable is not set",
            file=sys.stderr,
        )
        return 1

    try:
        tools = asyncio.run(
            asyncio.wait_for(
                _async_list_tools(server_argv), timeout=MCP_TIMEOUT_SECONDS
            )
        )
    except (asyncio.TimeoutError, TimeoutError):
        print(
            f"error: MCP server did not respond within {MCP_TIMEOUT_SECONDS}s",
            file=sys.stderr,
        )
        return 6
    except Exception as exc:
        print(f"error: MCP error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5

    tool_names = [getattr(t, "name", "") for t in tools]
    tools_payload = []
    for t in tools:
        schema = (
            getattr(t, "inputSchema", None)
            or getattr(t, "input_schema", None)
            or {}
        )
        tools_payload.append(
            {
                "name": getattr(t, "name", "") or "",
                "description": getattr(t, "description", "") or "",
                "input_schema": schema,
            }
        )

    if not tools_payload:
        print(
            "note: server advertised no tools; passing task to Claude as text only",
            file=sys.stderr,
        )

    client = Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
    create_kwargs = {
        "model": args.model,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": args.task}],
    }
    if tools_payload:
        create_kwargs["tools"] = tools_payload
    try:
        response = client.messages.create(**create_kwargs)
    except APIError as exc:
        print(
            f"error: API call failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    content = getattr(response, "content", []) or []
    text_parts = [
        getattr(b, "text", "") or ""
        for b in content
        if getattr(b, "type", None) == "text" and getattr(b, "text", None)
    ]
    tool_uses = [b for b in content if getattr(b, "type", None) == "tool_use"]
    joined_text = "".join(text_parts)

    base_record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task": args.task,
        "model": args.model,
        "response_chars": 0,
        "mcp_proposed_by": "claude",
    }

    if not tool_uses:
        if joined_text:
            print(joined_text)
        _log_run(args.task, joined_text)
        record = dict(base_record)
        record["response_chars"] = len(joined_text)
        record["mcp_decision"] = "text-only"
        record["claude_reasoning"] = joined_text
        _append_history(record)
        return 0

    if len(tool_uses) > 1:
        print(
            f"error: Claude proposed {len(tool_uses)} tool calls; "
            f"--mcp-claude (slice 1) only supports one — multi-step is a future slice",
            file=sys.stderr,
        )
        record = dict(base_record)
        record["mcp_decision"] = "rejected"
        record["mcp_rejection_reason"] = "multi-tool"
        record["claude_reasoning"] = joined_text
        _append_history(record)
        return 5

    tu = tool_uses[0]
    tu_name = getattr(tu, "name", None)
    tu_input = getattr(tu, "input", None)

    if tu_name not in tool_names:
        print(
            f"error: Claude proposed tool {tu_name!r} which is not in the server's "
            f"advertised tools (likely hallucination)",
            file=sys.stderr,
        )
        record = dict(base_record)
        record["mcp_decision"] = "rejected"
        record["mcp_rejection_reason"] = "hallucinated-tool"
        record["mcp_tool_name"] = tu_name
        record["claude_reasoning"] = joined_text
        _append_history(record)
        return 5

    if not isinstance(tu_input, dict):
        print(
            f"error: Claude's proposed tool input is not a JSON object "
            f"(got: {type(tu_input).__name__})",
            file=sys.stderr,
        )
        record = dict(base_record)
        record["mcp_decision"] = "rejected"
        record["mcp_rejection_reason"] = "non-dict-input"
        record["mcp_tool_name"] = tu_name
        record["claude_reasoning"] = joined_text
        _append_history(record)
        return 5

    if joined_text:
        print(f"Claude: {joined_text}")
    print(f"Proposed MCP tool call: {tu_name}({json.dumps(tu_input)})")
    sys.stderr.write("Run this tool? [y/N]: ")
    sys.stderr.flush()
    try:
        answer = input()
    except EOFError:
        answer = ""

    record = dict(base_record)
    record["mcp_tool_name"] = tu_name
    record["mcp_tool_args"] = tu_input
    record["claude_reasoning"] = joined_text

    if answer.strip() not in {"y", "Y"}:
        print("aborted", file=sys.stderr)
        record["mcp_decision"] = "aborted"
        _append_history(record)
        return 0

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _async_call_tool(server_argv, tu_name, tu_input),
                timeout=MCP_TIMEOUT_SECONDS,
            )
        )
    except (asyncio.TimeoutError, TimeoutError):
        print(
            f"error: MCP server did not respond within {MCP_TIMEOUT_SECONDS}s",
            file=sys.stderr,
        )
        return 6
    except Exception as exc:
        print(f"error: MCP error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5

    is_error = bool(
        getattr(result, "isError", None) or getattr(result, "is_error", False)
    )
    text = _extract_text(result)
    if text:
        print(text)

    record["mcp_decision"] = "run"
    record["mcp_is_error"] = is_error
    record["response_chars"] = len(text)
    _append_history(record)

    return 5 if is_error else 0


def _run_mcp_call_tool(args) -> int:
    raw = args.mcp_server or ""
    try:
        server_argv = shlex.split(raw)
    except ValueError as exc:
        print(f"error: invalid --mcp-server: {exc}", file=sys.stderr)
        return 5
    if not server_argv:
        print("error: invalid --mcp-server: empty command", file=sys.stderr)
        return 5

    try:
        tool_args = json.loads(args.mcp_tool_args)
    except json.JSONDecodeError as exc:
        print(
            f"error: --mcp-tool-args must be a JSON object: {exc}",
            file=sys.stderr,
        )
        return 5
    if not isinstance(tool_args, dict):
        print(
            f"error: --mcp-tool-args must be a JSON object (got: {type(tool_args).__name__})",
            file=sys.stderr,
        )
        return 5

    if args.task:
        print(
            "note: --mcp-call-tool mode ignores the task argument",
            file=sys.stderr,
        )

    tool_name = args.mcp_call_tool
    proposed_payload = json.dumps(tool_args)
    print(f"Proposed MCP tool call: {tool_name}({proposed_payload})")
    sys.stderr.write("Run this tool? [y/N]: ")
    sys.stderr.flush()
    try:
        answer = input()
    except EOFError:
        answer = ""

    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task": args.task,
        "model": args.model,
        "response_chars": 0,
        "mcp_tool_name": tool_name,
        "mcp_tool_args": tool_args,
        "mcp_proposed_by": "user",
    }

    if answer.strip() not in {"y", "Y"}:
        print("aborted", file=sys.stderr)
        record["mcp_decision"] = "aborted"
        _append_history(record)
        return 0

    try:
        result = asyncio.run(
            asyncio.wait_for(
                _async_call_tool(server_argv, tool_name, tool_args),
                timeout=MCP_TIMEOUT_SECONDS,
            )
        )
    except (asyncio.TimeoutError, TimeoutError):
        print(
            f"error: MCP server did not respond within {MCP_TIMEOUT_SECONDS}s",
            file=sys.stderr,
        )
        return 6
    except Exception as exc:
        print(f"error: MCP error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5

    is_error = bool(
        getattr(result, "isError", None) or getattr(result, "is_error", False)
    )
    text = _extract_text(result)
    if text:
        print(text)

    record["mcp_decision"] = "run"
    record["mcp_is_error"] = is_error
    record["response_chars"] = len(text)
    _append_history(record)

    return 5 if is_error else 0


def _run_mcp_list_tools(args) -> int:
    raw = args.mcp_server or ""
    try:
        server_argv = shlex.split(raw)
    except ValueError as exc:
        print(f"error: invalid --mcp-server: {exc}", file=sys.stderr)
        return 5
    if not server_argv:
        print("error: invalid --mcp-server: empty command", file=sys.stderr)
        return 5

    if args.task:
        print("note: --mcp-list-tools mode ignores the task argument", file=sys.stderr)

    try:
        tools = asyncio.run(
            asyncio.wait_for(
                _async_list_tools(server_argv), timeout=MCP_TIMEOUT_SECONDS
            )
        )
    except (asyncio.TimeoutError, TimeoutError):
        print(
            f"error: MCP server did not respond within {MCP_TIMEOUT_SECONDS}s",
            file=sys.stderr,
        )
        return 6
    except Exception as exc:
        print(
            f"error: MCP error: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 5

    for tool in tools:
        name = getattr(tool, "name", "") or ""
        description = getattr(tool, "description", None) or ""
        print(f"{name}: {description}")
    return 0


def _run_git(args, text: str) -> int:
    command_text = text.strip()
    if not command_text:
        print("error: model returned no command", file=sys.stderr)
        return 3
    try:
        argv_list = shlex.split(command_text)
    except ValueError as exc:
        print(f"error: model returned no command: {exc}", file=sys.stderr)
        return 3
    if not argv_list:
        print("error: model returned no command", file=sys.stderr)
        return 3

    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task": args.task,
        "model": args.model,
        "response_chars": len(text),
        "git_command": command_text,
    }

    if argv_list[0] != "git":
        reason = f"command does not start with `git` (got: {argv_list[0]})"
        print(
            f"error: --git mode requires the proposed command to start with `git` "
            f"(got: {argv_list[0]})",
            file=sys.stderr,
        )
        record["git_decision"] = "rejected"
        record["git_rejection_reason"] = reason
        _append_history(record)
        return 4

    if len(argv_list) < 2:
        print("error: --git mode requires a subcommand", file=sys.stderr)
        record["git_decision"] = "rejected"
        record["git_rejection_reason"] = "missing subcommand"
        _append_history(record)
        return 4

    sub = argv_list[1]
    if sub not in READONLY_GIT_SUBCMDS:
        print(
            f"error: --git mode rejects subcommand `{sub}` "
            f"(write subcommands need a separate --allow-write flag, not yet supported)",
            file=sys.stderr,
        )
        record["git_decision"] = "rejected"
        record["git_rejection_reason"] = (
            f"subcommand `{sub}` is not in the read-only allowlist"
        )
        _append_history(record)
        return 4

    print(f"Proposed command: {command_text}")
    sys.stderr.write("Run this command? [y/N]: ")
    sys.stderr.flush()
    try:
        answer = input()
    except EOFError:
        answer = ""

    if answer.strip() not in {"y", "Y"}:
        print("aborted", file=sys.stderr)
        record["git_decision"] = "aborted"
        _append_history(record)
        return 0

    result = subprocess.run(argv_list, shell=False, check=False)
    record["git_decision"] = "run"
    record["git_exit"] = result.returncode
    _append_history(record)
    return result.returncode


def _run_exec(args, text: str) -> int:
    command_text = text.strip()
    if not command_text:
        print("error: model returned no command", file=sys.stderr)
        return 3
    try:
        argv_list = shlex.split(command_text)
    except ValueError as exc:
        print(f"error: model returned no command: {exc}", file=sys.stderr)
        return 3
    if not argv_list:
        print("error: model returned no command", file=sys.stderr)
        return 3

    print(f"Proposed command: {command_text}")
    sys.stderr.write("Run this command? [y/N]: ")
    sys.stderr.flush()
    try:
        answer = input()
    except EOFError:
        answer = ""

    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task": args.task,
        "model": args.model,
        "response_chars": len(text),
        "exec_command": command_text,
    }

    if answer.strip() not in {"y", "Y"}:
        print("aborted", file=sys.stderr)
        record["exec_decision"] = "aborted"
        _append_history(record)
        return 0

    result = subprocess.run(argv_list, shell=False, check=False)
    record["exec_decision"] = "run"
    record["exec_exit"] = result.returncode
    _append_history(record)
    return result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.mcp_list_tools and args.mcp_server is None:
        print("error: --mcp-list-tools requires --mcp-server", file=sys.stderr)
        return 5
    if args.mcp_call_tool is not None and args.mcp_server is None:
        print("error: --mcp-call-tool requires --mcp-server", file=sys.stderr)
        return 5
    if (
        args.mcp_server is not None
        and not args.mcp_list_tools
        and args.mcp_call_tool is None
        and not args.mcp_claude
    ):
        print(
            "error: --mcp-server is only meaningful with --mcp-list-tools, "
            "--mcp-call-tool, or --mcp-claude",
            file=sys.stderr,
        )
        return 5
    if args.mcp_tool_args != "{}" and args.mcp_call_tool is None:
        print(
            "error: --mcp-tool-args is only meaningful with --mcp-call-tool",
            file=sys.stderr,
        )
        return 5

    if args.mcp_claude and args.mcp_server is None:
        print("error: --mcp-claude requires --mcp-server", file=sys.stderr)
        return 5

    if args.mcp_list_tools:
        return _run_mcp_list_tools(args)
    if args.mcp_call_tool is not None:
        return _run_mcp_call_tool(args)
    if args.mcp_claude:
        return _run_mcp_claude(args)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "error: ANTHROPIC_API_KEY environment variable is not set",
            file=sys.stderr,
        )
        return 1

    if args.git:
        git_context = _load_git_context()
        user_content = (
            "Reply with exactly ONE git read-only command. "
            "No commentary, no markdown, no fences. "
            "Allowed subcommands: status, log, diff, show, blame, "
            "rev-parse, ls-files, describe, shortlog, name-rev. "
            "Repository context follows.\n\n"
            f"{git_context}\n\n"
            f"Task: {args.task}"
        )
    elif args.exec:
        user_content = (
            f"Reply with exactly ONE POSIX shell command. "
            f"No commentary, no markdown, no fences. Task: {args.task}"
        )
    else:
        user_content = args.task

    client = Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = client.messages.create(
            model=args.model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": user_content}],
        )
    except APIError as exc:
        print(
            f"error: API call failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2
    text = _extract_text(response)

    if args.git:
        return _run_git(args, text)
    if args.exec:
        return _run_exec(args, text)

    print(text)
    _log_run(args.task, text)
    _append_history(
        {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "task": args.task,
            "model": args.model,
            "response_chars": len(text),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
