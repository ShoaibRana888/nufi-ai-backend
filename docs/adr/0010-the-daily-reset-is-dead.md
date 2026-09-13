# 10. The daily context reset is dead; delete it, and the per-read cleanup with it

Date: 2026-09-13
Status: Accepted

## Context

`GET /chat/context/check/{user_id}` and `POST /chat/context/daily-reset/{user_id}`
were the client's "new day" housekeeping: on every app open and every chat open,
`ChatApi.checkAndResetDailyContext` asked whether the newest `chat_contexts` row was
today's and, if not, had `ensure_daily_context` create an empty one for the user's
day. Both routes were unreachable until the doubled-prefix fix (`CONTEXT.md`), then
moved to the user's day (`tests/test_context_daily_reset_timezone.py`).

[ADR-0008](0008-chat-context-rebuilds-on-read.md) made `GET /chat/context/{user_id}`
rebuild on read, which creates and fills the day's row itself. That raised the
question this ADR answers: is the reset still load-bearing? Same shape as candidate
#4's question — rebuild, or keep a cache warm? — and it was checked against the
callers rather than assumed.

**Who reads a stored `chat_contexts` row.** Every reference to the table, in this
repo: `get_or_create_context` (the read), `create_initial_context` and
`_save_context` (writes), `ensure_daily_context` (the reset itself), `check_context_date`
(feeds only the reset decision), and `DELETE /context/cleanup`. One reader.

**When that reader runs.** Two paths, both after a rebuild of the same row:

- The coach: `generate_chat_response` calls `rebuild_context(user_id, today)`, then
  `get_comprehensive_context → get_enhanced_context → get_or_create_context(today)`.
  The row it reads is the one it just wrote.
- The endpoint: `GET /chat/context/{id}` calls `rebuild_context`, and reaches
  `get_or_create_context` only in its `except`, when the rebuild raised.

So the reset's row is observed only when the rebuild for that day has *failed* — and
on that path, with no row, `get_or_create_context` calls `create_initial_context`
and produces the same empty row anyway. The reset bought nothing on any path.

**The client discarded the answer.** `home_page._ensureDailyContext` awaits the bool
and drops it; `chat_page.initState` does not even await. `is_new` in the reset's
response was never set by `ensure_daily_context`, so it was always `false`.

**What it cost.** Two round-trips per app open and per chat open — the check, and
the reset when the day had changed — on the same path ADR-0008 had just shortened.

**And the rows it left.** The two most recent `chat_contexts` rows on the live
database (dated 2026-09-12 and 2026-09-13) are version-1 rows with zero meals and no
flat `total_*` fields: the reset's empty rows, written after the rebuild-on-read
deploy, never read.

**`deduplicate_context`** ran on every stored-row read: it collapsed repeated meal
and exercise ids and re-synced the flat `total_*` fields with `totals`. Both were
for rows the old incremental merge produced. ADR-0008 deleted the merge and said
"once no such rows exist it is a deletion candidate". The database, queried
directly: 184 rows; **3 carry duplicates, all dated September 2025**; 114 have
flat totals that disagree with `totals`, of which the recent ones are the reset's
initial rows (no flat fields at all) and the rest are pre-ADR-0008 rows. Note
`chat_contexts` has `UNIQUE (user_id, date)`: the duplicates were never rows, only
entries inside `context_data`.

