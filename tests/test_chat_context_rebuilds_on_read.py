"""`GET /chat/context/{user_id}` rebuilds; the incremental refresh is gone.

The question left open by candidate #4 was whether the cached-context
endpoint should rebuild or declare its staleness, because the answer decides
whether the incremental refresh in every tracker write endpoint is
load-bearing or dead. The inventory (ADR-0008) found one live reader of the
cache -- the chat page's welcome banner -- which wants today's numbers and
already fires a rebuild in parallel with the read. So the read rebuilds, the
fallback declares staleness, and the write-side refresh machinery
(`update_context_activity`, `remove_from_context`, fifteen call sites) is
deleted rather than kept warm for nobody.
"""
import inspect
from datetime import date

import pytest
from fastapi.testclient import TestClient

import api.chat as chat_endpoints
import main
from services.chat_context_manager import ChatContextManager

PATH = '/api/health/chat/context'
USER = 'u1'
DAY = date(2026, 9, 6)


class FakeContextManager:
    def __init__(self, rebuild_fails=False, read_fails=False):
        self.rebuild_fails, self.read_fails = rebuild_fails, read_fails
        self.rebuilt, self.read = [], []

    async def rebuild_context(self, user_id, target_date):
        self.rebuilt.append(target_date)
        if self.rebuild_fails:
            raise RuntimeError('supabase down')
        return {'context': {'today_progress': {'date': str(target_date), 'source': 'rebuilt'}}}

    async def get_or_create_context(self, user_id, target_date):
        self.read.append(target_date)
        if self.read_fails:
            raise RuntimeError('supabase still down')
        return {'context': {'today_progress': {'date': str(target_date), 'source': 'cached'}}}


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def wire(monkeypatch, manager):
    monkeypatch.setattr(chat_endpoints, 'get_context_manager', lambda: manager)
    return manager


def test_the_read_rebuilds_for_the_requested_day(client, monkeypatch):
    manager = wire(monkeypatch, FakeContextManager())

    body = client.get(f'{PATH}/{USER}?date=2026-09-06').json()

    assert manager.rebuilt == [DAY]
    assert manager.read == [], 'a successful rebuild never touches the cache'
    assert body['success'] is True
    assert body['today_progress']['source'] == 'rebuilt'
    assert 'stale' not in body


def test_a_failed_rebuild_serves_the_cache_and_says_so(client, monkeypatch):
    """Declare staleness only when the fresh answer could not be produced."""
    manager = wire(monkeypatch, FakeContextManager(rebuild_fails=True))

    response = client.get(f'{PATH}/{USER}?date=2026-09-06')

    assert response.status_code == 200
    assert manager.rebuilt == [DAY] and manager.read == [DAY]
    body = response.json()
    assert body['stale'] is True
    assert body['today_progress']['source'] == 'cached'


def test_when_neither_works_it_is_a_500_not_an_empty_day(client, monkeypatch):
    wire(monkeypatch, FakeContextManager(rebuild_fails=True, read_fails=True))

    response = client.get(f'{PATH}/{USER}?date=2026-09-06')

    assert response.status_code == 500
    assert 'supabase' not in response.text, 'no exception text on the wire'


def test_a_malformed_date_is_a_400(client, monkeypatch):
    manager = wire(monkeypatch, FakeContextManager())

    assert client.get(f'{PATH}/{USER}?date=yesterday').status_code == 400
    assert manager.rebuilt == []


def test_no_date_resolves_to_the_users_day(client, monkeypatch):
    """26 hours apart, so a server-clock resolution cannot pass by luck."""
    manager = wire(monkeypatch, FakeContextManager())

    client.get(f'{PATH}/{USER}', headers={'X-Timezone-Offset': '840'})
    client.get(f'{PATH}/{USER}', headers={'X-Timezone-Offset': '-720'})

    assert manager.rebuilt[0] != manager.rebuilt[1]


# --- the incremental refresh is gone, everywhere ----------------------------


def test_the_context_manager_has_no_incremental_merge():
    for name in ('update_context_activity', 'remove_from_context'):
        assert not hasattr(ChatContextManager, name), (
            f'{name} is back. The cache is rebuilt on read; nothing should '
            f'merge into it incrementally (ADR-0008).'
        )


def test_no_write_endpoint_touches_the_context_manager():
    """The refresh cost every tracker write two round-trips for a cache with
    one reader that now rebuilds for itself. `api/sharing.py` keeps its
    rebuild: a toggle changes what the coach may see and should take effect
    before the next chat open, which does not go through this endpoint."""
    import api.exercise, api.meals, api.sleep, api.steps, api.supplements, api.water, api.weight

    for module in (api.exercise, api.meals, api.sleep, api.steps,
                   api.supplements, api.water, api.weight):
        source = inspect.getsource(module)
        assert 'get_context_manager' not in source, module.__name__
        assert 'context_manager' not in source, module.__name__
