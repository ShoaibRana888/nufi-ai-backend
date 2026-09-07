# 3. Don't build the daily-metric store; delete and collapse instead

Date: 2026-09-07
Status: Accepted

## Context

Backend candidate #2 proposed collapsing the store into a **daily-metric store keyed by a
metric descriptor**, on the premise recorded in `CONTEXT.md`:

> each tracker repeats the same CRUD family (create / update / get_by_date /
> get_by_date+shared / history / range / delete)

An inventory of all 86 methods and their callers before writing any code found the
premise does not hold.

**The family is not uniform.** `exercise` and `weight` have no update. `supplement` has no
delete. Four of the eight trackers have no range read at all. `period` is not keyed by a
date column — a row spans `start_date..end_date`.

**The range leg was almost entirely dead.** `get_water_entries_in_range`,
`get_step_entries_in_range` and `get_daily_nutrition_range` had zero callers anywhere, as
did `get_weight_entries` — whose only caller had been the weekly summary deleted in
[ADR-0001](0001-extract-health-trends.md). Only `get_steps_in_range` survives, and steps
carried *two* range methods differing solely in parameter types and sort order.

**Three trackers had two by-date reads each, and the unsafe one was the more used one:**

| tracker | shared-aware | callers | older, no `shared_only` | callers |
|---|---|---|---|---|
| water | `get_water_by_date` | 2 | `get_water_entry_by_date` | **5** |
| steps | `get_steps_by_date` | 2 | `get_step_entry_by_date` | **3** |
| sleep | `get_sleep_by_date` | 1 | `get_sleep_entry_by_date` | **4** |

Nothing had leaked — all twelve callers are owner-facing endpoints where seeing your own
hidden entries is correct, and each was checked by hand. But the names gave no hint which
was which, and one caller on a chat path picking the wrong one would have quietly fed the
coach entries the user had hidden from it.

**And what remains differs on five axes a descriptor would have to encode:** table name,
date column name, date column *type* (`timestamptz` / `timestamp` / `date` — see
[ADR-0002](0002-shared-activities-for-a-date.md)), row cardinality, and return shape
(`get_weight_by_date` projects; the rest return raw rows).

Confirmed with the author: **no ninth tracker is planned.** That removes the one
justification — cheap addition of new trackers — that would have made the descriptor pay
for itself.

## Decision

1. **Do not build the metric descriptor.** Encoding those five axes relocates the
   complexity into a config table and inserts a layer of indirection between a bug and its
   cause. The date-type variation in particular is exactly the kind of detail that hides
   well in a descriptor and surfaces in production.
2. **Delete the seven dead methods** — the range leg plus `create_conversation` (a
   docstring-declared placeholder), `initialize_starting_weight` (dead twin of the live
   `initialize_starting_weight_for_user`) and `migrate_all_users_starting_weights` (an
   orphaned backfill; this repo does backfills as SQL migrations, and git history keeps it).
3. **Collapse the three duplicate by-date pairs** onto their shared-aware versions and
   repoint the callers. All calls were positional and `shared_only` defaults to `False`,
   so behaviour is unchanged.
4. **Lock the by-date read surface with a test** rather than a convention. The removed
   names must stay removed, every read composed into `get_shared_activities_for_date` must
   accept `shared_only` defaulting to `False`, and the set of by-date reads is pinned so
   adding a second door for one question fails the suite.
5. **Re-frame what #2 was for.** The pain worth removing was never interface width — 86
   methods in a file nobody reads top-to-bottom is an aesthetic complaint. It was the
   correctness trap in (3), which is now gone.

## Consequences

- 86 methods → 76; net **−241 lines** across `services/` and `api/` (253 deleted, 12
  added), plus one test file.
- The store's interface is still wide, and that is accepted. Width is not the defect;
  ambiguity was.
- **Not folded in:** `get_user_meals_by_date` is a fourth instance of the pattern by
  caller count, but it is not a duplicate — it takes a `str` date, projects an explicit
  column list, and orders `desc`. Its three callers are owner-facing. Recorded in the
  guard test's expected set with the reasoning, so the next person meets the decision
  rather than the smell.
- If a ninth tracker ever *is* planned, reopen this. The right shape then is probably not
  a full descriptor either, but one generic single-row `get_daily_entry(table,
  date_column, user_id, date, shared_only)` covering the four trackers that genuinely
  match — water, steps, sleep, weight — leaving meals, exercise, supplements and period as
  themselves.
- Third time in this track that "duplicated code worth abstracting" turned out to be
  partly dead code worth deleting ([ADR-0001](0001-extract-health-trends.md),
  [ADR-0002](0002-shared-activities-for-a-date.md)). The `CONTEXT.md` convention "prove a
  thing is dead before deleting it, then delete it" earned its place.
