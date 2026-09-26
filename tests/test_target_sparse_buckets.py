"""Tests for target_sparse_buckets.py"""
from __future__ import annotations

import json

from idle_hours import target_sparse_buckets as tsb
from idle_hours.target_sparse_buckets import expected_targets, sentence_window, templates_for_bucket


class TestExpectedTargets:
    def _coverage(self, empty=None, sparse=None):
        return {
            "empty_buckets": empty or [],
            "sparse_buckets": [{"bucket": b, "count": c} for b, c in (sparse or [])],
        }

    def test_empty_buckets_first(self):
        coverage = self._coverage(empty=["h1_exact", "h2_exact"], sparse=[("h3_exact", 1)])
        targets = expected_targets(coverage, max_buckets=10)
        assert targets[0] == "h1_exact"
        assert targets[1] == "h2_exact"
        assert targets[2] == "h3_exact"

    def test_max_buckets_cap(self):
        coverage = self._coverage(empty=[f"h{h}_exact" for h in range(1, 13)])
        targets = expected_targets(coverage, max_buckets=5)
        assert len(targets) == 5

    def test_deduplicates(self):
        # Bucket appearing in both empty and sparse should appear only once
        coverage = self._coverage(empty=["h1_exact"], sparse=[("h1_exact", 2), ("h2_exact", 1)])
        targets = expected_targets(coverage, max_buckets=10)
        assert targets.count("h1_exact") == 1

    def test_empty_coverage(self):
        targets = expected_targets({}, max_buckets=10)
        assert targets == []

    def test_returns_list(self):
        coverage = self._coverage(empty=["h1_exact"])
        result = expected_targets(coverage, max_buckets=10)
        assert isinstance(result, list)


class TestTemplatesForBucket:
    def test_five_past_contains_hour_word(self):
        templates = templates_for_bucket("h3_five_past")
        phrases = [phrase for phrase, _ in templates]
        assert any("three" in p for p in phrases)

    def test_five_past_uses_current_hour(self):
        templates = templates_for_bucket("h3_five_past")
        phrases = [phrase for phrase, _ in templates]
        assert any("five past three" in p for p in phrases)

    def test_quarter_to_uses_next_hour(self):
        templates = templates_for_bucket("h3_quarter_to")
        phrases = [phrase for phrase, _ in templates]
        assert any("four" in p for p in phrases)
        assert not any("three" in p for p in phrases)

    def test_h12_wraps_to_h1(self):
        templates = templates_for_bucket("h12_quarter_to")
        phrases = [phrase for phrase, _ in templates]
        assert any("one" in p for p in phrases)

    def test_half_past_uses_current_hour(self):
        templates = templates_for_bucket("h5_half_past")
        phrases = [phrase for phrase, _ in templates]
        assert any("five" in p for p in phrases)
        assert any("half past five" in p for p in phrases)

    def test_unknown_state_returns_empty(self):
        templates = templates_for_bucket("h3_exact")
        assert templates == []

    def test_implied_state_in_tuple(self):
        templates = templates_for_bucket("h3_quarter_to")
        for phrase, implied_state in templates:
            assert implied_state == "quarter_to"

    def test_all_valid_states_return_templates(self):
        states_with_templates = [
            "five_past", "ten_past", "quarter_past", "twenty_past",
            "twenty_five_past", "half_past", "twenty_five_to", "twenty_to",
            "quarter_to", "ten_to", "five_to",
        ]
        for state in states_with_templates:
            templates = templates_for_bucket(f"h6_{state}")
            assert len(templates) > 0, f"No templates for h6_{state}"


class TestSentenceWindow:
    def test_extracts_sentence(self):
        text = "She woke early. It was five o'clock in the morning. The birds sang."
        start = text.index("five")
        end = start + len("five o'clock")
        quote, context, line_no = sentence_window(text, start, end)
        assert "five o'clock" in quote
        # Quote should start after the period before "It"
        assert quote.startswith("It")

    def test_context_window(self):
        text = "A" * 50 + "TARGET" + "B" * 50
        start = 50
        end = 56
        _, context, _ = sentence_window(text, start, end, context_chars=10)
        assert "TARGET" in context
        assert len(context) <= 26  # 10 + 6 + 10

    def test_line_number_first_line(self):
        text = "It was three o'clock."
        _, _, line_no = sentence_window(text, 7, 20)
        assert line_no == 1

    def test_line_number_third_line(self):
        text = "Line one.\nLine two.\nIt was three o'clock."
        start = text.index("three")
        _, _, line_no = sentence_window(text, start, start + 5)
        assert line_no == 3

    def test_no_preceding_sentence_boundary(self):
        text = "It was three o'clock in the morning"
        start = text.index("three")
        quote, _, _ = sentence_window(text, start, start + 5)
        # No prior sentence terminator — should still return something
        assert "three" in quote

    def test_whitespace_normalized_in_context(self):
        text = "She  waited.\nIt   was   noon.\nShe left."
        start = text.index("noon")
        _, context, _ = sentence_window(text, start, start + 4, context_chars=20)
        # context should have normalized whitespace
        assert "  " not in context


