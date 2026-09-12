"""`get_exercise_logs` filters a range with a half-open bound on the end day.

The last known instance of the family: `.lte('exercise_date', end_date)` on a
`timestamp with time zone` column compares against midnight of the end day,
so a workout logged at 14:30 on that day is outside the range. Three callers
end their range on *today* -- `GET /exercise/stats`, `/exercise/weekly-summary`
and the client's compact exercise tracker's this-week read -- so it was
today's workouts that went missing, on the rows that carry a time-of-day.

The client sends `exercise_date` as a date, so 422 of the 428 rows sit at
midnight and the bug bit only the six that do not. Real, small, and the same
fix as the nutrition trend's (test_nutrition_trends_date_range.py): `lt` on
the day after. That also subsumes the old same-day special case, which built
`T00:00:00`..`T23:59:59` by hand.

The fake applies the filters, lexicographically on ISO strings, which orders
the way the timestamps do: '2026-09-06T14:30:00' sorts after '2026-09-06'
and before '2026-09-07'.
"""
import asyncio

from services.supabase_service import SupabaseService

DAY1, DAY2, DAY3 = '2026-09-05', '2026-09-06', '2026-09-07'

ROWS = [
    {'id': 'a', 'exercise_date': f'{DAY1}T00:00:00+00:00'},   # midnight, first day
    {'id': 'b', 'exercise_date': f'{DAY2}T00:00:00+00:00'},   # midnight, middle day
    {'id': 'c', 'exercise_date': f'{DAY2}T14:30:00+00:00'},   # afternoon, middle day
    {'id': 'd', 'exercise_date': f'{DAY3}T00:00:00+00:00'},   # midnight, last day
    {'id': 'e', 'exercise_date': f'{DAY3}T21:15:00+00:00'},   # evening, last day
]


class _FilteringQuery:
    def __init__(self, rows):
        self._rows = list(rows)
        self.bounds = []

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        if column != 'user_id':
            self._rows = [r for r in self._rows if r.get(column) == value]
        return self

    def gte(self, column, value):
        self.bounds.append(('gte', value))
        self._rows = [r for r in self._rows if str(r[column]) >= str(value)]
        return self

    def lte(self, column, value):
        self.bounds.append(('lte', value))
        self._rows = [r for r in self._rows if str(r[column]) <= str(value)]
        return self

    def lt(self, column, value):
        self.bounds.append(('lt', value))
        self._rows = [r for r in self._rows if str(r[column]) < str(value)]
        return self

    def order(self, column, desc=False):
        self._rows.sort(key=lambda r: str(r[column]), reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return type('R', (), {'data': self._rows})()


class _Client:
    def __init__(self):
        self.query = _FilteringQuery(ROWS)

    def table(self, _name):
        return self.query


def logs(**kwargs):
    store = SupabaseService.__new__(SupabaseService)
    store.client = _Client()
    result = asyncio.run(store.get_exercise_logs('u1', **kwargs))
    return sorted(r['id'] for r in result), store.client.query.bounds


def test_a_multi_day_range_keeps_the_last_days_afternoon_workout():
    """The case that was broken: `e` at 21:15 on the end day was dropped."""
    ids, _ = logs(start_date=DAY1, end_date=DAY3)

    assert ids == ['a', 'b', 'c', 'd', 'e']


def test_a_single_day_keeps_every_time_of_day():
    """Same-day used to be a hand-built `T00:00:00`..`T23:59:59` special case."""
    ids, _ = logs(start_date=DAY2, end_date=DAY2)

    assert ids == ['b', 'c']


def test_the_end_bound_is_exclusive_of_the_next_day():
    ids, bounds = logs(start_date=DAY1, end_date=DAY2)

    assert ids == ['a', 'b', 'c']
    assert ('lt', DAY3) in bounds, 'end day is bounded by `lt` on the day after'
    assert not any(op == 'lte' for op, _ in bounds), 'no `.lte` on a timestamptz'


def test_end_date_alone_includes_that_whole_day():
    ids, _ = logs(end_date=DAY2)

    assert ids == ['a', 'b', 'c']


def test_start_date_alone_is_unchanged():
    ids, _ = logs(start_date=DAY3)

    assert ids == ['d', 'e']


def test_no_range_returns_everything():
    ids, bounds = logs()

    assert ids == ['a', 'b', 'c', 'd', 'e']
    assert bounds == []
