# Next Task

## Title
Add `--exec` mode: Claude proposes one POSIX command, the user confirms, we run with `shell=False`

## Why
GOAL.md v0.1 — "Shell execution mode with confirmation prompt". This is the safe minimum first slice: ONE command proposed by the model, ALWAYS confirmed by the user, NEVER routed through a shell, AND the prompt defaults to "no" so accidental input cannot trigger execution

## Acceptance
- [x] `src/workbuddy/cli.py` adds an argparse boolean flag `--exec` (default `False`). Help text: `Ask Claude for a single shell command and execute it after y/N confirmation`
- [x] When `--exec` is set, the user-message content sent to `messages.create` becomes:
  `f"Reply with exactly ONE POSIX shell command. No commentary, no markdown, no fences. Task: {args.task}"`
  When `--exec` is NOT set, the message stays exactly as before (`args.task`)
- [x] After `_extract_text(response)`, when `--exec` is set, follow this flow exactly (use `import shlex, subprocess` at top of `cli.py`):
  1. `command_text = text.strip()`. If `command_text` is empty OR `shlex.split(command_text)` is empty → print `error: model returned no command` to stderr, do NOT subprocess, do NOT log to history, return `3`
  2. Print `Proposed command: {command_text}` to **stdout**
  3. Print prompt `Run this command? [y/N]: ` to **stderr** with no trailing newline; use `input()` to read one line — wrap in `try: answer = input(...)` / `except EOFError: answer = ""`
  4. If `answer.strip() not in {"y", "Y"}` → print `aborted` to stderr; **append history with `exec_decision="aborted"`** (see record schema below); return `0`
  5. Otherwise: `result = subprocess.run(shlex.split(command_text), shell=False, check=False)` — let stdin/stdout/stderr pass through (do NOT use `capture_output=True`). Append history with `exec_decision="run"` and `exec_exit=result.returncode`. Return `result.returncode`
- [x] **CRITICAL safety property** — `subprocess.run` MUST be called with `shell=False` and the args MUST come from `shlex.split(command_text)`. Shell metacharacters in the model output (`;`, `|`, `&&`, `>`, backticks, `$(...)`, etc.) MUST NOT be expanded. This is the single most important behaviour in this round
- [x] **CRITICAL UX property** — empty input, EOF, and any answer other than exact `y`/`Y` MUST abort. Do NOT accept `yes`/`Yes`/`Y\n` (the latter is fine because of `.strip()`)
- [x] When `--exec` is set, the success path does NOT call `_log_run` (the "response" is a command, not user-facing prose; slice 2 can revisit). The success path DOES call `_append_history` with the standard record shape PLUS:
  - `exec_command: <command_text>` (the raw model text after strip)
  - `exec_decision: "run" | "aborted"`
  - `exec_exit: <int>` — present ONLY when decision == "run"
  Build this on top of the current `{ts, task, model, response_chars}` shape — `response_chars` should be `len(text)` (the full pre-strip model output)
- [x] When `--exec` is NOT set, behaviour is identical to slice 2 (`729a26f`). All 24 existing tests must pass unchanged
- [x] `tests/test_cli.py` adds 8 tests:
  - `test_exec_runs_after_yes` — stub model returns `echo hello`, `monkeypatch.setattr("builtins.input", lambda *a, **k: "y")`, monkeypatch `cli_mod.subprocess` to a recorder fake whose `.run(*a, **k)` returns `types.SimpleNamespace(returncode=0)`. Assert recorder was called with `args=["echo", "hello"]`, `shell=False`. Assert `main(["--exec", "task"])` returns `0`
  - `test_exec_aborts_on_n` — input `"n"`, subprocess.run NOT called (recorder's call list is empty), return `0`, stderr contains `aborted`
  - `test_exec_aborts_on_empty_input` — input `""`, subprocess NOT called, return `0`, stderr contains `aborted`
  - `test_exec_aborts_on_eof` — `monkeypatch.setattr("builtins.input", _raises_eof)` where `_raises_eof` raises `EOFError`. Subprocess NOT called, return `0`
  - `test_exec_empty_model_response_errors` — stub returns `""` (override `_StubMessages` text); assert subprocess NOT called, return `3`, stderr contains `no command`. Also a variant where the response is just whitespace `"   "`
  - **`test_exec_shell_metacharacters_are_not_expanded`** — stub returns `echo a ; rm -rf /tmp/should-not-exist`, input `"y"`, recorder asserts argv == `["echo", "a", ";", "rm", "-rf", "/tmp/should-not-exist"]` and `shell=False`. This test is the safety canary — do NOT delete it casually
  - `test_exec_history_records_run_decision_and_exit` — input `"y"`, recorder returns `returncode=7`. Read `history.jsonl` and assert the row contains `exec_command`, `exec_decision == "run"`, `exec_exit == 7`. Also assert `main` returns `7`
  - `test_exec_aborted_history_record` — input `"n"`, history row contains `exec_decision == "aborted"` and does NOT contain `exec_exit`
- [x] Tests must NEVER actually invoke a shell or run a real subprocess. The recorder pattern (replace `cli_mod.subprocess.run`) is the safe path
- [x] `python -m pytest` passes (no network, no real `ANTHROPIC_API_KEY`, no real subprocess)
- [x] `README.md` "Usage" section gains a `--exec` paragraph after the config.json paragraph: a one-line `workbuddy --exec "list git branches sorted by commit date"` example, and an explicit safety note: "Each proposed command is shown for explicit y/N confirmation. Commands run with `shell=False` and arguments parsed via `shlex.split`, so shell metacharacters in the proposed command are not expanded. The default answer is no — empty input or EOF aborts."
- [x] Total project Python LOC stays under ~700 (relaxed for this larger feature). Don't pad

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
