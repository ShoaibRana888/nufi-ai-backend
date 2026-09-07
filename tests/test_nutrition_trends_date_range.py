"""The nutrition-trend endpoint's exercise date range.

`get_nutrition_trends` used to filter exercise with
`.lte('exercise_date', str(end_date))`. `exercise_logs.exercise_date` is
`timestamp with time zone`, so that compares against midnight of the last day
and dropped every workout logged during it -- which is most of them, since
`api/exercise.py` falls back to `get_user_now()` (a datetime) whenever the
client omits the field.

Unlike `FakeClient` in test_daily_activities_characterization.py, which ignores
filters on purpose, this fake *applies* them. A filter bug is invisible to a
fake that does not filter.

Comparisons are lexicographic on the stored string. For ISO-8601 values that
matches Postgres ordering closely enough to reproduce both the bug and the fix:
'2026-09-06T14:30:00' sorts after '2026-09-06' and before '2026-09-07', exactly
as the timestamps do.
"""
import asyncio
from datetime import date, timedelta

import pytest

from api import meals as meals_module

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)

# A workout logged at 14:30 today -- the shape api/exercise.py writes when the
# client sends no exercise_date -- and one at midnight yesterday.
EXERCISE_ROWS = [
    {'exercise_date': f'{YESTERDAY}T08:00:00+00:00', 'calories_burned': 120},
    {'exercise_date': f'{TODAY}T14:30:00+00:00', 'calories_burned': 350},
]

NUTRITION_ROWS = [
    {'date': str(YESTERDAY), 'calories_consumed': 1800, 'protein_g': 90,
     'carbs_g': 200, 'fat_g': 60, 'fiber_g': 20, 'meals_logged': 3},
    {'date': str(TODAY), 'calories_consumed': 2000, 'protein_g': 100,
     'carbs_g': 220, 'fat_g': 70, 'fiber_g': 25, 'meals_logged': 3},
]


def run(coro):
    return asyncio.run(coro)


class _FilteringQuery:
    """Applies eq/gte/lte/lt so a wrong bound actually changes the result."""

    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        if column == 'user_id':          # fixtures carry no user_id
            return self
        self._rows = [r for r in self._rows if r.get(column) == value]
        return self

    def gte(self, column, value):
        self._rows = [r for r in self._rows if str(r.get(column, '')) >= str(value)]
        return self

    def lte(self, column, value):
        self._rows = [r for r in self._rows if str(r.get(column, '')) <= str(value)]
        return self

    def lt(self, column, value):
        self._rows = [r for r in self._rows if str(r.get(column, '')) < str(value)]
        return self

    def order(self, column, desc=False):
        self._rows.sort(key=lambda r: str(r.get(column, '')), reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return type('Response', (), {'data': list(self._rows)})()


class _FakeClient:
    TABLES = {'exercise_logs': EXERCISE_ROWS, 'daily_nutrition': NUTRITION_ROWS}

    def table(self, name):
        return _FilteringQuery(self.TABLES.get(name, []))


class _FakeStore:
    def __init__(self):
        self.client = _FakeClient()

    async def get_user_by_id(self, user_id):
        return {'id': user_id, 'tdee': 2200}


@pytest.fixture
def trends(monkeypatch):
    monkeypatch.setattr(meals_module, 'get_supabase_service', lambda: _FakeStore())

    def call(days=7):
        return run(meals_module.get_nutrition_trends(
            'u1', days=days, tz_offset=0))
    return call


def _day(result, when):
    return next(d for d in result['trend_data'] if d['date'] == str(when))


def test_todays_exercise_is_counted(trends):
    """The regression. A workout logged at 14:30 today must appear in today's
    bucket; the old `.lte(end_date)` bound stopped at midnight and lost it."""
    today = _day(trends(), TODAY)

    assert today['calories_burned'] == 350


def test_earlier_days_still_counted(trends):
    """The fix must not have traded the last day for the first."""
    assert _day(trends(), YESTERDAY)['calories_burned'] == 120


def test_net_calories_uses_the_full_days_exercise(trends):
    """The user-visible symptom: net calories were overstated for the last day
    of every trend response."""
    today = _day(trends(), TODAY)

    assert today['net_calories'] == 2000 - 350


def test_exercise_outside_the_window_is_excluded(trends):
    """The lower bound is still enforced -- this is a range, not "everything"."""
    result = trends(days=0)          # window is today only

    assert [d['date'] for d in result['trend_data']] == [str(TODAY)]
    assert _day(result, TODAY)['calories_burned'] == 350
