"""The daily-snapshot response shape, against the frozen contract.

`docs/contracts/daily-snapshot-endpoint.md` (authoritative copy: nufi_app
docs/adr/0003) freezes what the client's `DailySnapshot.forDay` will read.
These tests hold the mapping to it, and in particular the three-state rule the
contract turns on: a section that loaded, a section the user logged nothing
for, and a section whose read failed must be three distinguishable answers.

`snapshot_from_day` is pure, so all of this is exercised without FastAPI, a
database or an event loop.
"""
import json
from datetime import date

import pytest

from api.daily_snapshot import (
    CONTRACT_SECTIONS,
    exercise_section,
    meals_section,
    snapshot_from_day,
    supplements_section,
)

DAY = date(2026, 9, 6)
USER = 'u1'

MEAL = {'id': 'm1', 'food_item': 'oats', 'calories': 300, 'protein_g': 10,
        'carbs_g': 50, 'fat_g': 5, 'fiber_g': 8, 'sugar_g': 2,
        'sodium_mg': 100, 'shared_with_chat': False}
EXERCISE = {'id': 'e1', 'exercise_name': 'run', 'duration_minutes': 30,
            'calories_burned': 350, 'shared_with_chat': True}
WATER = {'id': 'wa1', 'glasses_consumed': 6, 'shared_with_chat': False}
STEPS = {'id': 's1', 'steps': 8200, 'shared_with_chat': True}
SLEEP = {'id': 'sl1', 'total_hours': 7.5, 'shared_with_chat': False}
WEIGHT = {'id': 'w1', 'weight': 70.0, 'shared_with_chat': False}
SUPPLEMENTS = {'D3': {'taken': True, 'supplement_name': 'D3'},
               'Magnesium': {'taken': False, 'supplement_name': 'Magnesium'}}


def full_day(**overrides):
    """What get_owner_activities_for_date returns for a fully logged day."""
    day = {
        'meals': [MEAL],
        'water': WATER,
        'steps': STEPS,
        'sleep': SLEEP,
        'exercise': [EXERCISE],
        'weight': WEIGHT,
        'supplements': SUPPLEMENTS,
        'period': {},
        '_read_errors': {},
    }
    day.update(overrides)
    return day


def empty_day(**overrides):
    """A day the user logged nothing on: every read succeeded, all empty."""
    day = {'meals': [], 'water': {}, 'steps': {}, 'sleep': {}, 'exercise': [],
           'weight': {}, 'supplements': {}, 'period': {}, '_read_errors': {}}
    day.update(overrides)
    return day


# --- The envelope ----------------------------------------------------------

def test_a_full_day_carries_every_contract_section():
    snapshot = snapshot_from_day(USER, DAY, full_day())

    assert snapshot['user_id'] == USER
    assert snapshot['date'] == '2026-09-06'
    for section in CONTRACT_SECTIONS:
        assert section in snapshot, f"{section} missing from a full day"


def test_period_is_not_emitted():
    """The store reads eight sections; this contract carries seven.

    The client's DaySnapshot has no period section. Adding one later is
    additive -- this test is here so it is a deliberate act.
    """
    assert 'period' not in snapshot_from_day(USER, DAY, full_day())


# --- ok / missing / error --------------------------------------------------

def test_a_row_section_with_nothing_logged_is_omitted():
    """Omitted means missing: the user logged no weight that day."""
    snapshot = snapshot_from_day(USER, DAY, full_day(weight={}))

    assert 'weight' not in snapshot
    assert snapshot['_read_errors'] == {}


def test_a_failed_section_is_omitted_and_named_in_read_errors():
    day = full_day(sleep={}, _read_errors={'sleep': 'sleep_entries exploded'})
    snapshot = snapshot_from_day(USER, DAY, day)

    assert 'sleep' not in snapshot
    assert snapshot['_read_errors'] == {'sleep': 'read_failed'}


def test_the_stores_error_message_never_reaches_the_wire():
    """The value is an opaque token, whatever the store recorded.

    A real PostgREST failure string carries the SQL message, the Postgres
    error code and a hint naming tables and columns; an HTTP failure carries
    the request URL. The route has no auth, and the client only reads the
    key. So the message stays in the server log and the body says
    `read_failed` -- for every failed section, identically.
    """
    postgrest = ("{'message': 'column daily_water.total_glasses does not exist', "
                 "'code': '42703', 'hint': 'Perhaps you meant \"daily_water.total_ml\"'}")
    http = ("Server error '500' for url "
            "'https://wehzxcqudlfvewilgokf.supabase.co/rest/v1/daily_steps'")
    day = full_day(water={}, steps={}, _read_errors={'water': postgrest, 'steps': http})

    snapshot = snapshot_from_day(USER, DAY, day)

    assert snapshot['_read_errors'] == {'water': 'read_failed', 'steps': 'read_failed'}
    for leaked in ('daily_water', '42703', 'total_ml', 'supabase.co', 'daily_steps'):
        assert leaked not in json.dumps(snapshot), leaked


