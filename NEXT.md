# Next Task

## Title
Add `--git` mode: read-only git helper that loads repo context and rejects write subcommands

## Why
GOAL.md v0.1 — "Git operations helper". The risk-conscious slice 1: load `git status` / branch / recent commits as context for Claude, ask for ONE git read-only command, run only after y/N confirm AND only if argv[0] is `git` AND argv[1] is in a curated read-only allowlist. Write subcommands (`commit`, `push`, `merge`, `rebase`, `reset`, `restore`, `checkout`, `clean`, `tag`, `notes`, `worktree`, etc.) MUST be rejected cold — without the user even seeing a confirmation prompt — so an accidental `y` cannot execute one. Write workflows can stay on `--exec` for now and get a separate `--allow-write` gate later

## Acceptance
- [x] Add `READONLY_GIT_SUBCMDS = {"status", "log", "diff", "branch", "show", "blame", "rev-parse", "ls-files", "describe", "reflog", "shortlog", "name-rev"}` as a module-level constant in `cli.py`
- [x] Add `--git` argparse flag (boolean, default False). Use `parser.add_mutually_exclusive_group()` so `--git` and `--exec` are mutually exclusive (argparse will fail with `usage:` message if both are passed). Help text: `Read-only git helper: loads repo context, runs a Claude-proposed git read command after y/N confirmation. Write subcommands are blocked`
- [x] Add a helper `_load_git_context() -> str` that runs three commands via `subprocess.run([...], shell=False, capture_output=True, text=True, check=False, timeout=10)`:
  1. `git rev-parse --abbrev-ref HEAD` → branch name (one line)
  2. `git status --porcelain=v1` → terse status
  3. `git log --oneline -10` → recent commits
  Concatenate into a multi-line string with `[Branch: ...]`, `[Status: ...]`, `[Recent commits: ...]` section markers. On any failure (not a git repo, git missing, timeout, OSError), return `"[Branch: (unknown — not a git repository or git unavailable)]"` as the entire context AND print one-line `warning: git context unavailable: <reason>` to stderr. Continue — workbuddy is still useful outside a repo
- [x] When `--git` is set, the user message sent to `messages.create` becomes:
  ```
  Reply with exactly ONE git read-only command. No commentary, no markdown, no fences. Allowed subcommands: status, log, diff, branch, show, blame, rev-parse, ls-files, describe, reflog, shortlog, name-rev. Repository context follows.

  <output of _load_git_context()>

  Task: <args.task>
  ```
- [x] After the model response, branch into a new helper `_run_git(args, text)`:
  1. `command_text = text.strip()` — empty → exit 3 `error: model returned no command`
  2. `argv_list = shlex.split(command_text)` — empty or `ValueError` → exit 3
  3. **VALIDATE argv[0]**: must equal `"git"` (literal). If not → exit 4 with stderr `error: --git mode requires the proposed command to start with \`git\` (got: <argv[0]>)`. NO y/N prompt. NO subprocess
  4. **VALIDATE argv[1]**: must exist and be in `READONLY_GIT_SUBCMDS`. If missing → exit 4 `error: --git mode requires a subcommand`. If not in allowlist → exit 4 `error: --git mode rejects subcommand \`<argv[1]>\` (write subcommands need a separate --allow-write flag, not yet supported)`. NO y/N prompt. NO subprocess
  5. From step 3+4 onwards: same flow as `_run_exec` — print `Proposed command:` to stdout, `Run this command? [y/N]: ` to stderr, `input()`-with-EOFError-fallback, strict `{"y","Y"}` gate. On run: `subprocess.run(argv_list, shell=False, check=False)`
  6. History record uses keys `git_command`, `git_decision`, `git_exit` (parallel to the exec_* keys but namespaced for git so future analytics can distinguish). Aborted runs record `git_decision="aborted"` and omit `git_exit`. Cold-rejected commands (steps 3 & 4) DO write a history record with `git_decision="rejected"` and a `git_rejection_reason` field — useful audit signal
