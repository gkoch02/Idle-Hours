"""Tests for pick_quote.py — scoring, selection, and fallback logic.

The primitives (minute_bucket, bucket_for_time, neighbor_buckets) are owned by
``buckets`` and exercised in ``test_buckets.py``. This file tests pick_quote's
own selection logic.
"""
from __future__ import annotations

import datetime as dt
import json

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
        # Display quote kept well above the 60-char short-quote floor so the
        # length_penalty component is just |len - 140| + exactness_bonus.
        display = "It was quarter past three when the bells in the tower rang out across the square."
        row = make_row(matched_text="quarter past three", quality_score=80, display_quote=display)
        overrides = self._overrides()
        score = pq.score_row(row, "h3_exact", overrides)
        assert score[9] < abs(len(display) - 140)

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

    def test_expanded_with_context_treated_as_clean(self):
        # cleanup_penalty (tuple index 1) must be 0 for both "complete_sentence"
        # and the new "expanded_with_context" status; otherwise expanded runs
        # would be unfairly penalised in ranking.
        overrides = self._overrides()
        expanded = make_row(display_fragment=False, cleanup_status="expanded_with_context",
                            quality_score=80, display_quote="A well-formed sentence run joined across a paragraph boundary and carrying real literary context.")
        assert pq.score_row(expanded, "h3_exact", overrides)[1] == 0

    def test_short_quote_floor_penalises_under_60_chars(self):
        # Two rows, identical except for display_quote length. The short one
        # should have a strictly larger length_penalty component (tuple index 9).
        overrides = self._overrides()
        short = make_row(quality_score=80, display_quote="It was three o'clock.")  # 21 chars
        medium = make_row(quality_score=80,
                          display_quote="It was three o'clock when the bells began to ring across the square loudly.")  # 75 chars
        short_score = pq.score_row(short, "h3_exact", overrides)
        medium_score = pq.score_row(medium, "h3_exact", overrides)
        # Medium quote (75 chars) has length_penalty = |75-140| = 65.
        # Short quote (21 chars) has length_penalty = |21-140| + 80 = 199.
        assert short_score[9] > medium_score[9]
        assert short_score[9] >= abs(len(short["display_quote"]) - 140) + 80

    def test_short_quote_floor_not_applied_at_60_chars(self):
        overrides = self._overrides()
        # Exactly 60 chars — floor must not apply.
        exactly_60 = "a" * 60 + "."
        row = make_row(quality_score=80, display_quote=exactly_60)
        score = pq.score_row(row, "h3_exact", overrides)
        assert score[9] == abs(len(exactly_60) - 140)


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

    def test_return_ranked_yields_sorted_pool_with_scores(self):
        rows = [
            make_row(fuzzy_bucket="h3_exact", quality_score=60,
                     display_quote="A rougher three o'clock phrase."),
            make_row(fuzzy_bucket="h3_exact", quality_score=95,
                     display_quote="A pristine three o'clock line."),
            make_row(fuzzy_bucket="h3_exact", quality_score=75,
                     display_quote="A mid-tier three o'clock line."),
        ]
        chosen, resolved, ranked = pq.pick_best(
            rows, "h3_exact", 0, 60, self._overrides(), return_ranked=True,
        )
        assert resolved == "h3_exact"
        # Ranked list is a sorted pool of {"row": ..., "score": tuple}.
        assert len(ranked) == 3
        assert ranked[0]["row"]["quality_score"] == 95
        assert isinstance(ranked[0]["score"], tuple)
        assert chosen["quality_score"] == 95


