# 9. The store reports failure; it does not return it as data

Date: 2026-09-13
Status: Accepted

## Context

[ADR-0004](0004-daily-snapshot-endpoint.md) made the seven by-date reads propagate
their errors, and PR #15 did the same for `get_exercise_logs`. `CONTEXT.md` recorded
the rest of the class — "41 store methods still swallow a failure into `[]`, `{}`,
`None` or `False`" — as one sweep needing a per-caller inventory first, because some
callers treat the empty value as a legitimate branch.

The inventory, walking the AST for every `except` handler in `services/supabase_service.py`
and every call site of the methods it found, changed the premise in four places.

**It was 42, not 41.** The count came from handlers that *return* an empty value.
`update_preset_usage` returns nothing, so its `except: print(...)` was missed. Same
class; its only caller already wraps it as "non-critical".

**`get_user_by_id` could not simply propagate.** It queried with `.single()`, and
PostgREST answers a single-object request for zero rows with an error (`PGRST116`),
which `supabase-py` raises as `APIError`. So the swallowing handler was not only
hiding outages — it was the mechanism by which "no such user" became `None`. Removing
the handler alone would have turned every genuine 404 into a 500. The method now
indexes the list, as `get_user` and `get_user_by_email` already did (and is now
byte-for-byte the same query as `get_user`; two doors for one question, noted below).

**The "duplicate row" consequences were mostly not duplicates.** `CONTEXT.md` said
`get_supplement_log_by_date → None` reads as "no existing log, create one — the
duplicate-row class ADR-0004 closed for water and steps". Checked against the live
schema: `supplement_logs` has `UNIQUE (user_id, supplement_name, date)`, and
`daily_water`, `daily_steps` and `daily_nutrition` all have `UNIQUE (user_id, date)`.
A failed existence check on those tables turned an *update* into an *insert that
violated the constraint* — a 500 for the user, and the update they asked for not
made — but never a second row. ADR-0004's water/steps claim had the same gap. The
one table without such a guard is `period_entries`, and there the duplicate is real:
`POST /period` looks for an open period and creates one when the read says there is
none, so a failed read opened a second period beside the first.

**Three callers were doing something worse than returning empty.** Each is a
read-then-write where the read's empty value drives the write:

| site | on a failed read it | now |
|---|---|---|
| `api/meals.py` `recalculate_daily_nutrition` (after a meal delete) | summed `[]` to zero and **wrote the zeros** over the day's `daily_nutrition` totals | skips; the helper's own `except` catches the raise, as it was written to |
| `api/weight.py` `delete_weight_entry` | read `get_latest_weight → None` as "no entries remain" and **reverted the profile weight to the starting weight** with entries still in the table | 500 after the delete; the profile write does not happen |
| `api/supplements.py` `save_supplement_preferences` | ignored `clear_supplement_preferences → False` and inserted the new set, leaving the old preferences **active beside the new ones** | 500 before any insert |

And two that lie about who the user is: `get_user_by_id → None` answers a database
outage with 404 "User not found" on `GET /users/{id}` and eleven other handlers, and
`get_user_by_email → None` answers it with 401 "Invalid credentials" on both login
routes — a user who cannot log in during an outage is told their password is wrong.

**The ten `delete_*` never said "not found".** Each returned `True` whenever the
query executed, whether or not a row matched, and `False` only on an exception. So the
endpoints' `else: "Step entry not found"` / `"Failed to delete"` branches were
reachable only on a database failure, and a delete of a row that does not exist has
always answered "deleted successfully". This sweep does not change that; see below.

**The callers.** Ninety-one call sites across `api/`, `services/` and the store itself.
Every one was read. What the table records is how each caller treated the empty
value, because that is what decides whether a raise is safe there.

