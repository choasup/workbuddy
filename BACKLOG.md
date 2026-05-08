# Backlog

## v0 (MVP)
- [x] Project skeleton: `pyproject.toml`, `src/workbuddy/__init__.py`, `src/workbuddy/cli.py`, `tests/`
- [x] CLI entry point `workbuddy "<task>"`: parse args, echo task back (no API yet)
- [x] Anthropic SDK integration: send task to Claude API, print response
- [x] Append responses to `~/.workbuddy/log.md` with UTC timestamps
- [x] Add `--model` flag (default `claude-sonnet-4-6`)
- [⏳] Error handling: missing `ANTHROPIC_API_KEY`, network errors
- [ ] README usage section with install + example
- [ ] Unit tests for CLI parsing and log writer

## v0.1
- [ ] Persistent local state (config, history) under `~/.workbuddy/`
- [ ] Shell execution mode with confirmation prompt
- [ ] Git operations helper

## v0.2
- [ ] MCP integration
