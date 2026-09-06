# 2. Give "shared activities for a date" one home in the store

Date: 2026-09-06
Status: Accepted

## Context

Backend candidate #1: the context builders re-derived "the user's shared entries across
all trackers on one date" instead of asking the store for it. Investigating before
building changed both the size and the point of the job.

**It was mis-sized.** `CONTEXT.md` described "~70 raw `.client.table(...)` calls across 15
files". That is every leaked read in the repo. The shared-activities concept is **17 reads
across 3 files** — and `weekly_context_manager`, one of the three named, turned out to
have **zero**: all six of its raw reads are `weekly_contexts` persistence. The other 62
are the context managers' own `chat_contexts`/`weekly_contexts` storage plus `api/`
modules reading notifications, FCM tokens, debug and meal presets. Folding those into one
number made a one-day job look like a week's.

**The store already had the reads.** Seven of the eight sections had a correct,
`shared_only`-aware method sitting in `supabase_service` already. The leaked reads were
re-implementations of methods that existed. Only the period read was genuinely missing.

**And the re-implementations had drifted.** The same read was spelled three ways:

| | filter on the date column |
|---|---|
| `supabase_service.get_meals_by_date` | `gte(date)` / `lt(next_day)` — half-open range |
| `chat_service.get_today_activities` | `gte("<d>T00:00:00")` / `lte("<d>T23:59:59")` |
| `chat_context_manager._fetch_all_daily_activities` | `eq(str(date))` |

The leaked builders also used `.eq()` on `exercise_date` and `sleep_entries.date` where
the store uses a range. That is not stylistic: `api/exercise.py` writes `exercise_date`
as `get_user_date(...).isoformat()` when the client sends the field and
`get_user_now(...).isoformat()` when it does not — and `get_user_now` returns a
**datetime**. So that column receives a date string sometimes and a timestamp string
other times, decided by whether the client sent a field. Whether `.eq()` silently misses
those rows depends on the column's declared type, which is not recorded anywhere in this
repo. The half-open range is correct either way.

## Decision

1. **`supabase_service.get_shared_activities_for_date(user_id, target_date)`** owns the
   concept. It *composes* the existing per-tracker store methods rather than issuing its
   own queries, so every caller inherits the range form.
2. **Add `get_active_period_for_date`** — the one read that did not exist. `period_entries`
   has no date column; a row spans `start_date..end_date`, so "active on this date" is its
   own predicate and deserves a named method rather than an inline `.or_()`.
3. **Shared-only by construction.** No `shared_only` parameter: this read *is* the coach's
   view. The owner's complete day is a different interface
   (`docs/contracts/daily-snapshot-endpoint.md`), and a boolean flag would be the exact
   conflation the contract warns against.
4. **Return `_read_errors` alongside the eight sections.** A failed section still carries
   its empty value, so callers that ignore the key behave as the inline reads did; callers
   that must tell a broken tracker from an empty day now can. Sections stay independent —
   one failing read never fails the others.
5. **Characterize before rewiring.** The three builders sit in the
   rebuild-before-every-reply path; their shapes were pinned first so the behaviour delta
   would be a reviewable diff.
6. **Leave the other 62 leaked reads alone**, and stop describing them as one thing.

## Consequences

- Net **−211 lines** across `chat_context_manager` and `chat_service` (45 added, 256
  deleted); 17 leaked reads become 3 delegating calls. The store grew 97 lines.
- **Three behaviour changes**, each pinned by an updated test rather than discovered later:
  - `chat_service.get_today_activities` returned **seven** sections — it never read
    `period_entries` — so on that path the coach's period guardrail saw nothing. It now
    returns all eight.
  - `generate_fresh_context` read only meals, exercise, water and steps, then hardcoded
    `weight=None`, `sleep_hours=None`, `supplements_taken=[]`. The fallback context told
    the coach the user had logged no weight and no sleep even with both in the database.
  - The weight section changes shape: `get_weight_by_date` projects the row into a fixed
    field set rather than returning it raw. Inert for current consumers, which read only
    `['weight']`.
- **Carried forward to the daily-snapshot work:** that projection **drops
  `shared_with_chat`**, which the contract explicitly requires rows to keep
  ("Row shapes = the existing per-tracker payloads unchanged, incl. `shared_with_chat`").
  The snapshot endpoint cannot reuse `get_weight_by_date` as-is.
- The reads run sequentially. `supabase-py`'s `execute()` is blocking, so `asyncio.gather`
  would not overlap them; making the day's fan-out concurrent is a change to the client
  layer, not to this method. Worth doing — the client's `DailySnapshot` already fans out in
  parallel — but it is its own decision.
- **Unresolved and worth one `\d exercise_logs`:** whether `exercise_date` is a date,
  timestamp or text column. If it is not a date, the old `.eq()` reads were silently
  dropping exercises from the coach's context, and this change fixes a live bug rather
  than a latent one. Not settled here because it needs the production schema, and reading
  it was outside what this work was authorized to touch.