class TestSearchBucket:
    def test_finds_matching_phrase(self, tmp_path):
        pg = tmp_path / "pg1234.txt"
        pg.write_text("The morning was quiet. It was five past three when she looked up.\n")
        results = tsb.search_bucket("h3_five_past", tmp_path)
        assert len(results) == 1
        hit = results[0]
        assert hit["source_id"] == "1234"
        assert hit["target_bucket"] == "h3_five_past"
        assert hit["resolved_bucket"] == "h3_five_past"
        assert "five past three" in hit["matched_text"].lower()
        assert "five past three" in hit["quote_text"].lower()
        assert hit["line_number"] == 1

    def test_empty_templates_returns_empty(self, tmp_path):
        pg = tmp_path / "pg1.txt"
        pg.write_text("Nothing interesting here.\n")
        assert tsb.search_bucket("h3_exact", tmp_path) == []

    def test_non_pg_stem_has_null_source_id(self, tmp_path):
        book = tmp_path / "local_book.txt"
        book.write_text("It was quarter to eight in the cold morning.\n")
        results = tsb.search_bucket("h7_quarter_to", tmp_path)
        assert len(results) == 1
        assert results[0]["source_id"] is None
        assert results[0]["source_path"].endswith("local_book.txt")

    def test_dedupes_same_position(self, tmp_path):
        # "five to three" appears in templates as both "five to {next_hour}"
        # and "five minutes to {next_hour}" — the same text match should not fire twice.
        pg = tmp_path / "pg2.txt"
        pg.write_text("It was five to three.\n")
        results = tsb.search_bucket("h2_five_to", tmp_path)
        # Only one match per (start, end, implied_state) position
        positions = {(r["match_start"], r["match_end"]) for r in results}
        assert len(results) == len(positions)

    def test_implied_state_differs_from_target_bucket(self, tmp_path):
        # "fifty-five minutes past two" is templated under h2_five_to with implied_state=five_to;
        # resolved bucket should still be h2_five_to.
        pg = tmp_path / "pg3.txt"
        pg.write_text("She arrived at fifty-five minutes past two precisely.\n")
        results = tsb.search_bucket("h2_five_to", tmp_path)
        assert len(results) == 1
        assert results[0]["resolved_bucket"] == "h2_five_to"

    def test_multiple_files_searched(self, tmp_path):
        (tmp_path / "pg1.txt").write_text("It was half past four in the garden.\n")
        (tmp_path / "pg2.txt").write_text("The clock chimed half past four downstairs.\n")
        results = tsb.search_bucket("h4_half_past", tmp_path)
        source_ids = {r["source_id"] for r in results}
        assert source_ids == {"1", "2"}


class TestMainCLI:
    def test_writes_targeted_candidates(self, tmp_path, monkeypatch, capsys):
        search_dir = tmp_path / "gutenberg"
        search_dir.mkdir()
        (search_dir / "pg1.txt").write_text("It was five past three when the letter came.\n")
        (search_dir / "pg2.txt").write_text("The clock struck half past nine sharp.\n")

        coverage_path = tmp_path / "coverage.json"
        coverage_path.write_text(json.dumps({
            "empty_buckets": ["h3_five_past"],
            "sparse_buckets": [{"bucket": "h9_half_past", "count": 1}],
        }))
        output_path = tmp_path / "targeted.jsonl"

        monkeypatch.setattr(
            "sys.argv",
            [
                "target_sparse_buckets.py",
                str(coverage_path),
                "--search-dir", str(search_dir),
                "--output", str(output_path),
                "--max-buckets", "10",
            ],
        )
        assert tsb.main() == 0
        assert output_path.exists()
        lines = output_path.read_text().strip().splitlines()
        assert len(lines) == 2
        buckets = {json.loads(line)["target_bucket"] for line in lines}
        assert buckets == {"h3_five_past", "h9_half_past"}
        out = capsys.readouterr().out
        assert "Targeted buckets searched: 2" in out
        assert "Targeted candidates found: 2" in out


