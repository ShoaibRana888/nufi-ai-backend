# 6. The coach reads the user's day, and the day is required

Date: 2026-09-12
Status: Accepted

## Context

`CONTEXT.md` recorded, after the doubled-prefix fix made the daily reset reachable,
that "the coach's day is still the server's day":
`chat_service.generate_chat_response` rebuilt the context for
`datetime.now().date()` and `get_enhanced_context` read it back through the dateless
`get_or_create_context`, which resolved "today" the same way — while the context
endpoints and the daily reset had moved to `get_timezone_offset`. It was filed as
**inert**: the coach rebuilds from source tables before every reply, so it never reads
the reset's row.

The inventory before this fix found the premise wrong in the direction that matters.

**The server clock is UTC**, confirmed from the data rather than assumed:
`chat_contexts.context_metadata.created_at` (written with `datetime.now()`) and the
row's DB-side `created_at` (`now()`) agree to the tenth of a second.

**Every tracker write is keyed by the user's day.** Meals compute `user_date` from
the offset; water, steps, sleep and supplements go through `get_user_date`, which
returns the client's local date. So the coach's rebuild read a *different day's rows*
from the ones being written, for `|offset|` hours of every day. The rebuild was not a
defence here; it rebuilt the wrong day, faithfully, on every reply.

**And that window is where the users are.** 31 of the 79 user chat messages ever sent
(39%) landed between 19:00 and 24:00 UTC — 00:00 to 05:00 for a UTC+5 user, which the
data suggests these are. Each of those chats presented the previous user-day as
"today" and could not see anything logged after local midnight. The last message in
the table was at 20:07 UTC.

**The disagreement was internal to `chat_service` too**, not just between it and the
endpoints: the rebuild spelled the server day as `_dt.now().date()` and the read
spelled it as "no argument". Two spellings of one wrong value.

**One caller.** `generate_chat_response` is called only by `POST /chat`, whose handler
already takes `tz_offset` and uses it for the response timestamp — and nothing else.
The three context getters are called only from inside `chat_service`. Threading a
value through changes no other caller.

**Nothing else on the chat path reaches the client with a server day.** The client
always sends `date` to `/context/{id}`, `/context/cached/{id}` and `/context/rebuild/{id}`.
`/context/fix-today`, `/rebuild-context` and `/context/update` have no client caller.
The one exception was the `except` fallback in `GET /context/{user_id}`, which
regenerated for `datetime.now().date()` on a failed cache read.

## Decision

1. **`generate_chat_response(user_id, message, today: date)`** — the endpoint resolves
   `today = get_user_today(tz_offset)` and passes the value. The service speaks in
   dates already (`rebuild_context(user_id, target_date)`); it should not learn about
   HTTP headers to fix this.
2. **One value, both halves.** `today` goes to `rebuild_context`, to
   `get_comprehensive_context` → `get_enhanced_context` → `get_or_create_context`, to
   the `get_user_context` fallback (and its yesterday-for-sleep read), and to the weekly
   manager (`get_or_create_weekly_context(user_id, today)`,
   `get_recent_weeks_context(..., end_date=today)`), so "this week" is the week
   containing the user's today.
3. **Required, not defaulted, all the way down.** `today` has no default on the four
   `chat_service` methods; `get_or_create_context` and `ensure_daily_context` lose
   their `None` defaults and the dateless branch. Their only dateless caller was the
   coach's read. A default is exactly where the server day creeps back in, and
   `tests/test_coach_day_is_the_users_day.py` pins every signature and greps the
   sources for `now().date()`.
4. **`GET /context/{user_id}` resolves its date before the `try`** and regenerates for
   that date on a failed read. A malformed `date` is now a 400 rather than a fresh
   context for the server's today with `success: true`.
5. **`GET /context/cached/{user_id}`'s fallback passes its arguments through.** It
   called `get_user_chat_context(user_id)` directly — not through FastAPI — so
   `tz_offset` arrived as the bare `Depends` marker and `get_user_today` raised
   `TypeError` inside the handler's `try`. The server-day `except` branch then
   caught it, which is why it appeared to work. With that branch gone the crash would
   have surfaced; the call now hands over `date` and `tz_offset`.

## Consequences

- A UTC+5 user chatting at 01:00 now gets a context for their day, with the breakfast
  they just logged in it, instead of yesterday's dinner presented as today.
- **A live behaviour change for a real share of traffic**, not a latent one — 39% of
  historical chats fell in the affected window. Worth watching the first evening of
  chats after deploy.
- The weekly window moves with the user's day. This ADR first said the current-week
  check (`week_end >= datetime.now().date()`) could stay on the server clock because
  "a few hours' difference on a TTL decision is immaterial". **Wrong, caught in
  review:** it is not a TTL decision. A week judged *completed* is served from cache
  and never revalidated, so a UTC-8 user still on Sunday evening when UTC reaches
  Monday would have the rest of that Sunday dropped from the week — permanently.
  `get_or_create_weekly_context` now takes `today` and judges currency on it; the
  chat path passes the user's day to it and through `get_recent_weeks_context`.
  Other callers (`api/weekly_context.py`, `api/debug.py`) default to the server date
  and carry the same defect on their own routes — the "its own change" already noted.
- `tests/test_context_daily_reset_timezone.py` had pinned `ensure_daily_context`'s
  server-date default as "unchanged for the internal caller". That pin is retired
  with the caller; the inverse — the date is required — is pinned in the new file.
- **Still on the server clock, deliberately, because the client never reaches them
  without a date:** the `date`-absent fallbacks in `POST /context/rebuild/{user_id}`
  and `POST /rebuild-context`, `POST /context/fix-today/{user_id}` (uncalled), and
  `DELETE /context/cleanup`'s cutoff (a retention window; a day either way is fine).
  `GET /weekly/context/{user_id}` in `api/weekly_context.py` is the same shape and
  the same question, and is its own change.
- Third time in this track that "inert" or "dormant" was wrong on inspection
  (`_read_errors` in ADR-0004, the water refresh in PR #7, this). A path that is
  *bounded* — the coach only sees the leaked value if the rebuild fails — is not the
  same as a path that is *inert*; check what the rebuild actually reads.
