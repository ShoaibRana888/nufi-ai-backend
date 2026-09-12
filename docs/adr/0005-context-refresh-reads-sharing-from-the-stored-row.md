# 5. The incremental context refresh reads `shared_with_chat` from the stored row

Date: 2026-09-12
Status: Accepted

## Context

`chat_context_manager.update_context_activity` is the shortcut the write endpoints
take after logging an entry: merge the new value into the day's cached
`chat_contexts` row rather than rebuilding it. It merged its payload blind. Logging
against a row the user had hidden with `PATCH /sharing/{user_id}` wrote the hidden
value straight back, reversing the rebuild that endpoint performs. The exposure is
bounded — `generate_chat_response` rebuilds from source tables before every reply,
so the coach only sees the leaked value if that rebuild fails and it falls back to
the cached row — but `GET /chat/context/{user_id}` serves the cached row directly.

[ADR-0004](0004-daily-snapshot-endpoint.md)'s follow-up work guarded `api/water.py`
by reading the flag off the existing row before the write, and recorded the other
six trackers as "same hole, six more call sites, its own fix". This is that fix, and
the inventory before it changed where the guard has to look.

**A row can be born hidden.** `users.chat_sharing_defaults` — the per-tracker map
that `PUT /sharing/{user_id}/defaults` writes — is not applied by this codebase. It is
applied by a `BEFORE INSERT` trigger, `trg_share_default`, on all seven tracker tables
(`apply_chat_sharing_default` in Postgres, verified against the live schema). A user
who has set `weight: false` gets every new weight row inserted with
`shared_with_chat = false`, and nothing in the repo mentions the trigger. Two
consequences for the guard:

- **The pre-write row cannot answer.** Water's guard read `existing_entry`, which
  does not exist on the create path — so the day's *first* glass, born hidden by the
  trigger, refreshed the context anyway. The precedent was incomplete on its own
  tracker.
- **The always-create trackers leak too.** Weight, exercise and the three meal paths
  never have an existing row, so "upsert against a hidden row" did not describe them;
  the trigger does. For a user with a default set, *every* write on that tracker
  pushed the hidden value into the cache, with no `PATCH` involved.

**The write payload cannot answer either.** It is built before the row exists and
never carries the flag; the request schemas do not accept one, and the trigger
overrides it on insert regardless.

**Only the stored row knows.** Every `create_*` / `update_*` in the store returns
`response.data[0]` — the row as Postgres wrote it, trigger applied. Meals and
exercise already handed that row to the refresh; water, steps, sleep, supplements and
weight handed the write dict.

Nobody has hit either door in production yet: zero rows carry `shared_with_chat =
false` and zero users have a default set. The mechanism is live on both sides
(client toggles, DB trigger); the data just has not arrived.

## Decision

1. **The guard lives in `update_context_activity`, once.** An explicit
   `shared_with_chat: False` on the payload returns `{'success': True, 'skipped':
   'hidden_from_chat'}` before any read. Seven endpoint-level guards would be seven
   places to forget, and water's showed that a local guard reads whatever is locally
   convenient rather than what is correct.
2. **The payload contract is: the stored row.** `data` is what the store returned
   after the write, never the dict the endpoint built. Water, steps, sleep,
   supplements and weight change to pass it; meals and exercise already did. Water's
   endpoint-level guard is deleted rather than kept alongside — two guards with
   different sources of truth is how the create-path gap went unnoticed.
3. **Only an explicit `False` hides.** The delete paths pass a reset (`{'steps': 0}`,
   `{'weight': None}`) with no flag, and a reset is the shared view's value whether
   the deleted row was hidden or not. A missing column is not a no.
4. **Test through both layers, not at the seam.** `tests/test_context_refresh_respects_sharing.py`
   drives each write endpoint through `TestClient` with the store faked to return a
   hidden row and the *real* `ChatContextManager` over a fake Supabase client, then
   asserts `chat_contexts` was not written. Faking the context manager at the endpoint
   — the precedent in `tests/test_water_context_refresh.py` — would have proved that
   the endpoint called it, not that the value stayed out. Verified to fail 11 ways on
   the old code, and 9 ways with the guard alone, which is exactly the five endpoints
   that passed write dicts (exercise passes with the guard alone).

## Consequences

- The six unguarded call sites are closed, and water's create path with them. The
  five upsert/create endpoints change what they pass and nothing about what they
  return; the response bodies are pinned.
- `POST /chat/context/update/{user_id}` reads `result.get('version')` now, since a
  skipped refresh has no version. *Corrected the same day:* this ADR first recorded
  that endpoint's client method, `ChatApi.updateChatContext`, as having zero callers.
  The grep missed the in-file wrapper `syncContext`, which nine tracker Apis call after
  every write. So the endpoint was **live**, and it bypasses this very guard: the client
  sends its own payload, with its own copy of `shared_with_chat` (or none), not the
  stored row. Both sides are deleted in the follow-up
  (`chore/delete-dead-context-endpoints` here, `chore/delete-dead-api-methods` in
  `nufi_app`); every write it echoed is already refreshed by the endpoint that stored
  the row. Until that merges, the guard here is complete for the backend's own
  refreshes and incomplete for the client's echo.
- **The trigger is now recorded** in `CONTEXT.md`. It is the kind of fact that hides
  well: the backend stores the defaults, reads them back for the settings screen,
  and never applies them, so a reader of this repo concludes they are inert. They are
  not. Any future write path that bypasses the store's returned row — a bulk insert,
  a client-side default — meets the same trap.
- The full rebuild path was already correct (it reads through
  `get_shared_activities_for_date`, which is shared-only by construction, ADR-0002),
  and is unchanged.
- **Still open**, and unchanged by this: whether `GET /chat/context/{user_id}` should
  rebuild rather than serve the cache — the re-scoped candidate #4 question in
  `CONTEXT.md`. This fix makes the cache correct for one more input; it does not make
  the cache fresh.
