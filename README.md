# workbuddy

A minimal Python CLI agent assistant. **Currently bootstrapping** — being built end-to-end by 3 collaborating scheduled Claude agents (Planner / Coder / Reviewer).

## Architecture (control plane)

| File | Owner | Purpose |
|---|---|---|
| `GOAL.md` | human only | North-star scope |
| `BACKLOG.md` | Planner / Reviewer | Open tasks |
| `NEXT.md` | Planner → Coder | Single in-flight task |
| `REVIEW.md` | Reviewer | Verdict on last commit |
| `LOG.md` | all three | Append-only activity log |
| `AGENTS/` | human (initial) | Role specs |
| `src/`, `tests/` | Coder | Source + tests |

## Schedule

| Agent | Cron (UTC) | Role |
|---|---|---|
| Planner | `0 * * * *` | Picks next task → writes `NEXT.md` |
| Coder | `20 * * * *` | Implements `NEXT.md` → commits |
| Reviewer | `45 * * * *` | Reviews latest commit → writes `REVIEW.md` |

## Status

Pre-v0. See `BACKLOG.md`.
