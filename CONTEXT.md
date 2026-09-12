# Context — nufi-ai-backend (FastAPI + Supabase)

The domain glossary for the nufi backend. When code, an issue title, a refactor, or a
test names a domain concept, use the term as defined here — don't drift to a synonym.
If a concept you need isn't here, that's a signal: either you're inventing language the
project doesn't use, or there's a real gap worth adding.

The backend owns persistence (Supabase/Postgres) and the AI coach. The Flutter client
(`nufi_app`, a separate repo) is a thin front-end over the HTTP endpoints here. The
**HTTP contract between the two repos is the only real coupling** — treat it as a
designed interface, not an accident.

## Core nouns

- **User** — an onboarded person, one row in the users table. Created during
  **onboarding**; identified by `user_id`.
- **Tracker** — one health domain the user logs against: **meal, water, steps, sleep,
  exercise, supplement, period, weight**. Each has its own table(s) and an `api/<tracker>.py`
  endpoint module.
- **Entry** — a single logged record for one tracker on one date. Most trackers upsert
  one entry per date; meals/exercise allow several. Meals additionally roll up into
  **daily nutrition** (`daily_nutrition` table).
- **Entry date columns are not one type.** What the code treats as "the day an entry
  belongs to" is stored three different ways, verified against the live schema:
  `exercise_logs.exercise_date` is `timestamptz`, `meal_entries.meal_date` is
  `timestamp without time zone`, `sleep_entries.date` is `date`. So `.eq('<column>',
  '2026-09-06')` matches only rows stored at exactly midnight, and whether that is
  correct depends on what each writer happens to store — `api/exercise.py` writes a real
  time-of-day whenever the client omits `exercise_date`, because it falls back to
  `get_user_now()`, which returns a datetime. **Always filter a day with a half-open
  range** (`gte(date)` / `lt(next_day)`), which is correct for all three. The store's
  by-date reads already do, and since 2026-09-12 so does the one surviving range read
  on a timestamptz, `get_exercise_logs` — the last known `.lte` instance; three callers
  ended their range on today and lost that day's time-of-day rows
  (`tests/test_exercise_logs_date_range.py`). Reaching past the store is how this
  bites next.
- **Shared with chat** — a per-entry privacy flag (`shared_with_chat`). The store exposes
  it as a `shared_only: bool` parameter on the by-date reads
  (`get_meals_by_date(..., shared_only=True)`, `get_water_by_date`, `get_steps_by_date`, …).
  Entries not shared are excluded from chat context.
  - **A row can be born hidden.** The flag is set two ways: after the fact by
    `PATCH /sharing/{user_id}`, and **at insert time by a database trigger**.
    `users.chat_sharing_defaults` (written by `PUT /sharing/{user_id}/defaults`) is
    applied by `trg_share_default`, a `BEFORE INSERT` trigger on all seven tracker
    tables. Nothing in this repo applies the defaults, so reading the code alone says
    they are inert; they are not. Verified against the live schema in
    [ADR-0005](docs/adr/0005-context-refresh-reads-sharing-from-the-stored-row.md).
  - **So the only thing that knows a row's flag is the stored row** — what
    `create_*` / `update_*` return. Not the write payload (built before the row
    exists, and the trigger overrides it anyway) and not the pre-write row (absent on
    the create path). `update_context_activity` takes the stored row for this reason.
- **A day read** — one user's entries across all trackers on one date. There are
  **two**, both public methods on `supabase_service`, sharing one private composition
  (`_activities_for_date`). Each returns the eight tracker sections plus `_read_errors`
  (a per-section failure map, empty on success); sections are independent, so one broken
  tracker read never fails the others. See
  [ADR-0002](docs/adr/0002-shared-activities-for-a-date.md) and
  [ADR-0004](docs/adr/0004-daily-snapshot-endpoint.md).
  - **Shared activities for a date** — `get_shared_activities_for_date`. The *coach's*
    view: only entries with `shared_with_chat`. Backs the chat context builders.
  - **Owner activities for a date** — `get_owner_activities_for_date`. The *owner's*
    complete day, every entry regardless of the flag, because the owner sees and edits
    all of their own data. Backs `GET /api/health/daily-snapshot/{user_id}/{date}`.
  - **Neither takes a `shared_only` flag** — the flag is on the private composition and
    the names carry the meaning. A boolean on a public day read is how the two views get
    conflated, and it costs in both directions: the coach seeing entries the user hid, or
    the user's dashboard hiding their own data from them. Pinned by
    `tests/test_store_by_date_surface.py`. Same plumbing, two interfaces; do not conflate.
  - **`_read_errors` only became real in ADR-0004.** The map shipped with candidate #1,
    but seven of the eight component reads swallowed their exceptions into the same value
    they return for an empty day, so in production it was only ever populated for
    `period`. The composition was right; the leaves were lying to it. **The by-date reads
    now propagate**, and a failed read is distinguishable from a quiet day — which the
    daily-snapshot contract requires and ADR-0001 had flagged.
  - Before candidate #1, the three context builders re-derived the shared view with 17
    leaked reads, filtering meal dates three different ways and using `.eq()` on columns
    the store reads with a half-open range. Composing the store's own per-tracker methods
    means every caller inherits the range form, which is correct whether a column holds a
    date or a timestamp.
