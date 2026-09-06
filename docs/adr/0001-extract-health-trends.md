# 1. Extract pure derivations into `health_trends`; delete the weekly summary

Date: 2026-09-06
Status: Accepted

## Context

Backend candidate #3 was scoped as "extract the pure health insights" — weight status,
weight trend, weekly summary, average calories/sleep, hydration consistency — out of
`chat_context_manager` and `chat_service`, which held some of them byte-for-byte
duplicated. Grilling the candidate against the code changed most of its shape.

What the code actually held:

- **Two functions genuinely duplicated.** `_calculate_weight_status` and
  `_calculate_weight_trend` were identical in both modules.
- **Three functions dead.** `_calculate_hydration_consistency`, `_calculate_avg_calories`
  and `_calculate_avg_sleep` had no call sites anywhere. The live weekly summary computed
  all three inline — and read `glasses_consumed` where the dead hydration helper read
  `glasses`, so extracting them would have carried a stale key into the new module.
- **A fourth weight derivation** nobody had counted, inline in `api/weight.py`, with a
  different vocabulary (`gaining` vs `gaining_1.2kg`) and threshold (0.5kg vs 0.2kg).
- **Two divergent weekly summaries, not two copies.** `chat_context_manager` and
  `chat_service` produced the same key names from different arithmetic:

  | | `chat_context_manager` | `chat_service` |
  |---|---|---|
  | window | `end-6 … end` | `end-7 … end-1` (**excludes today**) |
  | `avg_daily_calories` | ÷ days with meals | ÷ a flat 7 |
  | `total_workouts` | distinct workout **days** | exercise **entries** |

  Characterization tests confirmed that on identical data the two disagreed on every
  field, including reporting weight moving in **opposite directions**
  (`losing_1.5kg` vs `gaining_0.5kg`). Both fed the same coach.
- **And nothing read the weekly summary.** Not `_create_system_prompt` (which reads
  `user_profile`, `today_progress`, `body_state`), not `_create_enhanced_system_prompt`
  (which reads `current_week`, from the separate and live `weekly_context_manager`), and
  not the Flutter client. Producing it cost 42 sequential queries per call in
  `chat_service` and 29 in `chat_context_manager`.

The repo also had **no tests at all**, while the client repo has a suite — so "extract for
testability" was a promise nothing could keep.

## Decision

1. **Delete dead code rather than extract it.** The three uncalled helpers went first, in
   their own commit, so only live logic moved.
2. **Stand up pytest before touching behaviour**, and characterize the two weekly
   summaries so any convergence would be a reviewable diff rather than a silent change to
   what the coach sees.
3. **Create `services/health_trends.py`** — free functions over plain data, no class (the
   `self` on the old private methods was a lie; none used it). Holds `weight_status`,
   `weight_trend`, `weight_direction`. Callers import them directly; the private methods
   are deleted rather than left as forwarding shims.
4. **Name it `health_trends`, not `health_insights`.** Everything in it answers "which way
   is this user moving?". "Insight" is a category label that invites anything derived to be
   filed here.
5. **Keep `weight_direction` separate from `weight_trend`.** Same English word, two
   concepts, two audiences, two thresholds; `weight_direction`'s output shape is on the
   wire for `GET /weight/{user_id}/stats`.
6. **Preserve the string encodings** (`'no_data'`, `'losing_1.5kg'`) rather than
   modernising them to structured values. They are a live contract: the client compares
   `goals_progress.weight_progress.status` against the literal `'no_data'`, and the values
   are persisted verbatim in `chat_contexts.context_data`. They also read well as LLM
   prompt input, which is their other consumer.
7. **Enforce purity with tests, not a docstring** (`tests/test_health_trends_purity.py`):
   no `async def`, no import that can reach the database, no classes, imports with no
   environment configured.
8. **Delete the weekly summary outright** instead of converging it — both implementations,
   their call sites, and the `weekly_summary` key. Converging a value with no reader is
   sunk cost; the characterization tests had already paid for themselves by proving the
   divergence, and they were deleted alongside the code they characterized.
9. **Leave the leaked reads alone.** `chat_service.get_today_activities` keeps its six raw
   `.client.table(...)` calls. Pulling them behind the store is candidate #1, and #3 does
   not need it.
10. **Leave `weekly_context_manager._calculate_weekly_insights` and `_quality_label` in
    place.** Both are already pure and already testable where they sit; moving them is
    taxonomy, not leverage, and would inflate this diff.

## Consequences

- The repo has a test suite: 22 tests, and it runs on `pytest` alone — no `openai`, no
  `supabase`, no environment. That property is worth protecting; the moment a test needs
  the app's runtime dependencies, the purity seam has moved.
- Production code is net **−164 lines** (266 deleted, 102 added across `services/` and
  `api/`), against **+201** of tests and config. 71 sequential database round-trips
  removed from the chat-context path (42 in `chat_service`, 29 in `chat_context_manager`).
- `weekly_summary` did ship in `GET /chat/context/{user_id}`, so its removal is a
  response-shape change. Taken anyway, against a field with no consumer on either side,
  and recorded in `docs/contracts/`. This is the one place the additive-only convention
  was knowingly not followed.
- Historical `chat_contexts` rows still carry the old key. Neither read path validates
  freshness — `get_or_create_context` and `ensure_daily_context` return stored
  `context_data` verbatim, and the `version` column is written but never read for any
  decision. Stale keys are harmless here because nothing reads them; **if a future change
  alters a value the coach or client *does* read, this ADR is where to note that the
  invalidation mechanism still does not exist.**
- **Contradicts `nufi_app` ADR-0002**, which calls `dayStatus` "the client twin of the
  backend's emerging `health_insights` module". They are cousins: same spirit (pure
  projection, testable without I/O), different question (goal-relative for one day vs.
  direction over a window), different output (structured `MetricStatus` vs. encoded
  strings). Flagged rather than silently overridden; a superseding note belongs on
  ADR-0002 in that repo.
- Deliberately **not** done here, and worth their own decisions: `chat_service`'s
  remaining `_get_recent_activity_summary` still costs 42 sequential queries and *is*
  read by the client; the per-day reads swallow exceptions into empty results, so a failed
  read and an empty day are indistinguishable — which the daily-snapshot contract
  explicitly forbids for its sections; and the store carries near-duplicate
  `get_step_entries_in_range` / `get_steps_in_range`, differing only in parameter types and
  sort order (candidate #2).
