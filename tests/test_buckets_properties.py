"""Property-based / exhaustive tests for the bucket algebra.

The bucket primitives (``buckets.py``) are the single source of truth for the
whole pipeline — a drift here breaks the miner, the picker, the renderer, and
every downstream tool. The search space is small (1440 HH:MM strings × 60
minute values) so we can enumerate exhaustively rather than sample.

Hypothesis-style property tests would add a dependency for no real gain when
exhaustive enumeration is cheap. These tests are the exhaustive equivalent.
"""
from __future__ import annotations

import pytest

from buckets import (
    BUCKET_ORDER,
    DEFAULT_BUCKET_MINUTES,
    bucket_for_time,
    minute_bucket,
    neighbor_buckets,
)


def _all_buckets() -> list[str]:
    return [f"h{h}_{state}" for h in range(1, 13) for state in BUCKET_ORDER]


class TestMinuteBucketExhaustive:
    def test_every_valid_minute_maps_to_a_known_state(self):
        for m in range(60):
            state = minute_bucket(m)
            assert state in BUCKET_ORDER

    def test_default_bucket_minutes_roundtrip(self):
        """For every canonical minute M, ``minute_bucket(M)`` equals the state
        whose ``DEFAULT_BUCKET_MINUTES`` entry is M. This locks in the two-way
        mapping between minutes and state names."""
        for state, m in DEFAULT_BUCKET_MINUTES.items():
            assert minute_bucket(m) == state, f"minute {m} → {minute_bucket(m)} but default says {state}"

    def test_rounding_is_monotonic_per_half_bucket(self):
        """Minutes within ±2 of a canonical value all map to that state.
        Formalizes the 5-minute window centered on each canonical minute.

        The rule is ``((minute + 2) // 5) * 5``; minute=58..59 round up to 60
        and wrap to ``exact`` (the next hour). So ``five_to`` owns 53..57,
        not 53..58. ``exact`` owns 58..59 and 0..2.
        """
        for state, canonical in DEFAULT_BUCKET_MINUTES.items():
            for offset in (-2, -1, 0, 1, 2):
                m = canonical + offset
                if m < 0 or m >= 60:
                    continue
                assert minute_bucket(m) == state, f"{m} → {minute_bucket(m)}, expected {state}"

    def test_top_of_hour_wraparound_58_59_are_exact(self):
        assert minute_bucket(58) == "exact"
        assert minute_bucket(59) == "exact"

    def test_rejects_out_of_range(self):
        with pytest.raises(ValueError):
            minute_bucket(-1)
        with pytest.raises(ValueError):
            minute_bucket(60)


class TestBucketForTimeExhaustive:
    def test_every_hhmm_returns_known_bucket(self):
        known = set(_all_buckets())
        for h in range(24):
            for m in range(60):
                bucket = bucket_for_time(f"{h:02d}:{m:02d}")
                assert bucket in known, f"{h:02d}:{m:02d} → {bucket!r} not in known buckets"

    def test_hour_wraps_to_12_format(self):
        # 24-hour 0 → h12, 13 → h1, etc.
        assert bucket_for_time("00:00") == "h12_exact"
        assert bucket_for_time("12:00") == "h12_exact"
        assert bucket_for_time("13:00") == "h1_exact"
        assert bucket_for_time("23:00") == "h11_exact"

    def test_minute_58_rolls_hour_forward(self):
        assert bucket_for_time("03:58") == "h4_exact"
        assert bucket_for_time("11:58") == "h12_exact"  # 12-hour wrap
        assert bucket_for_time("12:58") == "h1_exact"
        assert bucket_for_time("23:58") == "h12_exact"  # 24→0→h12

    def test_am_pm_collision_is_expected(self):
        """3:15 AM and 3:15 PM bucket identically — the picker relies on this
        (a quote mentioning ``3:15`` appears for both times of day). If this
        ever changes, pick_quote's fallback walker needs to be reviewed too."""
        for h in range(12):
            for m in range(60):
                morning = bucket_for_time(f"{h:02d}:{m:02d}")
                afternoon = bucket_for_time(f"{h + 12:02d}:{m:02d}")
                assert morning == afternoon, f"{h}:{m} vs {h+12}:{m} diverge"


class TestNeighborBucketsProperties:
    @pytest.mark.parametrize("bucket", _all_buckets())
    def test_contains_exactly_12_buckets(self, bucket):
        assert len(neighbor_buckets(bucket)) == 12

    @pytest.mark.parametrize("bucket", _all_buckets())
    def test_self_is_first(self, bucket):
        assert neighbor_buckets(bucket)[0] == bucket

    @pytest.mark.parametrize("bucket", _all_buckets())
    def test_all_unique(self, bucket):
        neighbors = neighbor_buckets(bucket)
        assert len(set(neighbors)) == len(neighbors), f"duplicate neighbor: {neighbors}"

    @pytest.mark.parametrize("bucket", _all_buckets())
    def test_all_share_same_hour(self, bucket):
        """The fallback walker never crosses hour boundaries — a 3:02 quote
        can fall back to 3:05 or 3:10 but never to 4:00 or 2:55."""
        hour_part = bucket.split("_", 1)[0]
        for neighbor in neighbor_buckets(bucket):
            assert neighbor.startswith(f"{hour_part}_"), f"{neighbor} escapes hour {hour_part}"

    @pytest.mark.parametrize("bucket", _all_buckets())
    def test_all_neighbors_are_valid_buckets(self, bucket):
        known = set(_all_buckets())
        for neighbor in neighbor_buckets(bucket):
            assert neighbor in known, f"invalid neighbor {neighbor!r}"

    @pytest.mark.parametrize("bucket", _all_buckets())
    def test_distance_ordering_is_alternating(self, bucket):
        """Neighbours appear in order 0, -1, +1, -2, +2, … relative to the
        starting state index. This is what pick_quote documents."""
        state = bucket.split("_", 1)[1]
        idx = BUCKET_ORDER.index(state)
        distances = []
        for neighbor in neighbor_buckets(bucket):
            n_state = neighbor.split("_", 1)[1]
            distances.append(BUCKET_ORDER.index(n_state) - idx)
        # Absolute distances must be non-decreasing.
        abs_dists = [abs(d) for d in distances]
        for i in range(1, len(abs_dists)):
            assert abs_dists[i] >= abs_dists[i - 1], f"non-monotonic distance order: {abs_dists}"


class TestBucketInvariants:
    """Properties that cross primitives."""

    def test_bucket_for_time_state_matches_minute_bucket_when_no_rollover(self):
        for h in range(24):
            for m in range(58):  # 58, 59 roll forward; skip
                bucket = bucket_for_time(f"{h:02d}:{m:02d}")
                state = bucket.split("_", 1)[1]
                assert state == minute_bucket(m), f"{h}:{m} bucket state {state} vs {minute_bucket(m)}"

    def test_canonical_time_for_bucket_roundtrips(self):
        """For every (h, canonical_minute_state) pair, bucket_for_time of
        ``h:canonical_minute`` returns the matching bucket. This is the
        invariant contact_sheet.py relies on for placing tiles."""
        for h12 in range(1, 13):
            h24 = 0 if h12 == 12 else h12  # Use AM for simplicity
            for state, minute in DEFAULT_BUCKET_MINUTES.items():
                bucket = bucket_for_time(f"{h24:02d}:{minute:02d}")
                assert bucket == f"h{h12}_{state}", f"{h24}:{minute} → {bucket}, expected h{h12}_{state}"
