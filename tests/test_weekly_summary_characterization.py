"""Characterization tests for the two weekly-summary implementations.

These pin down what the code does *today*, before the health_trends
extraction converges them. They are not a statement that this behaviour is
correct — `chat_service._get_weekly_summary` is demonstrably wrong (it reports
a week that ends yesterday) and these tests exist so that fixing it is a
visible, reviewable diff rather than a silent change to what the coach sees.

`ChatContextManager` and `HealthChatService` are built with `object.__new__`
so their `__init__` never reaches Supabase; the collaborators each method
actually uses are injected by hand.
"""
import asyncio
from datetime import date, datetime, timedelta

import pytest

from services import chat_service as chat_service_module
from services.chat_context_manager import ChatContextManager
from services.chat_service import HealthChatService

TODAY = date(2026, 9, 6)


def run(coro):
    """Run one coroutine. Avoids a pytest-asyncio dependency for four tests."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# One week of fixture data, shared by both implementations.
#
# Chosen so that every field of the summary differs between the two: the
# windows overlap but neither contains the other (ccm covers Aug 31–Sep 6,
# chat_service covers Aug 30–Sep 5).
# ---------------------------------------------------------------------------
DAYS = {
    "2026-08-30": {
        "meals": [{"calories": 1000}],
        "exercise": [{"duration_minutes": 30}, {"duration_minutes": 20}],
        "sleep": {"total_hours": 6.0},
        "weight": {"date": "2026-08-30", "weight": 70.0},
    },
    "2026-09-01": {
        "meals": [{"calories": 300}, {"calories": 700}],
        "exercise": [],
        "sleep": None,
        "weight": {"date": "2026-09-01", "weight": 70.5},
    },
    "2026-09-06": {
        "meals": [{"calories": 500}],
        "exercise": [{"duration_minutes": 45}],
        "sleep": {"total_hours": 8.0},
        "weight": {"date": "2026-09-06", "weight": 69.0},
    },
}


def _day(d):
    return DAYS.get(str(d), {})


class FakeStore:
    """The slice of supabase_service that ccm._get_weekly_summary touches."""

    async def get_meals_by_date(self, user_id, d, shared_only=False):
        return _day(d).get("meals", [])

    async def get_sleep_by_date(self, user_id, d, shared_only=False):
        return _day(d).get("sleep")

    async def get_water_by_date(self, user_id, d, shared_only=False):
        return _day(d).get("water")

    async def get_exercises_by_date(self, user_id, d, shared_only=False):
        return _day(d).get("exercise", [])

    async def get_weight_entries(self, user_id, start_date=None, end_date=None,
                                 shared_only=False):
        return [
            day["weight"]
            for key, day in sorted(DAYS.items())
            if day.get("weight") and start_date <= key <= end_date
        ]


class FrozenDatetime(datetime):
    """`chat_service` reads the clock directly; freeze it for the test."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 6, 12, 0, 0)


@pytest.fixture
def ccm():
    manager = object.__new__(ChatContextManager)
    manager.supabase_service = FakeStore()
    return manager


@pytest.fixture
def cs(monkeypatch):
    service = object.__new__(HealthChatService)

    async def fake_get_today_activities(user_id, target_date):
        day = _day(target_date)
        return {
            "meals": day.get("meals", []),
            "exercise": day.get("exercise", []),
            "sleep": day.get("sleep") or {},
            "weight": day.get("weight") or {},
        }

    service.get_today_activities = fake_get_today_activities
    monkeypatch.setattr(chat_service_module, "datetime", FrozenDatetime)
    return service


# ---------------------------------------------------------------------------
# Current behaviour, implementation by implementation.
# ---------------------------------------------------------------------------
def test_context_manager_weekly_summary_today_inclusive(ccm):
    """ccm covers Aug 31–Sep 6 and averages calories over days that have meals."""
    summary = run(ccm._get_weekly_summary("u1", TODAY))

    assert summary == {
        # Sep 1 (1000) + Sep 6 (500) over the 2 days that had meals.
        "avg_daily_calories": 750,
        # Sep 6 only: counts distinct workout *days*.
        "total_workouts": 1,
        "avg_sleep_hours": 8.0,
        # Sep 1 (70.5) -> Sep 6 (69.0)
        "weight_trend": "losing_1.5kg",
        "hydration_consistency": 0,
        "workout_streak": 0,
    }


def test_chat_service_weekly_summary_excludes_today(cs):
    """chat_service covers Aug 30–Sep 5 and averages calories over a flat 7."""
    summary = run(cs._get_weekly_summary("u1"))

    assert summary == {
        # Aug 30 (1000) + Sep 1 (1000) divided by 7 regardless of data density.
        "avg_daily_calories": 286,
        # Aug 30's two entries: counts exercise *entries*, not days.
        "total_workouts": 2,
        "avg_sleep_hours": 6.0,
        # Aug 30 (70.0) -> Sep 1 (70.5)
        "weight_trend": "gaining_0.5kg",
    }


def test_the_two_summaries_disagree_on_every_field(ccm, cs):
    """The bug this extraction exists to fix, stated as a test.

    Same user, same data, same day, same key names, two different answers --
    including opposite directions for weight. Both are fed to the coach.
    """
    a = run(ccm._get_weekly_summary("u1", TODAY))
    b = run(cs._get_weekly_summary("u1"))

    for key in ("avg_daily_calories", "total_workouts", "avg_sleep_hours",
                "weight_trend"):
        assert a[key] != b[key], f"{key} unexpectedly agrees"

    assert a["weight_trend"].startswith("losing")
    assert b["weight_trend"].startswith("gaining")


def test_windows_differ_by_a_day_at_each_end():
    """Spells out the off-by-one so the convergence diff is unambiguous."""
    ccm_window = [TODAY - timedelta(days=6) + timedelta(days=i) for i in range(7)]
    cs_window = [TODAY - timedelta(days=7) + timedelta(days=i) for i in range(7)]

    assert ccm_window[-1] == TODAY
    assert cs_window[-1] == TODAY - timedelta(days=1)
    assert TODAY not in cs_window