> **Corrected in review (Codex, PR #19).** This first said every such row "is
> rewritten by `rebuild_context` on its next read, before the cleanup could have
> run on it". That holds only when the rebuild succeeds. On the rebuild-failed
> fallback — the one path that reads a stored row without rewriting it — a legacy
> row would be served as it is, duplicates and drifted `total_*` included. The
> claim assumed the success path; the fallback is the path the cleanup existed
> for. So the condition ADR-0008 set — *once no such rows exist* — has to be made
> true, not argued around. Counted precisely: of 184 rows, **172 are older than
> the 7-day retention `DELETE /context/cleanup` already defines**, and every row
> the fallback could expose with a wrong value is among them — the 2 with
> duplicates (newest 2025-09-28) and the 52 with drifted flat totals where the
> banner would show a number (newest 2026-07-09). The 12 rows within retention
> are clean. Decision 2 stands on those rows being repaired, and not before.
>
> **Migrated 2026-09-14, by running the function once at rest.** Rather than
> delete past-retention rows or reimplement the repair in SQL, the 53 flagged
> rows were fetched, `main`'s `deduplicate_context` was run over each (unbound;
> it never used `self`) on exactly the input it saw in production, and the keys
> it changes were merged back into `today_progress` with `||` in one batched
> `UPDATE … FROM (VALUES …)` — nothing else in `context_data` touched, the
> statement guarded to rows older than retention. **52 rows changed**: 51 only
> gained the flat `total_*` fields and counters (their `totals` were already
> what the function computes), and 2025-09-24 also lost two genuinely repeated
> meal ids. **One row was deliberately not touched** (2025-09-28): its two meals
> and three exercises are distinct entries with no `id`, already consistent
> (1200 = 550 + 650). It was flagged only because grouping by `id` lumps nulls —
> and the function has the same blind spot, collapsing them to one meal and one
> exercise, with `exercise_minutes` 0 because its key is `duration`. So every
> read of that row through the "repair" had shown the wrong numbers; one more
> reason the function does not survive. After: 0 rows with a repeated id, 0
> rows whose flat totals differ where `meals_logged > 0`; the 62 that still
> differ are the empty initial rows (no flat fields, `meals_logged` 0), which
> the banner never reads. Spot-checked 2026-07-09 at 1700 / 1700.

## Decision

1. **Delete the two routes, `ensure_daily_context`, and the client's
   `checkAndResetDailyContext` with its two callers** (`nufi_app` PR #21). Merge
   the client first, so it stops calling before the routes stop answering.
2. **Delete `deduplicate_context`, after the legacy rows are repaired** — done,
   by applying the function once at rest (above), so no row it existed for
   remains for the fallback to serve. `get_or_create_context` serves
   `context_data` as stored: what `rebuild_context` writes is what is read.
3. **Refresh the client-path fixture** — the two lines go, and the header names
   the client commit that removed the calls. `tests/test_daily_reset_is_gone.py`
   pins the routes and methods absent and the stored row served verbatim.
4. **`create_initial_context` stays.** It is `get_or_create_context`'s create
   branch, on the rebuild-failed path. Whether that path should create an empty
   row and serve it as `stale: true` rather than answer 500 is a question about
   ADR-0008's fallback, not about the reset; recorded below.

## Consequences

- Two fewer requests on every app open and chat open. −173 lines here
  (74 in `api/chat.py`, 109 in the context manager) and the reset's test file;
  `nufi_app` loses the method and two callers.
- `tests/test_coach_day_is_the_users_day.py` loses its two `ensure_daily_context`
  entries; the property it pinned (the day is required) holds for the callers
  that remain.
- **Found while proving it dead:** `main.py` registers `OPTIONS /{rest_of_path:path}`
  for CORS preflight, so every unknown path on this API answers **405, not 404** —
  the path matches the catch-all and the method does not. `test_client_contract.py`
  is unaffected (it matches the route table, `Match.FULL`), but "had always 404'd"
  in earlier records was, strictly, 405; the client checks `== 200` and never saw
  the difference.
- **Open, its own decision:** on the rebuild-failed path with no stored row,
  `get_or_create_context` creates an empty day and `GET /chat/context/{id}` serves
  it with `stale: true`. ADR-0008 decision 2 says "if that fails too, 500 — not an
  empty day"; an empty row that was just created is an empty day with a flag on
  it. Now that the reset no longer pre-creates rows, this branch is the only
  writer of empty rows.
