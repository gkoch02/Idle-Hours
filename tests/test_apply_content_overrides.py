"""Tests for apply_content_overrides.py"""
from __future__ import annotations

import json
import sys

import pytest

from idle_hours.apply_content_overrides import apply_overrides, load_overrides, main, row_key


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
        sample_row["normalized_time"] = "03:00"
        sample_row["fuzzy_bucket"] = "h3_exact"
        patched, _ = apply_overrides([sample_row], {"1:1": {"normalized_time": "25:99"}})
        err = capsys.readouterr().err
        assert "invalid" in err
        assert "25:99" in err
        # Issue #305: an invalid time is skipped loudly rather than landing on
        # the row, where it would desynchronise hour/minute/bucket.
        assert patched[0]["normalized_time"] == "03:00"
        assert patched[0]["fuzzy_bucket"] == "h3_exact"

    def test_normalized_time_override_rederives_hour_and_minute(self, sample_row):
        # Issue #305: hour/minute used to keep describing the old time.
        sample_row.update(source_id="1", line_number=1, hour=3, minute=0,
                          normalized_time="03:00", fuzzy_bucket="h3_exact")
        (patched,), _ = apply_overrides([sample_row], {"1:1": {"normalized_time": "16:45"}})
        assert (patched["hour"], patched["minute"]) == (16, 45)
        assert patched["fuzzy_bucket"] == "h4_quarter_to"
        assert patched["override_originals"] == {"normalized_time": "03:00", "hour": 3, "minute": 0}
        (restored,), _ = apply_overrides([patched], {})
        assert restored == sample_row

    def test_explicit_hour_survives_a_normalized_time_override(self, sample_row):
        sample_row.update(source_id="1", line_number=1, hour=3, minute=0, normalized_time="03:00")
        (patched,), _ = apply_overrides([sample_row], {"1:1": {"normalized_time": "04:30", "hour": 4}})
        assert (patched["hour"], patched["minute"]) == (4, 30)

    @pytest.mark.parametrize("field,value", [
        ("minute", "30"),
        ("hour", "4"),
        ("hour", True),
        ("hour", 24),
        ("minute", 60),
        ("quality_score", "90"),
        ("quality_score", 101),
        ("normalized_time", "4:30"),
        ("normalized_time", 430),
    ])
    def test_rejects_ill_typed_values(self, sample_row, capsys, field, value):
        sample_row.update(source_id="1", line_number=1, hour=3, minute=0,
                          normalized_time="03:00", fuzzy_bucket="h3_exact", quality_score=80)
        before = dict(sample_row)
        (patched,), applied = apply_overrides([sample_row], {"1:1": {field: value, "display_quote": "Kept."}})
        err = capsys.readouterr().err
        assert f"invalid {field}" in err
        assert patched[field] == before[field]
        assert patched["fuzzy_bucket"] == "h3_exact"
        assert patched["display_quote"] == "Kept."
        assert applied == 1

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


