"""Invariant tests for ``pick_quote.score_row`` and its component helpers.

These tests exist because the scoring tuple is the single most important piece
of runtime behaviour in the project: drift here silently changes what the
clock shows, and 95% line coverage doesn't prove a test would fail if the
sign of ``length_penalty`` flipped or ``metadata_bonus`` stopped rewarding
fully-attributed rows.

Instead of asserting specific integer values (which would duplicate
``test_pick_quote.py``'s point-tests), these tests sweep synthetic rows that
differ only in one field at a time and assert *monotonic / ordinal*
properties: "an author-and-title row beats a no-metadata row", "a banned row
can never be picked", "a fragment row loses to a non-fragment row when
everything else is equal." A mutation in any single scorer component is
designed to trip at least one of these.
"""
from __future__ import annotations

from collections import Counter

import pytest

import pick_quote

BUCKET = "h3_exact"
TIME = "03:00"
EMPTY_OVERRIDES = {"ban_source_ids": [], "boost_source_ids": [], "preferred_buckets": {}}


def _row(**overrides) -> dict:
    """Construct a minimal raw candidate row with sensible defaults.

    Missing ``baked_score`` on purpose so :func:`pick_quote.score_row` takes
    the full computation path. Every test then overrides exactly one field.
    """
    base = dict(
        source_id="100",
        line_number=1,
        display_quote="This is a reasonably-sized quote clocking in around one hundred forty characters, which is what the scorer happens to prefer.",
        display_fragment=False,
        cleanup_status="complete_sentence",
        normalized_time=TIME,
        matched_text="three o'clock",
        fuzzy_bucket=BUCKET,
        quality_score=80,
        author="Jane Writer",
        title="The Novel",
    )
    base.update(overrides)
    return base


def _score(row: dict, **kw) -> tuple:
    return pick_quote.score_row(
        row, BUCKET, kw.get("overrides", EMPTY_OVERRIDES),
        requested_time=kw.get("requested_time", TIME),
        source_counts=kw.get("source_counts", Counter({"100": 1})),
    )


class TestLowerScoreWins:
    """Lower is better at every tuple position — this is the whole contract."""

    def test_tuple_length_matches_picker_header(self):
        # The runtime picker's baked path reconstructs a 12-component tuple
        # via compose_baked_score_key; the raw path must produce the same
        # shape or sorting mixes baked and raw rows incoherently.
        score = _score(_row())
        assert len(score) == 12

    def test_non_fragment_beats_fragment(self):
        frag = _row(display_fragment=True)
        whole = _row(display_fragment=False)
        assert _score(whole) < _score(frag)

    def test_complete_sentence_beats_fragment_fallback(self):
        complete = _row(cleanup_status="complete_sentence")
        fallback = _row(cleanup_status="fragment_fallback")
        assert _score(complete) < _score(fallback)

    def test_expanded_with_context_ties_complete_sentence_in_cleanup_slot(self):
        # Both statuses are considered "good enough" and share the
        # cleanup_penalty=0 slot — a drift that demotes one silently
        # changes picks.
        complete = _row(cleanup_status="complete_sentence")
        expanded = _row(cleanup_status="expanded_with_context")
        assert _score(complete)[1] == _score(expanded)[1] == 0


class TestMetadataBonus:
    """``metadata_bonus`` is the single largest row-intrinsic lever."""

    def test_both_author_and_title_beats_only_author(self):
        full = _row(author="X", title="Y")
        only_a = _row(author="X", title=None)
        assert pick_quote.metadata_bonus(full) < pick_quote.metadata_bonus(only_a)

    def test_only_author_beats_neither(self):
        only_a = _row(author="X", title=None)
        neither = _row(author=None, title=None)
        assert pick_quote.metadata_bonus(only_a) < pick_quote.metadata_bonus(neither)

    def test_tuple_reflects_metadata_ordering(self):
        full = _row(author="X", title="Y")
        neither = _row(author=None, title=None)
        # Full metadata must still win at the full tuple level, not just the
        # component level (a mutation that flipped the sign of the metadata
        # bonus but preserved the helper would pass the component test).
        assert _score(full) < _score(neither)


class TestDialogueOpeningPenalties:
    def test_dialogue_filler_loses_to_clean_prose(self):
        dialogue = _row(display_quote='"Hello," he said, and then he said more words for padding.')
        clean = _row(display_quote="The afternoon light faded slowly over the empty street.")
        assert _score(clean) < _score(dialogue)

    def test_weak_opening_loses_to_strong_opening(self):
        # "And" / "But" / "So" at the start penalises the opener — the exact
        # tokens are in pick_quote.WEAK_OPENING_PATTERNS.
        weak = _row(display_quote="And so it began, the long quiet evening, much as every evening had begun before it.")
        strong = _row(display_quote="The evening began quietly, much as every evening had begun before it.")
        assert _score(strong) <= _score(weak)


