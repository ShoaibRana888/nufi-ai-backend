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
  by-date reads already do; reaching past them is how this bites.
- **Shared with chat** — a per-entry privacy flag (`shared_with_chat`). The store exposes
  it as a `shared_only: bool` parameter on the by-date reads
  (`get_meals_by_date(..., shared_only=True)`, `get_water_by_date`, `get_steps_by_date`, …).
  Entries not shared are excluded from chat context.
- **Shared activities for a date** — the set of a user's shared entries across all
  trackers on one date. Owned by `supabase_service.get_shared_activities_for_date`,
  which returns the eight tracker sections plus `_read_errors` (a per-section failure
  map, empty on success). Sections are independent: one broken tracker read never fails
  the others. See [ADR-0002](docs/adr/0002-shared-activities-for-a-date.md).
  - **Shared-only by construction.** This is the *coach's* view. The **owner's complete
    day** — every entry regardless of `shared_with_chat` — is a different read, requested
    by the client in `docs/contracts/daily-snapshot-endpoint.md`. Same plumbing, two
    interfaces; do not conflate them.
  - Before this, the three context builders re-derived it with 17 leaked reads, filtering
    meal dates three different ways and using `.eq()` on columns the store reads with a
    half-open range. Composing the store's own per-tracker methods means every caller
    inherits the range form, which is correct whether a column holds a date or a timestamp.
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
- **Daily summary** — a composed read for one day (`api/daily_summary.py`), the backend
  counterpart to the client's "today report".

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
- **Leaked read** — a raw `.client.table(...)` call made *outside* the store. The
  context builders have none left: candidate #1 pulled all 17 behind
  `get_shared_activities_for_date`. What remains is two distinct groups, and neither is
  "more of #1":
  - **Context persistence** — `chat_contexts` and `weekly_contexts` reads inside the two
    context managers. These are the context store's *own* storage, not tracker data. If
    they get a home it is a context-store module, not the tracker store.
  - **Endpoint reads** — `api/` modules reaching tables directly (notifications, FCM,
    debug, meal suggestions, meal presets). Separate concerns, separate decisions.
- **`log_daily_metric` use-case** *(emerging term)* — candidate #4. Endpoints repeat
  "upsert-by-date, then remember to refresh chat context", and this use-case would own
  that flow as one atomic move. **Its stated justification does not hold as written** and
  it should be re-grilled before anyone builds it:
  - The claim is that forgetting the refresh is a real bug class. `api/periods.py` does
    have 4 write endpoints and no refresh call at all — and period data reaches the coach's
    safety guardrail via `compute_period_status`.
  - But `chat_service.generate_chat_response` calls `rebuild_context` **unconditionally
    before every reply**, so the coach never reads a stale context. The bug is already
    defended, bluntly, by rebuilding every turn.
  - Which inverts the question. Not "how do we make every write refresh?" but "given the
    read path rebuilds anyway, what are the ~28 refresh calls scattered across the write
    endpoints buying?" The stale-cache exposure that remains is
    `GET /chat/context/{user_id}`, which serves cached context without rebuilding.

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
  dead code into looking live.
- Architecture vocabulary (module, interface, seam, adapter, depth, leverage, locality)
  lives in the design skill, not here. This file names the *domain*; that file names the
  *shapes*.
