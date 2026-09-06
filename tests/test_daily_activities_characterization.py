"""Characterization of the three daily-activity builders before rewiring them.

`chat_service.get_today_activities`, `chat_context_manager._fetch_all_daily_activities`
and `chat_context_manager.generate_fresh_context` each assemble "the user's shared
activities for a date" from raw table reads. Candidate #1 replaces all three with
`supabase_service.get_shared_activities_for_date`.

These tests pin the *shape* each builder produces -- section keys, and what each one
uses to mean "nothing logged" -- so the rewiring diff shows exactly what changes. They
deliberately do not pin the date filtering: the whole point of the rewiring is that the
three builders filter dates three different ways and the store's half-open range is the
correct one. `FakeClient` therefore ignores filters and serves whatever rows the fixture
holds for a table.
"""
import asyncio
from datetime import date

import pytest

from services.chat_context_manager import ChatContextManager
from services.chat_service import HealthChatService
from services.supabase_service import SupabaseService

DAY = date(2026, 9, 6)

ROWS = {
    'meal_entries': [
        {'food_item': 'oats', 'calories': 300, 'protein_g': 10, 'carbs_g': 50,
         'fat_g': 5, 'fiber_g': 8, 'sugar_g': 2, 'sodium_mg': 100},
    ],
    'daily_water': [{'glasses_consumed': 6, 'total_ml': 1500}],
    'daily_steps': [{'steps': 8200}],
    'sleep_entries': [{'total_hours': 7.5, 'quality_score': 0.8}],
    'exercise_logs': [{'exercise_name': 'run', 'duration_minutes': 30}],
    'weight_entries': [{'date': '2026-09-06', 'weight': 70.0}],
    'period_entries': [],
    'supplement_logs': [],
    'user_supplements': [],
}


def run(coro):
    return asyncio.run(coro)


class _Query:
    """Chainable no-op query. Every filter returns self; execute serves the table."""

    def __init__(self, table):
        self._table = table

    def __getattr__(self, _name):
        return lambda *args, **kwargs: self

    def execute(self):
        return type('Response', (), {'data': list(ROWS.get(self._table, []))})()


class FakeClient:
    def __init__(self):
        self.tables_read = []

    def table(self, name):
        self.tables_read.append(name)
        return _Query(name)


def build_store():
    store = object.__new__(SupabaseService)
    store.client = FakeClient()
    return store


@pytest.fixture
def store():
    return build_store()


@pytest.fixture
def ccm(store):
    manager = object.__new__(ChatContextManager)
    manager.supabase_service = store
    return manager


@pytest.fixture
def cs(store):
    service = object.__new__(HealthChatService)
    service.supabase_service = store
    return service


# ---------------------------------------------------------------------------
# The eight sections, and what each builder means by "nothing logged".
# ---------------------------------------------------------------------------
def test_chat_service_builder_returns_seven_sections(cs):
    """No period section: get_today_activities never read period_entries."""
    activities = run(cs.get_today_activities('u1', DAY))

    assert set(activities) == {'meals', 'water', 'exercise', 'sleep',
                               'supplements', 'weight', 'steps'}


def test_context_manager_builder_returns_eight_sections(ccm):
    activities = run(ccm._fetch_all_daily_activities('u1', DAY))

    assert set(activities) == {'meals', 'water', 'exercise', 'steps', 'sleep',
                               'weight', 'supplements', 'period'}


@pytest.mark.parametrize('section,expected', [
    ('meals', [{'food_item': 'oats', 'calories': 300, 'protein_g': 10,
                'carbs_g': 50, 'fat_g': 5, 'fiber_g': 8, 'sugar_g': 2,
                'sodium_mg': 100}]),
    ('water', {'glasses_consumed': 6, 'total_ml': 1500}),
    ('steps', {'steps': 8200}),
    ('sleep', {'total_hours': 7.5, 'quality_score': 0.8}),
    ('exercise', [{'exercise_name': 'run', 'duration_minutes': 30}]),
    ('weight', {'date': '2026-09-06', 'weight': 70.0}),
])
def test_both_builders_agree_on_the_shared_sections(ccm, cs, section, expected):
    from_ccm = run(ccm._fetch_all_daily_activities('u1', DAY))
    from_cs = run(cs.get_today_activities('u1', DAY))

    assert from_ccm[section] == expected
    assert from_cs[section] == expected


def test_a_section_with_no_rows_is_an_empty_dict_not_none(ccm):
    """Single-row sections use {} for "nothing logged"; consumers rely on it."""
    activities = run(ccm._fetch_all_daily_activities('u1', DAY))

    assert activities['period'] == {}


# ---------------------------------------------------------------------------
# generate_fresh_context: the fallback path, which reads only four trackers.
# ---------------------------------------------------------------------------
def test_fresh_context_reads_only_four_trackers(ccm):
    """Pins the gap: no sleep, weight, period or supplement read happens here."""
    ccm.supabase_service.get_user_by_id = _returns({'name': 'A', 'tdee': 2000})
    run(ccm.generate_fresh_context('u1', DAY))

    tracker_tables = [t for t in ccm.supabase_service.client.tables_read
                      if t != 'chat_contexts']
    assert tracker_tables == ['meal_entries', 'exercise_logs', 'daily_water',
                              'daily_steps']


def test_fresh_context_hardcodes_the_trackers_it_never_read(ccm):
    """weight, sleep and supplements are None/[] regardless of what is logged.

    The fixture has a weight entry and 7.5h of sleep for this date. This is the
    bug the rewiring fixes: the fallback context tells the coach the user logged
    neither.
    """
    ccm.supabase_service.get_user_by_id = _returns({'name': 'A', 'tdee': 2000})
    result = run(ccm.generate_fresh_context('u1', DAY))
    progress = result['context']['today_progress']

    assert progress['weight'] is None
    assert progress['sleep_hours'] is None
    assert progress['supplements_taken'] == []

    # ...while the trackers it does read come through.
    assert progress['water_glasses'] == 6
    assert progress['steps'] == 8200
    assert progress['meals_logged'] == 1


def _returns(value):
    async def _read(*args, **kwargs):
        return value
    return _read
