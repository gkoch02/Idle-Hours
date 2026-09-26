"""Tests for merge_candidates.py — text normalization and deduplication."""
from __future__ import annotations

import json

from idle_hours import merge_candidates as mc
from tests.conftest import make_row

# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------

class TestNormalizeText:
    def test_lowercases(self):
        assert mc.normalize_text("Hello World") == "hello world"

    def test_collapses_whitespace(self):
        assert mc.normalize_text("hello   world") == "hello world"

    def test_strips_leading_trailing(self):
        assert mc.normalize_text("  hello  ") == "hello"

    def test_replaces_smart_apostrophe(self):
        result = mc.normalize_text("it\u2019s time")
        assert "\u2019" not in result
        assert "'" in result

    def test_replaces_smart_quotes(self):
        result = mc.normalize_text("\u201chello\u201d")
        assert "\u201c" not in result
        assert "\u201d" not in result

    def test_strips_leading_quote(self):
        result = mc.normalize_text('"hello world"')
        assert not result.startswith('"')

    def test_strips_trailing_punctuation(self):
        result = mc.normalize_text("hello world.")
        assert not result.endswith(".")

    def test_empty_string(self):
        assert mc.normalize_text("") == ""


# ---------------------------------------------------------------------------
# dedupe
# ---------------------------------------------------------------------------

class TestDedupe:
    def _record(self, quote, context="context", source_id="1", normalized_time="03:00",
                fuzzy_bucket="h3_exact", daypart_bucket="morning", line_number=100):
        raw = make_row(
            quote_text=quote,
            context_text=context,
            source_id=source_id,
            line_number=line_number,
            normalized_time=normalized_time,
            fuzzy_bucket=fuzzy_bucket,
            daypart_bucket=daypart_bucket,
        )
        return mc.Record(
            raw=raw,
            canonical_quote=mc.normalize_text(quote),
            canonical_context=mc.normalize_text(context),
        )

    def test_unique_rows_all_kept(self):
        records = [
            self._record("First quote.", source_id="1"),
            self._record("Second quote.", source_id="2"),
        ]
        merged, summary = mc.dedupe(records)
        assert len(merged) == 2
        assert summary["deduped_rows"] == 2
        assert summary["duplicates_removed"] == 0

    def test_duplicate_removed(self):
        records = [
            self._record("Same quote.", context="short"),
            self._record("Same quote.", context="short"),
        ]
        merged, summary = mc.dedupe(records)
        assert len(merged) == 1
        assert summary["duplicates_removed"] == 1

    def test_tie_broken_by_longer_context(self):
        records = [
            self._record("Same quote.", context="short context"),
            self._record("Same quote.", context="much longer context that gives more information"),
        ]
        merged, _ = mc.dedupe(records)
        assert len(merged) == 1
        assert "longer" in merged[0]["context_text"]

    def test_different_time_not_deduplicated(self):
        records = [
            self._record("Same quote text.", normalized_time="03:00", fuzzy_bucket="h3_exact"),
            self._record("Same quote text.", normalized_time="03:05", fuzzy_bucket="h3_five_past"),
        ]
        merged, _ = mc.dedupe(records)
        assert len(merged) == 2

    # Issue #294: the key is the hit's position and phrase, not the sentence
    # window or the buckets derived from its time.
    def test_same_hit_with_different_sentence_windows_deduplicated(self):
        records = [
            self._record("It was three o'clock.", context="short"),
            self._record("He looked up. It was three o'clock. Nobody came.", context="longer context here"),
        ]
        merged, summary = mc.dedupe(records)
        assert len(merged) == 1
        assert summary["duplicates_removed"] == 1
        assert "longer" in merged[0]["context_text"]

    def test_derived_daypart_drift_does_not_split_a_hit(self):
        records = [
            self._record("Same quote text.", daypart_bucket="dawn"),
            self._record("Same quote text.", daypart_bucket="night"),
        ]
        merged, _ = mc.dedupe(records)
        assert len(merged) == 1

    def test_same_text_on_different_lines_kept(self):
        a = self._record("Same quote text.")
        b = self._record("Same quote text.")
        b.raw["line_number"] = a.raw["line_number"] + 1
        merged, _ = mc.dedupe([a, b])
        assert len(merged) == 2

    def test_different_phrase_on_same_line_kept(self):
        a = self._record("Ten o'clock, close on ten o'clock.")
        b = self._record("Ten o'clock, close on ten o'clock.", normalized_time="09:55", fuzzy_bucket="h9_five_to")
        b.raw["matched_text"] = "close on ten o'clock"
        merged, _ = mc.dedupe([a, b])
        assert len(merged) == 2

    def test_rows_without_source_id_fall_back_to_quote_text(self):
        a = self._record("Same quote.", source_id=None)
        b = self._record("Same quote.", source_id=None)
        b.raw["line_number"] = 999
        merged, _ = mc.dedupe([a, b])
        assert len(merged) == 1
        assert mc.dedupe_key(a.raw, a.canonical_quote) == ("03:00", "morning", a.canonical_quote)

    def test_dedupe_key_normalises_phrase_case_and_whitespace(self):
        a = self._record("Same quote.")
        b = self._record("Same quote.")
        b.raw["matched_text"] = "Three  O'CLOCK"
        assert mc.dedupe_key(a.raw, a.canonical_quote) == mc.dedupe_key(b.raw, b.canonical_quote)

    def test_summary_counts_correct(self):
        records = [
            self._record("Quote A.", source_id="1"),
            self._record("Quote B.", source_id="2"),
            self._record("Quote A.", source_id="1"),  # duplicate
        ]
        _, summary = mc.dedupe(records)
        assert summary["input_rows"] == 3
        assert summary["deduped_rows"] == 2
        assert summary["duplicates_removed"] == 1

    def test_smart_quote_variants_deduplicated(self):
        # Both should normalize to the same canonical form
        records = [
            self._record("\u201cSame quote.\u201d"),
            self._record('"Same quote."'),
        ]
        merged, _ = mc.dedupe(records)
        assert len(merged) == 1

    def test_canonical_fields_added_to_output(self):
        records = [self._record("A unique quote.")]
        merged, _ = mc.dedupe(records)
        assert "canonical_quote" in merged[0]
        assert "canonical_context" in merged[0]


