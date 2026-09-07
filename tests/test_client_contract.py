"""Every path the Flutter client calls must reach a route here.

`CONTEXT.md`: "the HTTP contract between the two repos is the only real
coupling -- treat it as a designed interface, not an accident." Nothing
enforced that. A backend path can be renamed, or never have matched, and the
only symptom is a 404 inside a client `try/catch`.

That is not hypothetical. `api/chat.py` builds its router with
`prefix="/chat"` and then declared three routes as `@router.get("/chat/...")`,
so they were served at `/chat/chat/...`. Two of them are called by the client
on app open and on chat open, and both had always 404'd --
`ChatApi.checkAndResetDailyContext` swallows the failure and returns false, so
the daily context reset silently never ran.

The fixture is a snapshot of the client's call sites, so it cannot see paths
the client adds later; refresh it when the client's API surface changes. What
it does catch is this direction -- the backend not serving what the client
already calls -- which is the direction that fails silently.

Known exceptions are listed in UNSERVED below, each with a reason.
"""
import pathlib

import pytest
from starlette.routing import Match

import main

BASE = '/api/health'
FIXTURE = pathlib.Path(__file__).parent / 'fixtures' / 'nufi_app_client_paths.txt'

# Client call sites with no route here, deliberately not "fixed" by adding one.
# Each is dead on the client side: the method exists but nothing calls it.
# Listed rather than deleted from the fixture so that regenerating it does not
# silently resurrect them as failures.
UNSERVED = {
    # ExerciseApi.deleteExercise -- zero callers. The live delete is
    # deleteExerciseLog, which calls DELETE /exercise/log/{id} and is served.
    'DELETE /exercise/X',
    # ExerciseApi.updateExercise -- zero callers, and there is no exercise
    # update endpoint at all (ADR-0003: exercise and weight have no update).
    'PUT /exercise/X',
    # AuthApi.emailExists -- zero callers. The live login is AuthApi.login at
    # POST /auth/login, which is served; this one posts a dummy password to
    # /login and reads a 401 as "the email exists".
    'POST /login',
}


def client_calls():
    lines = [line.strip() for line in FIXTURE.read_text().splitlines()]
    return [line for line in lines if line and not line.startswith('#')]


def is_served(method, path):
    scope = {'type': 'http', 'method': method, 'path': BASE + path,
             'headers': [], 'query_string': b'', 'root_path': ''}
    return any(route.matches(scope)[0] == Match.FULL for route in main.app.routes)


@pytest.mark.parametrize('call', client_calls())
def test_every_client_path_reaches_a_route(call):
    method, path = call.split(' ', 1)

    if call in UNSERVED:
        pytest.skip(f'{call} is a dead client method (see UNSERVED)')

    assert is_served(method, path), (
        f"nufi_app calls {method} {BASE}{path} and nothing here serves it. "
        f"The client wraps its calls in try/catch, so this is a silent 404."
    )


@pytest.mark.parametrize('call', sorted(UNSERVED))
def test_the_known_exceptions_are_still_unserved(call):
    """If one of these starts working, it stops being an exception.

    Keeps UNSERVED from quietly becoming a list of stale excuses.
    """
    method, path = call.split(' ', 1)

    assert not is_served(method, path), (
        f"{call} is now served -- remove it from UNSERVED."
    )


def test_the_fixture_is_not_empty():
    """A regeneration that silently produced nothing would pass everything."""
    assert len(client_calls()) > 40
