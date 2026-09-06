# services/health_trends.py
"""Pure derivations over a user's logged activity. No I/O, no Supabase.

Named `health_trends`, not `health_insights`: everything here answers "which
way is this user moving?" over a window of entries. That is a different
question from the client's `dayStatus` projection in `nufi_app`
(`lib/data/services/day_status.dart`), which answers "is this user at their
goal today?" over a single day. ADR-0002 in `nufi_app` calls `dayStatus` the
twin of this module; it is a cousin. See `docs/adr/0001-extract-health-trends.md`.

**The string encodings here are on the wire.** `weight_status` values reach the
Flutter client through `GET /chat/context/{user_id}` as
`goals_progress.weight_progress.status`, and the client compares against the
literal `'no_data'`. They are also persisted verbatim in
`chat_contexts.context_data`. Structured values would read better in isolation
and would break both. Changing an encoding here is a contract change.

Every function in this module is synchronous and takes plain data. That is
enforced by `tests/test_health_trends_purity.py`, not by convention.
"""
from typing import Any, Mapping, Optional, Sequence, Tuple

# A weight change smaller than this reads as noise rather than a trend, for the
# coach's narrative vocabulary.
TREND_NOISE_KG = 0.2

# The weight-stats endpoint uses a coarser threshold than the coach does: it
# reports a 30-day direction, where 0.2kg really is noise.
DIRECTION_NOISE_KG = 0.5

# Distance from target within which the user counts as having arrived.
AT_GOAL_KG = 0.5


def weight_status(current: Optional[float], target: Optional[float]) -> str:
    """Where the user stands against their target weight.

    Returns `'no_data'`, `'at_goal'`, `'lose_<n>kg'` or `'gain_<n>kg'`.

    `'no_data'` covers a missing *or zero* value on either side, because a
    stored 0.0 weight is missing data rather than a real measurement. The
    client depends on this exact string.
    """
    if not current or not target:
        return 'no_data'

    diff = abs(current - target)
    if diff < AT_GOAL_KG:
        return 'at_goal'
    if current > target:
        return f'lose_{diff:.1f}kg'
    return f'gain_{diff:.1f}kg'


def weight_trend(entries: Sequence[Mapping[str, Any]]) -> str:
    """Direction of travel across a window of weight entries, for the coach.

    Returns `'insufficient_data'`, `'stable'`, `'gaining_<n>kg'` or
    `'losing_<n>kg'`. Entries are ordered here by their `date` field rather
    than trusted in arrival order, because callers source them from reads with
    differing sort directions.
    """
    if len(entries) < 2:
        return 'insufficient_data'

    ordered = sorted(entries, key=lambda e: e.get('date', ''))
    change = ordered[-1].get('weight', 0) - ordered[0].get('weight', 0)

    if abs(change) < TREND_NOISE_KG:
        return 'stable'
    if change > 0:
        return f'gaining_{abs(change):.1f}kg'
    return f'losing_{abs(change):.1f}kg'


def weight_direction(weights: Sequence[float]) -> Tuple[str, float]:
    """Direction and net change for the weight-stats endpoint.

    Returns `(label, total_change)` where label is `'gaining'`, `'losing'` or
    `'stable'` — a coarser vocabulary than `weight_trend`'s, on a coarser
    threshold, and part of the `GET /weight/{user_id}/stats` response shape.

    Deliberately *not* merged with `weight_trend`: same word, two concepts, two
    audiences. `weights` is expected newest-first, matching
    `get_weight_history`, so the change is `first - last`.
    """
    if len(weights) < 2:
        return 'stable', 0.0

    total_change = weights[0] - weights[-1]
    if total_change > DIRECTION_NOISE_KG:
        return 'gaining', total_change
    if total_change < -DIRECTION_NOISE_KG:
        return 'losing', total_change
    return 'stable', total_change
