"""Tests for pick_quote.py — scoring, selection, and fallback logic."""
from __future__ import annotations

import pytest

import pick_quote as pq
from tests.conftest import make_row

# ---------------------------------------------------------------------------
# minute_bucket
# ---------------------------------------------------------------------------

class TestMinuteBucket:
    def test_exact(self):
        assert pq.minute_bucket(0) == "exact"

    def test_just_after_boundaries(self):
        assert pq.minute_bucket(1) == "just_after"
        assert pq.minute_bucket(5) == "just_after"

    def test_early_past_boundaries(self):
        assert pq.minute_bucket(6) == "early_past"
        assert pq.minute_bucket(14) == "early_past"

    def test_quarter_pastish_boundaries(self):
        assert pq.minute_bucket(15) == "quarter_pastish"
        assert pq.minute_bucket(19) == "quarter_pastish"

    def test_half_pastish_boundaries(self):
        assert pq.minute_bucket(20) == "half_pastish"
        assert pq.minute_bucket(34) == "half_pastish"

    def test_late_past_boundaries(self):
        assert pq.minute_bucket(35) == "late_past"
        assert pq.minute_bucket(39) == "late_past"

    def test_quarter_toish_boundaries(self):
        assert pq.minute_bucket(40) == "quarter_toish"
        assert pq.minute_bucket(49) == "quarter_toish"

    def test_just_before_boundaries(self):
        assert pq.minute_bucket(50) == "just_before"
        assert pq.minute_bucket(59) == "just_before"

    def test_invalid_minute_raises(self):
        with pytest.raises(ValueError):
            pq.minute_bucket(60)


# ---------------------------------------------------------------------------
# bucket_for_time
# ---------------------------------------------------------------------------

class TestBucketForTime:
    def test_midnight_exact(self):
        assert pq.bucket_for_time("00:00") == "h12_exact"

    def test_noon_exact(self):
        assert pq.bucket_for_time("12:00") == "h12_exact"

    def test_hour12_wraps(self):
        # 13:00 -> hour12=1
        assert pq.bucket_for_time("13:00") == "h1_exact"

    def test_23_59(self):
        assert pq.bucket_for_time("23:59") == "h11_just_before"

    def test_3_30(self):
        assert pq.bucket_for_time("03:30") == "h3_half_pastish"

    def test_14_45(self):
        assert pq.bucket_for_time("14:45") == "h2_quarter_toish"


# ---------------------------------------------------------------------------
# metadata_bonus
# ---------------------------------------------------------------------------

class TestMetadataBonus:
    def test_both_present(self):
        assert pq.metadata_bonus({"author": "Austen", "title": "Emma"}) == -3

    def test_only_author(self):
        assert pq.metadata_bonus({"author": "Austen", "title": ""}) == -1

    def test_only_title(self):
        assert pq.metadata_bonus({"author": None, "title": "Emma"}) == -1

    def test_neither(self):
        assert pq.metadata_bonus({}) == 2


# ---------------------------------------------------------------------------
# dialogue_penalty
# ---------------------------------------------------------------------------

class TestDialoguePenalty:
    def test_no_dialogue(self):
        assert pq.dialogue_penalty({"display_quote": "The clock struck three."}) == 0

    def test_he_said(self):
        assert pq.dialogue_penalty({"display_quote": "It is three, he said quietly."}) == 2

    def test_she_said(self):
        assert pq.dialogue_penalty({"display_quote": "Three o'clock, she said."}) == 2

    def test_replied(self):
        assert pq.dialogue_penalty({"display_quote": "He replied at once."}) == 2

    def test_empty_quote(self):
        assert pq.dialogue_penalty({}) == 0


# ---------------------------------------------------------------------------
# opening_penalty
# ---------------------------------------------------------------------------

class TestOpeningPenalty:
    def test_neutral_opening(self):
        assert pq.opening_penalty({"display_quote": "The clock struck three."}) == 0

    def test_weak_opener_and(self):
        assert pq.opening_penalty({"display_quote": "And then the clock struck three."}) == 2

    def test_weak_opener_but(self):
        assert pq.opening_penalty({"display_quote": "But it was only three o'clock."}) == 2

    def test_pronoun_opener_he(self):
        assert pq.opening_penalty({"display_quote": "He arrived at three o'clock."}) == 1

    def test_pronoun_opener_she(self):
        assert pq.opening_penalty({"display_quote": "She heard three o'clock strike."}) == 1

    def test_empty(self):
        assert pq.opening_penalty({}) == 0