| method | callers | empty value meant | after |
|---|---|---|---|
| `get_user_by_id` | `api/users.py` ×2, `api/sharing.py` ×2, `api/auth.py` ×3, `api/meals.py` ×4, `api/meal_suggestions.py` ×2, `api/frameworks.py`, `api/periods.py`, `api/weight.py`; `chat_context_manager.create_initial_context`, `chat_service.get_user_context`; in-store `delete_user_account`, `initialize_starting_weight_for_user` | not found → 404 / `success: false` (12); `if user:` skip (periods, meal_suggestions quick); raise "User not found" (context manager); `return {}` (chat_service, inside its own `except → _get_empty_context`) | not found is still `None` (no `.single()`); a failure is a 500 via `internal_error`, or the caller's own degradation where it has one |
| `get_user_by_email` | `api/users.py` ×2, `api/auth.py` ×3 | "email free" on register (`users.email` is `UNIQUE`, so a failure here met the constraint at insert); "invalid credentials" on login | 500 on register; 500 on login instead of 401 |
| `get_user` | `api/steps.py` ×2, `chat_context_manager.rebuild_context`, `weekly_context_manager.create_weekly_context` | default step goal 10000 (steps); raise (both managers) | steps: 500 instead of a default goal on an outage — the entries read in the same handler already did; managers: unchanged |
| `get_meal_by_id`, `get_sleep_entry_by_id`, `get_exercise_by_id`, `get_weight_entry_by_id` | the four by-id delete endpoints | not found → 404 / `success: false` | not found unchanged; failure is 500 |
| `delete_meal`, `delete_water_entry`, `delete_step_entry_by_date`, `delete_weight_entry`, `delete_sleep_entry`, `delete_supplement_preference`, `delete_exercise_log`, `delete_period_entry`, `clear_chat_messages` | their endpoints, all `if success:` | `False` → 200 `success: false` "not found" / "Failed to delete" (steps, periods, supplement pref, water, sleep, weight, chat) or 500 (meals, exercise) | 500 with the generic detail; the `else` branches are unreachable (`True` is the only return) |
| `get_daily_nutrition` | `api/meal_suggestions.py` ×2, `api/meals.py` ×4 | "no totals yet" → zeros (energy balance, remaining macros, suggestions); "no row, create one" (`update_daily_nutrition`, `recalculate_daily_nutrition` — both inside the helpers' own `except`) | endpoints 500; helpers skip |
| `get_user_meal_presets`, `get_recent_unique_meals`, `get_user_meals` | `api/meals.py` | empty list served as `success: true` | 500 |
| `update_preset_usage` | `api/meals.py` use-preset, inside its own "non-critical" `try` | nothing | unchanged at the caller |
| `search_cached_meal` | `meal_analysis_service.analyze_meal_with_cache` (from `POST /meals/analyze`); `meal_parser_service.parse_and_analyze_meal_with_cache` (**no caller**) | cache miss → analyse with the LLM, then store — and the store step fails on the same outage, after the LLM call was paid for | the analyse endpoint fails before the LLM call |
| `get_user_meals_by_date` | `api/daily_summary.py`, `api/meals.py` ×2 (one is `recalculate_daily_nutrition`) | empty day | 500; the recalculation skips instead of zeroing |
| `get_water_history`, `get_step_history`, `get_steps_in_range`, `get_weight_history`, `get_sleep_history`, `get_supplement_history`, `get_period_history` | their history/stats endpoints | empty history → zeroed stats with `success: true` | 500 |
| `get_latest_weight` | `GET /weight/{id}/latest`; `delete_weight_entry` | `None` → "no weight yet"; **"no entries remain"** (the profile revert above) | 500; no revert |
| `update_user_weight` | `PATCH /user/{id}/weight` (`if success:`); `delete_weight_entry` ×2 (return ignored, after the delete) | `False` → 500 "Failed to update"; silently stale profile | 500 in both; the delete has already happened, and the endpoint's catch-all reports the failure |
| `initialize_starting_weight_for_user` | `POST /weight` after the entry is stored; `GET /users/{id}` (auth) as a lazy backfill | return value ignored by both | **both callers wrap it.** Weight has no upsert — every save is a new row — so a 500 after the row is stored invites the retry that writes a second one. The profile read logs and serves the row it has. These are the two places in this change where a caller degrades on purpose, and each says why. Every existing user has `starting_weight` set (checked), so the method now runs only for a new user's first save. |
| `get_supplement_preferences` | `GET /supplements/preferences/{id}` | empty | 500 |
| `clear_supplement_preferences` | `POST /supplements/preferences`, return ignored | old set stays active beside the new one | 500 before the inserts |
| `get_supplement_log_by_date` | `POST /supplements/log` | "no log, create" → unique violation → 500 anyway | 500 before the write |
| `get_current_period` | `POST /period`; `GET /period/{id}/current` | "no open period, create one" (**real duplicate**); `None` served as no period | 500, nothing written; 500 |
| `save_chat_message` ×4, `get_recent_chat_context` | `chat_service.generate_chat_response`, each inside its own `try: … except: print` | the caller's `except` was dead code — the method could not raise | the caller's `except` is live; the reply still goes out, unsaved, as those handlers were written to allow |
| `get_or_create_daily_session` | `save_chat_message` | "continue without `session_id`" | the message save fails with the session lookup; caught by `chat_service` as above. (It still keys the session by the server date — a `chat_sessions` grouping nothing in the client reads; noted, not changed.) |
| `get_chat_messages` ×2, `get_recent_chat_messages` | `api/chat.py` history/messages routes, each with `except → {'success': False, 'messages': []}` | the `except` was dead; an outage was `success: true, messages: []` | `success: false`, which is what the handler was written to say. The client's `getChatHistory` reads `success` and returns `[]` either way. |

`weekly_context_manager` degrades per-read on purpose (ADR-0004) and touches none of
these beyond `get_user`, where it already raised on `None`. `api/debug.py` and the
notification modules read tables directly and are unaffected.

## Decision

1. **Every store method propagates.** The 42 `try/except`s come out. The store's three
   remaining swallowing handlers are the ones that turn a failure into a *report* a
   caller reads — `delete_user_account`'s per-table map, `health_check`'s `unhealthy`
   status, and `_activities_for_date`'s `_read_errors` — and
   `tests/test_store_reports_failure.py` names them as the allowlist, so the next
   swallowing handler fails the suite.
2. **`get_user_by_id` drops `.single()`** and indexes the list. "Not found" is `None`;
   a failed query raises. Pinned, including that the query never asks for a single
   object.
3. **The callers are left as they are, except two.** Every `api/` site sits inside a
   handler that ends in `raise internal_error(e)` (or answers `success: false` by
   design), and every `services/` site either raises on the empty value already or
   catches for its own reasons. The two exceptions wrap `initialize_starting_weight_for_user`
   at the caller, with the reason in a comment: the write it follows has already
   happened. That is the caller deciding, which is where the decision belongs — the
   store reports, the caller chooses.
4. **The `delete_*` return shape is not changed.** `True` regardless of rows matched
   is now the only return, and the ten endpoints' `else` branches are unreachable.
   The honest value is `bool(response.data)` (PostgREST returns the deleted rows;
   `delete_user_account` already counts them), and with it the three endpoints
   that have no get-first — steps, period, supplement preference — would answer
   "not found" for a row that is not there, instead of "deleted". That changes a 200
   body the client reads; its own change.
5. **Tested at the leaves and at the sharp callers.** The leaf tests drive each of
   the 42 methods over a client that fails at `execute()` and were run against the
   old store: 46 failures. The caller tests (`recalculate_daily_nutrition` skips,
   `POST /period` writes nothing, a delete is a 500, a weight save survives its
   bookkeeping) inject a raising store, so they pin what the caller does *given* a
   raise; on the old code they pass, because the old store never raised. Together
   they cover the path end to end; neither alone does, which is the caveat
   `CONTEXT.md` records for compositions over stubs.

## Consequences

- **A behaviour change on live endpoints, taken deliberately**, in the same spirit as
  ADR-0004: a store failure is a 500 with the generic detail where it was a 200 with
  an empty answer, a 404 "User not found", a 401 "Invalid credentials", or a "not
  found" on a delete. The client displays `detail` as text with a fallback and reads
  `success` as a boolean; nothing parses the messages that change.
- Three write paths stop acting on a failed read: the nutrition recalculation no
  longer writes zeros, the weight delete no longer reverts the profile, and the
  supplement preferences no longer keep the old set active beside the new one. One
  duplicate-row path closes (`POST /period`). Four "duplicate" paths named in
  `CONTEXT.md` and ADR-0004 were never duplicates — the schema's unique constraints
  caught them as failed inserts — and both documents now say so.
- `analyze_meal_with_cache` fails before the LLM call on an outage rather than after.
- Net **−170 lines** in the store (531 added, 701 deleted, most of it dedent); 42
  print-and-swallow sites replaced by the traceback `internal_error` already logs.
  `tests/test_store_reports_failure.py` adds 90 tests (256 → 346).
- **Corrections to earlier records**, made where the wrong claim lives:
  `CONTEXT.md`'s "41" and its duplicate-row sentence; ADR-0004's consequence about
  `api/water.py:30` / `api/steps.py:30` writing a duplicate row. `daily_water` and
  `daily_steps` carry `UNIQUE (user_id, date)`; a swallowed read there produced a
  failed insert, not a second row. The fix was right; the stated harm was not.
- **Found and left, each its own change:**
  - `get_user` and `get_user_by_id` are now the same query under two names, with 4
    and 20 callers. The ADR-0003 smell; fold when convenient.
  - The ten `delete_*` return a constant (decision 4).
  - `DELETE /chat/history/{user_id}` calls `supabase_service.clear_user_conversation`,
    which does not exist — an `AttributeError` caught into `success: false` on
    every call. The client's `ChatApi.clearChatHistory`, `clearChatMessages` and
    `getChatMessages` have zero callers in `lib/` (the wrapper check: `ChatService`
    wraps none of them); only `test/chat_test.dart` hits the URLs. "Clear Chat" in
    the client clears the local transcript and cache and never calls the backend, so
    the transcript reappears on the next open. Dead on both sides; deletion pass.
  - `parse_and_analyze_meal_with_cache` has no caller; `main.py` only instantiates
    the service to warm it.
  - `get_or_create_daily_session` groups chat sessions by the server date. Nothing
    reads `chat_sessions` in the client (`GET /chat/sessions` has no caller); it is
    a server-day read ADR-0006 did not list.
