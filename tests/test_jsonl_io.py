"""Tests for jsonl_io.iter_jsonl — the shared malformed-line-tolerant reader."""
from __future__ import annotations

from idle_hours.jsonl_io import iter_jsonl


class TestIterJsonl:
    def test_reads_valid_rows(self, tmp_path):
        path = tmp_path / "rows.jsonl"
        path.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
        assert list(iter_jsonl(path)) == [{"a": 1}, {"a": 2}]

    def test_skips_blank_lines(self, tmp_path):
        path = tmp_path / "rows.jsonl"
        path.write_text('{"a": 1}\n\n   \n{"a": 2}\n', encoding="utf-8")
        assert list(iter_jsonl(path)) == [{"a": 1}, {"a": 2}]

    def test_malformed_line_logged_and_skipped(self, tmp_path, capsys):
        path = tmp_path / "rows.jsonl"
        path.write_text('{"a": 1}\nnot-json\n{"a": 2}\n', encoding="utf-8")
        rows = list(iter_jsonl(path))
        assert rows == [{"a": 1}, {"a": 2}]
        err = capsys.readouterr().err
        assert "rows.jsonl:2" in err
        assert "skipping malformed JSON" in err

    def test_all_blank_yields_nothing(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("\n  \n\t\n", encoding="utf-8")
        assert list(iter_jsonl(path)) == []

    def test_trailing_newline_not_required(self, tmp_path):
        path = tmp_path / "rows.jsonl"
        path.write_text('{"a": 1}', encoding="utf-8")
        assert list(iter_jsonl(path)) == [{"a": 1}]

    def test_multiple_malformed_lines_each_logged(self, tmp_path, capsys):
        path = tmp_path / "rows.jsonl"
        path.write_text('nope\n{"ok": true}\nstill-bad\n', encoding="utf-8")
        rows = list(iter_jsonl(path))
        assert rows == [{"ok": True}]
        err = capsys.readouterr().err
        assert "rows.jsonl:1" in err
        assert "rows.jsonl:3" in err