# ---------------------------------------------------------------------------
# override_bonus / is_banned
# ---------------------------------------------------------------------------

class TestOverrides:
    def test_no_override(self):
        overrides = {"preferred_buckets": {}, "boost_source_ids": [], "ban_source_ids": []}
        row = make_row(source_id="999")
        assert pq.override_bonus(row, overrides, "h3_exact") == 0

    def test_preferred_bucket_hit(self):
        overrides = {"preferred_buckets": {"h3_exact": 1234}, "boost_source_ids": [], "ban_source_ids": []}
        row = make_row(source_id="1234")
        assert pq.override_bonus(row, overrides, "h3_exact") == -5

    def test_preferred_bucket_miss(self):
        overrides = {"preferred_buckets": {"h3_exact": 1234}, "boost_source_ids": [], "ban_source_ids": []}
        row = make_row(source_id="9999")
        assert pq.override_bonus(row, overrides, "h3_exact") == 0

    def test_boost_source_id(self):
        overrides = {"preferred_buckets": {}, "boost_source_ids": [42], "ban_source_ids": []}
        row = make_row(source_id="42")
        assert pq.override_bonus(row, overrides, "h3_exact") == -3

    def test_is_banned_true(self):
        overrides = {"ban_source_ids": [1234], "boost_source_ids": [], "preferred_buckets": {}}
        row = make_row(source_id="1234")
        assert pq.is_banned(row, overrides) is True

    def test_is_banned_false(self):
        overrides = {"ban_source_ids": [9999], "boost_source_ids": [], "preferred_buckets": {}}
        row = make_row(source_id="1234")
        assert pq.is_banned(row, overrides) is False


# ---------------------------------------------------------------------------
# score_row
# ---------------------------------------------------------------------------

class TestScoreRow:
    def _overrides(self):
        return {"preferred_buckets": {}, "boost_source_ids": [], "ban_source_ids": []}

    def test_perfect_row_beats_fragment(self):
        good = make_row(display_fragment=False, cleanup_status="complete_sentence", quality_score=90,
                        display_quote="It was three o'clock in the afternoon.")
        bad = make_row(display_fragment=True, cleanup_status="fragment_fallback", quality_score=60,
                       display_quote="three o'clock")
        overrides = self._overrides()
        assert pq.score_row(good, "h3_exact", overrides) < pq.score_row(bad, "h3_exact", overrides)

    def test_higher_quality_wins(self):
        high = make_row(quality_score=95, display_quote="It was three o'clock.")
        low = make_row(quality_score=60, display_quote="It was three o'clock.")
        overrides = self._overrides()
        assert pq.score_row(high, "h3_exact", overrides) < pq.score_row(low, "h3_exact", overrides)

    def test_exactness_bonus_five_minutes_to(self):
        row = make_row(matched_text="five minutes to three", quality_score=80,
                       display_quote="It was five minutes to three.")
        overrides = self._overrides()
        score = pq.score_row(row, "h3_exact", overrides)
        # exactness_bonus = -2, so length_penalty + exactness_bonus < length_penalty alone
        row_no_bonus = make_row(matched_text="three o'clock", quality_score=80,
                                display_quote="It was five minutes to three.")
        score_no_bonus = pq.score_row(row_no_bonus, "h3_exact", overrides)
        assert score[8] < score_no_bonus[8]

    def test_exactness_bonus_quarter(self):
        row = make_row(matched_text="quarter past three", quality_score=80,
                       display_quote="It was quarter past three.")
        overrides = self._overrides()
        score = pq.score_row(row, "h3_exact", overrides)
        assert score[8] < abs(len("It was quarter past three.") - 140)

    def test_no_source_id_penalty(self):
        with_id = make_row(source_id="1234")
        without_id = make_row(source_id=None)
        overrides = self._overrides()
        assert pq.score_row(with_id, "h3_exact", overrides)[5] == 0
        assert pq.score_row(without_id, "h3_exact", overrides)[5] == 1


