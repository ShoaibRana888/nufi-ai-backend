"""A route declared inside a prefixed router must not repeat that prefix.

`api/chat.py` builds its router as `APIRouter(prefix="/chat")`, and three of
its routes were then declared as `@router.post("/chat/...")`. FastAPI
concatenates, so they were served at `/api/health/chat/chat/...` -- a path no
caller ever guesses. Two of the three are called by the Flutter client on app
open and on chat open, and both had always 404'd; `checkAndResetDailyContext`
swallows the failure and returns false, so the daily context reset silently
never ran.

Nothing about this is visible at a call site or in a route decorator read on
its own -- the prefix lives in a different line of a different part of the
file. This test reads both.
"""
import importlib
import pkgutil

import pytest
from fastapi import APIRouter

import api


def router_modules():
    """Every api.* module that exposes an APIRouter."""
    found = []
    for info in pkgutil.iter_modules(api.__path__):
        module = importlib.import_module(f'api.{info.name}')
        for attr in vars(module).values():
            if isinstance(attr, APIRouter):
                found.append((f'api.{info.name}', attr))
                break
    return found


@pytest.mark.parametrize('name,router', router_modules(),
                         ids=[n for n, _ in router_modules()])
def test_no_route_repeats_its_routers_prefix(name, router):
    prefix = router.prefix
    if not prefix:
        pytest.skip(f'{name} has no router prefix')

    # APIRouter applies its prefix when the decorator runs, so route.path
    # already carries it exactly once. A second copy means the decorator
    # spelled the prefix out again.
    repeated = []
    for route in router.routes:
        path = getattr(route, 'path', '')
        if not path.startswith(prefix):
            continue
        rest = path[len(prefix):]
        if rest == prefix or rest.startswith(f'{prefix}/'):
            repeated.append(path)

    assert not repeated, (
        f"{name}'s router has prefix {prefix!r} and these routes name it again, "
        f"so they are served at {prefix}{prefix}/... where no caller will look: "
        f"{sorted(set(repeated))}"
    )
