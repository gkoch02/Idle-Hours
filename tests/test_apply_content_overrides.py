"""Tests for apply_content_overrides.py"""
from __future__ import annotations

import json
import sys

import pytest

from apply_content_overrides import apply_overrides, load_overrides, main, row_key


class TestRowKey:
    def test_builds_source_colon_line(self, sample_row):
        sample_row["source_id"] = "141"
        sample_row["line_number"] = 482
        assert row_key(sample_row) == "141:482"

    def test_missing_source_id_returns_none(self, sample_row):
        sample_row.pop("source_id", None)
        sample_row["line_number"] = 5
        assert row_key(sample_row) is None

    def test_missing_line_number_returns_none(self, sample_row):
        sample_row["source_id"] = "1"
        sample_row.pop("line_number", None)
        assert row_key(sample_row) is None


class TestLoadOverrides:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_overrides(tmp_path / "missing.json") == {}

    def test_reads_json_object(self, tmp_path):
        path = tmp_path / "overrides.json"
        path.write_text('{"1:1": {"display_quote": "hi"}}', encoding="utf-8")
        assert load_overrides(path) == {"1:1": {"display_quote": "hi"}}

    def test_non_object_root_fails_open(self, tmp_path, capsys):
        path = tmp_path / "overrides.json"
        path.write_text("[]", encoding="utf-8")
        result = load_overrides(path)
        assert result == {}
        err = capsys.readouterr().err
        assert "must be a JSON object" in err

    def test_truncated_json_fails_open(self, tmp_path, capsys):
        """An editor crash mid-save must not abort the pipeline."""
        path = tmp_path / "overrides.json"
        path.write_text('{"141:482": {"disp', encoding="utf-8")
        result = load_overrides(path)
        assert result == {}
        err = capsys.readouterr().err
        assert "not valid JSON" in err

    def test_garbage_bytes_fails_open(self, tmp_path, capsys):
        path = tmp_path / "overrides.json"
        path.write_text("not json at all", encoding="utf-8")
        result = load_overrides(path)
        assert result == {}
        assert "not valid JSON" in capsys.readouterr().err


class TestApplyOverrides:
    def test_empty_overrides_is_noop(self, sample_rows):
        rows = [dict(r, source_id="1", line_number=i) for i, r in enumerate(sample_rows, start=1)]
        patched, applied = apply_overrides(rows, {})
        assert applied == 0
        assert patched == rows
        assert all("override_applied" not in r for r in patched)

    def test_patches_display_quote(self, sample_row):
        sample_row["source_id"] = "141"
        sample_row["line_number"] = 482
        patched, applied = apply_overrides([sample_row], {"141:482": {"display_quote": "new text"}})
        assert applied == 1
        assert patched[0]["display_quote"] == "new text"
        assert patched[0]["override_applied"] is True

    def test_does_not_mutate_input_rows(self, sample_row):
        sample_row["source_id"] = "1"
        sample_row["line_number"] = 1
        original = dict(sample_row)
        apply_overrides([sample_row], {"1:1": {"display_quote": "X"}})
        assert sample_row == original

    def test_rederives_bucket_from_new_normalized_time(self, sample_row):
        sample_row["source_id"] = "1"
        sample_row["line_number"] = 1
        sample_row["normalized_time"] = "03:00"
        sample_row["fuzzy_bucket"] = "h3_exact"
        patched, _ = apply_overrides([sample_row], {"1:1": {"normalized_time": "04:30"}})
        assert patched[0]["normalized_time"] == "04:30"
        assert patched[0]["fuzzy_bucket"] == "h4_half_past"

    def test_rederives_normalized_time_from_hour_minute(self, sample_row):
        sample_row["source_id"] = "1"
        sample_row["line_number"] = 1
        sample_row["hour"] = 3
        sample_row["minute"] = 0
        sample_row["normalized_time"] = "03:00"
        sample_row["fuzzy_bucket"] = "h3_exact"
        patched, _ = apply_overrides([sample_row], {"1:1": {"hour": 4, "minute": 30}})
        assert patched[0]["normalized_time"] == "04:30"
        assert patched[0]["fuzzy_bucket"] == "h4_half_past"

    def test_explicit_normalized_time_wins_over_hour_minute(self, sample_row):
        sample_row["source_id"] = "1"
        sample_row["line_number"] = 1
        patched, _ = apply_overrides([sample_row], {
            "1:1": {"hour": 9, "minute": 9, "normalized_time": "04:30"}
        })
        assert patched[0]["normalized_time"] == "04:30"
        assert patched[0]["fuzzy_bucket"] == "h4_half_past"

    def test_warns_on_dangling_key(self, sample_row, capsys):
        sample_row["source_id"] = "1"
        sample_row["line_number"] = 1
        apply_overrides([sample_row], {"999:999": {"display_quote": "x"}})
        err = capsys.readouterr().err
        assert "999:999" in err
        assert "did not match any row" in err

    def test_warns_on_unsupported_field(self, sample_row, capsys):
        sample_row["source_id"] = "1"
        sample_row["line_number"] = 1
        patched, _ = apply_overrides([sample_row], {"1:1": {"quote_text": "ignored", "display_quote": "kept"}})
        err = capsys.readouterr().err
        assert "quote_text" in err
        assert patched[0]["display_quote"] == "kept"
        # Unsupported fields should not end up on the row.
        assert patched[0]["quote_text"] == sample_row["quote_text"]

    def test_lone_hour_override_with_null_minute_warns(self, sample_row, capsys):
        sample_row["source_id"] = "1"
        sample_row["line_number"] = 1
        sample_row["hour"] = None
        sample_row["minute"] = None
        sample_row["normalized_time"] = "03:00"
        sample_row["fuzzy_bucket"] = "h3_exact"
        patched, _ = apply_overrides([sample_row], {"1:1": {"hour": 5}})
        err = capsys.readouterr().err
        assert "inconsistent" in err
        # normalized_time was not touched; bucket is re-derived from the stale value.
        assert patched[0]["normalized_time"] == "03:00"
        assert patched[0]["fuzzy_bucket"] == "h3_exact"

    def test_invalid_normalized_time_warns(self, sample_row, capsys):
        sample_row["source_id"] = "1"
        sample_row["line_number"] = 1
        sample_row["fuzzy_bucket"] = "h3_exact"
        patched, _ = apply_overrides([sample_row], {"1:1": {"normalized_time": "25:99"}})
        err = capsys.readouterr().err
        assert "invalid" in err
        assert "25:99" in err
        # The override still lands on the row (loud failure, not silent drop),
        # but fuzzy_bucket is left as-was rather than corrupted.
        assert patched[0]["normalized_time"] == "25:99"
        assert patched[0]["fuzzy_bucket"] == "h3_exact"

    def test_non_object_patch_logs_and_skips(self, sample_row, capsys):
        sample_row["source_id"] = "1"
        sample_row["line_number"] = 1
        patched, applied = apply_overrides([sample_row], {"1:1": "not an object"})
        err = capsys.readouterr().err
        assert "not an object" in err
        assert applied == 0
        assert "override_applied" not in patched[0]