# ---------------------------------------------------------------------------
# neighbor_buckets
# ---------------------------------------------------------------------------

class TestNeighborBuckets:
    def test_first_bucket_expands_forward_only(self):
        neighbors = pq.neighbor_buckets("h3_exact")
        assert neighbors[0] == "h3_exact"
        assert "h3_just_after" in neighbors
        assert all(n.startswith("h3_") for n in neighbors)

    def test_last_bucket_expands_backward_only(self):
        neighbors = pq.neighbor_buckets("h3_just_before")
        assert neighbors[0] == "h3_just_before"
        assert "h3_quarter_toish" in neighbors

    def test_middle_bucket_expands_both_ways(self):
        neighbors = pq.neighbor_buckets("h3_half_pastish")
        assert "h3_quarter_pastish" in neighbors
        assert "h3_late_past" in neighbors

    def test_returns_all_states_eventually(self):
        neighbors = pq.neighbor_buckets("h3_exact")
        assert len(neighbors) == 8


# ---------------------------------------------------------------------------
# pick_best
# ---------------------------------------------------------------------------

class TestPickBest:
    def _overrides(self):
        return {"preferred_buckets": {}, "boost_source_ids": [], "ban_source_ids": []}

    def test_picks_highest_quality_in_bucket(self):
        rows = [
            make_row(fuzzy_bucket="h3_exact", quality_score=80, display_quote="It was three o'clock in the afternoon."),
            make_row(fuzzy_bucket="h3_exact", quality_score=95, display_quote="She heard three o'clock strike clearly."),
        ]
        best, bucket = pq.pick_best(rows, "h3_exact", 0, 60, self._overrides())
        assert best["quality_score"] == 95
        assert bucket == "h3_exact"

    def test_falls_back_to_neighbor_when_empty(self):
        rows = [
            make_row(fuzzy_bucket="h3_just_after", quality_score=80, display_quote="A few minutes past three."),
        ]
        best, bucket = pq.pick_best(rows, "h3_exact", 0, 60, self._overrides())
        assert bucket == "h3_just_after"
        assert best["fuzzy_bucket"] == "h3_just_after"

    def test_respects_min_quality(self):
        rows = [
            make_row(fuzzy_bucket="h3_exact", quality_score=40, display_quote="Three."),
            make_row(fuzzy_bucket="h3_just_after", quality_score=70, display_quote="Just after three the bell rang."),
        ]
        best, bucket = pq.pick_best(rows, "h3_exact", 0, 60, self._overrides())
        assert bucket == "h3_just_after"
        assert best["quality_score"] == 70

    def test_excludes_banned_source(self):
        overrides = {"ban_source_ids": ["1234"], "boost_source_ids": [], "preferred_buckets": {}}
        rows = [
            make_row(fuzzy_bucket="h3_exact", source_id="1234", quality_score=90,
                     display_quote="It was three o'clock."),
            make_row(fuzzy_bucket="h3_exact", source_id="5678", quality_score=70,
                     display_quote="She arrived at three."),
        ]
        best, _ = pq.pick_best(rows, "h3_exact", 0, 60, overrides)
        assert best["source_id"] == "5678"

    def test_raises_when_no_candidates(self):
        with pytest.raises(SystemExit):
            pq.pick_best([], "h3_exact", 0, 60, self._overrides())

    def test_seed_produces_stable_pick(self):
        rows = [
            make_row(fuzzy_bucket="h3_exact", quality_score=80,
                     display_quote="It was three o'clock in the hall."),
            make_row(fuzzy_bucket="h3_exact", quality_score=80,
                     display_quote="It was three o'clock in the hall."),
        ]
        best1, _ = pq.pick_best(rows, "h3_exact", seed=42, min_quality=60, overrides=self._overrides())
        best2, _ = pq.pick_best(rows, "h3_exact", seed=42, min_quality=60, overrides=self._overrides())
        assert best1["display_quote"] == best2["display_quote"]

    def test_used_fallback_flag_reflected_in_returned_bucket(self):
        rows = [make_row(fuzzy_bucket="h3_early_past", quality_score=80,
                         display_quote="It was about ten past three.")]
        _, resolved = pq.pick_best(rows, "h3_exact", 0, 60, self._overrides())
        assert resolved == "h3_early_past"
