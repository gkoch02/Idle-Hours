"""Tests for target_sparse_buckets.py"""
from __future__ import annotations

from target_sparse_buckets import expected_targets, sentence_window, templates_for_bucket


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
