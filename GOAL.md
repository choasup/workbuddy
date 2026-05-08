# workbuddy — North Star

A minimal Python CLI agent assistant. Drop-in command `workbuddy "<task>"` that turns natural-language tasks into agent runs against the Claude API.

This file is **human-edited only**. Agents must not modify it.

## v0 Scope (MVP)
- Python CLI: `workbuddy "<task>"`
- Calls Claude API (`anthropic` SDK), prints response
- Logs every run to `~/.workbuddy/log.md` with timestamp
- Reads `ANTHROPIC_API_KEY` from environment
- Default model: `claude-sonnet-4-6`

## v0.1 (post-MVP)
- Persistent local state in `~/.workbuddy/`
- Shell tool execution (with confirmation)
- Git operations

## v0.2
- MCP integration

## Constraints
- Python 3.10+
- Use the official `anthropic` SDK
- v0 stays under 500 LOC total
- Tests pass before any push