- **Coach** — the AI chat assistant (`chat_service` + `openai_service`). Answers using
  chat context.
- **Chat context** — the digest of a user's recent tracker data fed to the coach.
  Built daily by `chat_context_manager`, weekly by `weekly_context_manager`.
- **Trend** — a pure derivation over a window of a user's entries, answering *which way is
  this user moving?* Lives in `services/health_trends.py`: `weight_status`, `weight_trend`,
  `weight_direction`. The module is pure by enforcement, not by convention — no `async def`,
  no import that can reach the database (`tests/test_health_trends_purity.py`).
  See [ADR-0001](docs/adr/0001-extract-health-trends.md).
  - The term is **trend**, not *insight*. "Insight" was the working name while these were
    trapped inside `chat_context_manager` and `chat_service`; it invited anything derived to
    be filed here. Trend names the actual question.
  - **`weight_trend` and `weight_direction` are different concepts**, deliberately not
    unified. `weight_trend` is the coach's narrative vocabulary over a short window
    (`losing_1.5kg`, 0.2kg noise floor). `weight_direction` is the 30-day reading behind
    `GET /weight/{user_id}/stats` (`losing`, 0.5kg noise floor) and its shape is on the wire.
    Same word in English, two audiences — the same trap the daily-snapshot contract flags
    for candidate #1.
  - **The string encodings are a contract.** `weight_status` values reach the Flutter client
    as `goals_progress.weight_progress.status`, where it compares against the literal
    `'no_data'`, and they are persisted verbatim in `chat_contexts.context_data`.
- **Day status** *(client-side)* — the sibling question, *is this user at their goal today?*
  It lives in `nufi_app` (`lib/data/services/day_status.dart`) and has no backend twin,
  because the thin client computes it. `nufi_app` ADR-0002 calls it "the client twin of the
  backend's `health_insights`"; that is a **cousin**, not a twin — different window
  (one day vs. many), different question (goal-relative vs. directional), different output
  (structured `MetricStatus` vs. encoded strings). Corrected there in a superseding note.
- **Recent activity summary** — *removed.* `chat_service._get_recent_activity_summary`
  looped seven days of `get_today_activities` — **56 sequential queries** after candidate
  #1 widened that read to eight sections (it was 42 before) — to produce
  `meals_this_week` / `workouts_this_week` / `avg_sleep_hours`. Deleted rather than
  optimised, because tracing every consumer found none:
  - **No prompt read it.** `_create_system_prompt` reads `user_profile`,
    `today_progress` and `body_state`; `_create_enhanced_system_prompt` adds
    `current_week`.
  - **The client could not have read it.** `ChatService.getUserContext` calls
    `GET /api/health/chat/context/{user_id}`, which is served by
    `chat_context_manager` — a module that has never produced a `recent_activity` key.
    The only producer was `chat_service.get_user_context`, and the only path to *that*
    is the `except` branch of `get_enhanced_context`. Producer and endpoint were in
    different modules.
  - So the client's three `context['recent_activity'] ?? {}` reads in
    `lib/data/services/chat_service.dart` always took the fallback, and
    `generateContextSummary`'s **"Recent highlights" line has never once rendered** —
    it returns the generic greeting every time. Fixing that is a client-side decision
    about whether anyone wants the feature, not a reason to keep an unread producer.
  - The 56 queries were also worst-placed: on a fallback path, they fired only when the
    context manager had already failed.
- **Weekly summary** — *removed.* It was built by both `chat_context_manager` and
  `chat_service` under the same key names with divergent semantics (windows off by a day at
  each end, calories averaged over days-with-data vs. a flat 7, workouts counted as days vs.
  entries) and **read by nothing** — not the system prompt, not the client. Deleted rather
  than converged. Not to be confused with **weekly context**
  (`weekly_context_manager` → `nutrition_summary` / `exercise_summary` / `hydration`), which
  is live and does back the client's weekly screen.
