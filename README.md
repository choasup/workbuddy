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
