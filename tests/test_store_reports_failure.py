"""The store reports failure; it does not return it as data.

ADR-0004 fixed the seven by-date leaves and PR #15 `get_exercise_logs`. The
other 42 store methods still wrapped their query in `try/except` and returned
the value that means "nothing here" -- `[]`, `{}`, `None`, `False`, or nothing
at all -- so a database outage arrived at every caller as an empty answer with
`success: true`. The sharp cases (ADR-0009): `get_user_by_id -> None` became a
404 on the profile and login paths; `get_user_by_email -> None` became 401
"Invalid credentials"; `get_current_period -> None` created a second open
period; a failed meals read in `recalculate_daily_nutrition` summed to zero
and *wrote* the zeros; a failed `get_latest_weight` after a delete reverted
the profile weight to the starting weight; `clear_supplement_preferences ->
False` left the old preferences active beside the new ones.

These tests pin the leaves against a client that fails the way PostgREST
does, and the whole class by inspection so the next swallowing handler fails
the suite rather than waiting for the next outage.
"""
import ast
import asyncio
import pathlib
from datetime import date

import pytest
from fastapi.testclient import TestClient

import api.meals as meals_endpoints
import api.periods as periods_endpoints
import api.steps as steps_endpoints
import api.weight as weight_endpoints
import main
from services.supabase_service import SupabaseService
from utils.errors import INTERNAL_ERROR_DETAIL

ROOT = pathlib.Path(__file__).parent.parent
STORE = ROOT / 'services' / 'supabase_service.py'

DAY = date(2026, 9, 6)
BOOM = "PostgREST: connection reset"


def run(coro):
    return asyncio.run(coro)


# --- fakes --------------------------------------------------------------------


class _Query:
    """A query builder that records its chain and either yields rows or fails
    at execute()."""

    def __init__(self, rows, error, calls):
        self._rows, self._error, self.calls = rows, error, calls

    def __getattr__(self, name):
        def chain(*_a, **_k):
            self.calls.append(name)
            return self
        return chain

    def execute(self):
        if self._error is not None:
            raise self._error
        return type('Response', (), {'data': self._rows})()


class FakeClient:
    def __init__(self, rows=None, error=None):
        self._rows, self._error, self.calls = rows or [], error, []

    def table(self, _name):
        return _Query(self._rows, self._error, self.calls)


def build_store(rows=None, error=None):
    """A SupabaseService over a fake client; __init__ never runs."""
    store = object.__new__(SupabaseService)
    store.client = FakeClient(rows=rows, error=error)
    return store


# --- the leaves --------------------------------------------------------------

# Every method that used to swallow, with arguments that reach execute().
SWALLOWED = [
    ('get_user_by_id', ('u1',)),
    ('get_user_by_email', ('a@b.c',)),
    ('get_user', ('u1',)),
    ('get_meal_by_id', ('m1',)),
    ('delete_meal', ('m1',)),
    ('get_daily_nutrition', ('u1', str(DAY))),
    ('get_user_meal_presets', ('u1',)),
    ('update_preset_usage', ('p1',)),
    ('search_cached_meal', ('u1', 'oats', '1 cup')),
    ('get_recent_unique_meals', ('u1',)),
    ('get_user_meals', ('u1',)),
    ('get_user_meals_by_date', ('u1', str(DAY))),
    ('delete_water_entry', ('w1',)),
    ('get_water_history', ('u1',)),
    ('get_step_history', ('u1',)),
    ('delete_step_entry_by_date', ('u1', DAY)),
    ('get_steps_in_range', ('u1', DAY, DAY)),
    ('get_weight_history', ('u1',)),
    ('get_latest_weight', ('u1',)),
    ('delete_weight_entry', ('w1',)),
    ('get_weight_entry_by_id', ('w1',)),
    ('update_user_weight', ('u1', 70.0)),
    ('initialize_starting_weight_for_user', ('u1',)),
    ('get_sleep_entry_by_id', ('s1',)),
    ('get_sleep_history', ('u1',)),
    ('delete_sleep_entry', ('s1',)),
    ('get_supplement_preferences', ('u1',)),
    ('clear_supplement_preferences', ('u1',)),
    ('get_supplement_log_by_date', ('u1', 'D3', DAY)),
    ('get_supplement_history', ('u1',)),
    ('delete_supplement_preference', ('p1',)),
    ('delete_exercise_log', ('e1',)),
    ('get_exercise_by_id', ('e1',)),
    ('get_period_history', ('u1',)),
    ('get_current_period', ('u1',)),
    ('delete_period_entry', ('p1',)),
    ('save_chat_message', ('u1', 'hi', True)),
    ('get_chat_messages', ('u1',)),
    ('get_recent_chat_messages', ('u1',)),
    ('clear_chat_messages', ('u1',)),
    ('get_recent_chat_context', ('u1',)),
    ('get_or_create_daily_session', ('u1',)),
]


def test_the_inventory_is_the_one_in_the_adr():
    assert len(SWALLOWED) == 42
    assert len({name for name, _ in SWALLOWED}) == 42


@pytest.mark.parametrize('name,args', SWALLOWED)
def test_a_failed_query_raises(name, args):
    store = build_store(error=RuntimeError(BOOM))

    with pytest.raises(RuntimeError, match=BOOM):
        run(getattr(store, name)(*args))


