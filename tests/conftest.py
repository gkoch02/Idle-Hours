"""Shared fixtures for LitClock tests."""
from __future__ import annotations

import json
import pytest
from pathlib import Path


def make_row(**kwargs) -> dict:
    """Build a minimal candidate row with sensible defaults."""
    defaults = {
        "source_id": "1234",
        "source_path": "pg1234.txt",
        "match_type": "oclock_word",
        "matched_text": "three o'clock",
        "quote_text": "It was three o'clock in the afternoon.",
        "context_text": "It was three o'clock in the afternoon when she arrived.",
        "hour": 3,
        "minute": 0,
        "normalized_time": "03:00",
        "fuzzy_bucket": "h3_exact",
        "daypart_bucket": "morning",
        "display_quote": "It was three o'clock in the afternoon.",
        "display_fragment": False,
        "cleanup_status": "complete_sentence",
        "quality_score": 80,
        "quality_flags": [],
        "author": "Jane Austen",
        "title": "Mansfield Park",
    }
    defaults.update(kwargs)
    return defaults


@pytest.fixture
def sample_row():
    return make_row()


@pytest.fixture
def sample_rows():
    return [
        make_row(fuzzy_bucket="h3_exact", quality_score=80, display_quote="It was three o'clock in the afternoon."),
        make_row(fuzzy_bucket="h3_exact", quality_score=70, display_quote="Exactly three o'clock struck the bell."),
        make_row(fuzzy_bucket="h3_just_after", quality_score=90, display_quote="A few minutes past three the letter arrived."),
    ]


@pytest.fixture
def tmp_jsonl(tmp_path):
    """Returns a helper that writes rows to a temp JSONL file and gives back the path."""
    def _write(rows: list[dict], filename: str = "test.jsonl") -> Path:
        path = tmp_path / filename
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return path
    return _write
