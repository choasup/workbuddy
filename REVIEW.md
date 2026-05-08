# Review of 437b97b

## Verdict
NEEDS_FIX

## What's right
- All 43 tests pass independently with no env vars / no real git invocation. Implementation faithfully matches the NEXT.md spec.
- The two safety properties NEXT.md asked for are correctly implemented:
  1. `argv[0] != "git"` (line 210) is a literal-equality check that rejects `/usr/bin/git`, `./git`, `GIT`, `git2`, etc. The `test_git_rejects_argv0_path_variant` canary covers this.
  2. `argv[1] not in READONLY_GIT_SUBCMDS` (line 230) rejects subcommands outside the allowlist BEFORE the y/N prompt is shown. Verified by the three explicit write-rejection tests + `_input_must_not_be_called` sentinel that would `AssertionError` if the rejection path ever fell through to `input()`.
- `_load_git_context()` degrades gracefully — single warning + continue + `_GIT_CONTEXT_UNAVAILABLE` marker injected into the prompt.
- argparse mutex group correctly forbids `--git --exec` together (verified by `test_git_and_exec_mutually_exclusive`).
- Audit trail is solid: rejections write `git_decision="rejected"` with a `git_rejection_reason`, aborted runs write `git_decision="aborted"`, run completions write `git_decision="run"` with `git_exit`.
- `READONLY_GIT_SUBCMDS` is a `frozenset` — set-membership is O(1) and the constant is immutable.

## The blocker — allowlist membership ≠ "read-only subcommand"
The spec said write subcommands MUST be rejected before the prompt. The allowlist enforces that at the **subcommand-name** level, but **two members of the allowlist have write variants**:

- **`branch`** has destructive flags:
  - `git branch -d <name>` deletes a (merged) branch
  - `git branch -D <name>` force-deletes any branch (high blast radius — unmerged work can be lost; the reflog is the only recovery)
  - `git branch -m <old> <new>` renames the current branch
  - `git branch -c <old> <new>` copies a branch
  - `git branch --delete --remotes <remote>/<name>` deletes a remote-tracking ref
- **`reflog`** has destructive subcommands:
  - `git reflog expire --expire=0 --all` permanently prunes the reflog (irreversible — reflog is git's last-resort recovery)
  - `git reflog delete <ref>` removes a specific reflog entry

Under the current implementation, the model could output `git branch -d feature/foo` or `git reflog expire --all`, the user would see the proposed command in the prompt, and a single `y` would execute it. That violates the slice 1 promise that "write subcommands MUST be rejected cold". The user *can* still see and reject, but the spec's safeguard is bypassed at the implementation level — the allowlist treats `branch` as inherently read-only when it isn't.

`stash` was correctly omitted from the allowlist (it has `pop`, `drop`, `clear`, `apply`, `push` write variants). `branch` and `reflog` should get the same treatment, OR a second-level flag check.

The Coder's implementation matches the spec literally. The hole is in the spec — but it's a real safety hole and the next round MUST address it before the BACKLOG item can be marked `[x]`.

## What needs to change (next CODER round)
Pick ONE of these two strategies — Planner's call:

**Strategy A — tighten the allowlist (simpler, stricter, drops some legitimate read uses):**
- Remove `branch` and `reflog` from `READONLY_GIT_SUBCMDS`.
- Recommend users invoke `git status` / `git log --decorate` for the same information.
- Add a test: `git branch -d feature` is now cold-rejected (no prompt), `git reflog expire --all` is cold-rejected.

**Strategy B — second-level write-flag rejection (preserves read uses but more code):**
- After `argv[1]` allowlist check passes, if `argv[1] == "branch"`, scan `argv[2:]` for any of `{-d, -D, -m, -c, -M, -C, --delete, --move, --copy, --rename, --create, --force}`. Reject if found.
- If `argv[1] == "reflog"` and `len(argv) >= 3`, reject if `argv[2] in {"expire", "delete"}`. Allow if missing or `argv[2] == "show"`.
- Add tests: `git branch -d feature` rejected, `git branch` (list) accepted, `git reflog expire --all` rejected, `git reflog show HEAD` accepted, `git reflog` (defaults to show) accepted.

I'd suggest Strategy A for slice 1 (it's a 2-line change + a test), and treat Strategy B as a future enhancement when --allow-write lands.

## Other (non-blocking) observations
- Global git options before the subcommand are rejected by the simple `argv[1]` check: `git --no-pager log` becomes `argv[1]="--no-pager"`, not on allowlist → cold-rejected. This is a usability papercut but not a safety issue. Slice 2 could skip leading dashed args before checking the subcommand.
- PATH manipulation (a malicious `git` symlink earlier in PATH) is outside workbuddy's threat model — the literal-`"git"` check resolves via `subprocess.run`'s PATH lookup. Documenting this as out-of-scope is fine.
- LOC = 1066, ~18% over the planner's `~900` soft target. The bulk is the test setup helpers and the deliberately-named-per-subcommand rejection tests; collapsing via parametrize would hurt diagnosability. Acceptable.
- `_load_git_context` returns its own warning string before returning the unavailable marker — but the unavailable marker itself only mentions the Branch label even when the failure was on Status or Recent commits. Cosmetic.

## Suggestions for next round
- **Required next CODER round**: implement Strategy A or B above. Per PLANNER.md ("If REVIEW.md says NEEDS_FIX or FAIL on the latest commit, the next task MUST be fixing those issues"), the Planner's next pick is the fix, not a new feature.
- After the fix lands and the `[⏳]` flips to `[x]`, the v0.1 BACKLOG section is fully done — only v0.2 (MCP integration) remains.
- Reiterating: this is still a good place to pause the cron. The git-operations slice was the riskiest piece of v0.1, and the slip we're seeing in this round (allowlist correctness) is exactly why human review on security-sensitive scope is valuable.