def test_a_failed_section_is_distinguishable_from_an_empty_one():
    """The rule the contract exists for.

    Both sections are absent from the body. Only one of them is broken.
    """
    day = full_day(sleep={}, weight={}, _read_errors={'sleep': 'boom'})
    snapshot = snapshot_from_day(USER, DAY, day)

    assert 'sleep' not in snapshot and 'weight' not in snapshot
    assert 'sleep' in snapshot['_read_errors']
    assert 'weight' not in snapshot['_read_errors']


def test_a_failed_section_never_carries_a_value():
    """A broken read must not be served as real data.

    The store leaves a failed section's empty value in place for callers that
    ignore _read_errors; this endpoint must not promote that to a reading.
    """
    day = full_day(_read_errors={'meals': 'boom', 'exercise': 'boom'})
    snapshot = snapshot_from_day(USER, DAY, day)

    assert 'meals' not in snapshot
    assert 'exercise' not in snapshot


def test_one_broken_tracker_does_not_cost_the_others():
    day = full_day(steps={}, _read_errors={'steps': 'boom'})
    snapshot = snapshot_from_day(USER, DAY, day)

    assert snapshot['water'] == WATER
    assert snapshot['meals']['count'] == 1
    assert snapshot['sleep'] == SLEEP


def test_a_period_read_failure_is_not_reported_as_a_snapshot_failure():
    """period is not a section here, so its errors are not the client's."""
    day = full_day(_read_errors={'period': 'boom'})

    assert snapshot_from_day(USER, DAY, day)['_read_errors'] == {}


def test_an_empty_day_still_reports_the_rollups():
    """"You logged nothing" is an answer; the dashboard renders zeros."""
    snapshot = snapshot_from_day(USER, DAY, empty_day())

    assert snapshot['meals'] == {'totals': {'calories': 0.0, 'protein_g': 0.0,
                                            'carbs_g': 0.0, 'fat_g': 0.0,
                                            'fiber_g': 0.0, 'sugar_g': 0.0,
                                            'sodium_mg': 0.0},
                                 'count': 0, 'entries': []}
    assert snapshot['exercise'] == {'entries': [], 'total_minutes': 0,
                                    'total_calories_burned': 0.0}
    assert snapshot['supplements'] == {'items': [], 'taken_count': 0,
                                       'total_count': 0}
    for section in ('water', 'steps', 'sleep', 'weight'):
        assert section not in snapshot


# --- Rows keep shared_with_chat -------------------------------------------

@pytest.mark.parametrize('section,expected', [
    ('water', WATER), ('steps', STEPS), ('sleep', SLEEP), ('weight', WEIGHT),
])
def test_row_sections_are_the_raw_row(section, expected):
    """"Row shapes = the existing per-tracker payloads unchanged, incl.
    shared_with_chat.\""""
    value = snapshot_from_day(USER, DAY, full_day())[section]

    assert value == expected
    assert 'shared_with_chat' in value


def test_entry_lists_keep_shared_with_chat():
    snapshot = snapshot_from_day(USER, DAY, full_day())

    assert snapshot['meals']['entries'][0]['shared_with_chat'] is False
    assert snapshot['exercise']['entries'][0]['shared_with_chat'] is True


# --- Roll-ups --------------------------------------------------------------

def test_meal_totals_sum_every_tracked_macro():
    section = meals_section([MEAL, dict(MEAL, calories=200, protein_g=25)])

    assert section['count'] == 2
    assert section['totals']['calories'] == 500.0
    assert section['totals']['protein_g'] == 35.0
    assert section['totals']['fiber_g'] == 16.0


def test_meal_totals_survive_numerics_returned_as_strings():
    """PostgREST hands back `numeric` columns as strings often enough."""
    section = meals_section([dict(MEAL, calories='300.5')])

    assert section['totals']['calories'] == 300.5


def test_a_row_with_a_missing_macro_does_not_break_the_section():
    section = meals_section([{'food_item': 'water'}])

    assert section['count'] == 1
    assert section['totals']['calories'] == 0.0


def test_exercise_totals_sum_minutes_and_calories():
    section = exercise_section([EXERCISE, dict(EXERCISE, duration_minutes=15,
                                               calories_burned=120)])

    assert section['total_minutes'] == 45
    assert section['total_calories_burned'] == 470.0
    assert len(section['entries']) == 2


def test_supplements_become_a_sorted_list_with_counts():
    section = supplements_section(SUPPLEMENTS)

    assert section['items'] == [{'name': 'D3', 'taken': True},
                                {'name': 'Magnesium', 'taken': False}]
    assert section['taken_count'] == 1
    assert section['total_count'] == 2


def test_supplement_order_is_stable():
    """An unstable order reshuffles the client's list on every refresh."""
    forward = supplements_section({'A': {'taken': True}, 'B': {'taken': False}})
    reverse = supplements_section({'B': {'taken': False}, 'A': {'taken': True}})

    assert forward['items'] == reverse['items']
