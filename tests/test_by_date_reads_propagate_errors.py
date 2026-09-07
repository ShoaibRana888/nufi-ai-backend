"""The by-date reads report failure instead of swallowing it.

Every one of these reads used to wrap its query in `try/except` and return the
same "nothing logged" value it returns for an empty day -- `[]`, `None` or
`{}`. That made a broken tracker indistinguishable from a quiet one, which
ADR-0001 flagged and the daily-snapshot contract forbids outright.

It also made `get_shared_activities_for_date`'s `_read_errors` map structurally
dead: the composition catches per-section exceptions, but seven of its eight
component reads could never raise one, so in production the map was only ever
populated for `period`. Its tests passed because they stub the component reads
rather than the client underneath them -- so they exercised the composition's
isolation logic against fakes that raise, while the real reads did not.

These tests close that gap at the leaves, against a client that fails the way
PostgREST does. See ADR-0004.
"""
import asyncio
from datetime import date

import pytest

from services.supabase_service import SupabaseService

DAY = date(2026, 9, 6)

BOOM = "PostgREST: connection reset"


def run(coro):
    return asyncio.run(coro)


class _Query:
    """A query builder that either yields rows or fails at execute()."""

    def __init__(self, rows, error):
        self._rows = rows
        self._error = error

    def __getattr__(self, _name):
        # select / eq / gte / lt / order / limit / or_ all chain.
        return lambda *a, **k: self

    def execute(self):
        if self._error is not None:
            raise self._error
        return type('Response', (), {'data': self._rows})()


class FakeClient:
    def __init__(self, rows=None, error=None):
        self._rows = rows or []
        self._error = error

    def table(self, _name):
        return _Query(self._rows, self._error)


def build_store(rows=None, error=None):
    """A SupabaseService over a fake client; __init__ never runs."""
    store = object.__new__(SupabaseService)
    store.client = FakeClient(rows=rows, error=error)
    return store


# (method name, kwargs-free call, a row the read will accept)
READS = [
    ('get_meals_by_date', {'food_item': 'oats'}),
    ('get_water_by_date', {'glasses_consumed': 6}),
    ('get_steps_by_date', {'steps': 8200}),
    ('get_sleep_by_date', {'total_hours': 7.5}),
    ('get_exercises_by_date', {'exercise_name': 'run'}),
    ('get_weight_by_date', {'id': 'w1', 'user_id': 'u1', 'date': str(DAY),
                            'weight': 70.0}),
    ('get_supplement_status_by_date', {'supplement_name': 'D3', 'taken': True}),
    ('get_active_period_for_date', {'start_date': str(DAY)}),
]


@pytest.mark.parametrize('name,_row', READS)
def test_a_failed_read_raises(name, _row):
    store = build_store(error=RuntimeError(BOOM))
    read = getattr(store, name)

    with pytest.raises(RuntimeError, match=BOOM):
        run(read('u1', DAY))


@pytest.mark.parametrize('name,row', READS)
def test_a_successful_read_still_returns_its_rows(name, row):
    """The failure path is new; the success path is unchanged."""
    result = run(getattr(build_store(rows=[row]), name)('u1', DAY))

    assert result, f"{name} returned nothing for a row that exists"


@pytest.mark.parametrize('name,_row', READS)
def test_an_empty_day_is_not_an_error(name, _row):
    """The distinction the contract needs: empty is a value, not a failure."""
    result = run(getattr(build_store(rows=[]), name)('u1', DAY))

    assert result in ([], None, {}), f"{name} returned {result!r}"


def test_read_errors_is_populated_for_every_section_when_the_client_fails():
    """The property that was missing: composition + leaves, end to end.

    Previously this produced eight empty sections and an empty `_read_errors`
    -- a totally broken database reported as a day with nothing logged.
    """
    store = build_store(error=RuntimeError(BOOM))
    result = run(store.get_shared_activities_for_date('u1', DAY))

    assert set(result['_read_errors']) == {
        'meals', 'water', 'steps', 'sleep', 'exercise', 'weight',
        'supplements', 'period',
    }
    assert all(BOOM in message for message in result['_read_errors'].values())
