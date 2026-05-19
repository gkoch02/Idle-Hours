"""Tests for gutenberg_time_miner.py — regex patterns, time parsing, bucket logic."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from idle_hours import gutenberg_time_miner as gtm

# ---------------------------------------------------------------------------
# normalize_number_phrase
# ---------------------------------------------------------------------------

class TestNormalizeNumberPhrase:
    def test_single_word(self):
        assert gtm.normalize_number_phrase("five") == 5

    def test_compound_with_space(self):
        assert gtm.normalize_number_phrase("twenty five") == 25

    def test_compound_with_hyphen(self):
        assert gtm.normalize_number_phrase("twenty-five") == 25

    def test_unknown_returns_none(self):
        assert gtm.normalize_number_phrase("eleventy") is None

    def test_zero(self):
        assert gtm.normalize_number_phrase("zero") == 0

    def test_thirty(self):
        assert gtm.normalize_number_phrase("thirty") == 30

    def test_fifty_nine(self):
        assert gtm.normalize_number_phrase("fifty nine") == 59


# ---------------------------------------------------------------------------
# hour_word_to_int
# ---------------------------------------------------------------------------

class TestHourWordToInt:
    def test_valid_words(self):
        assert gtm.hour_word_to_int("one") == 1
        assert gtm.hour_word_to_int("twelve") == 12
        assert gtm.hour_word_to_int("six") == 6

    def test_case_insensitive(self):
        assert gtm.hour_word_to_int("THREE") == 3
        assert gtm.hour_word_to_int("Seven") == 7

    def test_zero_not_valid_hour(self):
        assert gtm.hour_word_to_int("zero") is None

    def test_thirteen_not_valid_hour(self):
        assert gtm.hour_word_to_int("thirteen") is None

    def test_unknown_returns_none(self):
        assert gtm.hour_word_to_int("noon") is None


# ---------------------------------------------------------------------------
# daypart_for_hour
# ---------------------------------------------------------------------------

class TestDaypartForHour:
    def test_midnight(self):
        assert gtm.daypart_for_hour(0) == "midnight"

    def test_dawn(self):
        assert gtm.daypart_for_hour(5) == "dawn"
        assert gtm.daypart_for_hour(6) == "dawn"

    def test_morning(self):
        assert gtm.daypart_for_hour(7) == "morning"
        assert gtm.daypart_for_hour(11) == "morning"

    def test_noon(self):
        assert gtm.daypart_for_hour(12) == "noon"

    def test_afternoon(self):
        assert gtm.daypart_for_hour(13) == "afternoon"
        assert gtm.daypart_for_hour(17) == "afternoon"

    def test_dusk(self):
        assert gtm.daypart_for_hour(18) == "dusk"
        assert gtm.daypart_for_hour(19) == "dusk"

    def test_evening(self):
        assert gtm.daypart_for_hour(20) == "evening"
        assert gtm.daypart_for_hour(22) == "evening"

    def test_night_late(self):
        assert gtm.daypart_for_hour(23) == "night"

    def test_wraps_24(self):
        assert gtm.daypart_for_hour(24) == "midnight"

    def test_none_returns_none(self):
        assert gtm.daypart_for_hour(None) is None


# ---------------------------------------------------------------------------
# build_bucket
# ---------------------------------------------------------------------------

class TestBuildBucket:
    def test_normal_hour_minute(self):
        # hour 3 is 3am → "night"; use hour 9 (9am → "morning") instead
        normalized, fuzzy, daypart = gtm.build_bucket(9, 0)
        assert normalized == "09:00"
        assert fuzzy == "h9_exact"
        assert daypart == "morning"

    def test_hour12_bucket(self):
        normalized, fuzzy, daypart = gtm.build_bucket(12, 30)
        assert normalized == "12:30"
        assert fuzzy == "h12_half_past"
        assert daypart == "noon"

    def test_explicit_daypart_ignores_hour_minute(self):
        normalized, fuzzy, daypart = gtm.build_bucket(None, None, "morning")
        assert normalized is None
        assert fuzzy is None
        assert daypart == "morning"

    def test_none_hour_minute_returns_nones(self):
        normalized, fuzzy, daypart = gtm.build_bucket(None, None)
        assert normalized is None
        assert fuzzy is None
        assert daypart is None

    def test_midnight_hour(self):
        normalized, fuzzy, _ = gtm.build_bucket(0, 0)
        assert normalized == "00:00"
        assert fuzzy == "h12_exact"


# ---------------------------------------------------------------------------
# candidate_from_match — one test per match type
# ---------------------------------------------------------------------------

def _make_match(pattern: re.Pattern, text: str) -> re.Match:
    m = pattern.search(text)
    assert m is not None, f"Pattern did not match: {text!r}"
    return m


def _get_pattern(name: str) -> re.Pattern:
    for match_type, pattern in gtm.TIME_PATTERNS:
        if match_type == name:
            return pattern
    raise KeyError(name)


class TestCandidateFromMatch:
    def _make(self, match_type: str, text: str) -> gtm.Candidate | None:
        pattern = _get_pattern(match_type)
        m = _make_match(pattern, text)
        return gtm.candidate_from_match("test.txt", "1234", text, match_type, m, 220)

    def test_oclock_word(self):
        c = self._make("oclock_word", "It was three o'clock when she left.")
        assert c is not None
        assert c.hour == 3
        assert c.minute == 0
        assert c.fuzzy_bucket == "h3_exact"

    def test_quarter_half_quarter(self):
        c = self._make("quarter_half", "The bell rang at quarter past five.")
        assert c is not None
        assert c.hour == 5
        assert c.minute == 15

    def test_quarter_half_half(self):
        c = self._make("quarter_half", "Half past two in the morning.")
        assert c is not None
        assert c.hour == 2
        assert c.minute == 30

    def test_quarter_to(self):
        c = self._make("quarter_to", "It was quarter to four.")
        assert c is not None
        assert c.hour == 3
        assert c.minute == 45

    def test_quarter_to_wraps_one(self):
        # quarter to one → hour 12, minute 45
        c = self._make("quarter_to", "Quarter to one in the afternoon.")
        assert c is not None
        assert c.hour == 12
        assert c.minute == 45

    def test_minutes_past(self):
        c = self._make("minutes_past_to", "Ten minutes past six she arrived.")
        assert c is not None
        assert c.hour == 6
        assert c.minute == 10

    def test_minutes_to(self):
        c = self._make("minutes_past_to", "Five minutes to eight the train left.")
        assert c is not None
        assert c.hour == 7
        assert c.minute == 55

    def test_minutes_to_wraps_one(self):
        c = self._make("minutes_past_to", "Five minutes to one the bell struck.")
        assert c is not None
        assert c.hour == 12
        assert c.minute == 55

    def test_just_after(self):
        c = self._make("just_after_before", "Just after three o'clock she appeared.")
        assert c is not None
        assert c.hour == 3
        assert c.minute == 3

    def test_just_before(self):
        # "almost five" means ~4:57, not 5:57.
        c = self._make("just_after_before", "Almost five o'clock when he returned.")
        assert c is not None
        assert c.hour == 4
        assert c.minute == 57

    def test_clock_struck(self):
        c = self._make("clock_struck", "The clock struck midnight.")
        assert c is not None
        assert c.hour == 0
        assert c.minute == 0

    def test_clock_struck_noon(self):
        c = self._make("clock_struck", "It struck noon at last.")
        assert c is not None
        assert c.hour == 12
        assert c.minute == 0

    def test_clock_struck_hour(self):
        c = self._make("clock_struck", "The clock struck seven.")
        assert c is not None
        assert c.hour == 7
        assert c.minute == 0

    def test_daypart(self):
        c = self._make("daypart", "He walked out into the morning air.")
        assert c is not None
        assert c.daypart_bucket == "morning"
        assert c.hour is None

    def test_digital_valid(self):
        c = self._make("digital", "The train departs at 14:30.")
        assert c is not None
        assert c.hour == 14
        assert c.minute == 30

    def test_digital_invalid_hour_returns_none(self):
        pattern = _get_pattern("digital")
        text = "Reference 25:00 in the manual."
        m = pattern.search(text)
        if m:
            result = gtm.candidate_from_match("test.txt", "1234", text, "digital", m, 220)
            assert result is None

    def test_digital_chapter_context_returns_none(self):
        text = "See chapter 3:45 for details."
        pattern = _get_pattern("digital")
        m = pattern.search(text)
        if m:
            result = gtm.candidate_from_match("test.txt", "1234", text, "digital", m, 220)
            assert result is None

    def test_twenty_five_minutes_past(self):
        c = self._make("minutes_past_to", "Twenty-five minutes past nine the carriage arrived.")
        assert c is not None
        assert c.hour == 9
        assert c.minute == 25

    def test_matched_text_whitespace_collapsed_across_line_break(self):
        # A time phrase split across a line break used to preserve the newline in
        # matched_text; the miner now collapses internal whitespace so downstream
        # consumers (render_quote, dedup) see a single clean phrase.
        c = self._make("minutes_past_to", "Ten\nminutes past six she arrived.")
        assert c is not None
        assert c.matched_text == "Ten minutes past six"
        assert "\n" not in c.matched_text


# ---------------------------------------------------------------------------
# iter_candidates — integration smoke test
# ---------------------------------------------------------------------------

class TestSentenceWindow:
    def test_basic_mid_text(self):
        text = "She arrived early. It was three o'clock. She sat down."
        start = text.index("three")
        end = start + len("three o'clock")
        quote, context, line_no = gtm.sentence_window(text, start, end, context_chars=100)
        assert "three o'clock" in quote
        assert line_no == 1

    def test_quote_starts_after_period(self):
        text = "First sentence. It was noon. Another sentence."
        start = text.index("noon")
        end = start + 4
        quote, _, _ = gtm.sentence_window(text, start, end, context_chars=50)
        assert quote.startswith("It")

    def test_quote_ends_at_sentence_boundary(self):
        text = "Before. It was midnight. After sentence."
        start = text.index("midnight")
        end = start + len("midnight")
        quote, _, _ = gtm.sentence_window(text, start, end, context_chars=50)
        assert quote.endswith(".")
        assert "After" not in quote

    def test_context_respects_context_chars(self):
        text = "A" * 100 + "TARGET" + "B" * 100
        start = 100
        end = 106
        _, context, _ = gtm.sentence_window(text, start, end, context_chars=10)
        assert "TARGET" in context
        # Should not include all 100 A's
        assert len(context) < 50

    def test_line_number_first_line(self):
        text = "It was three o'clock in the morning."
        _, _, line_no = gtm.sentence_window(text, 7, 20, context_chars=50)
        assert line_no == 1

    def test_line_number_multiline(self):
        text = "Line one.\nLine two.\nIt was three o'clock."
        start = text.index("three")
        _, _, line_no = gtm.sentence_window(text, start, start + 5, context_chars=50)
        assert line_no == 3

    def test_no_sentence_boundary_before_match(self):
        text = "It was three o'clock in the morning"
        start = text.index("three")
        quote, context, _ = gtm.sentence_window(text, start, start + 5, context_chars=50)
        # No prior period, but should still return something
        assert "three" in quote or "three" in context

    def test_exclamation_and_question_as_boundaries(self):
        text = "How strange! It was noon! Was it really?"
        start = text.index("noon")
        end = start + 4
        quote, _, _ = gtm.sentence_window(text, start, end, context_chars=50)
        assert "It was noon" in quote


class TestIterCandidates:
    def test_finds_multiple_match_types_in_text(self):
        text = (
            "She woke at seven o'clock. "
            "By half past eight the house was quiet. "
            "Quarter to ten she departed."
        )
        candidates = list(gtm.iter_candidates(Path("test.txt"), None, text, 220, 0))
        match_types = {c.match_type for c in candidates}
        assert "oclock_word" in match_types
        assert "quarter_half" in match_types
        assert "quarter_to" in match_types

    def test_max_per_file_limits_results(self):
        text = " ".join([f"It was {w} o'clock." for w in ["one", "two", "three", "four", "five"]])
        candidates = list(gtm.iter_candidates(Path("test.txt"), None, text, 220, max_per_file=2))
        assert len(candidates) == 2


# ---------------------------------------------------------------------------
# text_files_from_inputs
# ---------------------------------------------------------------------------

class TestTextFilesFromInputs:
    def test_file_input(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hi")
        result = list(gtm.text_files_from_inputs([str(f)]))
        assert result == [f]

    def test_directory_input_recurses(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("y")
        names = sorted(p.name for p in gtm.text_files_from_inputs([str(tmp_path)]))
        assert names == ["a.txt", "b.txt"]

    def test_missing_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            list(gtm.text_files_from_inputs([str(tmp_path / "nope.txt")]))


# ---------------------------------------------------------------------------
# fetch_gutenberg_text
# ---------------------------------------------------------------------------

class TestFetchGutenbergText:
    def test_cache_hit_skips_network(self, tmp_path, monkeypatch):
        cached = tmp_path / "pg1234.txt"
        cached.write_text("cached content")

        def exploding_urlopen(*args, **kwargs):
            raise AssertionError("urlopen must not be called when cache is warm")

        monkeypatch.setattr(gtm.urllib.request, "urlopen", exploding_urlopen)
        result = gtm.fetch_gutenberg_text("1234", tmp_path)
        assert result == cached
        assert result.read_text() == "cached content"

    def test_downloads_and_writes(self, tmp_path, monkeypatch):
        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload
            def read(self):
                return self._payload
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def fake_urlopen(url, timeout=30):
            return FakeResponse(b"downloaded body")

        monkeypatch.setattr(gtm.urllib.request, "urlopen", fake_urlopen)
        result = gtm.fetch_gutenberg_text("9999", tmp_path)
        assert result.exists()
        assert result.read_text() == "downloaded body"

    def test_all_urls_fail_raises(self, tmp_path, monkeypatch):
        def fake_urlopen(url, timeout=30):
            raise gtm.urllib.error.URLError("nope")

        monkeypatch.setattr(gtm.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="Failed to fetch"):
            gtm.fetch_gutenberg_text("4242", tmp_path)

    def test_falls_through_to_next_pattern(self, tmp_path, monkeypatch):
        calls = {"n": 0}

        class FakeResponse:
            def read(self):
                return b"second pattern body"
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def fake_urlopen(url, timeout=30):
            calls["n"] += 1
            if calls["n"] == 1:
                raise gtm.urllib.error.URLError("first pattern 404")
            return FakeResponse()

        monkeypatch.setattr(gtm.urllib.request, "urlopen", fake_urlopen)
        result = gtm.fetch_gutenberg_text("7", tmp_path)
        assert calls["n"] == 2
        assert result.read_text() == "second pattern body"


# ---------------------------------------------------------------------------
# mine / main / writers
# ---------------------------------------------------------------------------

class TestMine:
    def _args(self, **kwargs):
        # Derive defaults from the real parser so a new CLI flag can't silently
        # leave tests running against a stale default dict. parse_args() reads
        # sys.argv with no override, so stub it for the duration of the call.
        original_argv = sys.argv
        sys.argv = ["gutenberg_time_miner.py"]
        try:
            args = gtm.parse_args()
        finally:
            sys.argv = original_argv
        for key, value in kwargs.items():
            setattr(args, key, value)
        return args

    def test_no_inputs_raises_system_exit(self, tmp_path):
        with pytest.raises(SystemExit):
            gtm.mine(self._args(download_dir=str(tmp_path)))

    def test_local_file_mined(self, tmp_path):
        f = tmp_path / "book.txt"
        f.write_text("It was three o'clock in the afternoon.")
        candidates = gtm.mine(self._args(input=[str(f)], download_dir=str(tmp_path)))
        assert len(candidates) >= 1
        assert any(c.match_type == "oclock_word" for c in candidates)

    def test_strict_excludes_daypart_and_digital(self, tmp_path):
        f = tmp_path / "book.txt"
        f.write_text("At 14:30 it was afternoon. She arrived at three o'clock.")
        candidates = gtm.mine(self._args(input=[str(f)], download_dir=str(tmp_path), strict=True))
        match_types = {c.match_type for c in candidates}
        assert "digital" not in match_types
        assert "daypart" not in match_types
        assert "oclock_word" in match_types

    def test_exclude_match_type_filters(self, tmp_path):
        f = tmp_path / "book.txt"
        f.write_text("It was three o'clock in the afternoon.")
        candidates = gtm.mine(self._args(
            input=[str(f)], download_dir=str(tmp_path),
            exclude_match_type=["oclock_word"],
        ))
        assert all(c.match_type != "oclock_word" for c in candidates)

    def test_max_total_caps_results(self, tmp_path):
        f = tmp_path / "book.txt"
        f.write_text(" ".join(f"It was {w} o'clock." for w in ["one", "two", "three", "four", "five"]))
        candidates = gtm.mine(self._args(
            input=[str(f)], download_dir=str(tmp_path), max_total=2,
        ))
        assert len(candidates) == 2

    def test_skip_fetch_errors_continues(self, tmp_path, monkeypatch, capsys):
        def fake_fetch(ebook_id, download_dir):
            raise RuntimeError("simulated 404")

        monkeypatch.setattr(gtm, "fetch_gutenberg_text", fake_fetch)
        local = tmp_path / "local.txt"
        local.write_text("It was five o'clock in the morning.")
        candidates = gtm.mine(self._args(
            gutenberg_id=["404"],
            input=[str(local)],
            download_dir=str(tmp_path),
            skip_fetch_errors=True,
        ))
        # Local file still mined despite the bad Gutenberg id.
        assert any(c.match_type == "oclock_word" for c in candidates)
        err = capsys.readouterr().err
        assert "Skipping Gutenberg id 404" in err

    def test_fetch_failure_without_skip_reraises(self, tmp_path, monkeypatch):
        def fake_fetch(ebook_id, download_dir):
            raise RuntimeError("simulated 404")

        monkeypatch.setattr(gtm, "fetch_gutenberg_text", fake_fetch)
        with pytest.raises(RuntimeError, match="simulated 404"):
            gtm.mine(self._args(gutenberg_id=["404"], download_dir=str(tmp_path)))

    def test_uses_downloaded_gutenberg_text(self, tmp_path, monkeypatch):
        def fake_fetch(ebook_id, download_dir):
            p = Path(download_dir) / f"pg{ebook_id}.txt"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("It was four o'clock in the afternoon.")
            return p

        monkeypatch.setattr(gtm, "fetch_gutenberg_text", fake_fetch)
        candidates = gtm.mine(self._args(gutenberg_id=["42"], download_dir=str(tmp_path)))
        assert any(c.source_id == "42" for c in candidates)


class TestWriters:
    def test_write_jsonl(self, tmp_path):
        text = "It was three o'clock."
        candidates = list(gtm.iter_candidates(Path("a.txt"), "1", text, 100, 0))
        out = tmp_path / "out.jsonl"
        count = gtm.write_jsonl(out, candidates)
        assert count == len(candidates)
        rows = [json.loads(line) for line in out.read_text().splitlines()]
        assert all("normalized_time" in r for r in rows)

    def test_write_csv(self, tmp_path):
        text = "It was three o'clock."
        candidates = list(gtm.iter_candidates(Path("a.txt"), "1", text, 100, 0))
        out = tmp_path / "out.csv"
        count = gtm.write_csv(out, candidates)
        assert count == len(candidates)
        body = out.read_text()
        assert "normalized_time" in body.splitlines()[0]


class TestMainCLI:
    def test_jsonl_output_and_sample_print(self, tmp_path, monkeypatch, capsys):
        book = tmp_path / "book.txt"
        book.write_text("She waited until three o'clock. Later, four o'clock struck.")
        out = tmp_path / "candidates.jsonl"
        monkeypatch.setattr(
            "sys.argv",
            [
                "gutenberg_time_miner.py",
                "--input", str(book),
                "--output", str(out),
                "--download-dir", str(tmp_path / "dl"),
                "--print-sample", "2",
                "--exclude-match-type", "clock_struck",  # keep the assertion tight
            ],
        )
        assert gtm.main() == 0
        assert out.exists()
        rows = [json.loads(line) for line in out.read_text().splitlines()]
        assert [r["matched_text"].lower() for r in rows] == ["three o'clock", "four o'clock"]
        assert all(r["match_type"] == "oclock_word" for r in rows)
        captured = capsys.readouterr().out
        assert "Wrote 2 candidates" in captured
        # --print-sample 2 prints one "[1]" and one "[2]" header
        assert "[1]" in captured
        assert "[2]" in captured

    def test_csv_output_format(self, tmp_path, monkeypatch):
        book = tmp_path / "book.txt"
        book.write_text("It was three o'clock in the afternoon.")
        out = tmp_path / "candidates.csv"
        monkeypatch.setattr(
            "sys.argv",
            [
                "gutenberg_time_miner.py",
                "--input", str(book),
                "--output", str(out),
                "--download-dir", str(tmp_path / "dl"),
                "--format", "csv",
            ],
        )
        assert gtm.main() == 0
        body = out.read_text()
        assert "normalized_time" in body.splitlines()[0]
