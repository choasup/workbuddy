# Next Task

## Title
Create project skeleton with pyproject.toml, package structure, and tests directory

## Why
Foundation required by GOAL.md v0 scope to enable all subsequent CLI and API work

## Acceptance
- [x] `pyproject.toml` exists with `[project]` metadata and a `workbuddy` console-scripts entry point
- [x] `src/workbuddy/__init__.py` exists (may be empty)
- [x] `src/workbuddy/cli.py` exists with a stub `main()` function
- [x] `tests/` directory exists with at least a placeholder test file (e.g. `tests/test_placeholder.py`)
- [x] `pip install -e .` succeeds and `workbuddy` is importable without errors

## Files likely involved
- pyproject.toml
- src/workbuddy/__init__.py
- src/workbuddy/cli.py
- tests/test_placeholder.py
