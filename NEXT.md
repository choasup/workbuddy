# Next Task

## Title
Tighten the `--git` allowlist by removing `branch` and `reflog` (Strategy A from the 437b97b review)

## Why
REVIEW of `437b97b` (`51dfc75`) found that `git branch -d/-D/-m/-c` and `git reflog expire/delete` would be PROMPTED rather than cold-rejected under the current allowlist, violating the slice-1 promise that "write subcommands are rejected before the y/N prompt". Strategy A (drop both from `READONLY_GIT_SUBCMDS`) is the smaller, stricter fix; users who need read-only `branch`/`reflog` access can fall back to `--exec`. Strategy B (second-level write-flag scanning) is a future enhancement, not slice 1

## Acceptance
- [x] In `src/workbuddy/cli.py`, remove the strings `"branch"` and `"reflog"` from `READONLY_GIT_SUBCMDS`. The remaining 10 entries: `status, log, diff, show, blame, rev-parse, ls-files, describe, shortlog, name-rev`
- [x] Update the user-message prompt that `main()` constructs when `args.git` is set: the embedded "Allowed subcommands:" sentence must enumerate the same 10 names (drop `branch` and `reflog` from that prose so the model doesn't propose them and immediately get rejected)
- [x] `tests/test_cli.py` adds the following tests (all using `_input_must_not_be_called` so any rejection-fall-through fires `AssertionError` instead of hanging):
  - `test_git_branch_d_is_cold_rejected` — model returns `"git branch -d feature"`, exit 4, stderr contains `rejects subcommand` `` `branch` ``, recorder shows ONLY context calls (no `branch -d` invocation), history.jsonl row has `git_decision == "rejected"`
  - `test_git_branch_D_force_is_cold_rejected` — `"git branch -D feature"`, same shape
  - `test_git_branch_m_rename_is_cold_rejected` — `"git branch -m oldname newname"`, same
  - `test_git_branch_list_is_now_cold_rejected` — `"git branch"` (no flags, plain listing), same shape. Include a docstring noting this is the deliberate Strategy-A trade-off: read-only branch listing is no longer reachable via `--git`; users should fall back to `--exec` for `git branch`. Without this docstring a future maintainer might "fix" the rejection
  - `test_git_reflog_expire_is_cold_rejected` — `"git reflog expire --expire=0 --all"`, exit 4, stderr contains `rejects subcommand` `` `reflog` ``
  - `test_git_reflog_show_is_now_cold_rejected` — `"git reflog show HEAD"`, same shape, same docstring trade-off note as the branch-list test
- [x] Existing 43 tests must continue to pass. Audit the suite: no current test uses `git branch` or `git reflog` as the model output for `--git` mode (the existing happy-path test uses `git status`). No existing test should need editing. Verify by running `pytest -q` and confirming all 43 + 6 new = 49 tests pass
- [x] Update `README.md` "Usage" section: revise the allowlist enumeration in the `--git` paragraph to match the new 10 entries. Drop `branch` and `reflog` from the list. Add ONE short sentence after the list noting that `branch` and `reflog` were intentionally excluded because they have write variants (`branch -d/-D/-m`, `reflog expire/delete`); for read-only branch/reflog inspection, users can fall back to `--exec` and confirm the proposed plain-read command
- [x] No other code, no other tests, no scope creep — this is a focused fix round
- [x] `python -m pytest` passes (no network, no real git, no `ANTHROPIC_API_KEY`)
- [x] Total project Python LOC stays under ~1150 (small fix, mostly new tests)

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
