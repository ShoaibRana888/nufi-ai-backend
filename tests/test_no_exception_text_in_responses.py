"""A response body is not a log line.

111 handlers put `str(e)` in a response -- 96 as `HTTPException(500,
detail=str(e))`, 13 as `{'error': str(e)}`, 2 in f-strings -- plus three
`error=str(e)` fields in auth's response models. For a PostgREST failure that
is the SQL message, the Postgres error code and a hint naming tables and
columns; for an HTTP failure the request URL with the project host. No route
has auth. `_read_errors` was the first such door closed (ADR-0007); this is
the other 114, through one helper.

The same catch-all was also turning deliberate 4xx into 500s: a handler
raised `HTTPException(404)` inside its `try`, and `except Exception as e:
raise HTTPException(500, detail=str(e))` answered 500 with the detail
"404: User not found". `internal_error` passes an HTTPException through.
"""
import pathlib
import re

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api.users as users_endpoints
import api.water as water_endpoints
import main
from utils.errors import INTERNAL_ERROR_DETAIL, internal_error, public_message

API_DIR = pathlib.Path(__file__).parent.parent / 'api'

# `str(e)` or `{e}` on a line that builds a response -- a `detail=`, an
# `'error':` key, or an `error=` model field. Log lines are exempt.
RESPONSE_LINE = re.compile(r"""(detail\s*=|['"]error['"]\s*:|\berror\s*=)""")
EXCEPTION_TEXT = re.compile(r"""str\(e\)|\{e\}|\{str\(e\)\}""")


def test_no_handler_puts_exception_text_in_a_response():
    offenders = []
    for path in sorted(API_DIR.glob('*.py')):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if 'print(' in line:
                continue
            if RESPONSE_LINE.search(line) and EXCEPTION_TEXT.search(line):
                offenders.append(f'{path.name}:{number}: {line.strip()}')
    assert offenders == [], (
        'exception text in a response body -- use internal_error(e) / '
        'public_message(e):\n' + '\n'.join(offenders)
    )


# --- the helper ---------------------------------------------------------------


def test_a_deliberate_http_exception_passes_through_unchanged():
    deliberate = HTTPException(status_code=404, detail='User not found')

    assert internal_error(deliberate) is deliberate
    assert public_message(deliberate) == 'User not found'


def test_anything_else_becomes_a_generic_500():
    leaky = RuntimeError("{'message': 'column daily_water.total_glasses does not exist', "
                         "'code': '42703'}")

    produced = internal_error(leaky)

    assert produced.status_code == 500
    assert produced.detail == INTERNAL_ERROR_DETAIL
    assert public_message(leaky) == INTERNAL_ERROR_DETAIL


# --- through real handlers ----------------------------------------------------


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def test_a_missing_user_is_a_404_not_a_500(client, monkeypatch):
    """Was: 500 with detail "404: User not found"."""
    class _Store:
        async def get_user_by_id(self, user_id):
            return None

    monkeypatch.setattr(users_endpoints, 'get_supabase_service', lambda: _Store())

    response = client.get('/api/users/nobody')

    assert response.status_code == 404
    assert response.json() == {'detail': 'User not found'}


def test_a_store_failure_is_a_500_with_no_exception_text(client, monkeypatch):
    class _Store:
        async def get_water_history(self, user_id, limit=30):
            raise RuntimeError(
                "Server error '500' for url "
                "'https://wehzxcqudlfvewilgokf.supabase.co/rest/v1/daily_water'"
            )

    monkeypatch.setattr(water_endpoints, 'get_supabase_service', lambda: _Store())

    response = client.get('/api/health/water/u1/history')

    assert response.status_code == 500
    assert response.json() == {'detail': INTERNAL_ERROR_DETAIL}
    for leaked in ('supabase.co', 'daily_water', 'rest/v1'):
        assert leaked not in response.text, leaked