class TestSelectCandidates:
    def _write_corpus(self, tmp_jsonl, monkeypatch, tmp_path):
        rows = [
            make_row(fuzzy_bucket="h3_exact", source_id="141", line_number=1,
                     quality_score=95, display_quote="A pristine three o'clock line."),
            make_row(fuzzy_bucket="h3_exact", source_id="142", line_number=2,
                     quality_score=80, display_quote="Another three o'clock line, slightly worse."),
            make_row(fuzzy_bucket="h3_exact", source_id="143", line_number=3,
                     quality_score=60, display_quote="A barely-passing three o'clock line."),
        ]
        corpus = tmp_jsonl(rows)
        overrides = tmp_path / "overrides.json"
        overrides.write_text(
            json.dumps({"ban_source_ids": [], "boost_source_ids": [], "preferred_buckets": {}})
        )
        return corpus, overrides

    def test_select_candidates_returns_named_score_components(self, tmp_jsonl, monkeypatch, tmp_path):
        corpus, overrides = self._write_corpus(tmp_jsonl, monkeypatch, tmp_path)
        result = pq.select_candidates(
            bucket="h3_exact",
            top_n=3,
            input_path=str(corpus),
            overrides_path=str(overrides),
        )
        assert len(result) == 3
        first = result[0]
        # Every SCORE_COMPONENTS key must be present and numeric.
        for component in pq.SCORE_COMPONENTS:
            assert component in first["score"]
        # Winner flag points at the top-ranked row.
        winners = [e for e in result if e["is_winner"]]
        assert len(winners) == 1
        assert winners[0]["row"]["source_id"] == "141"

    def test_select_candidates_requires_time_or_bucket(self, tmp_jsonl, monkeypatch, tmp_path):
        corpus, overrides = self._write_corpus(tmp_jsonl, monkeypatch, tmp_path)
        with pytest.raises(ValueError, match="requires time_str or bucket"):
            pq.select_candidates(
                input_path=str(corpus),
                overrides_path=str(overrides),
            )

    def test_select_candidates_respects_top_n(self, tmp_jsonl, monkeypatch, tmp_path):
        corpus, overrides = self._write_corpus(tmp_jsonl, monkeypatch, tmp_path)
        result = pq.select_candidates(
            bucket="h3_exact",
            top_n=1,
            input_path=str(corpus),
            overrides_path=str(overrides),
        )
        assert len(result) == 1
        assert result[0]["is_winner"] is True

    def test_select_candidates_accepts_time_str(self, tmp_jsonl, monkeypatch, tmp_path):
        corpus, overrides = self._write_corpus(tmp_jsonl, monkeypatch, tmp_path)
        result = pq.select_candidates(
            time_str="03:00",
            top_n=3,
            input_path=str(corpus),
            overrides_path=str(overrides),
        )
        assert len(result) == 3
        assert result[0]["resolved_bucket"] == "h3_exact"


class TestSourceRarityTiebreak:
    def _overrides(self):
        return {"preferred_buckets": {}, "boost_source_ids": [], "ban_source_ids": []}

    def test_rarer_source_wins_tie(self):
        common = make_row(fuzzy_bucket="h3_exact", source_id="111", quality_score=80,
                          display_quote="It was three o'clock in the hall.")
        rare = make_row(fuzzy_bucket="h3_exact", source_id="999", quality_score=80,
                        display_quote="It was three o'clock in the hall.")
        # Pad the corpus with many rows from source 111 so it's heavily over-represented.
        filler = [make_row(fuzzy_bucket="h5_exact", source_id="111", quality_score=50) for _ in range(20)]
        rows = [common, rare, *filler]
        best, _ = pq.pick_best(rows, "h3_exact", seed=0, min_quality=60, overrides=self._overrides())
        assert best["source_id"] == "999"

    def test_rarity_penalty_is_cumulative_but_not_dominant(self):
        # A rare-source row should still lose to a high-quality common-source row,
        # because the rarity penalty is a tiebreak, not a primary ranking axis.
        high_quality_common = make_row(fuzzy_bucket="h3_exact", source_id="111", quality_score=95,
                                       display_quote="It was three o'clock in the hall.")
        mediocre_rare = make_row(fuzzy_bucket="h3_exact", source_id="999", quality_score=65,
                                 display_quote="It was three o'clock in the hall.")
        filler = [make_row(fuzzy_bucket="h5_exact", source_id="111", quality_score=50) for _ in range(20)]
        rows = [high_quality_common, mediocre_rare, *filler]
        best, _ = pq.pick_best(rows, "h3_exact", seed=0, min_quality=60, overrides=self._overrides())
        assert best["source_id"] == "111"

    def test_count_sources_ignores_rows_without_source_id(self):
        rows = [
            make_row(source_id="111"),
            make_row(source_id="111"),
            make_row(source_id=None),
            make_row(source_id="222"),
        ]
        counts = pq.count_sources(rows)
        assert counts == {"111": 2, "222": 1}


