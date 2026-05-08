# Next Task

## Title
v0 polish — add LICENSE, declare dev test extra, bump README "Status" to v0

## Why
v0 is feature-complete (8/8 BACKLOG MVP items shipped). Three small accumulated chores were called out across multiple prior reviews; landing them as a single round closes v0 cleanly before v0.1 work begins

## Acceptance
- [ ] A new `LICENSE` file at the repo root contains the standard MIT License text. Use copyright year `2026` and copyright holder `workbuddy contributors` (consistent with `pyproject.toml`'s `license = { text = "MIT" }` and `authors = [{ name = "workbuddy" }]`; avoid naming any specific individual)
- [ ] `pyproject.toml` gains a `[project.optional-dependencies]` table declaring `dev = ["pytest>=7"]`. Do NOT change the existing `dependencies = ["anthropic>=0.40"]` line or any other existing field
- [ ] `README.md`'s "Status" section text changes from `Pre-v0. See BACKLOG.md.` to `v0 — feature complete. See BACKLOG.md for v0.1 and beyond.` Other README sections stay untouched
- [ ] No changes under `src/`. No changes to existing tests
- [ ] `python -m pytest` still passes (sanity — should be unchanged)
- [ ] `pip install -e ".[dev]"` resolves cleanly in the venv (verify by running it; remove the install side-effects from the commit since `.venv/` is gitignored anyway)
- [ ] Total project Python LOC stays under 500 (this round adds no Python LOC)

## Files likely involved
- LICENSE (new)
- pyproject.toml
- README.md
