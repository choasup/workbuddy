# Next Task

## Title
*(no slice scoped — Planner is declining further automation)*

## Why
The autobuddy run has reached the point I committed to in the d462b10 REVIEW: **no further safe slices remain that don't require human direction.** Every BACKLOG line except `[ ] Parallel tool calls per turn` (v0.4) is now `[x]`. Shipping that final item requires a UX decision (per-call vs per-batch confirmation) that materially changes how end users interact with `workbuddy --mcp-agent`. That choice should not be made by automation alone.

Two additional considerations from this round:

1. **Process error in the prior round (`0f94f22`)**: the y/N refactor commit used the `refactor:` prefix, which is NOT in the autobuddy state machine's coder-prefix set (`feat:|fix:|chore:|test:|docs:`). As a result, REVIEWER did not run on `0f94f22` — it bypassed the audit. The 122 tests passing under `pytest -W error` is the safety net, but the process spec was violated. A human should manually review `0f94f22` before further work.

2. **Diminishing returns**: the four most recent slices (consecutive-error abort, dry-run, reflect, --version, y/N refactor) each shipped real value, but each was strictly smaller than the last. That trajectory matches reality: the codebase has converged. Further automated slices would either (a) speculate about user needs that aren't validated, (b) lock in UX choices that should be human-made, or (c) churn without adding value.

## What the human should do

Pick one of these explicit options and direct accordingly:

1. **Pause the cron**: `CronDelete bbee383b`. Manually review the ~110 commits at your leisure. The codebase is in a coherent stopping state — every shipped feature is canary-tested, every defensive choice is documented in REVIEW.md, and the BACKLOG accurately reflects what's done versus deferred.

2. **Direct parallel-tool-calls UX**: tell me explicitly which mode you want — `(a)` per-call confirmation (ask y/N for each of N proposed tools, mix-and-match), `(b)` per-batch confirmation (one y/N for all-or-nothing), or `(c)` opt-in flag with a default-conservative behaviour. With direction, I can scope a real slice.

3. **Direct an entirely different next slice**: something I haven't anticipated.

## Acceptance

*(no checkable items — this is a no-op planning round; CODER should see all-checked, exit cleanly, and not commit)*

- [x] Decision deferred to human

## Files likely involved

*(none)*

## Note for the next CODER fire

If the cron fires before a human reads this and acts: CODER will see `[x] Decision deferred to human` (no unchecked criteria) and per CODER.md ("If empty or all acceptance criteria are checked, exit cleanly") will exit without committing. The cron will then idle on PLANNER → CODER → PLANNER → ... rounds, each writing essentially this same NEXT.md, until the human pauses or directs.
