# workbuddy

A minimal Python CLI agent assistant. **Currently bootstrapping** — being built end-to-end by 3 collaborating scheduled Claude agents (Planner / Coder / Reviewer).

## Install

Requires Python 3.10 or newer.

```bash
pip install -e .
```

This installs an editable build of the `workbuddy` package and exposes a `workbuddy` console script on your `PATH`.

## Usage

Set your Anthropic API key in the shell, then invoke `workbuddy` with a task:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
workbuddy "summarize this paragraph"
```

Override the model with `--model` (default: `claude-sonnet-4-6`):

```bash
workbuddy --model claude-opus-4-7 "write a haiku about caching"
```

To persist a preferred default without typing `--model` every time, create `~/.workbuddy/config.json` with shape `{"default_model": "claude-opus-4-7"}`. An explicit `--model` flag still wins.

Pass `--exec` to ask Claude for a single shell command and run it after explicit confirmation:

```bash
workbuddy --exec "list git branches sorted by commit date"
```

Each proposed command is shown for explicit `y/N` confirmation. Commands run with `shell=False` and arguments parsed via `shlex.split`, so shell metacharacters in the proposed command (`;`, `|`, `&&`, `>`, `$(...)`, backticks, etc.) are not expanded. The default answer is no — empty input or EOF aborts.

Pass `--git` for a read-only git helper that auto-loads `git status`, the current branch, and recent commits as context for Claude:

```bash
workbuddy --git "what changed on this branch since main"
```

`--git` enforces a read-only subcommand allowlist (`status`, `log`, `diff`, `show`, `blame`, `rev-parse`, `ls-files`, `describe`, `shortlog`, `name-rev`). Write subcommands like `commit`, `push`, `reset`, `rebase`, `merge`, `checkout`, `clean`, etc. are rejected before the confirmation prompt is even shown — an accidental `y` cannot trigger a write. `branch` and `reflog` are intentionally excluded from the allowlist because they have write variants (`branch -d`/`-D`/`-m`, `reflog expire`/`delete`); for read-only branch or reflog inspection, fall back to `--exec` and confirm the proposed plain-read command. `--git` and `--exec` are mutually exclusive.

Pass `--mcp-list-tools --mcp-server "<cmd>"` to inspect an MCP server's advertised tools:

```bash
workbuddy --mcp-list-tools --mcp-server "python -m my_mcp_server" .
```

This mode connects to the MCP server over stdio, performs the standard initialize / list-tools handshake, and prints one line per tool (`name: description`). It does NOT call Claude and does NOT execute any tool — it is pure inspection. The task argument is required by argparse but ignored. `--mcp-list-tools` is mutually exclusive with `--exec`, `--git`, and `--mcp-call-tool`.

Pass `--mcp-call-tool NAME --mcp-tool-args JSON` to invoke a specific tool with user-provided arguments:

```bash
workbuddy --mcp-call-tool echo --mcp-tool-args '{"text": "hi"}' --mcp-server "python -m my_server" .
```

Arguments must be a JSON object (top-level `{...}`). Bad JSON or non-object args are rejected before any confirmation prompt. The proposed call is shown as `Proposed MCP tool call: name(json-args)`, then a `y/N` confirmation prompt with default no — empty input or EOF aborts. On success, the tool's text content is printed and exit code is 0; if the tool reports `isError: true`, the error text is still printed and exit code is 5; timeouts exit 6. `--mcp-call-tool` is mutually exclusive with `--exec`, `--git`, `--mcp-list-tools`, and `--mcp-claude`.

Pass `--mcp-claude` to ask Claude to pick ONE MCP tool for your task and execute it after y/N confirmation:

```bash
workbuddy --mcp-claude --mcp-server "python -m my_server" "echo hi to the world"
```

`--mcp-claude` is single-shot only — Claude picks at most one tool. Multi-step is `--mcp-agent` (below). Defenses: (1) Claude's proposed tool name MUST be one of the actual tools the server advertised — hallucinated names are cold-rejected before the prompt; (2) if Claude proposes more than one tool call, the run is cold-rejected; (3) non-dict tool args are cold-rejected; (4) the `y/N` gate is the same strict default-no contract as other modes. The user sees Claude's reasoning text prefixed with `Claude:` and the proposed call before confirming. `--mcp-claude` is mutually exclusive with `--exec`, `--git`, `--mcp-list-tools`, `--mcp-call-tool`, and `--mcp-agent`.

Pass `--mcp-agent` for a bounded multi-step loop where Claude calls a tool, sees the result, and decides the next tool — with a y/N gate at every turn:

```bash
workbuddy --mcp-agent --mcp-server "python -m my_server" "find the file with the most lines and print its first 5"
```

Defaults to 3 turns; `--mcp-agent-max-turns N` (capped at 5, hard) overrides. Each turn: Claude proposes ONE tool call (multi-tool-per-turn is cold-rejected — parallel tool calls are deferred), workbuddy shows Claude's reasoning + the proposed call + `Turn N/M`, you confirm with `y` (default no), the tool runs, and the result is fed back to Claude for the next turn. You can abort at any turn with `n` — the loop stops and exits 0. If the loop hits `max_turns` without a final-text response from Claude, it exits 7. Hallucinated tool names and non-dict inputs are cold-rejected per turn. `--mcp-agent` is mutually exclusive with all other mode flags.

Every successful run is appended to `~/.workbuddy/log.md` with a UTC timestamp, the task, and the response. Set `WORKBUDDY_HOME` to relocate that log directory (e.g. `WORKBUDDY_HOME=/tmp/wb workbuddy "..."` writes to `/tmp/wb/log.md`).

Each run also appends a compact JSON record to `~/.workbuddy/history.jsonl` (one object per line: `ts`, `task`, `model`, `response_chars`). The file rotates to the last 1000 entries so it stays bounded over time.

## Architecture (control plane)

| File | Owner | Purpose |
|---|---|---|
| `GOAL.md` | human only | North-star scope |
| `BACKLOG.md` | Planner / Reviewer | Open tasks |
| `NEXT.md` | Planner → Coder | Single in-flight task |
| `REVIEW.md` | Reviewer | Verdict on last commit |
| `LOG.md` | all three | Append-only activity log |
| `AGENTS/` | human (initial) | Role specs |
| `src/`, `tests/` | Coder | Source + tests |

## Schedule

| Agent | Cron (UTC) | Role |
|---|---|---|
| Planner | `0 * * * *` | Picks next task → writes `NEXT.md` |
| Coder | `20 * * * *` | Implements `NEXT.md` → commits |
| Reviewer | `45 * * * *` | Reviews latest commit → writes `REVIEW.md` |

## Status

v0 — feature complete. See `BACKLOG.md` for v0.1 and beyond.
