"""Tests for pick_quote.py — scoring, selection, and fallback logic.

The primitives (minute_bucket, bucket_for_time, neighbor_buckets) are owned by
``buckets`` and exercised in ``test_buckets.py``. This file tests pick_quote's
own selection logic.
"""
from __future__ import annotations

import pytest

import pick_quote as pq
from tests.conftest import make_row


class TestMetadataBonus:
    def test_both_present(self):
        assert pq.metadata_bonus({"author": "Austen", "title": "Emma"}) == -3

    def test_only_author(self):
        assert pq.metadata_bonus({"author": "Austen", "title": ""}) == -1

    def test_only_title(self):
        assert pq.metadata_bonus({"author": None, "title": "Emma"}) == -1

    def test_neither(self):
        assert pq.metadata_bonus({}) == 2


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
        row_no_bonus = make_row(matched_text="three o'clock", quality_score=80,
                                display_quote="It was five minutes to three.")
        score_no_bonus = pq.score_row(row_no_bonus, "h3_exact", overrides)
        assert score[9] < score_no_bonus[9]

    def test_exactness_bonus_quarter(self):
        row = make_row(matched_text="quarter past three", quality_score=80,
                       display_quote="It was quarter past three.")
        overrides = self._overrides()
        score = pq.score_row(row, "h3_exact", overrides)
        assert score[9] < abs(len("It was quarter past three.") - 140)

    def test_no_source_id_penalty(self):
        with_id = make_row(source_id="1234")
        without_id = make_row(source_id=None)
        overrides = self._overrides()
        assert pq.score_row(with_id, "h3_exact", overrides)[6] == 0
        assert pq.score_row(without_id, "h3_exact", overrides)[6] == 1

    def test_nearer_minute_wins_within_bucket(self):
        overrides = self._overrides()
        near = make_row(normalized_time="11:20", matched_text="twenty minutes past eleven", quality_score=90,
                        display_quote="It was twenty minutes past eleven.")
        far = make_row(normalized_time="11:25", matched_text="twenty-five minutes past eleven", quality_score=90,
                       display_quote="It was twenty-five minutes past eleven.")
        assert pq.score_row(near, "h11_twenty_past", overrides, "11:20") < pq.score_row(far, "h11_twenty_past", overrides, "11:20")


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
            make_row(fuzzy_bucket="h3_five_past", quality_score=80, display_quote="A few minutes past three."),
        ]
        best, bucket = pq.pick_best(rows, "h3_exact", 0, 60, self._overrides())
        assert bucket == "h3_five_past"
        assert best["fuzzy_bucket"] == "h3_five_past"

    def test_respects_min_quality(self):
        rows = [
            make_row(fuzzy_bucket="h3_exact", quality_score=40, display_quote="Three."),
            make_row(fuzzy_bucket="h3_five_past", quality_score=70, display_quote="Just after three the bell rang."),
        ]
        best, bucket = pq.pick_best(rows, "h3_exact", 0, 60, self._overrides())
        assert bucket == "h3_five_past"
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
        rows = [make_row(fuzzy_bucket="h3_ten_past", quality_score=80,
                         display_quote="It was about ten past three.")]
        _, resolved = pq.pick_best(rows, "h3_exact", 0, 60, self._overrides())
        assert resolved == "h3_ten_past"
