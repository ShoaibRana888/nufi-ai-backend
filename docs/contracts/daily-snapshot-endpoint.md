# Contract request: daily-snapshot endpoint

> **Source of truth:** `nufi_app` → `docs/adr/0003-daily-snapshot-contract-request.md`.
> This is a mirror for the backend track. Do not let it diverge; if a change is needed,
> change it there first.

Status: **Built** — requested by the frontend (F1 `DailySnapshot`), shipped by the backend
in [ADR-0004](../adr/0004-daily-snapshot-endpoint.md).

## What the frontend wants

```
GET /daily-snapshot/{user_id}/{date}      # date = YYYY-MM-DD, user's timezone
```

Returns the **owner's complete day** — every entry across all trackers, **regardless of
`shared_with_chat`** — for the dashboard and the today report.

```jsonc
{
  "user_id": "...", "date": "2026-09-06",
  "meals":       { "totals": {"calories":0,"protein_g":0,"carbs_g":0,"fat_g":0},
                   "count": 0, "entries": [ /* meal rows */ ] },
  "water":       { /* daily_water row */ },
  "steps":       { /* daily_steps row */ },
  "sleep":       { /* sleep row */ },
  "exercise":    { "entries": [...], "total_minutes": 0, "total_calories_burned": 0 },
  "weight":      { /* weight row */ },
  "supplements": { "items":[{"name":"...","taken":false}], "taken_count":0, "total_count":0 }
}
```

Row shapes = the existing per-tracker payloads unchanged, incl. `shared_with_chat`.
Per-section failures must be isolated (one broken tracker read must not fail the whole
response); a section may be omitted (⇒ client treats as missing).

## Related contract change already made

`GET /chat/context/{user_id}` no longer returns a `weekly_summary` key. It was built
twice with divergent semantics, read by neither the coach's prompt nor the client, and
was deleted — see [ADR-0001](../adr/0001-extract-health-trends.md). This is a
non-additive change to a live response shape, taken because the field had no consumer on
either side. Unrelated to the weekly screen, which reads `nutrition_summary` /
`exercise_summary` / `hydration` from the **weekly-context** endpoint and is unaffected.

`get_weight_by_date` **could not be reused as-is** for the `weight` section: it projected
the row into a fixed field set and dropped `shared_with_chat`, which this contract requires
rows to carry. Resolved by widening the store method rather than reading weight raw here —
a second spelling of the same read is the hazard ADR-0003 closed.

The per-section isolation this endpoint requires had a precedent to copy — but the
precedent was hollow. `get_shared_activities_for_date`
([ADR-0002](../adr/0002-shared-activities-for-a-date.md)) reports per-section failures
under `_read_errors`, and **seven of its eight component reads could not raise one**: each
swallowed its exception and returned the value meaning "nothing logged", so in production
the map was only ever populated for `period`. The composition was right; the leaves were
lying to it. Making this contract's `missing` vs `error` distinction real meant fixing the
reads themselves — see [ADR-0004](../adr/0004-daily-snapshot-endpoint.md).

## Do not conflate with candidate #1

Backend candidate #1 (`get_shared_activities_for_date`) returns the **shared subset** for
the AI coach. This endpoint returns the **full owner day**. Same plumbing, two distinct
interfaces — record both in `CONTEXT.md`.

## As built

Served at `GET /api/health/daily-snapshot/{user_id}/{date}` — the `/api/health` prefix is
the client's existing `ApiClient.baseUrl`, so the path above is what `forDay` should
request. Additive: the per-tracker endpoints are untouched while the client migrates.

Two prerequisites in the original text were **not** prerequisites, and neither exists:

- *"Build it on the daily-metric store (candidate #2)"* — #2 was inventoried and
  deliberately not built ([ADR-0003](../adr/0003-no-daily-metric-store.md)). This endpoint
  needs by-date reads, which the store already had.
- *"pair the write side with `log_daily_metric` (candidate #4)"* — #4's premise is
  recorded as void in `CONTEXT.md`. This is a read; it has no write side.

### Two additions that belong upstream in `nufi_app` ADR-0003

The mirror records them; the authoritative copy should carry them.

**1. The per-section error marker is `_read_errors`.** The contract asks for "a
5xx/partial-failure marker per section" without saying what it looks like. It is a
top-level map of section name to message, the same key and rule the store's day reads use:

```jsonc
{ "user_id": "...", "date": "2026-09-06",
  "meals": { ... }, "water": { ... },
  "_read_errors": { "sleep": "sleep_entries exploded" } }
```

So, per section: **present ⇒ `ok`**, **absent ⇒ `missing`**, **absent and named in
`_read_errors` ⇒ `error`** — exactly the client's `Section.ok` / `.missing` / `.error`.
A failed section is never served with a value. `_read_errors` is always present, `{}` when
every read succeeded.

**2. Meal totals are a superset.** They carry `fiber_g`, `sugar_g` and `sodium_mg`
alongside the four named here, because `/daily-summary` already returns them and
`MealApi.getDailySummary` already maps them into `totals`. Omitting them would make
migrating off `/daily-summary` a regression.

### Section rules

- **Roll-ups always present, single rows omitted when empty.** `meals`, `exercise` and
  `supplements` carry zeros for a day with nothing logged; `water`, `steps`, `sleep` and
  `weight` are omitted when there is no row. This mirrors `DailySnapshot`'s own fan-out,
  where `_entrySection` returns `missing` on null while `_mealsSection`,
  `_exerciseSection` and `_supplementsSection` always return `ok`.
- **`supplements.items`** is sorted by name, so the client's list does not reshuffle
  between refreshes. `taken_count` and `total_count` are emitted as specified even though
  `SupplementsDay` derives both from `items`.
- **`period` is not emitted.** The backend's day read covers eight trackers; `DaySnapshot`
  has seven sections and no period. Adding it is additive and needs no store change.

### Notes for the client migration

- The win is larger than "6+ calls → 1". `DailySnapshot._defaultWeight` currently reads the
  user's **entire weight history** (`GET /weight/{u}?limit=50`) and scans it client-side
  for a matching day; the snapshot's `weight` section is one row for the date.
- **`MealsDay.entries` is always empty today**, whatever the backend returns.
  `_mealsSection` reads `data['meals'] as List`, but `MealApi.getDailySummary` normalises
  its response to `{'totals': ..., 'meals_count': ...}` and never emits a `meals` key. The
  snapshot's `meals.entries` carries the raw rows, so wiring `forDay` onto it fixes that
  as a side effect — worth a test on the client side.
- Rows are the raw per-tracker records and carry `shared_with_chat`, including `weight`:
  `get_weight_by_date`'s projection was widened rather than bypassed.
