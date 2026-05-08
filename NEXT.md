# Next Task

## Title
Refactor: extract `_confirm_yn(prompt) -> bool` helper to de-duplicate the 5 copies of the y/N prompt code

## Why
The y/N confirmation prompt code is duplicated identically across `_run_exec`, `_run_git`, `_run_mcp_call_tool`, `_run_mcp_claude`, and inside the for-loop of `_run_mcp_agent`. Five copies of `sys.stderr.write(...) + flush + input() + EOFError handling + strict {"y","Y"} check`. Pure mechanical refactor: extract once, call from each site. NO new behaviour, NO UX change, NO new flags. The five existing canary tests for default-no semantics will all continue to pass byte-for-byte. Per the d462b10 REVIEW, this is the last safe automation slice — every other unchecked BACKLOG line requires either UX decisions or speculation about user needs

## Acceptance
- [ ] Add `def _confirm_yn(prompt: str) -> bool` to `src/workbuddy/cli.py`. Place it near the other small helpers (around `_extract_text` / `_log_path`). Body:
  ```python
  def _confirm_yn(prompt: str) -> bool:
      """Write `prompt` to stderr, read one line of input, return True only for 'y'/'Y'.
      EOFError and any other input return False — strict default-no contract."""
      sys.stderr.write(prompt)
      sys.stderr.flush()
      try:
          answer = input()
      except EOFError:
          answer = ""
      return answer.strip() in {"y", "Y"}
  ```
- [ ] Replace each of the 5 inline blocks with a single call. The 5 sites are:
  1. `_run_exec` — was `Run this command? [y/N]: ` → `if not _confirm_yn("Run this command? [y/N]: "):` opens the abort branch (else: continues to subprocess call)
  2. `_run_git` — same prompt as exec
  3. `_run_mcp_call_tool` — was `Run this tool? [y/N]: `
  4. `_run_mcp_claude` — was `Run this tool? [y/N]: `
  5. `_run_mcp_agent` (inside the for-loop) — was `Run this tool? [y/N]: `
  Preserve the EXACT prompt strings — they're user-facing UX
- [ ] No changes to `_run_mcp_agent`'s dry-run branch (it already skips the prompt entirely; that branch should not call `_confirm_yn`)
- [ ] No changes to control flow at any call site — the abort/run branches stay where they are. Only the prompt-and-input mechanics get factored out
- [ ] All 113 existing tests must continue to pass UNCHANGED (no test edits). The default-no canary tests, the EOFError tests, and the `_input_must_not_be_called` sentinel tests all rely on the existing semantics — the refactor must preserve them exactly
- [ ] `tests/test_cli.py` adds one new direct test of the helper:
  - `test_confirm_yn_strict_default_no` — exercise via `monkeypatch.setattr("builtins.input", lambda *a, **k: <X>)` for X in `["y", "Y", "n", "no", "yes", "", "  y  ", "Y\n"]` and assert `_confirm_yn("?: ")` returns the expected bool. Specifically:
    - `"y"` → True; `"Y"` → True; `"  y  "` → True (strip allowed); `"Y\n"` → True (input strips trailing newline; .strip() handles edges)
    - `"n"` → False; `"no"` → False; `"yes"` → False; `""` → False
  - Plus an EOFError sub-test: `monkeypatch.setattr("builtins.input", _raises_eof)`; assert `_confirm_yn("?: ")` returns False
- [ ] `python -m pytest -W error` passes
- [ ] No README changes (UX is identical — prompts unchanged)
- [ ] No BACKLOG changes (refactor only — doesn't close any backlog item; pure code hygiene)
- [ ] LOC SHOULD slightly DECREASE (de-duplication wins ~25 LOC; helper + 1 new test add ~25 LOC; net roughly neutral). Target: stay within `~3550` (same as prior round)

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
