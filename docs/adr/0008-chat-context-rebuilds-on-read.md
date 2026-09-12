# 8. `GET /chat/context/{user_id}` rebuilds on read; the incremental refresh is deleted

Date: 2026-09-12
Status: Accepted

## Context

Candidate #4 (`log_daily_metric`) was re-grilled on 2026-09-07 and re-scoped to one
question: *should the cached-context endpoint rebuild, or declare its staleness?* The
answer decides whether the incremental refresh — `update_context_activity`, called
from every tracker write endpoint — is load-bearing or dead. The coach never reads the
cache (it rebuilds before every reply, ADR-0006), so the refresh existed for exactly
one reader: `GET /api/health/chat/context/{user_id}`.

The inventory of that reader:

**One live consumer.** `ChatApi.getChatContext` is called from three places.
`chat_context_debug_page` rebuilds explicitly before reading, so the cache's freshness
is irrelevant there. `ChatService.getUserContext` feeds `chat_page._userContext`, which
has two uses: the **welcome banner** (rendered only when the transcript is empty —
first chat, or after clearing history) and the `context:` argument to `sendMessage`,
which that method documents as **ignored**. The three summary helpers in
`chat_service.dart` that also read it (`generateContextSummary`, `hasUserData`,
`getSmartSuggestions`) have no callers. So the cache has one reader, the banner, and it
wants today's numbers.

**That reader already races a rebuild.** `chat_page.initState` fires `_loadChatContext`
(the cached read) and `checkAndResetDailyContext → rebuildContextInBackground` (a full
rebuild) in parallel. The banner shows whichever the cache held when the read landed.

**The cache was written by two mechanisms that disagreed.** The rebuild reads
shared-only through the store and keys by the user's day; the incremental merge was
fed the write payload (fixed to the stored row in ADR-0005, then bypassed by the client
echo deleted in PR #12) and, from that echo, keyed by the server day. Two writers, two
answers, one row.

**The refresh had a cost on every write.** Each of the 15 call sites (13
`update_context_activity`, 2 `remove_from_context`) read the row and wrote it back —
two round-trips inside the write endpoint's latency, for every glass of water logged.

**`getCachedChatContext` (`GET /chat/context/cached/{id}`) has zero callers** — a
further dead client method, noted for the next deletion pass.

## Decision

1. **The endpoint rebuilds.** `GET /chat/context/{user_id}?date=` calls
   `rebuild_context(user_id, date)` and returns the result. The one reader gets an
   authoritative answer, filtered by `shared_with_chat` through the store's shared-only
   read, for the day it asked about.
2. **It declares staleness only when it must.** If the rebuild raises, the stored row is
   served with an additive `stale: true`. If that fails too, 500 — not an empty day. A
   caller can now tell a fresh answer from a cached one; before, it could not tell
   either from a day with nothing logged.
3. **The incremental refresh is deleted**: `update_context_activity`,
   `remove_from_context`, the 15 call sites across seven endpoint modules, and the two
   test files that pinned their behaviour (`test_water_context_refresh.py`,
   `test_context_refresh_respects_sharing.py`). 226 lines out of the context manager,
   149 out of `api/`. The guard ADR-0005 added is deleted with the method it guarded;
   the *finding* it recorded — the insert trigger, and that only the stored row knows a
   row's flag — stands and stays in `CONTEXT.md`.
4. **`api/sharing.py` keeps its rebuild.** A sharing toggle changes what the coach may
   see and should take effect before the next chat open, which does not go through this
   endpoint. `POST /context/rebuild/{id}` and `/rebuild-context` stay for the same
   reason; the client's `rebuildContextInBackground` calls are now redundant with the
   read but harmless, and are the client's to remove.
5. **`update_daily_nutrition` and `recalculate_daily_nutrition` are untouched.** They
   maintain the `daily_nutrition` table, a different cache with different readers
   (`/daily-summary`, the nutrition trend). Same smell, separate inventory.

## Consequences

- Every tracker write is two round-trips faster. The chat page's first open with an
  empty transcript is one rebuild slower (~10 sequential reads) than a cache hit, on a
  path that already fired the same rebuild in parallel.
- **`log_daily_metric` is closed.** There is no "remember to refresh" step left for a
  use-case to own. The premise was void on 2026-09-07; the mechanism it described is now
  gone.
- `chat_contexts` rows are written only by `rebuild_context`, `generate_fresh_context`
  and `create_initial_context`. `deduplicate_context` stays on the read path for rows
  the old merge left behind; once no such rows exist it is a deletion candidate.
- `tests/test_chat_context_rebuilds_on_read.py` pins the endpoint's three outcomes,
  the date resolution, and — by source inspection — that no write endpoint module
  mentions the context manager and the two methods do not exist. 231 → 238.
- This branch is built on the integration of PRs #8–#12 and supersedes #8's guard.
  Merge order: #8, #9, #10, #11, #12, then this. If #8 is merged, its mechanism lives
  for one merge and is then removed here; if it is closed unmerged, ADR-0005's text
  should still land, and does — it is in this branch.
- Two readers of `GET /chat/context` remain worth a look from the client side: the
  parallel `rebuildContextInBackground` on chat open is now a duplicate rebuild, and
  `getCachedChatContext` is dead.
