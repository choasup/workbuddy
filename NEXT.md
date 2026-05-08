# Next Task

## Title
Add `workbuddy --version` flag — print package version and exit

## Why
Standard CLI convention for commercial polish: every CLI tool ships `--version`. Users need to be able to ask "what version is installed?" in deployments and bug reports. Currently `workbuddy --version` raises argparse usage error because the flag isn't defined. This is a missed v0 polish item that surfaces now that the project has shipped v0.3 and is firmly in commercial-stable territory. Also creates a `cli_mod.VERSION` module constant that future BACKLOG-tracked features (e.g. version-conditional behaviour) can reference

## Acceptance
- [ ] `src/workbuddy/cli.py` adds a module-level `VERSION` constant resolved at import time. Use the standard pattern:
  ```python
  try:
      from importlib.metadata import version as _pkg_version, PackageNotFoundError
      try:
          VERSION = _pkg_version("workbuddy")
      except PackageNotFoundError:
          VERSION = "0.0.0+unknown"
  except ImportError:  # pragma: no cover — Python 3.10+ always has importlib.metadata
      VERSION = "0.0.0+unknown"
  ```
  Place this near the top with the other module constants
- [ ] In `_build_parser()`, add a version action: `parser.add_argument("--version", action="version", version=f"workbuddy {VERSION}")`. Place it immediately after the `prog`/`description` setup but BEFORE the positional `task` arg (so `--version` works without a task: `workbuddy --version` should NOT require a task argument). argparse handles this correctly because `action="version"` exits before positional validation
- [ ] `workbuddy --version` MUST work without `ANTHROPIC_API_KEY` set, without a `task` argument, and without `--mcp-server`. It exits 0 after printing
- [ ] `workbuddy --help` SHOULD include `--version` in the options list (argparse does this automatically when the action is registered)
- [ ] `tests/test_cli.py` adds 3 tests:
  - `test_version_prints_version_and_exits_zero` — `with pytest.raises(SystemExit) as ei: main(["--version"])`. Assert `ei.value.code == 0`. Assert captured stdout (or stderr — argparse versions vary) contains `workbuddy ` followed by the resolved VERSION. Use `cli_mod.VERSION` to read the actual constant for the assertion
  - `test_version_does_not_require_task_arg` — `--version` without a positional `task`; the test for `test_version_prints_version_and_exits_zero` already covers this if the flag is correctly placed before the positional, but add an explicit test asserting that calling `main(["--version"])` does NOT raise the argparse "task required" error
  - `test_version_does_not_require_api_key` — `monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)`. `with pytest.raises(SystemExit) as ei: main(["--version"])`. Assert `ei.value.code == 0`. The version flag short-circuits before any env-var checks
- [ ] All 110 existing tests must continue to pass unchanged. Existing tests don't pass `--version` so they're byte-identical
- [ ] `python -m pytest -W error` passes
- [ ] `README.md` "Install" section gets one new line at the end: `Run \`workbuddy --version\` to confirm the install: it prints the package version and exits.`
- [ ] BACKLOG: add a new section `## v0.4 (post-v0.3)` containing two entries:
  - `[x] \`--version\` flag` (this round)
  - `[ ] Parallel tool calls per turn — Claude proposes multiple tool_use blocks; UX decision (per-call vs per-batch confirmation) deferred to humans`
  Also flip the v0.3 line from `[⏳]` to `[x]` since slices 1-4 are shipped and the parallel-tool-calls work has been formally moved to v0.4 — annotation: `[x] Multi-step agent loop *(slices 1-4 shipped: --mcp-agent + per-turn y/N + hard cap; consecutive-error abort with exit 8; --mcp-agent-dry-run inspection; --reflect one-shot self-evaluation. Parallel tool calls moved to v0.4.)*`
- [ ] Total project Python LOC stays under ~3550 (very small addition)

## Files likely involved
- src/workbuddy/cli.py
- tests/test_cli.py
- README.md
- BACKLOG.md
