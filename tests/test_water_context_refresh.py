"""Logging water refreshes the chat context on both paths.

`save_water_entry` upserts: create on the day's first glass, update on every
one after. The update branch used to `return` the response directly, so the
`update_context_activity` call below the if/else only ran on the create path --
and the update path is the common one. `GET /chat/context/{user_id}` serves
stored context verbatim, so it kept reporting one glass however many were
logged.

api/steps.py has the same if/else and assigns `result`; water was the only
tracker that returned early.

Whether a refresh is *merged* is a separate question -- a row the user hid
from the coach must not be -- and that decision lives in
`update_context_activity`, covered by test_context_refresh_respects_sharing.py.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

import api.water as water_endpoints
import main

PATH = '/api/health/water'
USER = 'u1'


class FakeStore:
    """Records the upsert path taken."""

    def __init__(self, existing=None):
        self.existing = existing
        self.created = []
        self.updated = []

    async def get_water_by_date(self, user_id, entry_date):
        return self.existing

    async def create_water_entry(self, data):
        self.created.append(data)
        return dict(data)

    async def update_water_entry(self, entry_id, data):
        self.updated.append((entry_id, data))
        return dict(data, id=entry_id)


class FakeContextManager:
    def __init__(self):
        self.refreshes = []

    async def update_context_activity(self, user_id, activity, payload, entry_date):
        self.refreshes.append((user_id, activity, entry_date))


@pytest.fixture
def wiring(monkeypatch):
    def build(existing=None):
        store, context = FakeStore(existing), FakeContextManager()
        monkeypatch.setattr(water_endpoints, 'get_supabase_service', lambda: store)
        monkeypatch.setattr(water_endpoints, 'get_context_manager', lambda: context)
        return store, context
    return build


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def post(client, glasses):
    return client.post(f'{PATH}', json={
        'user_id': USER,
        'date': '2026-09-06',
        'glasses_consumed': glasses,
        'total_ml': glasses * 250.0,
        'target_ml': 2000.0,
        'notes': None,
    })


def test_the_first_glass_creates_and_refreshes(client, wiring):
    store, context = wiring(existing=None)

    assert post(client, 1).status_code == 200
    assert len(store.created) == 1
    assert len(context.refreshes) == 1


def test_a_later_glass_updates_and_still_refreshes(client, wiring):
    """The path that used to return early."""
    store, context = wiring(existing={'id': 'wa1', 'glasses_consumed': 1})

    response = post(client, 2)

    assert response.status_code == 200
    assert len(store.updated) == 1, "should have taken the update path"
    assert context.refreshes == [(USER, 'water', date(2026, 9, 6))], (
        "updating an existing water row must refresh the chat context too -- "
        "otherwise the cached context reports the day's first glass forever"
    )


def test_the_update_response_still_carries_the_entry(client, wiring):
    """Falling through must not change what the endpoint returns."""
    wiring(existing={'id': 'wa1', 'glasses_consumed': 1})

    body = post(client, 3).json()

    assert body['success'] is True
    assert body['id'] == 'wa1'
    assert body['entry']['glasses_consumed'] == 3
