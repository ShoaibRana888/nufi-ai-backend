"""Behaviour of the pure derivations in services.health_trends."""
import pytest

from services import health_trends as ht


class TestWeightStatus:
    def test_missing_either_side_is_no_data(self):
        assert ht.weight_status(None, 70.0) == 'no_data'
        assert ht.weight_status(70.0, None) == 'no_data'
        assert ht.weight_status(None, None) == 'no_data'

    def test_zero_counts_as_missing_not_as_a_measurement(self):
        # A stored 0.0 is an unset field, not someone weighing nothing. The
        # client keys off this exact string.
        assert ht.weight_status(0, 70.0) == 'no_data'
        assert ht.weight_status(70.0, 0) == 'no_data'

    def test_within_half_a_kilo_is_at_goal_in_both_directions(self):
        assert ht.weight_status(70.0, 70.0) == 'at_goal'
        assert ht.weight_status(70.4, 70.0) == 'at_goal'
        assert ht.weight_status(69.6, 70.0) == 'at_goal'

    def test_half_a_kilo_exactly_is_not_at_goal(self):
        # Boundary is exclusive: 0.5 away reports a distance, not arrival.
        assert ht.weight_status(70.5, 70.0) == 'lose_0.5kg'

    def test_above_target_reports_the_distance_to_lose(self):
        assert ht.weight_status(83.2, 75.0) == 'lose_8.2kg'

    def test_below_target_reports_the_distance_to_gain(self):
        assert ht.weight_status(62.0, 68.0) == 'gain_6.0kg'

    def test_distance_is_rounded_to_one_decimal(self):
        assert ht.weight_status(80.06, 75.0) == 'lose_5.1kg'


class TestWeightTrend:
    def test_fewer_than_two_entries_is_insufficient(self):
        assert ht.weight_trend([]) == 'insufficient_data'
        assert ht.weight_trend([{'date': '2026-09-01', 'weight': 70.0}]) == 'insufficient_data'

    def test_change_under_the_noise_floor_is_stable(self):
        entries = [
            {'date': '2026-09-01', 'weight': 70.0},
            {'date': '2026-09-06', 'weight': 70.1},
        ]
        assert ht.weight_trend(entries) == 'stable'

    def test_rising_weight_reads_as_gaining(self):
        entries = [
            {'date': '2026-09-01', 'weight': 70.0},
            {'date': '2026-09-06', 'weight': 71.5},
        ]
        assert ht.weight_trend(entries) == 'gaining_1.5kg'

    def test_falling_weight_reads_as_losing(self):
        entries = [
            {'date': '2026-09-01', 'weight': 70.5},
            {'date': '2026-09-06', 'weight': 69.0},
        ]
        assert ht.weight_trend(entries) == 'losing_1.5kg'

    def test_arrival_order_does_not_change_the_answer(self):
        """Callers feed this from reads with opposite sort directions."""
        ascending = [
            {'date': '2026-09-01', 'weight': 70.5},
            {'date': '2026-09-03', 'weight': 70.0},
            {'date': '2026-09-06', 'weight': 69.0},
        ]
        assert ht.weight_trend(ascending) == 'losing_1.5kg'
        assert ht.weight_trend(list(reversed(ascending))) == 'losing_1.5kg'

    def test_only_the_endpoints_of_the_window_matter(self):
        """A midpoint excursion does not change first-to-last."""
        entries = [
            {'date': '2026-09-01', 'weight': 70.0},
            {'date': '2026-09-03', 'weight': 90.0},
            {'date': '2026-09-06', 'weight': 71.5},
        ]
        assert ht.weight_trend(entries) == 'gaining_1.5kg'

    def test_entries_missing_a_weight_are_read_as_zero(self):
        # Current behaviour, pinned rather than endorsed: a row without a
        # weight drags the trend to an absurd value instead of being skipped.
        entries = [
            {'date': '2026-09-01', 'weight': 70.0},
            {'date': '2026-09-06'},
        ]
        assert ht.weight_trend(entries) == 'losing_70.0kg'


class TestWeightDirection:
    def test_fewer_than_two_weights_is_stable_with_no_change(self):
        assert ht.weight_direction([]) == ('stable', 0.0)
        assert ht.weight_direction([70.0]) == ('stable', 0.0)

    def test_newest_first_ordering_means_first_minus_last(self):
        # get_weight_history returns newest first, so a higher head is a gain.
        label, change = ht.weight_direction([72.0, 70.0])
        assert label == 'gaining'
        assert change == pytest.approx(2.0)

        label, change = ht.weight_direction([68.0, 70.0])
        assert label == 'losing'
        assert change == pytest.approx(-2.0)

    def test_uses_a_coarser_threshold_than_the_coach_trend(self):
        """0.3kg is a trend for the coach but noise for the stats endpoint."""
        entries = [
            {'date': '2026-09-01', 'weight': 70.0},
            {'date': '2026-09-06', 'weight': 70.3},
        ]
        assert ht.weight_trend(entries) == 'gaining_0.3kg'
        assert ht.weight_direction([70.3, 70.0])[0] == 'stable'

    def test_the_threshold_itself_is_stable(self):
        assert ht.weight_direction([70.5, 70.0])[0] == 'stable'
        assert ht.weight_direction([70.51, 70.0])[0] == 'gaining'