- **Guardrails** — body-state safety checks over a user's recent data
  (period / sleep / calorie / already-logged), in `services/guardrails.py`, applied before
  the coach responds.
- **Daily summary** — `GET /api/health/daily-summary/{user_id}` (`api/daily_summary.py`).
  Despite the name it is **meals only**: nutrition totals plus a count. Not the day.
  A second handler for the same path lived in `api/activity_check.py` and was unreachable
  — Starlette matches in registration order and the first wins, silently — so it rotted
  unnoticed. Deleted in ADR-0004; `tests/test_no_shadowed_routes.py` now fails on any
  duplicated path+method.
- **Daily snapshot** — `GET /api/health/daily-snapshot/{user_id}/{date}`
  (`api/daily_snapshot.py`), the composed read for a user's whole day and the backend
  counterpart to the client's `DailySnapshot.forDay`. Shape frozen in
  `docs/contracts/daily-snapshot-endpoint.md` (authoritative copy: `nufi_app`
  docs/adr/0003). Composes `get_owner_activities_for_date`; the shaping is pure.
  - **Three states per section**, matching the client's `Section.ok` / `.missing` /
    `.error`: present ⇒ ok, absent ⇒ missing, absent and named in `_read_errors` ⇒ error.
  - **`_read_errors` values are the token `"read_failed"`**, not the store's message
    ([ADR-0007](docs/adr/0007-read-errors-carries-a-token-not-a-message.md)). The
    store's map keeps the raw exception text for the server log; the endpoint's
    shaping swaps it for the token on the way out. Presence carries the
    missing-vs-error distinction; the client never read the value.
  - **Roll-ups are always present, single rows are omitted when empty.** `meals`,
    `exercise` and `supplements` carry zeros for a day with nothing logged — that is an
    answer, not an absence. `water`, `steps`, `sleep` and `weight` are omitted when there
    is no row. Mirrors the client's own fan-out.

## Data access vocabulary (the architecture work touches this)

- **The store** — `services/supabase_service.py`, the single module that should own table
  access. Candidate #2 proposed collapsing it into a **daily-metric store** keyed by a
  metric descriptor, on the premise that "each tracker repeats the same CRUD family". The
  inventory did not support that, and the descriptor was **not built** — see
  [ADR-0003](docs/adr/0003-no-daily-metric-store.md). What the cleanup did instead:
  - Deleted 7 methods with no caller anywhere, including three of the four range reads.
  - Collapsed three duplicate by-date pairs onto their shared-aware versions.
  - Locked the by-date read surface with a test, so a second door for the same question
    fails the suite rather than waiting to be picked by mistake.
- **One question, one read.** Where a tracker has two ways to ask the same thing, one of
  them will not respect `shared_with_chat`, and its name will not say so. That is how the
  water/steps/sleep pairs arose — and in all three the unsafe variant was the *more* used
  one. `tests/test_store_by_date_surface.py` now pins the surface.
- **A read reports failure; it does not return it as data.** *(Still open on the range
  reads: `get_exercise_logs` swallows to `[]`, so `/exercise/stats` reports an
  unreachable database as a week with no workouts. ADR-0004 fixed the by-date leaves
  only.)* The by-date reads used to
  wrap every query in `try/except` and return the value that means "nothing logged" — a
  broken tracker and a quiet day were the same answer. That silently defeated the layer
  built on top of it (`_read_errors`), wrote duplicate rows on the upsert paths that
  check for an existing entry first, and told the coach the user had logged nothing when
  the database was unreachable. Fixed in
  [ADR-0004](docs/adr/0004-daily-snapshot-endpoint.md); pinned by
  `tests/test_by_date_reads_propagate_errors.py`. **The corollary for tests:** stubbing
  the method under a composition proves the composition, not the system — those tests
  passed for a year against leaves that could not raise.
- **A route that has never run has never been tested.** Fixing the doubled `/chat`
  prefix made `check_context_date` and `daily_context_reset` reachable for the first
  time, and both computed "today" from `datetime.now().date()` — the server clock —
  while every other date-sensitive endpoint takes `get_timezone_offset`. For a user
  far enough east of the Oregon region, a row dated to the server's today compared
  equal to "today" and the reset never fired. Making dormant code reachable is a
  behaviour change: read it before shipping the fix that switches it on.
