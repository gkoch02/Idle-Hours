"""Guards on ``scripts/generate_theme_previews.py``.

The script's *output* is fenced by CI running its own ``--check`` (a step in
the ``golden-render`` job), which is the expensive, thorough half. What is
left here is the cheap half: the ways the script can go wrong quietly rather
than loudly.

Three of them are worth naming because none would fail anything else. If the
pinned corpus row is dropped by a re-bake, a script that fell back to a fresh
pick would regenerate all 63 previews with a different passage and nobody
would know why the diff was so large. If the ``photo`` theme's environment
variable leaked in, a maintainer who had exported it for their own appliance
would commit their holiday photos into the README — the same trap
``tests/conftest.py`` unsets it to avoid for the golden fixtures. And the
``diags`` panel reads the real host name, outbound IP and uptime, so without a
stub its thumbnail is both unreproducible (the CI check would fail on every
run as the uptime ticks) and a leak of whichever machine generated it.
"""

from __future__ import annotations

import datetime
import importlib.util
import types
from pathlib import Path

import pytest

from idle_hours import path_resolution
from idle_hours import render_quote as rq
from idle_hours.pick_quote import DEFAULT_DATABASE_PATH
from idle_hours.theme_names import known_theme_names

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "generate_theme_previews.py"


def _load_script():
    """Import the generator by path — ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location("generate_theme_previews", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_script()


class TestPin:
    def test_the_pin_resolves_against_the_shipped_corpus(self, gen):
        row = gen.pinned_row(Path(DEFAULT_DATABASE_PATH))
        assert str(row["source_id"]) == gen.PREVIEW_SOURCE_ID
        assert row["line_number"] == gen.PREVIEW_LINE_NUMBER
        assert row["matched_text"] == gen.PREVIEW_MATCHED_TEXT
        # The README names the book, so the pin had better still be that book.
        assert row["title"] == "The Time Machine"
        assert row["author"] == "H. G. Wells"

    def test_a_dropped_pin_fails_loudly_rather_than_re_picking(self, gen, monkeypatch):
        """A silent fallback here would rewrite every preview with a new passage."""
        monkeypatch.setattr(gen, "PREVIEW_SOURCE_ID", "999999")
        with pytest.raises(SystemExit) as excinfo:
            gen.pinned_row(Path(DEFAULT_DATABASE_PATH))
        message = str(excinfo.value)
        assert "999999:646" in message
        assert "PREVIEW_" in message, "the error must name the fix"

    def test_a_matched_text_mismatch_is_distinguished_from_a_missing_row(self, gen, monkeypatch):
        """`(source_id, line_number)` does not identify a row — 128 keys are duplicated."""
        monkeypatch.setattr(gen, "PREVIEW_MATCHED_TEXT", "half past two")
        with pytest.raises(SystemExit) as excinfo:
            gen.pinned_row(Path(DEFAULT_DATABASE_PATH))
        message = str(excinfo.value)
        assert "matched phrase" in message
        assert "is not in" not in message, "must not report the row as missing"


class TestThemeSelection:
    def test_it_refuses_to_rewrite_every_preview_by_accident(self, gen):
        with pytest.raises(SystemExit, match="--all"):
            gen.select_themes(gen.parse_args([]))

    def test_check_needs_no_opt_in_because_it_writes_nothing(self, gen):
        assert gen.select_themes(gen.parse_args(["--check"])) == sorted(known_theme_names())

    def test_all_selects_every_registered_theme(self, gen):
        assert gen.select_themes(gen.parse_args(["--all"])) == sorted(known_theme_names())

    def test_an_unknown_theme_is_rejected(self, gen):
        with pytest.raises(SystemExit, match="nosuchtheme"):
            gen.select_themes(gen.parse_args(["--theme", "nosuchtheme"]))

    def test_duplicate_themes_collapse_and_order_is_the_callers(self, gen):
        chosen = gen.select_themes(gen.parse_args(["--theme", "dark", "--theme", "default", "--theme", "dark"]))
        assert chosen == ["dark", "default"]


class TestDeterminism:
    def test_an_operators_photo_path_cannot_reach_the_preview(self, gen, tmp_path, monkeypatch):
        """Verified against the real leak: without the guard the env changes the render."""
        row = gen.pinned_row(Path(DEFAULT_DATABASE_PATH))
        clean = gen.render_preview("photo", row).tobytes()

        holiday = tmp_path / "holiday.png"
        rq.Image.new("RGB", (600, 400), (200, 40, 40)).save(holiday)
        monkeypatch.setenv(path_resolution.PHOTO_PATH_ENV, str(holiday))

        assert gen.render_preview("photo", row).tobytes() == clean
        # The guard is load-bearing, not decorative: unguarded, that env wins.
        leaked = rq.render(gen.PREVIEW_TIME, dict(row), gen.WIDTH, gen.HEIGHT,
                           mode=gen.MODE, theme="photo").tobytes()
        assert leaked != clean
        # And it restores what it borrowed.
        assert gen.os.environ[path_resolution.PHOTO_PATH_ENV] == str(holiday)

    def test_the_diags_panel_shows_no_real_host_ip_or_uptime(self, gen, monkeypatch):
        """Unreproducible AND a leak: uptime moves, hostname and IP are the machine's.

        Caught by the CI check disagreeing with a file generated ten minutes
        earlier — `UPTIME 6m` against `UPTIME 14m`. The leak half is the worse
        one: generated on a maintainer's laptop this thumbnail carries their
        hostname and LAN IP into a public README.
        """
        real = {"host": "someones-laptop", "ip": "10.1.2.3", "uptime": "999d 1h 1m"}
        monkeypatch.setattr(rq, "_diags_system_info", lambda: dict(real))
        row = gen.pinned_row(Path(DEFAULT_DATABASE_PATH))

        stubbed = gen.render_preview("diags", row).tobytes()
        # The stub wins over whatever the machine reports...
        monkeypatch.setattr(rq, "_diags_system_info", lambda: {"host": "other", "ip": "10.9.9.9", "uptime": "3m"})
        assert gen.render_preview("diags", row).tobytes() == stubbed
        # ...and the guard is load-bearing: unguarded, those values reach the frame.
        leaked = rq.render(gen.PREVIEW_TIME, dict(row), gen.WIDTH, gen.HEIGHT,
                           mode=gen.MODE, theme="diags").tobytes()
        assert leaked != stubbed
        # The stand-in address must stay inside TEST-NET-1 (RFC 5737).
        assert gen.DIAGS_STUB_SYSTEM_INFO["ip"].startswith("192.0.2.")

    def test_the_clock_freeze_overrides_ambient_time(self, gen, monkeypatch):
        """`astrarium` prints the date; without the freeze its preview expires overnight."""
        row = gen.pinned_row(Path(DEFAULT_DATABASE_PATH))
        expected = gen.render_preview("astrarium", row).tobytes()

        # Pretend the machine clock is a year off. render_preview must not care.
        class _Other(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.datetime(2027, 11, 3, 4, 5, 6)

        class _OtherDate(datetime.date):
            @classmethod
            def today(cls):
                return datetime.date(2027, 11, 3)

        monkeypatch.setattr(rq, "datetime", types.SimpleNamespace(
            datetime=_Other, date=_OtherDate,
            timedelta=datetime.timedelta, timezone=datetime.timezone,
        ))
        assert gen.render_preview("astrarium", row).tobytes() == expected
        # Same guard: unfrozen, that ambient clock really does change the frame.
        drifted = rq.render(gen.PREVIEW_TIME, dict(row), gen.WIDTH, gen.HEIGHT,
                            mode=gen.MODE, theme="astrarium").tobytes()
        assert drifted != expected