- [x] **CRITICAL safety property**: write subcommands MUST be rejected before the y/N prompt is shown. The rejection MUST happen on the basis of `argv[1] in READONLY_GIT_SUBCMDS`, not the proposed command's prose. A test must assert that `git commit ...` produces NO confirmation prompt in stderr — failing this assertion means a write command could slip through with an accidental `y`
- [x] **CRITICAL safety property**: argv[0] must be the literal `"git"`. Reject `"git2"`, `"/usr/bin/git"`, `"./git"`, `"GIT"`. The literal-equality check enforces this — explicit test below
- [x] `tests/test_cli.py` adds these tests (use the existing `_make_stub_client_returning` helper and `_SubprocessRecorder` pattern):
  - `test_git_runs_status_after_yes` — model returns `"git status"`, input `"y"`, recorder asserts a subprocess call with argv `["git", "status"]` and `shell=False`. Return 0. **AND** the recorder must observe the THREE context-loading calls first (branch, status --porcelain, log --oneline) before the user-confirmed command call
  - `test_git_rejects_non_git_argv0` — model returns `"rm -rf /"`, NO `input()` patched (so the test would hang if we did prompt), assert exit 4, stderr contains `must start with \`git\``, recorder shows ONLY the context-loading calls (no `rm` invocation)
  - `test_git_rejects_write_subcommand_commit` — model returns `"git commit -m foo"`, no `input()` patched, exit 4, stderr contains `rejects subcommand \`commit\``, recorder shows only the context calls
  - `test_git_rejects_write_subcommand_push` — `"git push origin main"`, exit 4, stderr contains `rejects subcommand \`push\``
  - `test_git_rejects_write_subcommand_reset` — `"git reset --hard HEAD~"`, exit 4, stderr contains `rejects subcommand \`reset\``
  - `test_git_rejects_argv0_path_variant` — `"/usr/bin/git status"`, exit 4 (literal `"git"` check rejects path variants), stderr contains `must start with \`git\``
  - `test_git_and_exec_mutually_exclusive` — `with pytest.raises(SystemExit) as ei: main(["--git", "--exec", "task"])`; assert `ei.value.code != 0` AND captured.err mentions one of `not allowed with` / `--git` / `--exec` (exact phrasing depends on argparse version)
  - `test_git_aborts_on_n_with_history` — model returns `"git status"`, input `"n"`, exit 0, stderr contains `aborted`, history.jsonl row has `git_decision == "aborted"`, no `git_exit` key
  - `test_git_rejection_writes_history_record` — model returns `"git commit -m x"`, no input, exit 4, history.jsonl row has `git_decision == "rejected"` and a `git_rejection_reason` field; no subprocess.run beyond the context-loading calls
- [x] All 33 existing tests still pass unchanged. The `_SubprocessRecorder` from prior tests will capture the context-loading subprocess calls too — tests asserting "subprocess not called" should be reframed as "no NEW subprocess call beyond the 3 context-loading ones". Slightly fiddly; consider giving the recorder a `.exec_calls` filtered view OR pre-recording the count of context calls and asserting ≤ that count
- [x] `_load_git_context` failures (not a git repo) should be tested separately: with the recorder configured to make all three context calls return `returncode != 0`, assert the warning is written to stderr and the message-content sent to Claude contains `(unknown` / `not a git repository`. Optional but valuable
- [x] `python -m pytest` passes (no network, no real git invocation in tests)
- [x] `README.md` "Usage" section gains a `--git` paragraph after the `--exec` paragraph: explain it auto-loads `git status` / branch / recent commits, restricts to the read-only subcommand allowlist, and explicitly notes that `--git` and `--exec` are mutually exclusive
- [x] Total project Python LOC stays under ~900 (relaxed; this feature has ~100 LOC of impl plus ~150 LOC of tests). Don't pad

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
