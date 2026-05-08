# Review of ca1cacf

## Verdict
PASS

## Safety property check (the most layered yet)

The `--mcp-agent` slice was scoped with six explicit safety properties. I verified each by reading the source and confirming each test exercises the relevant path:

| Property | Source | Test |
|---|---|---|
| **Hard cap enforced at parse time** — user CANNOT pass `--mcp-agent-max-turns=99` | line 994: `if args.mcp_agent and not (1 <= args.mcp_agent_max_turns <= MAX_AGENT_TURNS_HARD_CAP): return 5` | `test_mcp_agent_max_turns_above_hard_cap_rejected`, `test_mcp_agent_max_turns_zero_rejected` |
| **Loop bounded** | line 330: `for turn_index in range(max_turns)` — validated `max_turns ∈ [1, 5]` | implicit; no infinite-loop test possible without timeouts |
| **Per-turn y/N gate** — never batch-confirm | line 427: `input()` inside the for-loop, called once per turn | `test_mcp_agent_two_turns_then_final` (input "y" twice), `test_mcp_agent_user_aborts_mid_loop` (input "n" stops the loop) |
| **Per-turn cold-rejection ordering** — multi-tool / hallucination / non-dict-input all return 5 BEFORE that turn's prompt at line 425 | lines 376, 393, 407 (returns precede line 425) | `test_mcp_agent_multi_tool_per_turn_cold_rejected`, `test_mcp_agent_hallucinated_tool_cold_rejected` (both with `_input_must_not_be_called` sentinel) |
| **`messages` list grows ONLY on run-success** — every cold-rejection / abort / error path returns before line 475 | inspected: lines 374, 387, 405, 419, 440 all `return` before line 475 | `test_mcp_agent_user_aborts_mid_loop` asserts `len(scripted.create_calls) == 1` (the abort prevented a second create() call, which would only happen if the messages list had been extended) |
| **Distinct exit code for max-turns** — separate from other failure modes | line 504: `return 7` | `test_mcp_agent_max_turns_reached` |

All 11 new tests pass; `pytest -W error` confirms no async leaks (the loop's `asyncio.run` per turn correctly cleans up coroutines).

## Findings
- All 12 acceptance criteria met. `pytest -q -W error` → 91 passed (80 prior + 11 new) clean.
- Module constants `DEFAULT_AGENT_TURNS = 3` and `MAX_AGENT_TURNS_HARD_CAP = 5` are named and used in:
  - argparse `default=` and `help=` (single source of truth in help text via f-string)
  - validation check (`1 <= ... <= MAX_AGENT_TURNS_HARD_CAP`)
  - error message (so user sees the actual cap if they exceed it)
- The argparse mutex group now includes 6 modes (`--exec`, `--git`, `--mcp-list-tools`, `--mcp-call-tool`, `--mcp-claude`, `--mcp-agent`); `test_mcp_agent_mutually_exclusive_with_other_modes` parametrically verifies all 5 pairings via SystemExit.
- The orphan-`--mcp-agent-max-turns` check is correct: comparison `args.mcp_agent_max_turns != DEFAULT_AGENT_TURNS` distinguishes user-set from default. Subtle edge case: if the user passes `--mcp-agent-max-turns 3` (matching the default), the orphan check doesn't fire — but this only matters when `--mcp-agent` is also unset, in which case the user's explicit `3` is a no-op anyway. Acceptable.
- `messages.append({"role": "assistant", "content": list(content)})` makes a list-copy of the SDK's response content. Shallow copy of immutable response blocks — sufficient.
- `tool_result` blocks correctly reference `getattr(tu, "id", "unknown-id")` so the next API call in the loop can pair the result with the right tool_use. The `"unknown-id"` fallback is a defense if the SDK shape changes; the API might reject it but that's better than a crashing AttributeError.
- The `joined_text` per turn is recorded in history.jsonl as `claude_reasoning` — the user can audit Claude's intent turn-by-turn. Combined with `turn_index`, this gives a complete reconstruction of the agent's decision tree.
- LOC = 2759 — well under the planner's `~2900` target. The implementation is clean and the tests are explicit/named (no over-parametrize collapsing).
- The `_ScriptedMessages` test helper is reusable for future multi-turn tests (e.g. v0.3 slice 2 parallel tool calls would need the same per-turn response control).

## Non-blocking observations
- The `is_error=True` path inside the loop currently lets Claude continue (the tool_result is appended with `is_error: true`, and Claude can decide to retry / give up). This is correct — Claude should be able to recover from a tool error. However, there's no upper bound on consecutive errors; a misbehaving tool could burn through all 5 turns producing errors. Slice 2 candidate: track consecutive `is_error` count and abort early if it exceeds a threshold (e.g. 2 consecutive errors → exit 8).
- The agent loop calls `_async_call_tool` separately each turn, opening a fresh `stdio_client` connection. For high-frequency loops this is inefficient (each turn pays the spawn-server cost). Slice 2 candidate: keep one server session open across turns. Not blocking — slice 1's per-turn-fresh-session is simple and correct.
- The user can't see which tool Claude is *about* to propose before the first turn's API call returns. That's inherent to the loop design — no way to know in advance. Mitigated by `Turn 1/N` framing so the user knows they're about to be asked.
- No streaming. Each turn's response is fully buffered before the prompt. For large responses this could be slow. Streaming + interrupt is out of scope for slice 1.

## Suggestions for next round
- BACKLOG v0.3 line is at `[⏳]` after this round. The annotation says slice 1 (single-tool-per-turn, no parallel calls, no self-reflection). The remaining v0.3 sub-features:
  - **Parallel tool calls per turn** — Claude responds with multiple tool_use blocks; workbuddy gates ALL of them in one prompt or per-call. Critical UX question: do you confirm 3 tools in one prompt, or 3 separate prompts? The latter is safer; the former is faster.
  - **Self-reflection / introspection** — let Claude inspect its own history.jsonl entries to learn from prior runs.
  - **Consecutive-error abort** (noted above) — bounded retry on tool errors.
- All of these have meaningful design choices that benefit from human input. The autobuddy run has now covered three independently-shipped Claude-loop variants (`--mcp-claude`, `--mcp-agent`, plus the prior `--exec` and `--git`); slicing further would push into novel territory faster than the cron's 1-min cadence really suits.
- **The honest stopping point is here.** After 80+ commits, every original BACKLOG line is shipped (v0/v0.0-polish/v0.1/v0.2 all `[x]`), v0.3 has its first slice landed, and the test suite is the highest signal I've ever seen on a single-session run. Run `CronDelete bbee383b`. The remaining v0.3 sub-features are the kind of design decisions that produce different products depending on which way you go — exactly the spot where a human PR review pays off most.
- If the cron continues, the next round should NOT be parallel-tool-calls (too many UX decisions). Better candidates: a small consecutive-error abort (clean small slice), OR a `--mcp-agent --dry-run` that prints what Claude WOULD do without executing (defensive, useful for debugging an agent's plan before running it).
