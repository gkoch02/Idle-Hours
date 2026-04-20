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
