"""The daily-snapshot route: path, date parsing, and which read it uses.

The shaping is covered by tests/test_daily_snapshot_endpoint.py. What is
covered here is the wiring, because a wrong prefix or a swallowed date is a
silent 404 or a silently wrong day rather than a visible failure -- and
because reaching for the coach's shared read here would hide the user's own
entries from their own dashboard.

Importing `main` needs no environment: every service is initialised in the
lifespan handler, and TestClient only runs that inside a `with` block.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

import api.daily_snapshot as endpoint
import main

PATH = '/api/health/daily-snapshot'
DAY = date(2026, 9, 6)


class FakeStore:
    """Records which day read was called, and with what."""

    def __init__(self, day=None, error=None):
        self.day = day if day is not None else {'_read_errors': {}}
        self.error = error
        self.owner_calls = []
        self.shared_calls = []

    async def get_owner_activities_for_date(self, user_id, target_date):
        self.owner_calls.append((user_id, target_date))
        if self.error:
            raise self.error
        return self.day

    async def get_shared_activities_for_date(self, user_id, target_date):
        self.shared_calls.append((user_id, target_date))
        return self.day


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(endpoint, 'get_supabase_service', lambda: fake)
    return fake


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def test_the_route_is_mounted_where_the_client_will_look(client, store):
    """The contract's path, under the prefix the Flutter client's base URL
    already points at (`.../api/health`)."""
    assert client.get(f'{PATH}/u1/2026-09-06').status_code == 200


def test_it_reads_the_owners_day_not_the_coachs_shared_subset(client, store):
    client.get(f'{PATH}/u1/2026-09-06')

    assert store.owner_calls == [('u1', DAY)]
    assert store.shared_calls == []


def test_the_path_date_is_the_day_that_gets_read(client, store):
    client.get(f'{PATH}/u1/2026-01-31')

    assert store.owner_calls == [('u1', date(2026, 1, 31))]


def test_the_response_echoes_the_user_and_date(client, store):
    body = client.get(f'{PATH}/u1/2026-09-06').json()

    assert body['user_id'] == 'u1'
    assert body['date'] == '2026-09-06'


@pytest.mark.parametrize('bad', ['not-a-date', '2026-13-01', '06-09-2026'])
def test_a_malformed_date_is_a_400_not_a_silent_fallback_to_today(
    client, store, bad
):
    """The neighbouring endpoints answer a bad date with today's data.

    api/water.py and api/steps.py both do `except ValueError: entry_date =
    get_user_today(...)`, so a typo silently returns the wrong day. This one
    says so instead.
    """
    response = client.get(f'{PATH}/u1/{bad}')

    assert response.status_code == 400
    assert bad in response.json()['detail']
    assert store.owner_calls == []


def test_a_store_failure_is_a_500_not_a_blank_day(client, monkeypatch):
    """Per-section isolation is the store's job; a total failure is still 500.

    Returning 200 with every section absent would tell the client the user
    logged nothing all day.
    """
    fake = FakeStore(error=RuntimeError('connection reset'))
    monkeypatch.setattr(endpoint, 'get_supabase_service', lambda: fake)

    assert client.get(f'{PATH}/u1/2026-09-06').status_code == 500
