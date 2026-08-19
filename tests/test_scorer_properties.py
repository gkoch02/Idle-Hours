"""Property-style invariant tests for the scoring tuple.

``test_scorer_invariants.py`` asserts pairwise ordinal properties on carefully
chosen rows: "an author+title row beats a no-metadata row," etc. Those are
excellent guards but they only exercise a handful of shape points. This module
complements them with *systematic sweeps* that would catch mutations the
pairwise tests miss:

* **Lexicographic dominance.** The scoring tuple is compared position by
  position, with earlier positions strictly dominating later ones. A mutation
  that accidentally collapses two adjacent positions (e.g. both
  ``minute_penalty`` and ``metadata_bonus`` getting summed) would still pass a
  "lower quality loses" test, but would fail a dominance sweep that forces an
  earlier-position worse-by-1 to win against a later-position better-by-100.

* **Position-isolation.** Each scorer component should only affect one
  position in the tuple. A refactor that duplicates a component into two
  positions would compound its effect and break fairness.

* **Request-time component recomputation.** ``minute_penalty`` and
  ``override_bonus`` are the only two components that change per-request — the
  rest are row-intrinsic. We pin that contract by asserting that, holding the
  row fixed, mutating ``requested_time`` or ``overrides`` only touches those
  two positions.

* **Baked/raw interleave correctness.** ``compose_baked_score_key`` stitches
  the two request-time components back into the baked tuple at positions 2
  and 7. A drift in which positions get interleaved would silently make baked
  picks diverge from raw picks — the existing equivalence suite pins one
  corpus, but this sweeps many shapes.

These tests follow ``test_buckets_properties.py``'s pattern: exhaustive
enumeration over a small bounded space, no Hypothesis dependency.
"""
from __future__ import annotations

from collections import Counter

import pytest

from idle_hours import pick_quote

BUCKET = "h3_exact"
TIME = "03:00"
EMPTY_OVERRIDES = {"ban_source_ids": [], "boost_source_ids": [], "preferred_buckets": {}}