- **The server clock is UTC.** Confirmed from `chat_contexts` rows, not assumed:
  `context_metadata.created_at` (server `datetime.now()`) and the DB-side
  `created_at` (`now()`) agree to the tenth of a second. So `datetime.now().date()`
  is the UTC date, and for a UTC+5 user it is yesterday until 05:00 local. Every
  "which day" decision takes the user's date as an argument; the places that still
  read the server clock are listed in ADR-0006 with the reason each is allowed to.
- **Two handlers can claim one route, and the loser is silent.** Starlette matches in
  registration order; the first wins with no warning. Twenty-odd routers share a handful
  of prefixes here, and it has already happened once (`/daily-summary`).
  `tests/test_no_shadowed_routes.py` fails on any duplicated path+method.
- **A route can also be served where nobody looks.** `APIRouter(prefix=...)` applies the
  prefix *at decoration time*, so a decorator that spells the prefix out again produces
  `/chat/chat/...`. Three of `api/chat.py`'s routes did, and two of them are called by
  the client on app open and chat open — `checkAndResetDailyContext` swallows the 404 and
  returns `false`, so the daily context reset had never once run.
  `tests/test_router_prefixes.py` pins the structural rule.
- **The HTTP contract with `nufi_app` is now enforced, not just asserted.**
  `tests/test_client_contract.py` holds a snapshot of all 80 paths the client's
  `ApiClient` calls and fails if one reaches no route here. It catches the direction that
  fails silently — the backend not serving what the client already calls — and cannot see
  paths the client adds after the snapshot, so **refresh the fixture when the client's API
  surface changes**. Three client calls reach nothing today; all three are dead client
  methods with zero callers, listed as documented exceptions with a test that they stay
  unserved.
- **A response body is not a log line.** 111 handlers in `api/` put `str(e)` into a
  response — 96 as `HTTPException(500, detail=str(e))`, 13 as `{'error': str(e)}`, 2 in
  f-strings — and no route has auth, so a PostgREST failure ships its SQL message,
  error code, hint and table/column names to whoever asked. `_read_errors` was the one
  such door on a 200 path and a contract field, so it was closed first (ADR-0007). The
  other 111 are one change, not 111 — a generic `detail` with the exception logged, or a
  5xx-rewriting middleware — and their own inventory: confirm nothing in `nufi_app`
  parses a 500 `detail` before choosing. Not done.
- **Leaked read** — a raw `.client.table(...)` call made *outside* the store. The
  context builders have none left: candidate #1 pulled all 17 behind
  `get_shared_activities_for_date`. What remains is two distinct groups, and neither is
  "more of #1":
  - **Context persistence** — `chat_contexts` and `weekly_contexts` reads inside the two
    context managers. These are the context store's *own* storage, not tracker data. If
    they get a home it is a context-store module, not the tracker store.
  - **Endpoint reads** — `api/` modules reaching tables directly (notifications, FCM,
    debug, meal suggestions, meal presets). Separate concerns, separate decisions.
