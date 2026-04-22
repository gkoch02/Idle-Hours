"""Shared fixtures for LitClock tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path_factory, monkeypatch):
    """Redirect ``~`` to a per-test tmp directory so tests that use default
    ``--state-path`` / ``--history-path`` / ``--telemetry-path`` / ``--pidfile``
    don't leak state into the developer's real ``~/.litclock`` (and can't
    contaminate *each other* within a test run by persisting state between
    tests). The main-loop now persists the render-identity triple
    (``last_bucket`` / ``last_quote_id`` / ``last_effective_theme``) to
    ``state.json`` after every successful render, so test isolation matters
    more than it used to.

    Uses ``tmp_path_factory`` (separate from the per-test ``tmp_path``
    fixture) so tests that assert ``tmp_path.iterdir()`` for "nothing was
    written" don't see the home subdirectory in the listing.
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    # ``pathlib.Path.expanduser`` reads ``$HOME`` on POSIX, so the env-var
    # patch above is enough. We don't touch ``Path.home`` directly so code
    # paths that rely on ``os.path.expanduser`` also pick up the override.
    yield home


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
