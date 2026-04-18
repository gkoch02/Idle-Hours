"""Tests for enrich_metadata.py"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from enrich_metadata import parse_header


class TestParseHeader:
    def test_extracts_title_and_author(self, tmp_path):
        text = "Title: Pride and Prejudice\nAuthor: Jane Austen\nSome content here.\n"
        path = tmp_path / "pg1342.txt"
        path.write_text(text, encoding="utf-8")
        title, author = parse_header(path)
        assert title == "Pride and Prejudice"
        assert author == "Jane Austen"

    def test_missing_file_returns_nones(self, tmp_path):
        title, author = parse_header(tmp_path / "nonexistent.txt")
        assert title is None
        assert author is None

    def test_title_only(self, tmp_path):
        path = tmp_path / "pg1.txt"
        path.write_text("Title: Moby Dick\nSome content.\n", encoding="utf-8")
        title, author = parse_header(path)
        assert title == "Moby Dick"
        assert author is None

    def test_author_only(self, tmp_path):
        path = tmp_path / "pg1.txt"
        path.write_text("Author: Herman Melville\nSome content.\n", encoding="utf-8")
        title, author = parse_header(path)
        assert title is None
        assert author == "Herman Melville"

    def test_neither_present(self, tmp_path):
        path = tmp_path / "pg1.txt"
        path.write_text("No metadata here.\n", encoding="utf-8")
        title, author = parse_header(path)
        assert title is None
        assert author is None

    def test_stops_after_both_found(self, tmp_path):
        # Second Title/Author lines should be ignored
        text = (
            "Title: First Title\n"
            "Author: First Author\n"
            "Title: Second Title\n"
            "Author: Second Author\n"
        )
        path = tmp_path / "pg1.txt"
        path.write_text(text, encoding="utf-8")
        title, author = parse_header(path)
        assert title == "First Title"
        assert author == "First Author"

    def test_leading_whitespace_stripped(self, tmp_path):
        path = tmp_path / "pg1.txt"
        path.write_text("  Title: The Great Gatsby\n  Author: F. Scott Fitzgerald\n", encoding="utf-8")
        title, author = parse_header(path)
        assert title == "The Great Gatsby"
        assert author == "F. Scott Fitzgerald"

    def test_scans_only_first_120_lines(self, tmp_path):
        lines = ["Filler line\n"] * 121 + ["Title: Late Title\n", "Author: Late Author\n"]
        path = tmp_path / "pg1.txt"
        path.write_text("".join(lines), encoding="utf-8")
        title, author = parse_header(path)
        assert title is None
        assert author is None

    def test_title_with_colon_in_name(self, tmp_path):
        path = tmp_path / "pg1.txt"
        path.write_text("Title: War and Peace: A Novel\nAuthor: Leo Tolstoy\n", encoding="utf-8")
        title, author = parse_header(path)
        assert title == "War and Peace: A Novel"
        assert author == "Leo Tolstoy"


class TestMain:
    def test_enriches_rows_with_metadata(self, tmp_path):
        from enrich_metadata import main
        import sys

        gutenberg_dir = tmp_path / "gutenberg"
        gutenberg_dir.mkdir()
        (gutenberg_dir / "pg1342.txt").write_text(
            "Title: Pride and Prejudice\nAuthor: Jane Austen\n", encoding="utf-8"
        )

        row = {"source_id": "1342", "quote_text": "It was three o'clock."}
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        input_file.write_text(json.dumps(row) + "\n", encoding="utf-8")

        sys.argv = [
            "enrich_metadata.py",
            str(input_file),
            "--output", str(output_file),
            "--gutenberg-dir", str(gutenberg_dir),
        ]
        main()

        result = json.loads(output_file.read_text(encoding="utf-8").strip())
        assert result["title"] == "Pride and Prejudice"
        assert result["author"] == "Jane Austen"

    def test_preserves_existing_title_author(self, tmp_path):
        from enrich_metadata import main
        import sys

        gutenberg_dir = tmp_path / "gutenberg"
        gutenberg_dir.mkdir()
        (gutenberg_dir / "pg1342.txt").write_text(
            "Title: Pride and Prejudice\nAuthor: Jane Austen\n", encoding="utf-8"
        )

        row = {
            "source_id": "1342",
            "title": "Custom Title",
            "author": "Custom Author",
            "quote_text": "It was three o'clock.",
        }
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        input_file.write_text(json.dumps(row) + "\n", encoding="utf-8")

        sys.argv = [
            "enrich_metadata.py",
            str(input_file),
            "--output", str(output_file),
            "--gutenberg-dir", str(gutenberg_dir),
        ]
        main()

        result = json.loads(output_file.read_text(encoding="utf-8").strip())
        assert result["title"] == "Custom Title"
        assert result["author"] == "Custom Author"

    def test_no_source_id_leaves_nulls(self, tmp_path):
        from enrich_metadata import main
        import sys

        gutenberg_dir = tmp_path / "gutenberg"
        gutenberg_dir.mkdir()

        row = {"quote_text": "It was three o'clock."}
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        input_file.write_text(json.dumps(row) + "\n", encoding="utf-8")

        sys.argv = [
            "enrich_metadata.py",
            str(input_file),
            "--output", str(output_file),
            "--gutenberg-dir", str(gutenberg_dir),
        ]
        main()

        result = json.loads(output_file.read_text(encoding="utf-8").strip())
        assert result["title"] is None
        assert result["author"] is None