- **`log_daily_metric` use-case** — candidate #4, **re-grilled 2026-09-07 and not
  built as scoped.** The proposal was that endpoints repeat "upsert-by-date, then
  remember to refresh chat context" and that a use-case should own the flow atomically,
  because forgetting the refresh is a real bug class. Checked against the code:
  - **The refresh calls number 14, not ~28**, and they are one method:
    `context_manager.update_context_activity`, across meals (4), water, steps, sleep,
    exercise, weight (2 each) and supplements (1). The earlier figure counted the
    context manager's whole surface.
  - **The bug class is already defended.** `chat_service.generate_chat_response` calls
    `rebuild_context` unconditionally before every reply, so the coach never reads a
    stale context regardless of what the write endpoints did.
  - **`api/periods.py` has 4 write endpoints and zero refresh calls, and is fine** —
    period data reaches the coach's guardrail through `compute_period_status`, which
    takes a `period_row` read from the table, not from cached context. The one endpoint
    family that "forgets" is the one that never needed to remember.
  - **So the 14 calls buy exactly one thing:** freshness for
    `GET /api/health/chat/context/{user_id}`, which serves stored `context_data`
    verbatim — `get_or_create_context` does no freshness check and the `version` column
    is written but never read for any decision.
  - *Amended after reviewing that work:* one of the 14 could not fire on its
    common path. `api/water.py`'s upsert returned early on the **update** branch,
    skipping the refresh below the `if/else`, so only the day's *first* glass
    refreshed the context. Fixed; `tests/test_water_context_refresh.py` covers
    both branches. A call site is not a call.
  - **The incremental refresh respects `shared_with_chat`** — fixed in
    [ADR-0005](docs/adr/0005-context-refresh-reads-sharing-from-the-stored-row.md).
    `update_context_activity` used to merge its payload into `chat_contexts` blind,
    so logging against a hidden row reversed the rebuild `PATCH /sharing/{user_id}`
    performs. The guard is in the shared method, once, and reads the flag off the
    **stored row** every write endpoint now passes. The premise "upsert against a
    row the user hid" was too narrow: the insert trigger above means a row can be
    hidden from birth, so the always-create trackers (weight, exercise, meals)
    leaked too, and water's endpoint-level guard — which read the pre-write row —
    missed its own create path. Pinned through both layers by
    `tests/test_context_refresh_respects_sharing.py`.
  - **`POST /chat/context/update/{user_id}` is live, and bypasses the guard.** First
    written here as "no live caller" after a grep that missed the in-file wrapper
    `ChatApi.syncContext`, called by nine tracker Apis after every write. It sends the
    client's payload, not the stored row. Deleted on both sides in the follow-up
    branches; see the contract-test bullet below once that lands.
  - **The coach's day is the user's day** — fixed in
    [ADR-0006](docs/adr/0006-the-coach-reads-the-users-day.md). This bullet used to
    say the server-day rebuild was *inert* because the coach rebuilds from source
    tables every reply. That was the wrong conclusion: the source tables are keyed by
    the **user's** day, so the rebuild read a different day's rows than the ones
    being written, for `|offset|` hours of every day — and 39% of all chat messages
    ever sent fell inside that window. `generate_chat_response` now takes `today`
    (a `date`, resolved by the endpoint from the offset) and hands the one value to
    the rebuild, the cached read and the weekly window. The date is **required** on
    every method that picks a day, including `get_or_create_context` and
    `ensure_daily_context`, whose server-date defaults are gone. *Bounded* is not
    *inert*: check what the rebuild actually reads.
  - **The re-scoped question**, which is much smaller than a use-case: *should the
    cached-context endpoint rebuild, or declare its staleness?* Answer that first. If it
    rebuilds, the 14 calls are dead and the question becomes a deletion. If it does not,
    they are load-bearing for one endpoint and `log_daily_metric` is still the wrong
    shape for saying so.
  - **Not a prerequisite for anything.** The daily-snapshot contract said to pair this
    endpoint with #4 for the write side and to build it on #2's daily-metric store.
    Neither was needed: #2 was inventoried and deliberately not built (ADR-0003), and the
    snapshot needed only by-date reads the store already had (ADR-0004).

## Conventions

- **Emerging vs. established terms.** Terms marked *(emerging term)* name a concept the
  code re-derives in several places but hasn't yet given a module. Drop the marker once
  the corresponding architecture work lands.
- **Contract-first with the client.** Any change to an endpoint's request/response shape
  is a change to the shared interface with `nufi_app`. Keep changes additive until the
  client is ready to consume them; design the shape once, from whichever side leads.
- **Decisions live in `docs/adr/`.** This file names the vocabulary; an ADR records a
  decision and why it went that way. Mirrors `nufi_app`'s practice — read the ADRs that
  touch an area before working in it, and if your change contradicts one, say so rather
  than overriding it silently.
- **Prove a thing is dead before deleting it, then delete it.** Twice in one afternoon a
  "duplicated helper worth extracting" turned out to have no callers at all. Grep both
  repos for the key or the function name, check the prompt builders, and check the Dart
  side — then remove it rather than carrying it into a new module, which only launders
  dead code into looking live. "Registered" is not "reachable": prove it against the
  route table, not the source.
- **Inventory the premise before building the candidate.** Five for five now, the
  written premise has been wrong in a way that changed the work: #1 was mis-sized by 4x,
  #3 was half dead code, #2's uniform CRUD family did not exist, and #4's justification
  is void. For the snapshot the premise held but the *precedent* did not — `_read_errors`
  was structurally dead. For the sharing guard the premise named the wrong source of
  truth — the pre-write row — and the precedent (water's guard) had the same gap.
  Check what is live before extending it, **and check the database, not just the
  repo**: the insert trigger that changed ADR-0005 is invisible from the code.
- Architecture vocabulary (module, interface, seam, adapter, depth, leverage, locality)
  lives in the design skill, not here. This file names the *domain*; that file names the
  *shapes*.