class TestMain:
    def test_in_place_no_op_with_empty_overrides(self, tmp_path):
        row = {
            "source_id": "1",
            "line_number": 1,
            "display_quote": "unchanged",
            "normalized_time": "03:00",
            "fuzzy_bucket": "h3_exact",
        }
        input_file = tmp_path / "input.jsonl"
        overrides_file = tmp_path / "overrides.json"
        input_file.write_text(json.dumps(row) + "\n", encoding="utf-8")
        overrides_file.write_text("{}", encoding="utf-8")

        sys.argv = ["apply_content_overrides.py", str(input_file), "--overrides", str(overrides_file)]
        main()

        result = json.loads(input_file.read_text(encoding="utf-8").strip())
        assert result["display_quote"] == "unchanged"
        assert "override_applied" not in result

    def test_writes_to_output_path_when_given(self, tmp_path):
        row = {"source_id": "1", "line_number": 1, "display_quote": "old", "normalized_time": "03:00"}
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        overrides_file = tmp_path / "overrides.json"
        input_file.write_text(json.dumps(row) + "\n", encoding="utf-8")
        overrides_file.write_text(json.dumps({"1:1": {"display_quote": "new"}}), encoding="utf-8")

        sys.argv = [
            "apply_content_overrides.py",
            str(input_file),
            "--overrides", str(overrides_file),
            "--output", str(output_file),
        ]
        main()

        # Input untouched, output patched.
        assert json.loads(input_file.read_text(encoding="utf-8").strip())["display_quote"] == "old"
        result = json.loads(output_file.read_text(encoding="utf-8").strip())
        assert result["display_quote"] == "new"
        assert result["override_applied"] is True

    def test_in_place_rewrite_atomic_on_failure(self, tmp_path, monkeypatch):
        """A crash during the in-place write must not truncate the picker's corpus."""
        import os

        row = {
            "source_id": "1",
            "line_number": 1,
            "display_quote": "original",
            "normalized_time": "03:00",
            "fuzzy_bucket": "h3_exact",
        }
        input_file = tmp_path / "input.jsonl"
        overrides_file = tmp_path / "overrides.json"
        input_file.write_text(json.dumps(row) + "\n", encoding="utf-8")
        overrides_file.write_text(json.dumps({"1:1": {"display_quote": "new"}}), encoding="utf-8")
        original_bytes = input_file.read_bytes()

        monkeypatch.setattr(
            os, "replace", lambda s, d: (_ for _ in ()).throw(OSError("simulated power loss"))
        )

        sys.argv = ["apply_content_overrides.py", str(input_file), "--overrides", str(overrides_file)]
        with pytest.raises(OSError):
            main()

        # The input corpus file must be byte-identical to its pre-call state.
        assert input_file.read_bytes() == original_bytes
        assert list(tmp_path.glob("*.tmp")) == []