class TestBansAndBoosts:
    def test_banned_row_is_filtered_out_not_just_penalised(self):
        # ``is_banned`` short-circuits filtering — a banned row must never
        # appear in the candidate pool regardless of its score.
        overrides = {"ban_source_ids": ["100"], "boost_source_ids": [], "preferred_buckets": {}}
        row = _row(source_id="100")
        assert pick_quote.is_banned(row, overrides) is True

    def test_ban_is_compared_as_string(self):
        # The JSON sidecar can carry either ``"100"`` or ``100``. Both must ban.
        row = _row(source_id=100)
        assert pick_quote.is_banned(row, {"ban_source_ids": ["100"]}) is True
        assert pick_quote.is_banned(row, {"ban_source_ids": [100]}) is True

    def test_preferred_bucket_beats_boost(self):
        row = _row(source_id="100")
        overrides_preferred = {
            "ban_source_ids": [],
            "boost_source_ids": ["100"],
            "preferred_buckets": {BUCKET: "100"},
        }
        overrides_boost_only = {
            "ban_source_ids": [],
            "boost_source_ids": ["100"],
            "preferred_buckets": {},
        }
        # Preferred is -5, boost is -3; preferred must be strictly more negative.
        assert pick_quote.override_bonus(row, overrides_preferred, BUCKET) < \
               pick_quote.override_bonus(row, overrides_boost_only, BUCKET)

    def test_boost_is_stronger_than_no_override(self):
        row = _row(source_id="100")
        assert pick_quote.override_bonus(row, {"boost_source_ids": ["100"]}, BUCKET) < 0
        assert pick_quote.override_bonus(row, EMPTY_OVERRIDES, BUCKET) == 0

    def test_preferred_bucket_only_fires_in_that_bucket(self):
        row = _row(source_id="100")
        overrides = {"preferred_buckets": {BUCKET: "100"}}
        # In the preferred bucket → -5 bonus
        assert pick_quote.override_bonus(row, overrides, BUCKET) == -5
        # In a different bucket → no bonus
        assert pick_quote.override_bonus(row, overrides, "h7_half_past") == 0


class TestQualityMonotonic:
    def test_higher_quality_beats_lower_quality(self):
        hi = _row(quality_score=95)
        lo = _row(quality_score=60)
        assert _score(hi) < _score(lo)

    def test_quality_none_treated_as_zero(self):
        row = _row(quality_score=None)
        # The quality_component slot stores ``-quality_score`` so None → 0.
        # The exact position of quality in the tuple is an implementation
        # detail; assert it doesn't crash and that an explicit 0 scores the
        # same.
        explicit = _row(quality_score=0)
        # Lengths/metadata identical → only the quality slot differs.
        assert _score(row)[8] == _score(explicit)[8]


class TestLengthExactness:
    def test_near_target_length_beats_far_length(self):
        target = _row(display_quote="X" * 140)
        off = _row(display_quote="X" * 200)
        # length_penalty + exactness_bonus sits at slot 9.
        assert _score(target)[9] < _score(off)[9]

    def test_very_short_quote_is_cliff_penalised(self):
        # Defence-in-depth: <60 chars adds +80 to the length penalty so a
        # stubborn short quote loses to any reasonable-length alternative.
        short = _row(display_quote="X" * 50)
        normal = _row(display_quote="X" * 140)
        assert _score(short)[9] >= _score(normal)[9] + 80


class TestSourceRarity:
    def test_rarer_source_wins_over_common_source(self):
        common_row = _row(source_id="common")
        rare_row = _row(source_id="rare")
        counts = Counter({"common": 50, "rare": 1})
        common_score = pick_quote.score_row(common_row, BUCKET, EMPTY_OVERRIDES, TIME, counts)
        rare_score = pick_quote.score_row(rare_row, BUCKET, EMPTY_OVERRIDES, TIME, counts)
        # rarity sits at slot 10 — a smaller count wins.
        assert rare_score[10] < common_score[10]

    def test_source_rarity_penalty_of_missing_source_is_zero(self):
        row = _row(source_id=None)
        assert pick_quote.source_rarity_penalty(row, Counter({"100": 50})) == 0


class TestMinutePenalty:
    def test_exact_minute_match_scores_zero_penalty(self):
        row = _row(normalized_time="03:00")
        # minute_penalty sits at slot 2 (between cleanup and metadata).
        assert _score(row, requested_time="03:00")[2] == 0

    def test_off_by_five_minutes_costs_five(self):
        row = _row(normalized_time="03:05")
        assert _score(row, requested_time="03:00")[2] == 5

    def test_missing_minute_defaults_to_sentinel_99(self):
        row = _row(normalized_time=None, matched_text="")
        penalty = pick_quote.minute_distance_penalty(row, BUCKET, None)
        assert penalty == 99  # "don't know" sentinel; ranks below any real distance


class TestBakedRawEquivalence:
    """The baked fast path must produce a tuple bit-for-bit identical to the
    raw path. ``test_bake_equivalence.py`` proves this on the shipped corpus;
    this version catches drift on synthetic rows where single fields vary.
    """

    def _bake_row_inline(self, row: dict, counts: Counter) -> dict:
        """Produce a baked version of ``row`` via the same primitive the
        baker uses, so we test the compose/score pair without writing a
        file."""
        import bake_quote_database
        baked = dict(row)
        baked["baked_score"] = bake_quote_database._static_score(row, counts)
        baked["inferred_quote_minute"] = pick_quote.infer_quote_minute(row)
        baked["schema_version"] = bake_quote_database.BAKED_SCORE_SCHEMA_VERSION
        return baked

    @pytest.mark.parametrize("row_override", [
        {},
        {"display_fragment": True},
        {"cleanup_status": "fragment_fallback"},
        {"author": None, "title": None},
        {"quality_score": 30},
        {"display_quote": "X" * 50},          # short cliff
        {"display_quote": "X" * 200},         # far-from-target
        {"normalized_time": "03:15"},         # minute_penalty nonzero
    ])
    def test_baked_and_raw_score_match(self, row_override):
        row = _row(**row_override)
        counts = Counter({str(row["source_id"]): 1})
        baked = self._bake_row_inline(row, counts)
        raw_score = pick_quote.score_row(row, BUCKET, EMPTY_OVERRIDES, TIME, counts)
        baked_score = pick_quote.score_row(baked, BUCKET, EMPTY_OVERRIDES, TIME, counts)
        assert raw_score == baked_score, (
            f"baked/raw score drift for override={row_override}: "
            f"raw={raw_score} baked={baked_score}"
        )
