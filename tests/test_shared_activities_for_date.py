"""Composition and failure isolation in get_shared_activities_for_date.

The per-tracker reads it composes are already covered by their own callers;
what is new here is the composition -- which sections it produces, how it
normalises "nothing logged", and that one broken tracker does not take the
others down. The service is built with `object.__new__` so `__init__` never
reaches Supabase, and every component read is stubbed.
"""
import asyncio
from datetime import date

import pytest

from services.supabase_service import SupabaseService

DAY = date(2026, 9, 6)

SECTIONS = ('meals', 'water', 'steps', 'sleep', 'exercise', 'weight',
            'supplements', 'period')

# Section key -> the store method it composes.
READERS = {
    'meals': 'get_meals_by_date',
    'water': 'get_water_by_date',
    'steps': 'get_steps_by_date',
    'sleep': 'get_sleep_by_date',
    'exercise': 'get_exercises_by_date',
    'weight': 'get_weight_by_date',
    'supplements': 'get_supplement_status_by_date',
    'period': 'get_active_period_for_date',
}

LIST_SECTIONS = ('meals', 'exercise')


def run(coro):
    return asyncio.run(coro)


def build_store(**overrides):
    """A SupabaseService whose component reads are stubs.

    Each override is either a value to return or an Exception to raise.
    Anything not overridden returns "nothing logged" for its section.
    """
    store = object.__new__(SupabaseService)
    calls = []

    def stub(section, outcome):
        async def read(*args, **kwargs):
            calls.append((section, args, kwargs))
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return read

    for section, method in READERS.items():
        default = [] if section in LIST_SECTIONS else None
        setattr(store, method, stub(section, overrides.get(section, default)))

    store.calls = calls
    return store


def test_produces_every_tracker_section():
    result = run(build_store().get_shared_activities_for_date('u1', DAY))

    assert set(result) == set(SECTIONS) | {'_read_errors'}


def test_none_from_a_single_row_read_becomes_an_empty_dict():
    """Callers have always expected {} for "nothing logged", not None."""
    result = run(build_store().get_shared_activities_for_date('u1', DAY))

    for section in ('water', 'steps', 'sleep', 'weight', 'supplements', 'period'):
        assert result[section] == {}, section
    for section in LIST_SECTIONS:
        assert result[section] == []


def test_passes_through_the_rows_each_reader_returns():
    store = build_store(
        meals=[{'calories': 500}],
        water={'glasses_consumed': 6},
        sleep={'total_hours': 7.5},
    )
    result = run(store.get_shared_activities_for_date('u1', DAY))

    assert result['meals'] == [{'calories': 500}]
    assert result['water'] == {'glasses_consumed': 6}
    assert result['sleep'] == {'total_hours': 7.5}


def test_every_read_is_shared_only():
    """This is the coach's view. The owner's full day is a different read."""
    store = build_store()
    run(store.get_shared_activities_for_date('u1', DAY))

    assert len(store.calls) == len(SECTIONS)
    for section, args, kwargs in store.calls:
        assert kwargs.get('shared_only') is True, section
        assert args == ('u1', DAY), section


def test_a_broken_tracker_does_not_fail_the_others():
    store = build_store(sleep=RuntimeError('sleep_entries exploded'),
                        meals=[{'calories': 500}])
    result = run(store.get_shared_activities_for_date('u1', DAY))

    assert result['meals'] == [{'calories': 500}]
    assert result['sleep'] == {}
    assert 'sleep_entries exploded' in result['_read_errors']['sleep']


def test_a_failed_section_is_distinguishable_from_an_empty_one():
    """The distinction the daily-snapshot contract requires.

    Both sections read as empty; only one of them is broken.
    """
    store = build_store(sleep=RuntimeError('boom'))
    result = run(store.get_shared_activities_for_date('u1', DAY))

    assert result['sleep'] == result['water'] == {}
    assert 'sleep' in result['_read_errors']
    assert 'water' not in result['_read_errors']


def test_read_errors_is_empty_when_everything_succeeds():
    result = run(build_store().get_shared_activities_for_date('u1', DAY))

    assert result['_read_errors'] == {}


def test_every_section_can_fail_independently():
    for broken in SECTIONS:
        store = build_store(**{broken: RuntimeError('boom')})
        result = run(store.get_shared_activities_for_date('u1', DAY))

        assert list(result['_read_errors']) == [broken]
        assert result[broken] == ([] if broken in LIST_SECTIONS else {})


def test_all_sections_failing_still_returns_the_full_shape():
    store = build_store(**{s: RuntimeError('boom') for s in SECTIONS})
    result = run(store.get_shared_activities_for_date('u1', DAY))

    assert set(result['_read_errors']) == set(SECTIONS)
    assert set(result) == set(SECTIONS) | {'_read_errors'}
