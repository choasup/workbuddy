# Next Task

## Title
Add a README usage section with install command and a working example

## Why
GOAL.md v0 — BACKLOG explicitly lists "README usage section with install + example"; without it, a human installing the project can't tell how to invoke it

## Acceptance
- [x] `README.md` keeps the existing "Architecture (control plane)", "Schedule", and "Status" sections (they are still accurate — do NOT delete the bootstrapping framing) but adds a top-level `## Install` and `## Usage` block above them
- [x] `## Install` section shows `pip install -e .` (editable install) and notes the Python version requirement (`3.10+`, sourced from `pyproject.toml`)
- [x] `## Usage` section shows: setting `ANTHROPIC_API_KEY` in the shell (one example line), a runnable `workbuddy "summarize this paragraph"` example, and a one-line note about the `--model` flag with the default model id (`claude-sonnet-4-6`) — copy the default from `cli.py:DEFAULT_MODEL`
- [x] `## Usage` section also mentions in one sentence each: per-run logging to `~/.workbuddy/log.md`, and the `WORKBUDDY_HOME` env override for relocating that log
- [x] No code, test, or `pyproject.toml` changes in this round — README-only edit
- [x] `python -m pytest` still passes (sanity — should be unchanged)

## Files likely involved
- README.md