# Get-or-create: an empty read triggers an insert, which the empty fake
# cannot answer. Their failure path is covered above; their empty path is
# the insert's, not theirs.
GET_OR_CREATE = {'get_or_create_daily_session', 'save_chat_message'}


@pytest.mark.parametrize('name,args', [c for c in SWALLOWED if c[0] not in GET_OR_CREATE])
def test_nothing_there_is_still_not_an_error(name, args):
    """The distinction the sweep is for: empty is a value, failure is not."""
    result = run(getattr(build_store(rows=[]), name)(*args))

    # Reads answer with their empty value; writes with True (the deletes) or
    # with what the method reports about its own work.
    assert result in ([], None, {}, True, False), f"{name} returned {result!r}"


def test_no_store_handler_swallows():
    """The class, by inspection: every `except` in the store re-raises,
    except the three that turn a failure into a *report* a caller reads --
    the per-table map of `delete_user_account`, the health check's
    `unhealthy` status, and `_activities_for_date`'s `_read_errors`."""
    REPORTS = {'delete_user_account', 'health_check', '_activities_for_date'}
    tree = ast.parse(STORE.read_text())
    offenders = []
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name in REPORTS:
                continue
            for handler in (n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)):
                if not any(isinstance(n, ast.Raise) for n in ast.walk(handler)):
                    offenders.append(f'{fn.name}:{handler.lineno}')
    assert offenders == [], (
        'a store method swallows a failure -- let it propagate, or add the '
        'method to REPORTS with the reason:\n' + '\n'.join(offenders)
    )


# --- get_user_by_id: not found is still None -----------------------------------


def test_a_missing_user_is_none_not_an_error():
    """`.single()` made PostgREST answer a missing row with an error, so the
    swallowing handler was also how "not found" became None. Without it the
    read indexes the list instead, and never asks for a single object."""
    store = build_store(rows=[])

    assert run(store.get_user_by_id('nobody')) is None
    assert 'single' not in store.client.calls


def test_a_present_user_is_the_row():
    row = {'id': 'u1', 'name': 'A'}

    assert run(build_store(rows=[row]).get_user_by_id('u1')) == row


# --- the sharp callers ----------------------------------------------------------


class _Recording:
    """A store whose named reads fail and whose writes are recorded."""

    def __init__(self, failing=(), rows=None):
        self.failing, self.rows = set(failing), rows or {}
        self.writes = []

    def __getattr__(self, name):
        async def call(*args, **kwargs):
            if name in self.failing:
                raise RuntimeError(BOOM)
            if name.startswith(('update_', 'create_', 'delete_', 'clear_')):
                self.writes.append((name, args))
                return {'id': 'new', **(kwargs or {})} if name.startswith('create_') else True
            return self.rows.get(name)
        return call


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def test_a_failed_meals_read_does_not_zero_the_days_nutrition():
    """`recalculate_daily_nutrition` summed the empty list a failed read
    returned and wrote the zeros over the day's real totals. The helper is
    best-effort by design (the meal is already deleted); it must skip, not
    write."""
    store = _Recording(failing={'get_user_meals_by_date'},
                       rows={'get_daily_nutrition': {'id': 'n1', 'calories_consumed': 900}})

    run(meals_endpoints.recalculate_daily_nutrition(store, 'u1', str(DAY)))

    assert store.writes == []


def test_a_failed_open_period_read_does_not_open_a_second_one(client, monkeypatch):
    """`POST /period` looked for an open period first and created one when
    the read said there was none. `period_entries` has no uniqueness on an
    open period, so a failed read wrote a second one."""
    store = _Recording(failing={'get_current_period'})
    monkeypatch.setattr(periods_endpoints, 'get_supabase_service', lambda: store)

    response = client.post('/api/health/period',
                           json={'user_id': 'u1', 'start_date': str(DAY)})

    assert response.status_code == 500
    assert response.json()['detail'] == INTERNAL_ERROR_DETAIL
    assert store.writes == []


def test_a_failed_delete_is_a_500_not_not_found(client, monkeypatch):
    """`delete_step_entry_by_date -> False` was reported as "Step entry not
    found" with a 200. A delete that raised never reached that branch; now
    it cannot."""
    store = _Recording(failing={'delete_step_entry_by_date'})
    monkeypatch.setattr(steps_endpoints, 'get_supabase_service', lambda: store)

    response = client.delete(f'/api/health/steps/u1/{DAY}')

    assert response.status_code == 500
    assert response.json()['detail'] == INTERNAL_ERROR_DETAIL


def test_a_saved_weight_is_not_failed_by_its_bookkeeping(client, monkeypatch):
    """The starting-weight backfill runs after the row is stored. Weight has
    no upsert, so a 500 here invites the retry that writes a second entry;
    the endpoint logs the failure and reports the save it made."""
    store = _Recording(failing={'initialize_starting_weight_for_user'})
    monkeypatch.setattr(weight_endpoints, 'get_supabase_service', lambda: store)

    response = client.post('/api/health/weight',
                           json={'user_id': 'u1', 'date': str(DAY), 'weight': 70.0})

    assert response.status_code == 200
    assert response.json()['success'] is True
    assert [name for name, _ in store.writes] == ['create_weight_entry']
