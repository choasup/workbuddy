# Next Task

## Title
Implement CLI entry point that parses a `<task>` argument and echoes it back

## Why
GOAL.md v0 names `workbuddy "<task>"` as the primary CLI surface; argument parsing must land before any Claude API integration

## Acceptance
- [ ] `workbuddy "do something"` prints `do something` (or an equivalent echo line containing the task) to stdout and exits 0
- [ ] Running `workbuddy` with no argument prints a short usage message to stderr and exits non-zero
- [ ] `src/workbuddy/cli.py` uses `argparse` (stdlib) to parse a single positional `task` argument
- [ ] `tests/test_cli.py` covers both the happy path and the missing-argument case (use `subprocess.run([sys.executable, "-m", "workbuddy", ...])` or call `main(argv=...)` directly)
- [ ] `python -m pytest` passes

## Files likely involved
- src/workbuddy/cli.py
- src/workbuddy/__main__.py (only if tests use `python -m workbuddy`)
- tests/test_cli.py
