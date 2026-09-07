"""Shared fixtures for Idle Hours tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from idle_hours import path_resolution


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path_factory, monkeypatch):
    """Redirect ``~`` to a per-test tmp directory so tests that use default
    ``--state-path`` / ``--history-path`` / ``--telemetry-path`` / ``--pidfile``
    don't leak state into the developer's real ``~/.idle-hours`` (and can't
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


@pytest.fixture(autouse=True)
def _isolate_photo_theme(monkeypatch):
    """Unset the ``photo`` theme's source for every test.

    The theme reads an operator-configured path out of the environment, so a
    developer who exported it for their own appliance would otherwise have it
    silently leak into the suite — and the damage is not a visible failure but
    a **wrong golden fixture**: ``standard_photo_production`` is regenerated
    with ``UPDATE_RENDER_GOLDEN=1``, and with the variable set it would be
    baked from that developer's own photographs and committed. Unsetting it
    here is what makes the fallback-to-the-bundled-plate path the only thing
    the fixture can capture.

    The env name comes from ``path_resolution`` rather than ``render_quote``
    precisely so this fixture stays Pillow-free: ``conftest`` is loaded for
    every session, including the many test modules that never render, and a
    top-level renderer import would make all of them pay for Pillow. The
    decoded-frame cache is cleared only when the renderer is *already*
    imported, which is exactly the sessions where it can matter — a test
    asserting on a degradation warning must not be silenced by an earlier test
    having latched it.
    """
    monkeypatch.delenv(path_resolution.PHOTO_PATH_ENV, raising=False)

    def _clear():
        module = sys.modules.get("idle_hours.render_quote")
        if module is not None:
            module.clear_photo_cache()

    _clear()
    yield
    _clear()


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


@pytest.fixture(autouse=True)
def _clear_corpus_cache():
    """Isolate the stat-keyed in-process corpus cache (#192) between tests.

    Fast test loops can rewrite a tmp corpus file with the same size inside
    the filesystem's timestamp granularity; clearing around every test keeps
    a stale hit from leaking across cases.
    """
    from idle_hours import pick_quote

    pick_quote.clear_corpus_cache()
    yield
    pick_quote.clear_corpus_cache()


@pytest.fixture(autouse=True)
def _clear_preview_cache():
    """Isolate the /api/preview PNG LRU (#193) between tests."""
    import sys

    ws = sys.modules.get("idle_hours.web_server")
    if ws is not None:
        ws.clear_preview_cache()
    yield
    ws = sys.modules.get("idle_hours.web_server")
    if ws is not None:
        ws.clear_preview_cache()
