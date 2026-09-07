# 4. Serve the owner's day from one composition; make per-section failure real

Date: 2026-09-07
Status: Accepted

## Context

The Flutter client's `DailySnapshot.forDay` shipped over a seven-call parallel fan-out
and froze the shape it wants from the backend in `nufi_app` ADR-0003, mirrored here as
`docs/contracts/daily-snapshot-endpoint.md`. The endpoint became worth building once
`forDay` had real callers (`dashboard_home`, `today_report_screen`).

An inventory before writing code — the practice that has now paid three times — turned up
four things.

**`_read_errors` was structurally dead.** [ADR-0002](0002-shared-activities-for-a-date.md)
gave `get_shared_activities_for_date` a per-section failure map, and the contract names it
as the precedent for its own missing-vs-error rule. But **seven of the eight component
reads could not raise**: each wrapped its query in `try/except` and returned the same value
it returns for an empty day — `[]`, `None` or `{}`. Only `get_active_period_for_date`
re-raised. So in production the map was only ever populated for `period`, and a completely
unreachable database was reported to the coach as a day with nothing logged.

Its tests passed because they stub the *component reads*, not the client underneath them.
They exercised the composition's isolation logic against fakes that raise, while the real
reads did not. The composition was right; the leaves were lying to it.
[ADR-0001](0001-extract-health-trends.md) had already flagged this — "a failed read and an
empty day are indistinguishable — which the daily-snapshot contract explicitly forbids" —
and deferred it. This is the work that could not defer it.

**A third full-day read existed, and was unreachable.**
`api/activity_check.py` registered `GET /daily-summary/{user_id}`, the same path
`api/daily_summary.py` already claimed. Starlette matches in registration order, first
match wins, silently; `api/daily_summary.py` is included four routers earlier. The
shadowed handler had rotted accordingly — reading `total_glasses` where the column is
`glasses_consumed`, and treating `get_supplement_status_by_date`'s values as booleans
after that method began returning dicts. Adding a fourth full-day read while leaving it in
place would have been worse than either.

**The client's fan-out is not seven by-date calls.** `_defaultWeight` reads the user's
*entire* weight history (`GET /weight/{u}?limit=50`) and scans it client-side for a
matching day. The one-round-trip win is therefore larger than "7 → 1" suggests.

**And `get_weight_by_date` really could not be reused as-is**, as ADR-0002 predicted: its
projection dropped `shared_with_chat`, which the contract requires every row to carry.

## Decision

1. **The by-date reads propagate their errors.** The `try/except` comes out of all seven
   swallowing reads. A failed read and an empty day are different answers and the caller
   decides what to do with each.
   - Every caller was checked rather than assumed. All twelve `api/` call sites already sit
     inside an endpoint-level `try` that raises `HTTPException(500)`; the seven in
     `weekly_context_manager` already wrap each read in their own `try/except` and keep
     degrading per-day exactly as before.
   - Two call sites read strictly better now. `api/water.py:30` and `api/steps.py:30` look
     up an existing row before an upsert, so a swallowed read meant "no existing entry" and
     wrote a **duplicate row** instead of updating.
2. **Widen `get_weight_by_date` to keep `shared_with_chat`** rather than reading weight raw
   for this one endpoint. Widening the store method keeps the column from going missing on
   one caller's path only; reading raw would have put a second spelling of the same read
   back into the codebase, which is the hazard ADR-0003 closed.
3. **One private composition, two named public reads.** `_activities_for_date(user_id,
   target_date, shared_only)` holds the plumbing;
   `get_shared_activities_for_date` and `get_owner_activities_for_date` are its faces and
   take **no flag**. That preserves ADR-0002's decision. The cost of conflating the two
   views runs both ways: the coach seeing entries the user hid from it, or the user's own
   dashboard hiding their own data from them. The flag is private; the names carry the
   meaning, and `tests/test_store_by_date_surface.py` fails if either public read grows a
   parameter.