class TestRecentHistory:
    def _write_ledger(self, path, entries):
        with path.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

    def test_empty_when_disabled(self, tmp_path):
        path = tmp_path / "history.jsonl"
        self._write_ledger(path, [{"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "source_id": "1", "line_number": 1}])
        assert pq.load_recent_history(str(path), 0) == set()
        assert pq.load_recent_history("", 7) == set()
        assert pq.load_recent_history(None, 7) == set()

    def test_returns_empty_when_file_missing(self, tmp_path):
        assert pq.load_recent_history(str(tmp_path / "nope.jsonl"), 7) == set()

    def test_includes_recent_excludes_old(self, tmp_path):
        path = tmp_path / "history.jsonl"
        now = dt.datetime.now(dt.timezone.utc)
        entries = [
            {"ts": (now - dt.timedelta(days=1)).isoformat(), "source_id": "1", "line_number": 100},
            {"ts": (now - dt.timedelta(days=30)).isoformat(), "source_id": "2", "line_number": 200},
            {"ts": now.isoformat(), "source_id": "3", "line_number": 300},
        ]
        self._write_ledger(path, entries)
        recent = pq.load_recent_history(str(path), 7)
        assert ("1", 100) in recent
        assert ("3", 300) in recent
        assert ("2", 200) not in recent

    def test_skips_malformed_lines(self, tmp_path, capsys):
        path = tmp_path / "history.jsonl"
        with path.open("w") as f:
            f.write("not-json\n")
            f.write(json.dumps({"ts": "bogus-date", "source_id": "1", "line_number": 1}) + "\n")
            f.write(json.dumps({"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "source_id": "ok", "line_number": 42}) + "\n")
            f.write(json.dumps({"ts": dt.datetime.now(dt.timezone.utc).isoformat()}) + "\n")  # missing fields
        recent = pq.load_recent_history(str(path), 7)
        assert recent == {("ok", 42)}
        # We now log a single warning on stderr when a parse-error line is encountered
        # so ledger corruption from a crashed write doesn't silently defeat anti-repeat.
        err = capsys.readouterr().err
        assert "malformed line skipped" in err
        # "subsequent bad lines ... suppressed" is part of the one-shot message, so it
        # appears exactly once even though there are two unparseable lines above.
        assert err.count("malformed line skipped") == 1

    def test_malformed_line_warning_is_suppressed_after_first(self, tmp_path, capsys):
        path = tmp_path / "history.jsonl"
        with path.open("w") as f:
            for _ in range(5):
                f.write("not-json\n")
        pq.load_recent_history(str(path), 7)
        err = capsys.readouterr().err
        # All 5 bad lines, but only one warning — otherwise a fully-corrupt ledger would spam stderr.
        assert err.count("malformed line skipped") == 1

    def test_append_history_writes_entry(self, tmp_path):
        path = tmp_path / "history.jsonl"
        pq.append_history(str(path), "1234", 5678)
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["source_id"] == "1234"
        assert entry["line_number"] == 5678
        assert "ts" in entry

    def test_append_history_is_noop_when_path_empty(self, tmp_path):
        pq.append_history("", "1234", 5678)
        pq.append_history(None, "1234", 5678)
        # No file created, no exception.
        assert not (tmp_path / "history.jsonl").exists()

    def test_append_history_is_noop_for_missing_fields(self, tmp_path):
        path = tmp_path / "history.jsonl"
        pq.append_history(str(path), None, 1)
        pq.append_history(str(path), "1", None)
        assert not path.exists()

    def test_append_history_creates_parent_dir(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "history.jsonl"
        pq.append_history(str(path), "1234", 5678)
        assert path.exists()

    def test_append_history_fsyncs_before_close(self, tmp_path):
        """The write path must fsync so a power loss immediately after an
        append can't leave the line in the kernel page cache and vanish."""
        path = tmp_path / "history.jsonl"
        from unittest.mock import patch
        with patch("pick_quote.os.fsync") as mock_fsync:
            pq.append_history(str(path), "1234", 5678)
        # Exactly one fsync call per append.
        assert mock_fsync.call_count == 1
        # Targeted at a real, opened file descriptor (not stdin/stdout/stderr),
        # so a future refactor that accidentally fsyncs the wrong fd fails here.
        fd_arg = mock_fsync.call_args[0][0]
        assert isinstance(fd_arg, int) and fd_arg >= 3
        # Write still succeeded even though fsync was mocked to a no-op.
        entry = json.loads(path.read_text().strip())
        assert entry["source_id"] == "1234"

    def test_remove_last_history_entry_removes_most_recent_match(self, tmp_path):
        path = tmp_path / "history.jsonl"
        pq.append_history(str(path), "1", 1)
        pq.append_history(str(path), "2", 2)
        pq.append_history(str(path), "1", 1)  # duplicate — we expect this one to go
        removed = pq.remove_last_history_entry(str(path), "1", 1)
        assert removed is True
        remaining = [json.loads(line) for line in path.read_text().splitlines()]
        # The first (1, 1) entry must still be there; only the duplicate was removed.
        assert [(e["source_id"], e["line_number"]) for e in remaining] == [("1", 1), ("2", 2)]

    def test_remove_last_history_entry_returns_false_when_no_match(self, tmp_path):
        path = tmp_path / "history.jsonl"
        pq.append_history(str(path), "1", 1)
        assert pq.remove_last_history_entry(str(path), "42", 99) is False
        # Unchanged.
        assert len(path.read_text().splitlines()) == 1

    def test_remove_last_history_entry_noop_for_empty_path(self, tmp_path):
        assert pq.remove_last_history_entry("", "1", 1) is False
        assert pq.remove_last_history_entry(None, "1", 1) is False

    def test_remove_last_history_entry_noop_when_file_missing(self, tmp_path):
        path = tmp_path / "missing.jsonl"
        assert pq.remove_last_history_entry(str(path), "1", 1) is False

    def test_remove_last_history_entry_leaves_empty_file_when_last_removed(self, tmp_path):
        path = tmp_path / "history.jsonl"
        pq.append_history(str(path), "1", 1)
        assert pq.remove_last_history_entry(str(path), "1", 1) is True
        assert path.read_text() == ""

    def test_remove_last_history_entry_atomic_on_replace_failure(self, tmp_path, monkeypatch):
        """A mid-rewrite crash must leave the original ledger untouched, not wiped."""
        import os

        path = tmp_path / "history.jsonl"
        pq.append_history(str(path), "1", 1)
        pq.append_history(str(path), "2", 2)
        original = path.read_text(encoding="utf-8")

        monkeypatch.setattr(
            os, "replace", lambda s, d: (_ for _ in ()).throw(OSError("simulated power loss"))
        )
        with pytest.raises(OSError):
            pq.remove_last_history_entry(str(path), "1", 1)

        # Ledger must be byte-identical to pre-call state — no truncation, no tmp left behind.
        assert path.read_text(encoding="utf-8") == original
        assert list(tmp_path.glob("*.tmp")) == []

    def test_pick_best_filters_recently_shown(self):
        overrides = {"preferred_buckets": {}, "boost_source_ids": [], "ban_source_ids": []}
        fresh = make_row(fuzzy_bucket="h3_exact", source_id="1", line_number=100, quality_score=80,
                         display_quote="It was three o'clock in the fresh place.")
        stale = make_row(fuzzy_bucket="h3_exact", source_id="2", line_number=200, quality_score=95,
                         display_quote="It was three o'clock in the stale place.")
        # Stale would normally win (quality 95 > 80), but it's in recent history.
        recent = {("2", 200)}
        best, _ = pq.pick_best([fresh, stale], "h3_exact", 0, 60, overrides, recent_history=recent)
        assert best["source_id"] == "1"

    def test_pick_best_falls_back_to_recent_when_all_filtered(self):
        overrides = {"preferred_buckets": {}, "boost_source_ids": [], "ban_source_ids": []}
        rows = [
            make_row(fuzzy_bucket="h3_exact", source_id="1", line_number=100, quality_score=80,
                     display_quote="Three o'clock only quote."),
        ]
        # Even though the only candidate is recently shown, we still pick it rather than empty out.
        recent = {("1", 100)}
        best, _ = pq.pick_best(rows, "h3_exact", 0, 60, overrides, recent_history=recent)
        assert best["source_id"] == "1"

    def test_select_quote_disables_history_by_default(self, tmp_jsonl, monkeypatch, tmp_path):
        rows = [
            make_row(fuzzy_bucket="h3_exact", source_id="1", line_number=100, quality_score=80,
                     display_quote="It was three o'clock in the fresh place."),
        ]
        corpus_path = tmp_jsonl(rows)
        overrides_path = tmp_path / "overrides.json"
        overrides_path.write_text('{"ban_source_ids": [], "boost_source_ids": [], "preferred_buckets": {}}')
        # No history_path passed → no file reads even if ~/.litclock exists.
        result = pq.select_quote(bucket="h3_exact", input_path=str(corpus_path), overrides_path=str(overrides_path))
        assert result["source_id"] == "1"


class TestCompactHistory:
    """Compact ledger rewrite that drops entries older than ``2 × days``."""

    def _write_ledger(self, path, entries):
        with path.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

    def test_drops_expired_keeps_fresh(self, tmp_path):
        """Acceptance: 1000 expired + 50 fresh → only the 50 fresh survive."""
        path = tmp_path / "history.jsonl"
        now = dt.datetime.now(dt.timezone.utc)
        # 2 × 7 = 14 days window; anything older than 14d is dropped.
        fresh = [
            {"ts": (now - dt.timedelta(hours=h)).isoformat(), "source_id": str(h), "line_number": h}
            for h in range(50)
        ]
        expired = [
            {"ts": (now - dt.timedelta(days=30 + i)).isoformat(), "source_id": f"exp{i}", "line_number": i}
            for i in range(1000)
        ]
        self._write_ledger(path, expired + fresh)

        dropped = pq.compact_history(str(path), 7)

        assert dropped == 1000
        surviving = [json.loads(line) for line in path.read_text().splitlines()]
        assert len(surviving) == 50
        # All surviving entries are the fresh ones; order of fresh entries is preserved.
        assert [e["source_id"] for e in surviving] == [str(h) for h in range(50)]

    def test_noop_when_all_fresh(self, tmp_path):
        """Every entry is within the 2× window → no rewrite at all.

        Guards against a pathological "always rewrite" bug that would burn
        disk IO on every date rollover for a healthy appliance.
        """
        path = tmp_path / "history.jsonl"
        now = dt.datetime.now(dt.timezone.utc)
        entries = [
            {"ts": (now - dt.timedelta(days=d)).isoformat(), "source_id": str(d), "line_number": d}
            for d in range(5)
        ]
        self._write_ledger(path, entries)
        original_bytes = path.read_bytes()
        mtime_before = path.stat().st_mtime_ns

        assert pq.compact_history(str(path), 7) == 0

        # Byte-identical and mtime-untouched — no atomic rewrite path was taken.
        assert path.read_bytes() == original_bytes
        assert path.stat().st_mtime_ns == mtime_before

    def test_routes_through_atomic_io_when_rewriting(self, tmp_path, monkeypatch):
        """The rewrite path goes through atomic_io so a mid-compact crash can't wipe the ledger."""
        import atomic_io

        path = tmp_path / "history.jsonl"
        now = dt.datetime.now(dt.timezone.utc)
        expired = {"ts": (now - dt.timedelta(days=30)).isoformat(), "source_id": "x", "line_number": 1}
        fresh = {"ts": now.isoformat(), "source_id": "f", "line_number": 2}
        self._write_ledger(path, [expired, fresh])

        calls: list[tuple] = []
        original = atomic_io.atomic_write_text

        def spy(target, payload, **kwargs):
            calls.append((target, payload))
            return original(target, payload, **kwargs)

        monkeypatch.setattr("pick_quote.atomic_io.atomic_write_text", spy)
        assert pq.compact_history(str(path), 7) == 1
        assert len(calls) == 1
        # The rewritten payload contains only the fresh entry.
        surviving = [json.loads(line) for line in path.read_text().splitlines()]
        assert [(e["source_id"], e["line_number"]) for e in surviving] == [("f", 2)]

    def test_noop_for_empty_path_or_disabled(self, tmp_path):
        path = tmp_path / "history.jsonl"
        assert pq.compact_history("", 7) == 0
        assert pq.compact_history(None, 7) == 0
        assert pq.compact_history(str(path), 0) == 0

    def test_noop_when_file_missing(self, tmp_path):
        assert pq.compact_history(str(tmp_path / "nope.jsonl"), 7) == 0

    def test_preserves_malformed_lines(self, tmp_path):
        """Compact is about bounded growth, not corruption repair.

        A malformed line that load_recent_history would warn-and-skip should
        still be preserved on disk so the operator can inspect it later.
        """
        path = tmp_path / "history.jsonl"
        now = dt.datetime.now(dt.timezone.utc)
        good_expired = {"ts": (now - dt.timedelta(days=30)).isoformat(), "source_id": "x", "line_number": 1}
        good_fresh = {"ts": now.isoformat(), "source_id": "f", "line_number": 2}
        lines = [
            json.dumps(good_expired),
            "not-json",
            json.dumps(good_fresh),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        dropped = pq.compact_history(str(path), 7)

        assert dropped == 1  # the good_expired entry
        remaining = path.read_text(encoding="utf-8").splitlines()
        # Malformed line preserved; fresh preserved; expired good line gone.
        assert "not-json" in remaining
        assert any('"source_id": "f"' in line for line in remaining)


class TestLoadOverrides:
    def test_missing_file_returns_defaults(self, tmp_path):
        result = pq.load_overrides(tmp_path / "does-not-exist.json")
        assert result == {"ban_source_ids": [], "boost_source_ids": [], "preferred_buckets": {}}

    def test_valid_file_parsed(self, tmp_path):
        path = tmp_path / "ov.json"
        path.write_text(json.dumps({
            "ban_source_ids": ["1"],
            "boost_source_ids": ["2"],
            "preferred_buckets": {"h3_exact": 42},
        }))
        result = pq.load_overrides(path)
        assert result["ban_source_ids"] == ["1"]
        assert result["preferred_buckets"] == {"h3_exact": 42}

    def test_unknown_preferred_bucket_warns_on_stderr(self, tmp_path, capsys):
        path = tmp_path / "ov.json"
        path.write_text(json.dumps({
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": {"h3_exact": 1, "h99_bogus": 2, "not_a_bucket": 3},
        }))
        pq.load_overrides(path)
        err = capsys.readouterr().err
        assert "unknown buckets" in err
        assert "h99_bogus" in err
        assert "not_a_bucket" in err
        assert "h3_exact" not in err  # valid bucket must not be listed

    def test_all_valid_preferred_buckets_silent(self, tmp_path, capsys):
        path = tmp_path / "ov.json"
        path.write_text(json.dumps({
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": {"h3_exact": 1, "h12_quarter_to": 2},
        }))
        pq.load_overrides(path)
        assert capsys.readouterr().err == ""

    def test_non_dict_preferred_buckets_does_not_crash(self, tmp_path, capsys):
        path = tmp_path / "ov.json"
        path.write_text(json.dumps({
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": ["oops", "list"],
        }))
        pq.load_overrides(path)
        assert capsys.readouterr().err == ""


class TestInferQuoteMinute:
    """The matched-text fallback is the only way to recover a minute when
    ``normalized_time`` is missing. It drives ``minute_distance_penalty`` and
    therefore directly affects which candidate wins in a given bucket, so
    every pattern in ``EXACT_MINUTE_PATTERNS`` needs explicit coverage."""

    def test_prefers_normalized_time_when_present(self):
        row = {"normalized_time": "03:17", "matched_text": "quarter past three"}
        # Normalized time wins even when matched_text disagrees.
        assert pq.infer_quote_minute(row) == 17

    def test_malformed_normalized_time_falls_through_to_matched_text(self):
        row = {"normalized_time": "not-a-time", "matched_text": "quarter past three"}
        assert pq.infer_quote_minute(row) == 15

    def test_no_normalized_time_uses_matched_text(self):
        row = {"matched_text": "half past eleven"}
        assert pq.infer_quote_minute(row) == 30

    def test_returns_none_when_nothing_matches(self):
        row = {"matched_text": "a vague reference"}
        assert pq.infer_quote_minute(row) is None

    def test_empty_row(self):
        assert pq.infer_quote_minute({}) is None

    @pytest.mark.parametrize("phrase,minute", [
        ("o’clock", 0),
        ("oclock", 0),
        ("the clock struck twelve", 0),
        ("five minutes past two", 5),
        ("five past two", 5),
        ("ten minutes past four", 10),
        ("ten past four", 10),
        ("quarter past six", 15),
        ("twenty minutes past three", 20),
        ("twenty past three", 20),
        ("half past nine", 30),
        ("half-past nine", 30),
        ("twenty-five minutes to three", 35),
        ("twenty five to three", 35),
        ("twenty minutes to three", 40),
        ("twenty to three", 40),
        ("quarter to eight", 45),
        ("ten minutes to one", 50),
        ("ten to one", 50),
        ("five minutes to two", 55),
        ("five to two", 55),
    ])
    def test_matched_text_patterns(self, phrase, minute):
        row = {"matched_text": phrase}
        assert pq.infer_quote_minute(row) == minute

    def test_matched_text_case_insensitive(self):
        row = {"matched_text": "QUARTER PAST THREE"}
        assert pq.infer_quote_minute(row) == 15

    def test_matched_text_with_embedded_newline(self):
        # gutenberg_time_miner now collapses newlines, but legacy rows may still
        # contain them — infer_quote_minute normalises before matching.
        row = {"matched_text": "half\npast two"}
        assert pq.infer_quote_minute(row) == 30

    def test_known_substring_collision_twenty_five_past_matches_shorter_pattern(self):
        # Documents a known limitation: "twenty-five minutes past" contains
        # "five minutes past" (the 5-minute pattern) and dict-iteration order
        # means the shorter pattern wins. In practice rows reach this code path
        # only when normalized_time is missing, so the impact is minimal — but
        # future callers should be aware.
        row = {"matched_text": "twenty-five minutes past seven"}
        assert pq.infer_quote_minute(row) == 5


class TestMinuteDistancePenalty:
    def test_returns_99_when_quote_minute_unknown(self):
        row = {"matched_text": "some vague phrase"}
        # Row has no normalized_time and no recognisable matched-text pattern.
        assert pq.minute_distance_penalty(row, "h3_exact", "03:00") == 99

    def test_returns_99_when_requested_is_unparseable(self):
        row = {"normalized_time": "03:15"}
        # bucket is a non-standard state name so DEFAULT_BUCKET_MINUTES returns None
        assert pq.minute_distance_penalty(row, "h3_nonsense", None) == 99

    def test_exact_distance_zero(self):
        row = {"normalized_time": "03:15"}
        assert pq.minute_distance_penalty(row, "h3_quarter_past", "03:15") == 0

    def test_distance_uses_absolute_value(self):
        row = {"normalized_time": "03:10"}
        assert pq.minute_distance_penalty(row, "h3_quarter_past", "03:15") == 5


class TestComposeBakedScoreKey:
    def test_layout_matches_score_row(self):
        """compose_baked_score_key must rebuild the exact 12-tuple layout that
        score_row produces, so tuple comparison gives identical pick ordering."""
        row = make_row(quality_score=80, normalized_time="03:00", fuzzy_bucket="h3_exact")
        counts = pq.Counter({"1234": 1})
        expected = pq.score_row(
            row, bucket="h3_exact", overrides={},
            requested_time="03:00", source_counts=counts,
        )
        # Simulate what the baker stores: the ten row-intrinsic positions.
        static_indices = (0, 1, 3, 4, 5, 6, 8, 9, 10, 11)
        baked = dict(row)
        baked["baked_score"] = [expected[i] for i in static_indices]
        baked["inferred_quote_minute"] = 0
        actual = pq.compose_baked_score_key(
            baked, bucket="h3_exact", overrides={}, requested_time="03:00",
        )
        assert actual == expected

    def test_minute_penalty_uses_cached_inferred_minute(self):
        """The baked row's inferred_quote_minute is what drives minute_penalty —
        recomputing from matched_text at runtime would be O(regex-sweep) per pick."""
        baked = make_row(fuzzy_bucket="h3_exact")
        baked["baked_score"] = [0] * 10
        baked["inferred_quote_minute"] = 20
        # Requested minute 20 ⇒ minute_penalty 0; requested 25 ⇒ penalty 5.
        key_aligned = pq.compose_baked_score_key(baked, "h3_exact", {}, "03:20")
        key_off = pq.compose_baked_score_key(baked, "h3_exact", {}, "03:25")
        assert key_aligned[2] == 0
        assert key_off[2] == 5

    def test_missing_inferred_minute_returns_sentinel(self):
        baked = make_row(fuzzy_bucket="h3_exact")
        baked["baked_score"] = [0] * 10
        baked["inferred_quote_minute"] = None
        key = pq.compose_baked_score_key(baked, "h3_exact", {}, "03:00")
        assert key[2] == 99

    def test_override_bonus_recomputed_per_pick(self):
        """Runtime selection_overrides can change between picks — bonus must
        not be cached in baked_score."""
        baked = make_row(source_id="42", fuzzy_bucket="h3_exact")
        baked["baked_score"] = [0] * 10
        baked["inferred_quote_minute"] = 0
        no_boost = pq.compose_baked_score_key(baked, "h3_exact", {}, "03:00")
        with_boost = pq.compose_baked_score_key(
            baked, "h3_exact", {"boost_source_ids": ["42"]}, "03:00",
        )
        assert no_boost[7] == 0
        assert with_boost[7] == -3


class TestScoreRowBakedShortCircuit:
    def test_baked_row_skips_intrinsic_recompute(self, monkeypatch):
        """When baked_score is present, score_row should not call the live
        intrinsic helpers — otherwise the bake would be wasted work."""
        baked = make_row(fuzzy_bucket="h3_exact", quality_score=80)
        baked["baked_score"] = [0] * 10
        baked["inferred_quote_minute"] = 0
        calls = {"metadata": 0, "dialogue": 0, "opening": 0}
        monkeypatch.setattr(pq, "metadata_bonus", lambda row: calls.__setitem__("metadata", calls["metadata"] + 1) or -3)
        monkeypatch.setattr(pq, "dialogue_penalty", lambda row: calls.__setitem__("dialogue", calls["dialogue"] + 1) or 0)
        monkeypatch.setattr(pq, "opening_penalty", lambda row: calls.__setitem__("opening", calls["opening"] + 1) or 0)
        pq.score_row(baked, bucket="h3_exact", overrides={}, requested_time="03:00", source_counts=None)
        assert calls == {"metadata": 0, "dialogue": 0, "opening": 0}


class TestResolveCorpus:
    def test_prefers_baked_when_present(self, tmp_path, monkeypatch):
        raw = tmp_path / "raw.jsonl"
        baked = tmp_path / "baked.jsonl"
        raw.write_text('{"source_id": "raw"}\n', encoding="utf-8")
        baked.write_text('{"source_id": "baked"}\n', encoding="utf-8")
        monkeypatch.setattr(pq, "BASE_DIR", tmp_path)
        rows = pq._resolve_corpus(str(baked), str(raw))
        assert rows[0]["source_id"] == "baked"

    def test_falls_back_to_raw_when_baked_missing(self, tmp_path, monkeypatch, capsys):
        """A stale ``--database`` path (or partial checkout) must not silently downgrade
        to the raw path — the operator should see a warning so they can fix the bake."""
        raw = tmp_path / "raw.jsonl"
        raw.write_text('{"source_id": "raw"}\n', encoding="utf-8")
        monkeypatch.setattr(pq, "BASE_DIR", tmp_path)
        rows = pq._resolve_corpus(str(tmp_path / "absent.jsonl"), str(raw))
        assert rows[0]["source_id"] == "raw"
        assert "not found" in capsys.readouterr().err

    def test_falls_back_to_raw_when_baked_empty(self, tmp_path, monkeypatch, capsys):
        """An editor truncating the baked file to 0 bytes must not starve the picker."""
        raw = tmp_path / "raw.jsonl"
        baked = tmp_path / "baked.jsonl"
        raw.write_text('{"source_id": "raw"}\n', encoding="utf-8")
        baked.write_text("", encoding="utf-8")
        monkeypatch.setattr(pq, "BASE_DIR", tmp_path)
        rows = pq._resolve_corpus(str(baked), str(raw))
        assert rows[0]["source_id"] == "raw"
        assert "empty" in capsys.readouterr().err

    def test_empty_database_path_forces_raw(self, tmp_path, monkeypatch):
        raw = tmp_path / "raw.jsonl"
        raw.write_text('{"source_id": "raw"}\n', encoding="utf-8")
        monkeypatch.setattr(pq, "BASE_DIR", tmp_path)
        rows = pq._resolve_corpus(None, str(raw))
        assert rows[0]["source_id"] == "raw"
        rows = pq._resolve_corpus("", str(raw))
        assert rows[0]["source_id"] == "raw"

    def test_falls_back_when_schema_version_mismatched(self, tmp_path, monkeypatch, capsys):
        """Issue #53: a baked DB stamped with a different schema_version must
        trigger a fallback to the raw corpus. This is the 'git pull updated
        pick_quote.py but not quote_database.jsonl' scenario — without the
        check, baked_score is scored against a mis-aligned tuple layout."""
        raw = tmp_path / "raw.jsonl"
        baked = tmp_path / "baked.jsonl"
        import json as _json
        raw.write_text(_json.dumps({"source_id": "raw"}) + "\n", encoding="utf-8")
        baked_row = {
            "source_id": "baked",
            "baked_score": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "schema_version": 9999,  # not the current version
            "inferred_quote_minute": None,
        }
        baked.write_text(_json.dumps(baked_row) + "\n", encoding="utf-8")
        monkeypatch.setattr(pq, "BASE_DIR", tmp_path)
        rows = pq._resolve_corpus(str(baked), str(raw))
        assert rows[0]["source_id"] == "raw"
        err = capsys.readouterr().err
        assert "schema_version" in err

    def test_missing_schema_version_also_falls_back(self, tmp_path, monkeypatch, capsys):
        """A baked DB predating the schema-version field has no marker on any
        row; treat that as version 0 so an upgrade surfaces loudly."""
        raw = tmp_path / "raw.jsonl"
        baked = tmp_path / "baked.jsonl"
        import json as _json
        raw.write_text(_json.dumps({"source_id": "raw"}) + "\n", encoding="utf-8")
        baked_row = {
            "source_id": "baked",
            "baked_score": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "inferred_quote_minute": None,
            # no schema_version
        }
        baked.write_text(_json.dumps(baked_row) + "\n", encoding="utf-8")
        monkeypatch.setattr(pq, "BASE_DIR", tmp_path)
        rows = pq._resolve_corpus(str(baked), str(raw))
        assert rows[0]["source_id"] == "raw"
        assert "schema_version" in capsys.readouterr().err

    def test_current_schema_version_loads_baked(self, tmp_path, monkeypatch, capsys):
        """Baseline: a baked DB with the current schema_version loads normally."""
        raw = tmp_path / "raw.jsonl"
        baked = tmp_path / "baked.jsonl"
        import json as _json
        raw.write_text(_json.dumps({"source_id": "raw"}) + "\n", encoding="utf-8")
        baked_row = {
            "source_id": "baked",
            "baked_score": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "schema_version": pq.BAKED_SCORE_SCHEMA_VERSION,
            "inferred_quote_minute": None,
        }
        baked.write_text(_json.dumps(baked_row) + "\n", encoding="utf-8")
        monkeypatch.setattr(pq, "BASE_DIR", tmp_path)
        rows = pq._resolve_corpus(str(baked), str(raw))
        assert rows[0]["source_id"] == "baked"
        # No warning on the happy path.
        assert "schema_version" not in capsys.readouterr().err


class TestSourceRarityPenalty:
    def test_no_source_id_returns_zero(self):
        assert pq.source_rarity_penalty({"source_id": None}, pq.Counter({"1234": 10})) == 0
        assert pq.source_rarity_penalty({}, pq.Counter({"1234": 10})) == 0

    def test_returns_count_for_known_source(self):
        counts = pq.Counter({"1234": 7})
        assert pq.source_rarity_penalty({"source_id": "1234"}, counts) == 7

    def test_unknown_source_returns_zero(self):
        counts = pq.Counter({"1234": 7})
        assert pq.source_rarity_penalty({"source_id": "9999"}, counts) == 0
