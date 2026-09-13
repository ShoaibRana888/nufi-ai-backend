"""Characterization of the daily-activity builders before rewiring them.

`chat_service.get_today_activities` and `chat_context_manager._fetch_all_daily_activities`
each assemble "the user's shared activities for a date" from raw table reads.
Candidate #1 replaced them with `supabase_service.get_shared_activities_for_date`.
(A third builder, `generate_fresh_context`, was characterized here too until it was
deleted on 2026-09-13 -- a second rebuilder reachable only from two `except`
fallbacks, which now fall back to `rebuild_context` instead.)

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
    'weight_entries': [{'id': 'w1', 'user_id': 'u1', 'date': '2026-09-06',
                        'weight': 70.0, 'shared_with_chat': True}],
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
SECTIONS = {'meals', 'water', 'exercise', 'steps', 'sleep', 'weight',
            'supplements', 'period'}


def test_both_builders_now_return_the_same_sections(ccm, cs):
    """Changed by the rewiring, in two ways.

    get_today_activities used to return seven sections -- it never read
    period_entries -- so the coach's period guardrail saw nothing on that
    path. Both builders now return all eight.

    Both also gained `_read_errors`. Every consumer reads named sections via
    .get(), so the extra key is inert for them.
    """
    from_ccm = run(ccm._fetch_all_daily_activities('u1', DAY))
    from_cs = run(cs.get_today_activities('u1', DAY))

    assert set(from_ccm) == set(from_cs) == SECTIONS | {'_read_errors'}
    assert from_ccm['_read_errors'] == {}


@pytest.mark.parametrize('section,expected', [
    ('meals', [{'food_item': 'oats', 'calories': 300, 'protein_g': 10,
                'carbs_g': 50, 'fat_g': 5, 'fiber_g': 8, 'sugar_g': 2,
                'sodium_mg': 100}]),
    ('water', {'glasses_consumed': 6, 'total_ml': 1500}),
    ('steps', {'steps': 8200}),
    ('sleep', {'total_hours': 7.5, 'quality_score': 0.8}),
    ('exercise', [{'exercise_name': 'run', 'duration_minutes': 30}]),
    # Changed by the rewiring: get_weight_by_date projects the row into a
    # fixed shape rather than returning it raw. The projection originally
    # dropped shared_with_chat; the daily-snapshot work widened it to keep the
    # flag, because that contract requires every row to carry it (ADR-0004).
    ('weight', {'id': 'w1', 'user_id': 'u1', 'date': '2026-09-06',
                'weight': 70.0, 'notes': None, 'body_fat_percentage': None,
                'muscle_mass_kg': None, 'shared_with_chat': True,
                'created_at': None, 'updated_at': None}),
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