class TestLooksLikeFalsePositive:
    """Context guards encoding the false-positive classes found during
    hand-curation of a real sweep: duration/measurement continuations and
    from/between ranges."""

    def _check(self, text, phrase):
        start = text.index(phrase)
        return tsb.looks_like_false_positive(text, start, start + len(phrase))

    def test_duration_months_rejected(self):
        assert self._check("It had been nearly seven months since the hearing.", "nearly seven") == "unit_tail"

    def test_measurement_feet_rejected(self):
        assert self._check("Nearly seven feet stood Kerchak on his short legs.", "Nearly seven") == "unit_tail"

    def test_adjective_then_unit_rejected(self):
        assert self._check("Nearly seven good leagues.", "Nearly seven") == "unit_tail"

    def test_large_number_rejected(self):
        assert self._check("back nearly seven hundred inscriptions from Yemen", "nearly seven") == "unit_tail"

    def test_range_lead_from_rejected(self):
        assert self._check("an annual term of from five to seven months only", "five to seven") == "range_lead"

    def test_range_lead_between_rejected(self):
        assert self._check("between ten to four hundred", "ten to four") == "range_lead"

    def test_clock_time_kept(self):
        assert self._check("Do you know it is nearly seven?", "nearly seven") is None

    def test_clock_time_with_clause_kept(self):
        assert self._check("It was nearly seven when she returned home.", "nearly seven") is None

    def test_oclock_kept(self):
        assert self._check("at twenty minutes past eight o'clock he rose", "twenty minutes past eight") is None

    # Bare "<minute> to <hour>" hits (issue #293): the gambling idiom and
    # ranges must be rejected, a real clock time with a cue must survive.
    def test_bare_to_one_without_time_cue_rejected(self):
        assert self._check("It is certainly ten to one that they go down-stream.", "ten to one") == "no_time_cue"

    def test_bare_to_one_odds_after_rejected_even_with_cue(self):
        assert self._check("Throwaway, says he, at twenty to one. A rank outsider.", "twenty to one") == "odds"

    def test_bare_to_one_bookmaker_call_rejected(self):
        assert self._check("Ten to one bar one! A dark horse bolts past.", "Ten to one") == "odds"

    def test_bare_to_one_wager_before_rejected(self):
        assert self._check("I will bet him twenty to one, and let any publisher hold it.", "twenty to one") == "odds"

    def test_bare_to_one_chances_rejected(self):
        assert self._check("The chances are twenty to one that it has nothing to do with it.", "twenty to one") == "odds"

    def test_bare_to_with_at_cue_kept(self):
        assert self._check("Come round to-morrow at twenty to three; don't be late.", "twenty to three") is None

    def test_bare_to_one_with_oclock_after_kept(self):
        assert self._check("It wanted ten to one o'clock when the carriage drew up.", "ten to one") is None

    def test_bare_to_with_struck_kept(self):
        assert self._check("It struck five to eight by the church clock.", "five to eight") is None

    def test_minutes_form_needs_no_cue(self):
        assert self._check("He rose at ten minutes to one and went out.", "ten minutes to one") is None
        assert self._check("Ten minutes to one, and still no sign of him.", "Ten minutes to one") is None

    def test_bare_past_form_needs_no_cue(self):
        assert self._check("Ten past seven, and she was still asleep.", "Ten past seven") is None


class TestSearchBucketGuards:
    def test_duration_hit_filtered_from_results(self, tmp_path):
        pg = tmp_path / "pg99.txt"
        pg.write_text(
            "It had been nearly seven months since the hearing ended.\n"
            "Do you know it is nearly seven?\n",
            encoding="utf-8",
        )
        results = tsb.search_bucket("h6_five_to", tmp_path)
        quotes = [r["quote_text"] for r in results]
        assert any("Do you know" in q for q in quotes)
        assert not any("months" in q for q in quotes)

    def test_range_hit_filtered_from_results(self, tmp_path):
        pg = tmp_path / "pg99.txt"
        pg.write_text(
            "The schools ran from five to seven months only.\n"
            "She said she would call at five minutes to seven.\n",
            encoding="utf-8",
        )
        results = tsb.search_bucket("h6_five_to", tmp_path)
        quotes = [r["quote_text"] for r in results]
        assert any("would call" in q for q in quotes)
        assert not any("schools" in q for q in quotes)


class TestCwdRelativeCoveragePath:
    """The coverage JSON argument resolves against the CWD (issue #295)."""

    def test_relative_coverage_json_resolves_against_cwd(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "output").mkdir()
        (tmp_path / "output" / "bucket-coverage.json").write_text(
            json.dumps({"empty_buckets": ["h3_five_past"], "sparse_buckets": []}), encoding="utf-8",
        )
        search_dir = tmp_path / "texts"
        search_dir.mkdir()
        (search_dir / "pg1.txt").write_text("It was five past three when he came in.\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "sys.argv",
            ["target_sparse_buckets.py", "output/bucket-coverage.json", "--search-dir", "texts", "--output", "output/hits.jsonl"],
        )
        assert tsb.main() == 0
        assert (tmp_path / "output" / "hits.jsonl").exists()
        assert "Targeted buckets searched: 1" in capsys.readouterr().out