class TestCwdRelativePaths:
    """Operator-typed paths resolve against the CWD, not the package dir (issue #295)."""

    def test_relative_input_resolves_against_cwd(self, tmp_path, monkeypatch):
        row = {"source_id": "1", "line_number": 1, "display_quote": "old", "normalized_time": "03:00"}
        (tmp_path / "work").mkdir()
        (tmp_path / "work" / "corpus.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        (tmp_path / "work" / "ov.json").write_text(json.dumps({"1:1": {"display_quote": "new"}}), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        sys.argv = ["apply_content_overrides.py", "work/corpus.jsonl", "--overrides", "work/ov.json", "--output", "work/out.jsonl"]
        main()
        result = json.loads((tmp_path / "work" / "out.jsonl").read_text(encoding="utf-8").strip())
        assert result["display_quote"] == "new"


class TestReversibleOverrides:
    """The stage writes its output over its input, so an override is baked into
    the raw corpus. It records what it replaced so deleting the sidecar entry
    and re-running restores the row — without that the edit was permanent."""

    @staticmethod
    def _row(**extra):
        row = {
            "source_id": "1", "line_number": 1, "display_quote": "Original text.",
            "matched_text": "three o'clock", "hour": 3, "minute": 0,
            "normalized_time": "03:00", "fuzzy_bucket": "h3_exact", "quality_score": 80,
        }
        row.update(extra)
        return row

    def test_records_the_value_it_replaced(self):
        (patched,), _ = apply_overrides([self._row()], {"1:1": {"display_quote": "Patched."}})
        assert patched["display_quote"] == "Patched."
        assert patched["override_originals"] == {"display_quote": "Original text."}
        assert patched["override_applied"] is True

    def test_removing_the_entry_restores_the_row(self):
        original = self._row()
        (patched,), _ = apply_overrides([original], {"1:1": {"display_quote": "Patched."}})
        stats: dict = {}
        (restored,), applied = apply_overrides([patched], {}, stats=stats)
        assert restored == original
        assert applied == 0 and stats == {"applied": 0, "reverted": 1}

    def test_editing_an_override_keeps_the_true_original(self):
        original = self._row()
        (once,), _ = apply_overrides([original], {"1:1": {"display_quote": "First edit."}})
        (twice,), _ = apply_overrides([once], {"1:1": {"display_quote": "Second edit."}})
        assert twice["display_quote"] == "Second edit."
        assert twice["override_originals"] == {"display_quote": "Original text."}
        (restored,), _ = apply_overrides([twice], {})
        assert restored == original

    def test_dropping_one_field_restores_only_that_field(self):
        original = self._row()
        (both,), _ = apply_overrides([original], {"1:1": {"display_quote": "Patched.", "author": "Someone"}})
        (one,), _ = apply_overrides([both], {"1:1": {"display_quote": "Patched."}})
        assert one["display_quote"] == "Patched."
        assert "author" not in one
        assert one["override_originals"] == {"display_quote": "Original text."}

    def test_reverting_a_time_override_restores_the_bucket(self):
        original = self._row()
        (moved,), _ = apply_overrides([original], {"1:1": {"hour": 4, "minute": 30}})
        assert moved["normalized_time"] == "04:30"
        assert moved["fuzzy_bucket"] == "h4_half_past"
        (restored,), _ = apply_overrides([moved], {})
        assert restored == original

    def test_reapplying_the_same_sidecar_is_a_no_op(self):
        sidecar = {"1:1": {"display_quote": "Patched.", "normalized_time": "04:30"}}
        (once,), _ = apply_overrides([self._row()], sidecar)
        (twice,), _ = apply_overrides([once], sidecar)
        assert twice == once

    def test_a_malformed_entry_keeps_the_active_override(self, capsys):
        """A present-but-malformed entry is a typo, not a deletion: the row
        stays as it was rather than being restored from its originals."""
        (patched,), _ = apply_overrides([self._row()], {"1:1": {"display_quote": "Patched."}})
        (kept,), applied = apply_overrides([patched], {"1:1": None})
        assert kept == patched
        assert applied == 0
        assert "left unchanged" in capsys.readouterr().err

    def test_untouched_rows_are_left_alone(self):
        row = self._row()
        (out,), applied = apply_overrides([row], {})
        assert out == row and applied == 0


class TestDawnExpansionDriverOrdering:
    """String fence on scripts/run_dawn_expansion.sh (issues #295 / #302).

    The driver rebuilds the live corpus from pipeline output, so it must
    re-apply the content-overrides sidecar before coverage and the bake, and
    it must check the merged row count before the merge replaces the corpus.
    """

    SCRIPT = __import__("pathlib").Path(__file__).resolve().parents[1] / "scripts" / "run_dawn_expansion.sh"

    def _pos(self, text, needle):
        assert needle in text, f"{needle!r} missing from {self.SCRIPT.name}"
        return text.index(needle)

    def test_overrides_reapplied_after_merge_and_before_bake(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        install = self._pos(text, 'mv "$TMP_OUT" "$EXISTING"')
        apply = self._pos(text, 'python3 -m idle_hours.apply_content_overrides "$EXISTING"')
        coverage = self._pos(text, "python3 -m idle_hours.bucket_coverage")
        bake = self._pos(text, "python3 -m idle_hours.bake_quote_database")
        assert install < apply < coverage < bake

    def test_shrink_check_runs_before_the_corpus_is_replaced(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        check = self._pos(text, "(( final_rows < baseline_rows ))")
        install = self._pos(text, 'mv "$TMP_OUT" "$EXISTING"')
        assert check < install


class TestReviewFollowUps:
    """Follow-ups from the adversarial review of the #305 change."""

    def _row(self):
        return {"source_id": "1", "line_number": 1, "hour": 2, "minute": 10,
                "normalized_time": "02:10", "fuzzy_bucket": "h2_ten_past", "display_quote": "q"}

    def test_invalid_edit_keeps_the_earlier_valid_override(self, capsys):
        first, _ = apply_overrides([self._row()], {"1:1": {"minute": 30}})
        assert first[0]["normalized_time"] == "02:30"
        second, _ = apply_overrides(first, {"1:1": {"minute": "30"}})
        row = second[0]
        assert (row["minute"], row["normalized_time"], row["fuzzy_bucket"]) == (30, "02:30", "h2_half_past")
        assert row["override_applied"] is True
        # ...and deleting the entry still restores the true original.
        third, _ = apply_overrides(second, {})
        assert (third[0]["minute"], third[0]["normalized_time"]) == (10, "02:10")
        assert "override_originals" not in third[0]

    def test_invalid_normalized_time_edit_keeps_earlier_time(self, capsys):
        first, _ = apply_overrides([self._row()], {"1:1": {"normalized_time": "03:45"}})
        second, _ = apply_overrides(first, {"1:1": {"normalized_time": "3:45"}})
        row = second[0]
        assert (row["hour"], row["minute"], row["normalized_time"]) == (3, 45, "03:45")

    def test_disagreeing_hour_yields_to_normalized_time(self, capsys):
        patched, _ = apply_overrides([self._row()], {"1:1": {"normalized_time": "03:45", "hour": 7, "minute": 50}})
        row = patched[0]
        assert (row["hour"], row["minute"], row["fuzzy_bucket"]) == (3, 45, "h3_quarter_to")
        assert "taken from normalized_time" in capsys.readouterr().err

    def test_non_ascii_digits_rejected(self, capsys):
        patched, _ = apply_overrides([self._row()], {"1:1": {"normalized_time": "\u0660\u0669:\u0663\u0660"}})
        assert patched[0]["normalized_time"] == "02:10"

    def test_bom_prefixed_sidecar_loads(self, tmp_path):
        path = tmp_path / "content_overrides.json"
        path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"1:1": {"display_quote": "x"}}).encode())
        assert load_overrides(path) == {"1:1": {"display_quote": "x"}}
