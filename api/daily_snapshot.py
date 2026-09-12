# api/daily_snapshot.py
#
# GET /api/health/daily-snapshot/{user_id}/{date} -- the owner's complete day
# in one round-trip. Frozen shape: docs/contracts/daily-snapshot-endpoint.md
# (authoritative copy: nufi_app docs/adr/0003). Design: docs/adr/0004.
#
# This is the OWNER's day: every entry regardless of shared_with_chat. The
# coach's shared subset is get_shared_activities_for_date, a different read.
from datetime import date as date_type
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from services.supabase_service import get_supabase_service
from utils.timezone_utils import get_timezone_offset, get_user_date

router = APIRouter()

# The sections this contract carries. `_activities_for_date` also reads
# `period`; the client's DaySnapshot has no period section, so it is not
# emitted here. Adding it later is additive and needs no change to the store.
CONTRACT_SECTIONS = ('meals', 'water', 'steps', 'sleep', 'exercise', 'weight',
                     'supplements')

# Sections that are a single row: no row for the day means the section is
# missing, and it is omitted. Mirrors the client's _entrySection.
ROW_SECTIONS = ('water', 'steps', 'sleep', 'weight')

# The one value `_read_errors` carries. The store's map holds the raw
# exception text, which for a PostgREST failure is the SQL message, the
# Postgres error code and a hint naming tables and columns, and for an HTTP
# failure the request URL with the project host in it. This route has no
# auth, and the client reads only the *key* -- `Section.error` holds the
# value and nothing renders it -- so the value is an opaque token. The
# missing-vs-error distinction is carried by presence, not by the message.
READ_FAILED = 'read_failed'

# The four the contract names, plus the three /daily-summary already returns
# and MealApi already maps. Additive: dropping them would make migrating off
# /daily-summary a regression for whoever reads fiber.
MEAL_TOTALS = ('calories', 'protein_g', 'carbs_g', 'fat_g', 'fiber_g',
               'sugar_g', 'sodium_mg')


def _number(value: Any) -> float:
    """A row's numeric field as a float, tolerating None and strings.

    PostgREST returns `numeric` columns as strings often enough that summing
    them raw is a real failure mode, and a single bad row must not take out
    the whole section.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def meals_section(meals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Totals for the dashboard, entries for the today report.

    Entries are the raw meal rows, unchanged and including
    `shared_with_chat` -- the contract requires rows to carry it.
    """
    totals = {field: 0.0 for field in MEAL_TOTALS}
    for meal in meals:
        for field in MEAL_TOTALS:
            totals[field] += _number(meal.get(field))

    return {'totals': totals, 'count': len(meals), 'entries': meals}


def exercise_section(exercises: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        'entries': exercises,
        'total_minutes': int(sum(_number(e.get('duration_minutes'))
                                 for e in exercises)),
        'total_calories_burned': sum(_number(e.get('calories_burned'))
                                     for e in exercises),
    }


def supplements_section(status: Dict[str, Any]) -> Dict[str, Any]:
    """The store keys supplements by name; the contract wants a list.

    Sorted by name so the response is stable across requests -- the client
    renders these in order and an unstable one reshuffles the list on every
    refresh.
    """
    items = [{'name': name, 'taken': bool(entry.get('taken'))}
             for name, entry in sorted(status.items())]

    return {
        'items': items,
        'taken_count': sum(1 for item in items if item['taken']),
        'total_count': len(items),
    }


def snapshot_from_day(
    user_id: str, target_date: date_type, day: Dict[str, Any]
) -> Dict[str, Any]:
    """Shape one day of owner activities into the contract's response.

    Pure: no I/O, so the mapping is testable without a database.

    Three states per section, matching the client's Section.ok / .missing /
    .error exactly:

      * present               -> ok
      * absent                -> missing (the user logged nothing)
      * absent, named in
        `_read_errors`        -> error (that tracker's read failed)

    A client that ignores `_read_errors` sees a failed section as an empty one,
    which is how it degrades today; one that reads it can tell a broken tracker
    from a quiet day. Same rule, and the same key, as the store's day reads --
    but not the same value: the store's message is for the server log, and the
    wire carries `READ_FAILED` in its place.

    Roll-up sections (meals, exercise, supplements) are always present when
    their read succeeded, carrying zeros for a day with nothing logged -- "you
    ate nothing today" is an answer, not an absence. Single-row sections are
    omitted when there is no row. This mirrors the client's own fan-out.
    """
    errors = day.get('_read_errors', {})
    snapshot: Dict[str, Any] = {'user_id': user_id, 'date': str(target_date)}

    values = {
        'meals': meals_section(day.get('meals') or []),
        'exercise': exercise_section(day.get('exercise') or []),
        'supplements': supplements_section(day.get('supplements') or {}),
    }
    for key in ROW_SECTIONS:
        values[key] = day.get(key) or None

    for key in CONTRACT_SECTIONS:
        if key in errors:
            continue
        if values[key] is not None:
            snapshot[key] = values[key]

    snapshot['_read_errors'] = {key: READ_FAILED for key in errors
                                if key in CONTRACT_SECTIONS}
    return snapshot


@router.get("/daily-snapshot/{user_id}/{date}")
async def get_daily_snapshot(
    user_id: str,
    date: str,
    tz_offset: int = Depends(get_timezone_offset),
):
    """The owner's complete day for one date, in one round-trip.

    Replaces the client's seven-call parallel fan-out behind
    `DailySnapshot.forDay`. Additive: the per-tracker endpoints stay in place
    while the client migrates.
    """
    try:
        target_date = get_user_date(date, tz_offset)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date '{date}'. Expected YYYY-MM-DD.",
        )

    print(f"📸 Daily snapshot for user {user_id} on {target_date}")

    day = await get_supabase_service().get_owner_activities_for_date(
        user_id, target_date
    )
    return snapshot_from_day(user_id, target_date, day)
