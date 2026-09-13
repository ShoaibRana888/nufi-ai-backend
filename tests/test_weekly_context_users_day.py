"""The weekly-context endpoints work on the user's day, not the server's.

`api/weekly_context.py` resolved both the target date and "today" from
`datetime.now()`. Three consequences, one per route:

* `GET /weekly/context/{id}` with no date -- what the dashboard's weekly card
  sends -- read the server's week. For a UTC-8 user on Sunday evening that
  is the next, empty week.
* The manager judges whether a week is still *current* against `today`, and
  a week judged complete is served from cache and never revalidated (see
  ADR-0006's correction). On the server clock, a western user's live Sunday
  was frozen without its evening.
* `GET /weekly/recent/{id}` counted back from the server date.

And a fourth, unrelated to the clock: `POST /weekly/rebuild/{id}` declared
`date` as a query parameter while the client sends it in the JSON body, so
the body was ignored and every rebuild targeted the server's current week.

Offsets 26 hours apart, as in test_context_daily_reset_timezone.py: a
server-clock handler cannot pass by luck.
"""
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import api.weekly_context as weekly_endpoints
import main

BASE = '/api/health/weekly'
USER = 'u1'
AHEAD, BEHIND = {'X-Timezone-Offset': '840'}, {'X-Timezone-Offset': '-720'}


def user_today(offset_minutes):
    return (datetime.utcnow() + timedelta(minutes=offset_minutes)).date()


class FakeManager:
    def __init__(self):
        self.reads, self.recent, self.rebuilt = [], [], []

    async def get_or_create_weekly_context(self, user_id, target_date, today=None):
        self.reads.append((target_date, today))
        return {'success': True}

    async def get_recent_weeks_context(self, user_id, weeks_count=4, end_date=None):
        self.recent.append((weeks_count, end_date))
        return []

    async def update_weekly_context(self, user_id, date=None):
        self.rebuilt.append(date)
        return {'success': True}


@pytest.fixture
def manager(monkeypatch):
    fake = FakeManager()
    monkeypatch.setattr(weekly_endpoints, 'get_weekly_context_manager', lambda: fake)
    return fake


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


# --- GET /context -------------------------------------------------------------


def test_no_date_means_the_users_today_for_both_target_and_currency(client, manager):
    client.get(f'{BASE}/context/{USER}', headers=AHEAD)
    client.get(f'{BASE}/context/{USER}', headers=BEHIND)

    ahead, behind = manager.reads
    assert ahead == (user_today(840), user_today(840))
    assert behind == (user_today(-720), user_today(-720))
    assert ahead != behind


def test_an_explicit_date_is_the_target_and_today_is_still_the_users(client, manager):
    """The weekly summary screen sends the selected date. Which week that is
    is the caller's; whether it is still current is judged on the user's
    today, never the server's."""
    client.get(f'{BASE}/context/{USER}?date=2026-08-16', headers=BEHIND)

    assert manager.reads == [(date(2026, 8, 16), user_today(-720))]


def test_a_malformed_date_is_a_400(client, manager):
    assert client.get(f'{BASE}/context/{USER}?date=next-week').status_code == 400
    assert manager.reads == []


# --- GET /recent --------------------------------------------------------------


def test_recent_weeks_count_back_from_the_users_today(client, manager):
    client.get(f'{BASE}/recent/{USER}?weeks=3', headers=AHEAD)

    assert manager.recent == [(3, user_today(840))]


# --- POST /rebuild ------------------------------------------------------------


def test_rebuild_reads_the_date_from_the_json_body(client, manager):
    """What the client actually sends. It used to be silently ignored."""
    client.post(f'{BASE}/rebuild/{USER}', json={'date': '2026-08-16'})

    assert manager.rebuilt == [date(2026, 8, 16)]


def test_rebuild_still_accepts_the_query_spelling(client, manager):
    client.post(f'{BASE}/rebuild/{USER}?date=2026-08-09')

    assert manager.rebuilt == [date(2026, 8, 9)]


def test_rebuild_with_no_date_is_the_users_today(client, manager):
    client.post(f'{BASE}/rebuild/{USER}', headers=BEHIND)

    assert manager.rebuilt == [user_today(-720)]
