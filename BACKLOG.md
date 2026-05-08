# Backlog

## v0 (MVP)
- [x] Project skeleton: `pyproject.toml`, `src/workbuddy/__init__.py`, `src/workbuddy/cli.py`, `tests/`
- [x] CLI entry point `workbuddy "<task>"`: parse args, echo task back (no API yet)
- [x] Anthropic SDK integration: send task to Claude API, print response
- [x] Append responses to `~/.workbuddy/log.md` with UTC timestamps
- [x] Add `--model` flag (default `claude-sonnet-4-6`)
- [x] Error handling: missing `ANTHROPIC_API_KEY`, network errors
- [x] README usage section with install + example
- [x] Unit tests for CLI parsing and log writer

## v0 polish (after MVP, before v0.1)
- [x] Add `LICENSE` (MIT), declare `[project.optional-dependencies] dev = ["pytest>=7"]`, bump README "Status" from `Pre-v0` to `v0 — feature complete`

## v0.1
- [x] Persistent local state (config, history) under `~/.workbuddy/` *(config.json `default_model` + history.jsonl with rotation)*
- [x] Shell execution mode with confirmation prompt *(`--exec` flag; single command via `shlex.split`; `shell=False`; default-no y/N confirm; exec_* fields in history)*
- [x] Git operations helper *(`--git` mode with strict read-only subcommand allowlist (10 entries); `branch`/`reflog` excluded due to write variants; mutually exclusive with `--exec`)*

## v0.2
- [x] MCP integration *(--mcp-list-tools, --mcp-call-tool, and --mcp-claude shipped; agent loop / multi-step deferred to v0.3)*

## v0.3 (post-MCP)
- [⏳] Multi-step agent loop: Claude calls tool, sees result, decides next tool — with per-call y/N gates *(slice 1: `--mcp-agent` + per-turn y/N + hard cap; slice 2: consecutive-error abort with exit 8; slice 3: `--mcp-agent-dry-run` inspection mode; slice 4: `--reflect` one-shot self-evaluation; parallel tool calls deferred)*