4. **`GET /api/health/daily-snapshot/{user_id}/{date}`**, with the shaping as pure
   functions (`snapshot_from_day` and three roll-ups) so the whole mapping is tested
   without FastAPI, a database or an event loop — the `health_trends` precedent.
5. **Three states per section, mapped onto the client's `Section.ok` / `.missing` /
   `.error`:** present ⇒ ok; absent ⇒ missing; absent and named in `_read_errors` ⇒ error.
   Same key and same rule as the store's day reads, so a client that ignores `_read_errors`
   degrades exactly as it does today. **This is the one place the contract was
   underspecified** — it says "a 5xx/partial-failure marker per section" without saying
   what the marker is. Copying the store's precedent rather than inventing a second
   vocabulary; `nufi_app` ADR-0003 needs the addendum.
   - The store leaves a failed section's empty value in place for callers that ignore the
     key. The endpoint **drops** it, so a failed read is never served as a reading.
6. **Roll-up sections are always present; single-row sections are omitted when empty.**
   "You logged nothing today" is an answer, not an absence, and the dashboard renders
   zeros. This mirrors the client's own fan-out exactly: `_entrySection` returns missing on
   null while `_mealsSection`, `_exerciseSection` and `_supplementsSection` always return
   ok.
7. **Delete the shadowed `/daily-summary` handler**, and add
   `tests/test_no_shadowed_routes.py` so any duplicated path+method fails the suite. Twenty
   routers under a handful of shared prefixes makes this easy to do again, and the failure
   mode is silent.
8. **Do not emit `period`.** The composition reads eight sections; the client's
   `DaySnapshot` has seven. Adding it is additive and needs no store change; a test pins
   the omission so it stays a deliberate act.
9. **Meal totals carry `fiber_g` / `sugar_g` / `sodium_mg`** alongside the four the
   contract names. `/daily-summary` already returns them and `MealApi` already maps them;
   omitting them would make migrating off it a regression.
10. **Build it on the store as it is.** The contract says to build this on candidate #2's
    daily-metric store and pair it with candidate #4's `log_daily_metric`. Neither exists:
    #2 was inventoried and deliberately not built (ADR-0003), and #4's premise is recorded
    as void. Neither was ever a prerequisite — this endpoint needs by-date reads, which
    the store already had.

## Consequences

- The client's seven-call fan-out — one of which reads the whole weight history — becomes
  one call, behind `DailySnapshot.forDay`'s interface, with no change to its callers.
- **A behaviour change on live endpoints, taken deliberately.** A tracker read that fails
  now surfaces as a 500 where it previously returned `{"success": false, "message": "No
  water entry found for this date"}` or `{"success": true, "status": {}}`. Those responses
  were lies: they reported a database failure as an empty day. `weekly_context_manager` is
  unaffected — it already caught per-read.
- `_read_errors` means something now, on both day reads. The existing composition tests did
  not change; `tests/test_by_date_reads_propagate_errors.py` covers the leaves, including
  the end-to-end case that previously produced eight empty sections and an empty error map.
- The reads still run sequentially, and `supabase-py`'s `execute()` is blocking, so
  `asyncio.gather` would not overlap them. One HTTP round-trip replaces seven, which is the
  win the client asked for; making the fan-out itself concurrent remains a separate change
  to the client layer, as ADR-0002 recorded.
- `nufi_app` ADR-0003 is the authoritative copy of this contract and **needs two additions**
  made there: the `_read_errors` spelling of the per-section error marker (decision 5), and
  the meal-totals superset (decision 9). Flagged rather than silently diverged; the mirror
  here records both.
- **Not done here, and each its own decision:** `get_exercise_logs` still filters a
  multi-day range with `.lte('exercise_date', end_date)` against a `timestamptz` — the same
  family as the bug fixed in the nutrition trend, and the last known instance. It does not
  bite the snapshot, which uses `get_exercises_by_date`, nor the client's current exercise
  reader, which passes `start == end` and hits a special case that builds a full-day range.
  Separately, `api/water.py` and `api/steps.py` answer a malformed `date` parameter with
  today's data; the snapshot endpoint returns 400 instead, and the older endpoints were
  left alone.