def _row(**overrides) -> dict:
    """Canonical mid-scoring row — every pairwise swap below starts from this."""
    base = dict(
        source_id="100",
        line_number=1,
        display_quote=(
            "This is a reasonably-sized quote clocking in around one hundred forty "
            "characters, which is what the scorer happens to prefer."
        ),
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


def _score(row: dict, *, overrides: dict = EMPTY_OVERRIDES, time: str = TIME,
           source_counts: Counter | None = None) -> tuple:
    return pick_quote.score_row(
        row, BUCKET, overrides,
        requested_time=time,
        source_counts=source_counts if source_counts is not None else Counter({"100": 1}),
    )


# Positions that change per-request; every other position should be invariant
# to ``requested_time`` and ``overrides``. If one of these constants goes out
# of sync with the actual tuple, every downstream consumer silently drifts.
MINUTE_POSITION = pick_quote.SCORE_COMPONENTS.index("minute_penalty")
OVERRIDE_POSITION = pick_quote.SCORE_COMPONENTS.index("override_bonus")
REQUEST_TIME_POSITIONS = {MINUTE_POSITION, OVERRIDE_POSITION}


class TestTupleLayoutPinning:
    """Catch accidental reordering or resizing of the score tuple.

    The ``score_row`` tuple layout is referenced from the web curator UI, the
    bake stage, and ``compose_baked_score_key`` — reordering it silently here
    would cascade. These tests lock the contract.
    """

    def test_tuple_has_exactly_twelve_components(self):
        score = _score(_row())
        assert len(score) == len(pick_quote.SCORE_COMPONENTS) == 12

    def test_minute_penalty_is_at_documented_position(self):
        """``compose_baked_score_key`` hardcodes position 2 for the interleave."""
        assert MINUTE_POSITION == 2

    def test_override_bonus_is_at_documented_position(self):
        """``compose_baked_score_key`` hardcodes position 7 for the interleave."""
        assert OVERRIDE_POSITION == 7

    def test_baked_components_omit_the_two_request_time_slots(self):
        """The baker bakes every component except the two that change per-request."""
        baked = set(pick_quote.BAKED_SCORE_COMPONENTS)
        live = set(pick_quote.SCORE_COMPONENTS)
        assert live - baked == {"minute_penalty", "override_bonus"}


class TestLexicographicDominance:
    """Earlier positions in the tuple must strictly dominate later ones.

    Sort key: tuple compared element-by-element, lower wins. A mutation that
    summed adjacent components (or dropped one into another's slot) would
    break this dominance. We construct row pairs where a *single earlier
    position* differs by 1 and a *single later position* differs by a huge
    amount in the opposite direction — the earlier-position row must still win.
    """

    def test_fragment_dominates_every_later_component(self):
        """``fragment_penalty`` is at position 0. A fragment row must lose to
        a non-fragment row even if the non-fragment row is worse on *every*
        subsequent axis (short, low quality, no metadata, dialogue, weak opener).
        """
        non_fragment = _row(
            display_fragment=False,
            display_quote="Short.",           # triggers short-quote cliff
            quality_score=0,
            author=None, title=None,
            cleanup_status="fragment_fallback",
        )
        fragment = _row(display_fragment=True)
        assert _score(non_fragment) < _score(fragment)

    def test_cleanup_dominates_every_later_component_except_fragment(self):
        """``cleanup_penalty`` at position 1: a ``fragment_fallback`` row
        must lose to a ``complete_sentence`` row of otherwise terrible quality.
        """
        clean = _row(
            cleanup_status="complete_sentence",
            display_quote="Short.",
            quality_score=0,
            author=None, title=None,
        )
        dirty = _row(cleanup_status="fragment_fallback")
        assert _score(clean) < _score(dirty)

    def test_minute_penalty_of_one_dominates_quality_delta_of_hundred(self):
        """``minute_penalty`` at position 2 dominates ``quality_component`` at
        position 8. A row one minute closer to the requested time wins even if
        it's 100 quality points worse.
        """
        closer_low_quality = _row(
            normalized_time="03:00",
            matched_text="three o'clock",
            quality_score=0,
        )
        farther_high_quality = _row(
            normalized_time="03:05",
            matched_text="five past three",
            quality_score=100,
        )
        assert _score(closer_low_quality) < _score(farther_high_quality)


class TestMonotonicityInQuality:
    """Holding every other input fixed, a higher quality score must weakly
    improve (never worsen) the score. The component is stored negated so
    "higher quality" means "more negative" means "earlier in sort order."
    """

    @pytest.mark.parametrize("quality_a,quality_b", [
        (0, 1), (50, 51), (99, 100), (30, 90), (0, 100),
    ])
    def test_higher_quality_weakly_beats_lower(self, quality_a, quality_b):
        lo, hi = _row(quality_score=quality_a), _row(quality_score=quality_b)
        assert _score(hi) <= _score(lo)

    def test_strict_monotonicity_at_quality_slot(self):
        """Sweep the full 0..100 quality range and confirm the quality slot
        is strictly monotonic. A mutation that clamped or wrapped quality would
        produce a non-monotonic slot series.
        """
        slot_idx = pick_quote.SCORE_COMPONENTS.index("quality_component")
        slots = [_score(_row(quality_score=q))[slot_idx] for q in range(0, 101, 5)]
        # quality is stored as ``-quality_score`` so the slot series must be
        # strictly *decreasing* as q increases. Equal adjacent values mean two
        # quality points collapsed — a mutation.
        for prev, curr in zip(slots, slots[1:]):
            assert curr < prev, f"quality slot not strictly monotonic: {slots}"


class TestMinutePenaltyDominatesTiesOnLaterFields:
    """Position 2 (``minute_penalty``) must tiebreak against positions 3+
    even when later positions would otherwise give a different winner. This is
    what "earlier is more important" buys you in practice.
    """

    def test_one_minute_closer_wins_vs_metadata_bonus(self):
        """Row A is one minute closer but has no metadata. Row B is one minute
        further but has full metadata. A wins on minute_penalty at position 2.
        """
        closer_no_meta = _row(
            normalized_time="03:00", matched_text="three o'clock",
            author=None, title=None,
        )
        further_full_meta = _row(
            normalized_time="03:05", matched_text="five past three",
            author="J. Writer", title="The Novel",
        )
        assert _score(closer_no_meta) < _score(further_full_meta)

    def test_one_minute_closer_wins_vs_dialogue_penalty(self):
        closer_dialogue = _row(
            normalized_time="03:00", matched_text="three o'clock",
            display_quote="'It's three o'clock,' he said, setting down his book.",
        )
        further_clean = _row(
            normalized_time="03:05", matched_text="five past three",
            display_quote="The clock had struck five past three some moments before.",
        )
        assert _score(closer_dialogue) < _score(further_clean)

    def test_one_minute_closer_wins_vs_quality_swing(self):
        """Even a 99-point quality swing must lose to a 1-minute delta."""
        closer_bad = _row(
            normalized_time="03:00", matched_text="three o'clock",
            quality_score=1,
        )
        further_great = _row(
            normalized_time="03:05", matched_text="five past three",
            quality_score=100,
        )
        assert _score(closer_bad) < _score(further_great)


class TestPreferredBucketVsBoost:
    """A row hit by ``preferred_buckets`` must beat a row hit by
    ``boost_source_ids``. The bonuses are -5 and -3 respectively, and they
    share the same tuple position, so preferred must win.
    """

    def test_preferred_beats_boost_when_both_apply(self):
        """Row A is preferred for this bucket; Row B is boosted. Equal otherwise."""
        overrides = {
            "ban_source_ids": [],
            "preferred_buckets": {BUCKET: "200"},
            "boost_source_ids": ["201"],
        }
        preferred = _row(source_id="200")
        boosted = _row(source_id="201")
        score_pref = _score(preferred, overrides=overrides,
                            source_counts=Counter({"200": 1, "201": 1}))
        score_boost = _score(boosted, overrides=overrides,
                             source_counts=Counter({"200": 1, "201": 1}))
        assert score_pref < score_boost

    def test_preferred_only_applies_to_matching_source(self):
        """A preferred entry for source 200 must not discount source 201."""
        overrides = {
            "ban_source_ids": [],
            "preferred_buckets": {BUCKET: "200"},
            "boost_source_ids": [],
        }
        pos = OVERRIDE_POSITION
        target_hit = _score(_row(source_id="200"), overrides=overrides)
        target_miss = _score(_row(source_id="999"), overrides=overrides)
        assert target_hit[pos] == -5
        assert target_miss[pos] == 0

    def test_preferred_bucket_bonus_is_strictly_stronger_than_boost(self):
        """Numerical pin: the absolute gap between -5 (preferred) and -3
        (boost) must survive any refactor of ``override_bonus``.
        """
        overrides_pref = {
            "ban_source_ids": [], "boost_source_ids": [],
            "preferred_buckets": {BUCKET: "100"},
        }
        overrides_boost = {
            "ban_source_ids": [], "preferred_buckets": {},
            "boost_source_ids": ["100"],
        }
        pos = OVERRIDE_POSITION
        pref_bonus = _score(_row(), overrides=overrides_pref)[pos]
        boost_bonus = _score(_row(), overrides=overrides_boost)[pos]
        assert pref_bonus == -5
        assert boost_bonus == -3
        assert pref_bonus < boost_bonus


class TestPositionIsolation:
    """Each scorer component should only move one position in the tuple.

    A refactor that duplicated a component into two positions, or that made
    one component leak into another's slot, would break these.
    """

    def test_changing_only_quality_moves_only_quality_slot(self):
        baseline = _score(_row(quality_score=50))
        moved = _score(_row(quality_score=90))
        diffs = [i for i in range(len(baseline)) if baseline[i] != moved[i]]
        assert diffs == [pick_quote.SCORE_COMPONENTS.index("quality_component")], (
            f"quality change leaked into other positions: {diffs}"
        )

    def test_changing_only_author_and_title_moves_only_metadata_slot(self):
        baseline = _score(_row(author="A", title="T"))
        moved = _score(_row(author=None, title=None))
        diffs = [i for i in range(len(baseline)) if baseline[i] != moved[i]]
        assert diffs == [pick_quote.SCORE_COMPONENTS.index("metadata_bonus")], (
            f"metadata change leaked into other positions: {diffs}"
        )

    def test_changing_only_fragment_flag_moves_only_fragment_slot(self):
        baseline = _score(_row(display_fragment=False))
        moved = _score(_row(display_fragment=True))
        diffs = [i for i in range(len(baseline)) if baseline[i] != moved[i]]
        assert diffs == [pick_quote.SCORE_COMPONENTS.index("fragment_penalty")], (
            f"fragment-flag change leaked into other positions: {diffs}"
        )


class TestRequestTimeRecomputation:
    """Only two positions (``minute_penalty`` and ``override_bonus``) depend
    on per-request inputs. Every other position must be invariant to changes
    in ``requested_time`` and ``overrides``. This is the contract baked-row
    caching relies on.
    """

    def test_changing_requested_time_moves_only_minute_slot(self):
        """A row-intrinsic-only view: holding the row and overrides fixed,
        scanning ``requested_time`` across the full hour must only move the
        ``minute_penalty`` position in the score tuple. If any other position
        moves, the bake/raw equivalence contract is broken.
        """
        row = _row(normalized_time="03:00", matched_text="three o'clock")
        base_score = _score(row, time="03:00")
        for minute in range(0, 60):
            t = f"03:{minute:02d}"
            score = _score(row, time=t)
            for pos in range(len(base_score)):
                if pos == MINUTE_POSITION:
                    continue
                assert score[pos] == base_score[pos], (
                    f"time {t} moved position {pos} ({pick_quote.SCORE_COMPONENTS[pos]})"
                )

    def test_changing_overrides_moves_only_override_slot(self):
        """Scanning ``override_bonus`` from -5 (preferred) through -3 (boost)
        to 0 (neither) must only move position 7."""
        row = _row(source_id="100")
        variants = [
            # (overrides, expected_bonus)
            ({"ban_source_ids": [], "boost_source_ids": [],
              "preferred_buckets": {BUCKET: "100"}}, -5),
            ({"ban_source_ids": [], "preferred_buckets": {},
              "boost_source_ids": ["100"]}, -3),
            (EMPTY_OVERRIDES, 0),
        ]
        scores = [_score(row, overrides=ov) for ov, _ in variants]
        base = scores[0]
        for score, (_, expected_bonus) in zip(scores, variants):
            assert score[OVERRIDE_POSITION] == expected_bonus
            for pos in range(len(base)):
                if pos == OVERRIDE_POSITION:
                    continue
                assert score[pos] == base[pos], (
                    f"overrides change moved non-override position {pos}"
                )


class TestBakedInterleaveEquivalence:
    """``compose_baked_score_key`` stitches the two request-time components
    back into a baked tuple. The result must be bit-identical to
    ``score_row`` on the raw (non-baked) form of the same row.

    ``test_bake_equivalence.py`` already sweeps all 144 canonical buckets for
    one corpus; this adds shape-variation sweeps that don't depend on the
    committed corpus file.
    """

    @pytest.mark.parametrize("author,title,fragment,cleanup,quality,source_id", [
        ("A", "T", False, "complete_sentence", 80, "100"),
        (None, None, False, "complete_sentence", 60, "100"),
        ("A", None, True, "fragment_fallback", 40, "100"),
        (None, "T", False, "expanded_with_context", 90, None),
        ("A", "T", True, "fragment_fallback", 0, "100"),
    ])
    def test_baked_matches_raw_across_shapes(
        self, author, title, fragment, cleanup, quality, source_id,
    ):
        """For every corner of the row shape-space, the baked and raw paths
        must agree. A mutation in either path would diverge here.
        """
        # Build a raw row and compute its score.
        raw = _row(
            author=author, title=title,
            display_fragment=fragment, cleanup_status=cleanup,
            quality_score=quality, source_id=source_id,
            normalized_time="03:05", matched_text="five past three",
        )
        counts = Counter({"100": 1}) if source_id else Counter()
        raw_score = _score(raw, source_counts=counts)

        # Build the baked version: inline the nine row-intrinsic components
        # and the source rarity at positions matching BAKED_SCORE_COMPONENTS.
        # The interleave must re-produce the full 12-tuple exactly.
        baked = dict(raw)
        baked["inferred_quote_minute"] = 5
        # Extract the same components the baker would have computed.
        baked["baked_score"] = [
            raw_score[0], raw_score[1],             # fragment_penalty, cleanup_penalty
            raw_score[3], raw_score[4], raw_score[5], raw_score[6],  # meta/dialogue/opening/source
            raw_score[8], raw_score[9],             # quality_component, length_exactness
            raw_score[10], raw_score[11],           # source_rarity_penalty, length_tiebreak
        ]
        baked_score = _score(baked, source_counts=counts)
        assert baked_score == raw_score, (
            f"baked/raw drift: baked={baked_score} raw={raw_score}"
        )


class TestMinutePenaltySweep:
    """``minute_distance_penalty`` should produce the correct circular
    distance for every (requested_minute, quote_minute) pair, with 99 as the
    sentinel for missing information.
    """

    def test_circular_distance_over_all_pairs(self):
        """Brute-force: for every pair in [0..55] step 5, the penalty must
        equal the wrap-around clock-face distance min(d, 60-d). Plain abs()
        penalised an 11:58 quote 58 minutes away from a 12:00 request even
        though it is 2 minutes early (#184)."""
        for requested in range(0, 60, 5):
            for quote_minute in range(0, 60, 5):
                row = {
                    "normalized_time": f"03:{quote_minute:02d}",
                    "matched_text": "",
                }
                bucket = "h3_exact"  # bucket's default minute matches when requested_time is None
                penalty = pick_quote.minute_distance_penalty(
                    row, bucket, f"03:{requested:02d}",
                )
                d = abs(requested - quote_minute)
                assert penalty == min(d, 60 - d), (
                    f"requested={requested} quote={quote_minute}: got {penalty}"
                )

    def test_top_of_hour_rollover_pairs(self):
        """The concrete #184 failure: a :58 quote lands in the next hour's
        exact bucket (bucket_for_time rounds 58 up), where it must score
        distance 2 from the :00 request — not 58."""
        row = {"normalized_time": "11:58", "matched_text": ""}
        assert pick_quote.minute_distance_penalty(row, "h12_exact", "12:00") == 2
        row55 = {"normalized_time": "03:55", "matched_text": ""}
        assert pick_quote.minute_distance_penalty(row55, "h4_exact", "04:00") == 5

    def test_missing_minute_returns_sentinel(self):
        row_no_minute = {"normalized_time": None, "matched_text": ""}
        assert pick_quote.minute_distance_penalty(row_no_minute, BUCKET, None) == 99
        assert pick_quote.minute_distance_penalty(row_no_minute, BUCKET, "03:00") == 99


class TestScoreRowPurity:
    """``score_row`` must not mutate its inputs — the same row scored twice
    must produce the same tuple, and the second call must not see any
    leftover state from the first. This is what lets ``pick_best`` sort
    in-place without cloning.
    """

    def test_repeated_scoring_is_deterministic(self):
        row = _row()
        a = _score(row)
        b = _score(row)
        c = _score(row)
        assert a == b == c

    def test_scoring_does_not_mutate_row_fields(self):
        row = _row()
        snapshot = dict(row)
        _score(row)
        assert row == snapshot, (
            "score_row mutated a row field: "
            f"before={snapshot} after={row}"
        )

    def test_scoring_does_not_mutate_overrides(self):
        overrides = {
            "ban_source_ids": ["200"],
            "boost_source_ids": ["100"],
            "preferred_buckets": {BUCKET: "100"},
        }
        snapshot = {k: v.copy() for k, v in overrides.items()}
        _score(_row(source_id="100"), overrides=overrides)
        assert overrides == snapshot, (
            "score_row mutated overrides: "
            f"before={snapshot} after={overrides}"
        )
