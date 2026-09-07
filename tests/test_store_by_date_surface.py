"""Locks the store's by-date read surface.

Three trackers used to carry *two* by-date reads each -- an older one with no
`shared_only` parameter, and a newer shared-aware one -- with nothing in the
names to say which was which. The unsafe variant was the more widely used one
in every case. Nothing had leaked, but only because every caller happened to
be an owner-facing endpoint; one chat-path caller picking the wrong name would
have quietly fed the coach entries the user had hidden from it.

These tests make that class of mistake fail loudly instead of silently.
"""
import inspect

import pytest

from services.supabase_service import SupabaseService

# Deleted in the candidate #2 cleanup. If one of these comes back, it is almost
# certainly someone re-adding a non-shared-aware twin.
REMOVED = [
    'get_water_entry_by_date',
    'get_step_entry_by_date',
    'get_sleep_entry_by_date',
]

# The by-date reads that get_shared_activities_for_date composes. Every one of
# them is reached on an AI/chat path, so every one must be able to filter.
SHARED_AWARE = [
    'get_meals_by_date',
    'get_water_by_date',
    'get_steps_by_date',
    'get_sleep_by_date',
    'get_exercises_by_date',
    'get_weight_by_date',
    'get_supplement_status_by_date',
    'get_active_period_for_date',
]

# The complete by-date surface. Locked so that adding a read to it is a
# deliberate act with a test change attached, rather than a second way to ask
# the same question.
EXPECTED_BY_DATE_SURFACE = set(SHARED_AWARE) | {
    # Owner-facing, deliberately unfiltered:
    #   - a single named supplement's log for a day
    #   - the meals read behind daily_summary and the meal history endpoints.
    #     Not folded into get_meals_by_date: it takes a str date, projects an
    #     explicit column list and orders desc. Worth revisiting, but it is not
    #     the same method wearing a different name.
    'get_supplement_log_by_date',
    'get_user_meals_by_date',
    # The two composed doors. Same plumbing (_activities_for_date), two
    # interfaces: the coach's shared subset and the owner's full day. Distinct
    # names rather than one read with a flag -- see ADR-0002 and ADR-0004.
    'get_shared_activities_for_date',
    'get_owner_activities_for_date',
}

# The two public day reads, and the shared_only value each one stands for.
COMPOSED_READS = {
    'get_shared_activities_for_date': 'True',
    'get_owner_activities_for_date': 'False',
}


@pytest.mark.parametrize('name', REMOVED)
def test_the_non_shared_aware_twins_stay_deleted(name):
    assert not hasattr(SupabaseService, name), (
        f"{name} is back. It was a duplicate of the shared-aware read with no "
        f"shared_only parameter; use the shared-aware one instead."
    )


@pytest.mark.parametrize('name', SHARED_AWARE)
def test_every_read_on_a_chat_path_can_filter_by_shared(name):
    method = getattr(SupabaseService, name)
    params = inspect.signature(method).parameters

    assert 'shared_only' in params, (
        f"{name} feeds get_shared_activities_for_date, so it must accept "
        f"shared_only -- otherwise the coach sees entries the user hid."
    )
    assert params['shared_only'].default is False, (
        f"{name}'s shared_only must default to False: the owner's own views "
        f"are the common caller and they should see everything."
    )


def test_the_by_date_surface_is_exactly_what_we_expect():
    """One question, one method. A second read for the same tracker is how the
    duplicate-pair hazard got in the first time."""
    actual = {
        name for name in dir(SupabaseService)
        if name.startswith('get_')
        and (name.endswith('_by_date') or name.endswith('_for_date'))
    }

    assert actual == EXPECTED_BY_DATE_SURFACE, (
        f"unexpected: {sorted(actual - EXPECTED_BY_DATE_SURFACE)}, "
        f"missing: {sorted(EXPECTED_BY_DATE_SURFACE - actual)}"
    )


def test_the_composed_read_covers_every_tracker():
    """The one composition behind both day reads touches every tracker."""
    source = inspect.getsource(SupabaseService._activities_for_date)

    for name in SHARED_AWARE:
        assert name in source, f"{name} is not composed into the day read"


@pytest.mark.parametrize('name', sorted(COMPOSED_READS))
def test_neither_public_day_read_takes_a_flag(name):
    """The conflation guard.

    A `shared_only` parameter on either of these is how the coach's view and
    the owner's view become one read that callers pick the wrong half of. The
    flag lives on the private composition; the public names carry the meaning.
    """
    params = inspect.signature(getattr(SupabaseService, name)).parameters

    assert set(params) == {'self', 'user_id', 'target_date'}, (
        f"{name} takes {sorted(set(params) - {'self'})}. Whether a day read is "
        f"shared-only must be fixed by the method's name, not by an argument."
    )


@pytest.mark.parametrize('name,shared_only', sorted(COMPOSED_READS.items()))
def test_each_public_day_read_delegates_with_the_right_flag(name, shared_only):
    source = inspect.getsource(getattr(SupabaseService, name))

    assert '_activities_for_date' in source, (
        f"{name} should compose _activities_for_date, not re-derive the day."
    )
    assert f'shared_only={shared_only}' in source, (
        f"{name} must pass shared_only={shared_only}."
    )
