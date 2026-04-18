"""Tests for merge_candidates.py — text normalization and deduplication."""
from __future__ import annotations

import pytest
from tests.conftest import make_row

import merge_candidates as mc


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
                fuzzy_bucket="h3_exact", daypart_bucket="morning"):
        raw = make_row(
            quote_text=quote,
            context_text=context,
            source_id=source_id,
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

    def test_different_bucket_not_deduplicated(self):
        records = [
            self._record("Same quote text.", fuzzy_bucket="h3_exact"),
            self._record("Same quote text.", fuzzy_bucket="h3_just_after"),
        ]
        merged, _ = mc.dedupe(records)
        assert len(merged) == 2

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
