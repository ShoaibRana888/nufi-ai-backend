"""No two handlers may claim the same path and method.

Starlette matches routes in registration order and the first match wins, with
no warning. `GET /api/health/daily-summary/{user_id}` was registered twice --
by api/daily_summary.py at include #12 and api/activity_check.py at #16 -- so
the second handler had been unreachable for as long as both existed.

It had rotted accordingly, in ways that prove nothing ever called it: it read
`water_entry['total_glasses']` where the column is `glasses_consumed`, and it
treated `get_supplement_status_by_date`'s values as booleans after that method
started returning dicts, making its `logged` flag unconditionally true.

Twenty-odd routers are mounted under a handful of shared prefixes, so this is
easy to do again -- and the failure is silent. This test makes it loud.
"""
from collections import defaultdict

import main


def test_no_two_routes_share_a_path_and_method():
    claims = defaultdict(list)

    for route in main.app.routes:
        path = getattr(route, 'path', None)
        endpoint = getattr(route, 'endpoint', None)
        if path is None or endpoint is None:
            continue
        for method in getattr(route, 'methods', None) or ():
            claims[(method, path)].append(
                f"{endpoint.__module__}.{endpoint.__name__}"
            )

    shadowed = {key: names for key, names in claims.items() if len(names) > 1}

    assert not shadowed, "\n".join(
        f"{method} {path} is claimed by {names} -- only {names[0]} is "
        f"reachable" for (method, path), names in sorted(shadowed.items())
    )
