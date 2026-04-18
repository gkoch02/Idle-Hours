"""Tests for the shared buckets module — the single source of truth for fuzzy-bucket naming."""
from __future__ import annotations

import pytest

import buckets as bk


class TestMinuteBucket:
    def test_exact_window(self):
        assert bk.minute_bucket(0) == "exact"
        assert bk.minute_bucket(1) == "exact"
        assert bk.minute_bucket(2) == "exact"
        assert bk.minute_bucket(58) == "exact"
        assert bk.minute_bucket(59) == "exact"

    def test_rounding_windows(self):
        assert bk.minute_bucket(3) == "five_past"
        assert bk.minute_bucket(7) == "five_past"
        assert bk.minute_bucket(8) == "ten_past"
        assert bk.minute_bucket(12) == "ten_past"
        assert bk.minute_bucket(13) == "quarter_past"
        assert bk.minute_bucket(17) == "quarter_past"
        assert bk.minute_bucket(18) == "twenty_past"
        assert bk.minute_bucket(22) == "twenty_past"
        assert bk.minute_bucket(23) == "twenty_five_past"
        assert bk.minute_bucket(27) == "twenty_five_past"
        assert bk.minute_bucket(28) == "half_past"
        assert bk.minute_bucket(32) == "half_past"
        assert bk.minute_bucket(33) == "twenty_five_to"
        assert bk.minute_bucket(37) == "twenty_five_to"
        assert bk.minute_bucket(38) == "twenty_to"
        assert bk.minute_bucket(42) == "twenty_to"
        assert bk.minute_bucket(43) == "quarter_to"
        assert bk.minute_bucket(47) == "quarter_to"
        assert bk.minute_bucket(48) == "ten_to"
        assert bk.minute_bucket(52) == "ten_to"
        assert bk.minute_bucket(53) == "five_to"
        assert bk.minute_bucket(57) == "five_to"

    def test_invalid_minute_raises(self):
        with pytest.raises(ValueError):
            bk.minute_bucket(60)
        with pytest.raises(ValueError):
            bk.minute_bucket(-1)

    def test_every_valid_minute_resolves(self):
        # Every 0-59 value must map to a declared state name.
        for m in range(60):
            assert bk.minute_bucket(m) in bk.BUCKET_ORDER


class TestBucketForTime:
    def test_midnight_exact(self):
        assert bk.bucket_for_time("00:00") == "h12_exact"

    def test_noon_exact(self):
        assert bk.bucket_for_time("12:00") == "h12_exact"

    def test_hour12_wraps(self):
        assert bk.bucket_for_time("13:00") == "h1_exact"

    def test_23_59_rolls_to_midnight(self):
        assert bk.bucket_for_time("23:59") == "h12_exact"

    def test_3_30(self):
        assert bk.bucket_for_time("03:30") == "h3_half_past"

    def test_14_45(self):
        assert bk.bucket_for_time("14:45") == "h2_quarter_to"

    def test_rollover_bumps_hour(self):
        # 02:58 rounds up to the next hour's "exact".
        assert bk.bucket_for_time("02:58") == "h3_exact"

    def test_11_58_rolls_into_noon(self):
        # 11:58 → noon (h12).
        assert bk.bucket_for_time("11:58") == "h12_exact"


class TestNeighborBuckets:
    def test_first_bucket_expands_forward_only(self):
        neighbors = bk.neighbor_buckets("h3_exact")
        assert neighbors[0] == "h3_exact"
        assert "h3_five_past" in neighbors
        assert all(n.startswith("h3_") for n in neighbors)

    def test_last_bucket_expands_backward_only(self):
        neighbors = bk.neighbor_buckets("h3_five_to")
        assert neighbors[0] == "h3_five_to"
        assert "h3_ten_to" in neighbors

    def test_middle_bucket_expands_both_ways(self):
        neighbors = bk.neighbor_buckets("h3_half_past")
        assert "h3_twenty_five_past" in neighbors
        assert "h3_twenty_five_to" in neighbors

    def test_returns_all_states_exactly_once(self):
        neighbors = bk.neighbor_buckets("h3_exact")
        assert len(neighbors) == 12
        assert len(set(neighbors)) == 12


class TestBucketOrderMatchesMinutes:
    def test_every_state_has_a_minute(self):
        for state in bk.BUCKET_ORDER:
            assert state in bk.DEFAULT_BUCKET_MINUTES

    def test_default_minutes_round_trip(self):
        # Each declared default-minute value must round back to its own state name.
        for state, minute in bk.DEFAULT_BUCKET_MINUTES.items():
            assert bk.minute_bucket(minute) == state