class TestIterRecords:
    def test_yields_records_with_canonical_fields(self, tmp_jsonl):
        path = tmp_jsonl([
            make_row(quote_text="Hello World.", context_text="  Hello   World.  "),
        ])
        records = list(mc.iter_records([str(path)]))
        assert len(records) == 1
        assert records[0].canonical_quote == "hello world"
        assert records[0].canonical_context == "hello world"


class TestMainCLI:
    def test_writes_merged_and_summary(self, tmp_path, tmp_jsonl, monkeypatch, capsys):
        input_path = tmp_jsonl([
            make_row(quote_text="A unique quote.", source_id="1"),
            make_row(quote_text="Another quote.", source_id="2"),
            make_row(quote_text="A unique quote.", source_id="1"),  # duplicate
        ])
        output_path = tmp_path / "merged.jsonl"
        summary_path = tmp_path / "summary.json"
        monkeypatch.setattr(
            "sys.argv",
            ["merge_candidates.py", str(input_path), "--output", str(output_path), "--summary", str(summary_path)],
        )
        exit_code = mc.main()
        assert exit_code == 0
        assert output_path.exists()
        assert summary_path.exists()
        lines = output_path.read_text().strip().splitlines()
        assert len(lines) == 2  # duplicate removed
        summary = json.loads(summary_path.read_text())
        assert summary["input_rows"] == 3
        assert summary["deduped_rows"] == 2
        assert summary["duplicates_removed"] == 1
        out = capsys.readouterr().out
        assert "Wrote 2 deduped" in out
        assert "Removed 1 duplicates" in out
