# 7. `_read_errors` carries a token, not a message

Date: 2026-09-12
Status: Accepted

## Context

`GET /api/health/daily-snapshot/{user_id}/{date}` names each failed section in
`_read_errors` ([ADR-0004](0004-daily-snapshot-endpoint.md), decision 5). The value it
carried was the store's `str(e)` — whatever the by-date read raised. For a PostgREST
failure that string is the SQL message, the Postgres error code and a hint that names
tables and columns (`column daily_water.total_glasses does not exist … Perhaps you
meant "daily_water.total_ml"`); for an HTTP failure it is the request URL with the
Supabase project host in it. The route has no auth.

The inventory before changing it turned up three things.

**Nothing on the API has auth.** `api/auth.py` serves login; no route declares a
bearer dependency and `main.py` adds only CORS. "Unauthenticated route" describes every
route here, not this one.

**And 111 other sites put `str(e)` in a response body.** 96 `HTTPException(500,
detail=str(e))`, 13 `{'error': str(e)}`, 2 f-strings. Every one of them carries the same
strings on a failure. `_read_errors` is one door of 112 for the same information, so
"closes a leak" overstates what this change does on its own. What makes it worth doing
separately is that it is different in kind: it is on the **200 path**, it is a **contract
field** the client parses, and its value shape is a design decision recorded in two
repos. The 500 `detail`s are ad-hoc and are a different fix (below).

**The client never reads the value.** `DailySnapshot._fromDocument` does
`Section<T>.error(errors[key])` — the value is stored on `Section.error` and
`today_report_screen`, the only consumer, reads `.value` and never `.error` or
`.status`. The client's tests used sample messages (`'sleep_entries exploded'`) and one
asserted `contains('exploded')` on the stored error, which is the only place the text
was ever inspected. So the message had no reader; only the **key's presence** carried
meaning, exactly as the contract's three-state rule says.

## Decision

1. **The value is the opaque token `"read_failed"`**, identical for every failed
   section. Presence carries the missing-vs-error distinction; the message never did.
   A single token rather than a coarse classification (`unavailable` / `invalid`)
   because the store cannot classify reliably and the client would not use it.
2. **The mapping happens in `snapshot_from_day`**, the endpoint's pure shaping, not in
   the store. `_activities_for_date` keeps recording the real message: it is the
   server-side diagnostic, already printed at the point of failure, and the context
   builders and the weekly manager are internal readers. The store reports; the
   endpoint decides what crosses the wire.
3. **Both contract copies are amended**, with the example changed and a dated note
   saying what it used to be and why. `nufi_app` ADR-0003 (authoritative) and the
   mirror here. The client's four fixture literals and the one `contains('exploded')`
   assertion move to the token, so `test/daily_snapshot_test.dart` keeps the property
   ADR-0006 there gave it — a document in the shape the endpoint actually returns.
4. **Tested at the boundary.** Beyond the shaping test, a route test drives the real
   handler with a store whose `_read_errors` carries a PostgREST-shaped string and
   asserts on `response.text` that the error code, the relation name and the phrase
   do not appear. The shaped dict is not the boundary; the bytes are.

## Consequences

- A section that fails to read is reported as `{"<section>": "read_failed"}`. The
  client's behaviour is unchanged — it never looked at the value.
- **The 111 `str(e)` sites remain**, and this ADR is where that is recorded rather
  than left implicit. They are one change, not 111: either a mass edit to a generic
  `detail` with the exception logged server-side, or a response middleware that
  rewrites 5xx bodies. The former is more honest about what each handler does; the
  latter cannot be forgotten by the next handler. Neither is a contract change with
  the client — nothing in `nufi_app` parses a 500 `detail` (worth confirming before
  that work, as the practice here goes). Its own inventory, its own decision.
- **No auth on the API** is likewise recorded, not fixed. It is a product decision
  about the client's session model, not a backend patch.
- `tests/test_daily_snapshot_endpoint.py` and `tests/test_daily_snapshot_route.py`
  gain one test each; one existing assertion changes from the message to the token.
