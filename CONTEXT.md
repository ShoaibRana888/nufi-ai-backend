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
- **Shared with chat** — a per-entry privacy flag (`shared_with_chat`). The store exposes
  it as a `shared_only: bool` parameter on the by-date reads
  (`get_meals_by_date(..., shared_only=True)`, `get_water_by_date`, `get_steps_by_date`, …).
  Entries not shared are excluded from chat context.
- **Shared activities for a date** *(emerging term)* — the set of a user's shared entries
  across all trackers on one date. It has no single read yet: the context builders
  re-derive it with ~70 raw `.client.table(...)` calls across 15 files outside the store.
  Candidate #1 gives it one home: `supabase_service.get_shared_activities_for_date(user_id, date)`.
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

- **The store** — `services/supabase_service.py` (1,828 lines, ~70 methods). The single
  module that should own table access. Its interface is currently nearly as wide as its
  implementation: each tracker repeats the same CRUD family (create / update /
  get_by_date / get_by_date+shared / history / range / delete). Candidate #2 collapses
  this into a **daily-metric store** keyed by a metric descriptor.
- **Leaked read** — a raw `.client.table(...)` call made *outside* the store (context
  builders and several endpoints). These are what candidate #1 pulls back behind the
  store's interface.
- **`log_daily_metric` use-case** *(emerging term)* — candidate #4. Endpoints currently
  repeat "upsert-by-date, then remember to refresh chat context"; forgetting the refresh
  is a real bug class. This use-case owns that flow as one atomic move.

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
