"""The daily context reset is gone, and the stored row is served as it is.

`GET /chat/context/check/{id}` and `POST /chat/context/daily-reset/{id}` created
an empty `chat_contexts` row for the user's day. Nothing read that row without
first rebuilding it: the coach rebuilds before every reply (ADR-0006), the
context endpoint rebuilds on read (ADR-0008), and `get_or_create_context` --
the only reader of stored rows -- is reached on both paths after the rebuild
has overwritten the same row. The client discarded the result on both of its
calls. Two round-trips on every app open and chat open, for a row nobody read.
See ADR-0010.

`deduplicate_context` went with it. It cleaned rows the old incremental merge
had left with repeated meals; the merge was deleted in ADR-0008, and the two
rows that still carry duplicates are dated September 2025.
"""
import inspect

import pytest
from fastapi.testclient import TestClient

import api.chat as chat_endpoints
import main
from services.chat_context_manager import ChatContextManager


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.mark.parametrize('method,path', [
    ('GET', '/api/health/chat/context/check/u1'),
    ('POST', '/api/health/chat/context/daily-reset/u1'),
])
def test_the_reset_routes_are_not_served(client, method, path):
    # 405, not 404: `main.py` registers `OPTIONS /{rest_of_path:path}` for
    # CORS preflight, so every unknown path matches that route by path and
    # fails by method. Either way, nothing answers here.
    assert client.request(method, path).status_code in (404, 405)
    assert not any(
        getattr(route, 'path', '').startswith(path.rsplit('/', 1)[0])
        for route in main.app.routes
    ), 'a route still claims the path'


@pytest.mark.parametrize('name', ['ensure_daily_context', 'deduplicate_context'])
def test_the_methods_do_not_exist(name):
    assert not hasattr(ChatContextManager, name)


def test_no_endpoint_mentions_the_reset():
    source = inspect.getsource(chat_endpoints)
    for name in ('check_context_date', 'daily_context_reset', 'ensure_daily_context'):
        assert name not in source, name


class _StoredRow:
    """A fake client holding one stored context row, duplicates and all."""

    def __init__(self, context_data):
        self.context_data = context_data

    def table(self, _name):
        return self

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        return type('R', (), {'data': [{
            'context_data': self.context_data, 'version': 3, 'last_updated': 'x',
        }]})()


def test_the_stored_row_is_served_as_it_is():
    """No per-read cleanup: what `rebuild_context` wrote is what is read."""
    stored = {'today_progress': {'meals': [{'id': 'm1'}, {'id': 'm1'}],
                                 'exercises': [], 'totals': {'calories': 1}}}
    manager = object.__new__(ChatContextManager)
    manager.supabase_service = type('S', (), {'client': _StoredRow(stored)})()

    import asyncio
    from datetime import date
    result = asyncio.run(manager.get_or_create_context('u1', date(2026, 9, 6)))

    assert result['context'] is stored
