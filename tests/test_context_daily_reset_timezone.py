"""The daily context reset works on the user's day, not the server's.

`/chat/context/check/{user_id}` and `/chat/context/daily-reset/{user_id}` were
declared under a router that already carried `prefix="/chat"` and spelled the
prefix out again, so they were served at `/chat/chat/...` and the client's
`ChatApi.checkAndResetDailyContext` had always 404'd. Correcting the paths made
them run for the first time -- and they computed "today" from
`datetime.now().date()`, the server clock, while every other date-sensitive
endpoint here takes `get_timezone_offset`.

The service runs in Render's Oregon region, so a user far enough east is on the
next day well before the server is. These tests drive the two routes with an
explicit `X-Timezone-Offset` and assert the day they act on.
"""
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import api.chat as chat_endpoints
import main

CHECK = '/api/health/chat/context/check'
RESET = '/api/health/chat/context/daily-reset'
USER = 'u1'

# UTC+14 (Kiribati) and UTC-12 (Baker Island): the two ends of the real offset
# range, 26 hours apart. More than 24 means their calendar dates *always*
# differ, whatever time the suite runs -- so a test that asserts each user gets
# their own date cannot pass by luck on a server-clock implementation.
AHEAD = {'X-Timezone-Offset': '840'}
BEHIND = {'X-Timezone-Offset': '-720'}
AHEAD_MINUTES, BEHIND_MINUTES = 840, -720


class FakeContextManager:
    """Captures the date each route decides to act on."""

    def __init__(self, stored_date=None):
        self.stored_date = stored_date
        self.ensured = []
        self.supabase_service = self

        outer = self

        class _Query:
            def __getattr__(self, _name):
                return lambda *a, **k: self

            def execute(self):
                rows = ([{'date': outer.stored_date}] if outer.stored_date else [])
                return type('R', (), {'data': rows})()

        class _Client:
            def table(self, _name):
                return _Query()

        self.client = _Client()

    async def ensure_daily_context(self, user_id, today=None):
        self.ensured.append(today)
        return {'is_new': True}


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def wire(monkeypatch, manager):
    monkeypatch.setattr(chat_endpoints, 'get_context_manager', lambda: manager)
    # Both handlers re-import the factory inside the function body.
    import services.chat_context_manager as ccm
    monkeypatch.setattr(ccm, 'get_context_manager', lambda: manager)


def user_today(offset_minutes):
    return (datetime.utcnow() + timedelta(minutes=offset_minutes)).date()


# --- /context/check ---------------------------------------------------------

def test_check_compares_against_the_users_today(client, monkeypatch):
    """A context stored for the user's today needs no reset."""
    today = user_today(AHEAD_MINUTES)
    wire(monkeypatch, FakeContextManager(stored_date=str(today)))

    body = client.get(f'{CHECK}/{USER}', headers=AHEAD).json()

    assert body['current_date'] == str(today)
    assert body['needs_reset'] is False


def test_check_reports_a_new_day_once_the_user_has_rolled_over(
    client, monkeypatch
):
    """Yesterday's context, in the user's reckoning, needs a reset."""
    wire(monkeypatch, FakeContextManager(
        stored_date=str(user_today(AHEAD_MINUTES) - timedelta(days=1))))

    body = client.get(f'{CHECK}/{USER}', headers=AHEAD).json()

    assert body['needs_reset'] is True


def test_check_uses_the_offset_it_is_given(client, monkeypatch):
    """Two users, two timezones, two different "today"s.

    This is the test that pins the fix. The offsets are 26 hours apart, so the
    two dates always differ; a handler reading the server clock returns the
    same date to both and fails here no matter when the suite runs.
    """
    wire(monkeypatch, FakeContextManager(stored_date=str(datetime.utcnow().date())))

    ahead = client.get(f'{CHECK}/{USER}', headers=AHEAD).json()
    behind = client.get(f'{CHECK}/{USER}', headers=BEHIND).json()

    assert ahead['current_date'] == str(user_today(AHEAD_MINUTES))
    assert behind['current_date'] == str(user_today(BEHIND_MINUTES))
    assert ahead['current_date'] != behind['current_date']


def test_check_with_no_stored_context_needs_a_reset(client, monkeypatch):
    wire(monkeypatch, FakeContextManager(stored_date=None))

    body = client.get(f'{CHECK}/{USER}', headers=AHEAD).json()

    assert body['needs_reset'] is True
    assert body['last_context_date'] is None


# --- /context/daily-reset ---------------------------------------------------

def test_reset_builds_the_context_for_the_users_day(client, monkeypatch):
    manager = FakeContextManager()
    wire(monkeypatch, manager)

    body = client.post(f'{RESET}/{USER}', headers=AHEAD).json()

    assert manager.ensured == [user_today(AHEAD_MINUTES)], (
        "ensure_daily_context must be given the user's date; defaulting to the "
        "server's writes the day's context under the wrong date"
    )
    assert body['date'] == str(user_today(AHEAD_MINUTES))


def test_reset_honours_a_western_offset_too(client, monkeypatch):
    manager = FakeContextManager()
    wire(monkeypatch, manager)

    client.post(f'{RESET}/{USER}', headers=BEHIND)

    assert manager.ensured == [user_today(BEHIND_MINUTES)]


# --- the default is unchanged ----------------------------------------------

def test_ensure_daily_context_still_defaults_to_the_server_date():
    """The internal caller (get_or_create_context with no date) is unchanged."""
    import inspect

    from services.chat_context_manager import ChatContextManager

    params = inspect.signature(ChatContextManager.ensure_daily_context).parameters
    assert params['today'].default is None

    source = inspect.getsource(ChatContextManager.ensure_daily_context)
    assert 'if today is None' in source
    assert 'datetime.now().date()' in source
