# Contract request: daily-snapshot endpoint

> **Source of truth:** `nufi_app` → `docs/adr/0003-daily-snapshot-contract-request.md`.
> This is a mirror for the backend track. Do not let it diverge; if a change is needed,
> change it there first.

Status: **Proposed** — requested by the frontend (F1 `DailySnapshot`), not yet built.

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

`get_weight_by_date` **cannot be reused as-is** for the `weight` section. It projects the
row into a fixed field set and **drops `shared_with_chat`**, which this contract requires
rows to carry. Either widen that store method or read weight raw for this endpoint.

The per-section isolation this endpoint requires now has a precedent to copy.
`get_shared_activities_for_date` ([ADR-0002](../adr/0002-shared-activities-for-a-date.md))
keeps its sections independent and reports per-section failures under `_read_errors`,
rather than the older swallow-into-empty behaviour that made a broken tracker read
indistinguishable from a day with nothing logged. The owner's-day read should do the same
— that mapping is exactly this contract's `missing` vs `error` distinction.

## Do not conflate with candidate #1

Backend candidate #1 (`get_shared_activities_for_date`) returns the **shared subset** for
the AI coach. This endpoint returns the **full owner day**. Same plumbing, two distinct
interfaces — record both in `CONTEXT.md`.

## When the backend track reaches this

- Build it on the daily-metric store (candidate #2); pair the write side with
  `log_daily_metric` (candidate #4).
- Additive — leave the per-tracker endpoints in place while the client migrates.
- When it lands, the client's `DailySnapshot.forDay` swaps 6+ parallel calls for this one,
  behind its interface — no client-caller changes.
