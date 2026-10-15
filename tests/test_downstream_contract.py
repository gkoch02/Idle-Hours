"""The Idle Hours names Idle Weather imports, pinned so a refactor here fails here.

Idle Weather (github.com/gkoch02/IdleWeather) installs this package and calls
into it for the renderer, the theme rotation, the mining helpers and the
appliance plumbing. Nothing else marks those names as used outside the repo,
so a rename or a new required argument would pass this suite and break Idle
Weather the next time it bumps its pin.

``CONTRACT`` is a hand-written copy of what Idle Weather calls, not something
read back from the code: it is the oracle (issue #392). Adding an optional
parameter, or a default to a required one, is compatible and passes. Removing
or renaming a name or a parameter, reordering positional parameters or putting
a new one in front of them, adding a required one, or dropping a default fails. When a change here has to break
the contract, change Idle Weather in step, then update this table.

The behaviour checks below call each name with the argument shapes Idle Weather
passes (a weather row, not a clock time), since a compatible signature can
still change what comes back.
"""
from __future__ import annotations

import importlib
import inspect
import sys

import pytest

from idle_hours import display_inky, render_quote
from idle_hours.clean_display_quotes import best_display_quote
from idle_hours.match_span import has_display_match
from idle_hours.pidfile import PidfileLockedError
from idle_hours.quality_filter import score_quote
from idle_hours.runtime_theme import pick_next_random_theme, random_theme_pool, recent_window_size
from idle_hours.theme_names import THEME_ORDER, TIME_SURFACE_THEMES
from tests.pixel_helpers import distinct_inks

POS = inspect.Parameter.POSITIONAL_OR_KEYWORD
KW = inspect.Parameter.KEYWORD_ONLY

# module -> {name: [(parameter, kind, has_default), ...]}; None for a non-callable.
CONTRACT: dict[str, dict[str, list[tuple[str, inspect._ParameterKind, bool]] | None]] = {
    "atomic_io": {
        "atomic_write_bytes": [("path", POS, False), ("payload", POS, False)],
        "atomic_write_text": [("path", POS, False), ("payload", POS, False), ("encoding", KW, True)],
        "atomic_write_lines": [("path", POS, False), ("lines", POS, False), ("encoding", KW, True)],
    },
    "sd_notify": {
        "notify_ready": [],
        "notify_watchdog": [],
    },
    "jsonl_io": {
        "iter_jsonl": [("path", POS, False)],
    },
    "pidfile": {
        "acquire_pidfile": [("pidfile_path", POS, True)],
        "PidfileLockedError": None,
    },
    "clean_display_quotes": {
        "best_display_quote": [("row", POS, False)],
        "curl_quotes": [("text", POS, False)],
        "split_sentences": [("text", POS, False)],
    },
    "enrich_metadata": {
        "parse_header": [("path", POS, False)],
    },
    "gutenberg_time_miner": {
        "fetch_gutenberg_text": [("ebook_id", POS, False), ("download_dir", POS, False)],
    },
    "quality_filter": {
        "score_quote": [("display_quote", POS, False), ("display_fragment", POS, False), ("cleanup_status", POS, False)],
    },
    "match_span": {
        "has_display_match": [("row", POS, False)],
    },
    "runtime_quiet": {
        "in_quiet_hours": [("time_str", POS, False), ("start", POS, False), ("end", POS, False)],
    },
    "runtime_theme": {
        "pick_random_theme": [],
        "pick_next_random_theme": [("bag", POS, False), ("recent", KW, True), ("pool", KW, True)],
        "random_theme_pool": [],
        "recent_window_size": [("pool_size", POS, False)],
    },
    "theme_names": {
        "THEME_ORDER": None,
        "TIME_SURFACE_THEMES": None,
    },
    # Idle Weather's tests pin the renderer's clock seam (astrarium reads it).
    "render_quote.clock": {
        "now": [],
    },
    "render_quote": {
        "render": [
            ("time_str", POS, False), ("quote_row", POS, False), ("width", POS, False), ("height", POS, False),
            ("mode", POS, True), ("theme", POS, True),
        ],
        "render_sleep_frame": [("time_str", POS, False), ("width", POS, False), ("height", POS, False), ("theme", POS, True)],
    },
}

CASES = [(module, name) for module, names in CONTRACT.items() for name in names]


@pytest.mark.parametrize(("module", "name"), CASES, ids=[f"{m}.{n}" for m, n in CASES])
def test_contract_name_is_compatible(module, name):
    obj = getattr(importlib.import_module(f"idle_hours.{module}"), name, None)
    assert obj is not None, f"idle_hours.{module}.{name} is gone; Idle Weather imports it"
    expected = CONTRACT[module][name]
    if expected is None:
        return
    params = inspect.signature(obj).parameters
    for param, kind, has_default in expected:
        assert param in params, f"{module}.{name} lost parameter {param!r}"
        actual = params[param]
        assert actual.kind == kind, f"{module}.{name}({param}) is now {actual.kind.description}"
        if has_default:
            assert actual.default is not inspect.Parameter.empty, f"{module}.{name}({param}) lost its default"
    expected_names = {param for param, _kind, _default in expected}
    # Idle Weather passes these positionally, so they must hold the leading
    # slots: a new optional parameter in front of one would take its argument.
    expected_positional = [p for p, kind, _d in expected if kind == POS]
    leading = [p.name for p in params.values() if p.kind in (inspect.Parameter.POSITIONAL_ONLY, POS)][: len(expected_positional)]
    assert leading == expected_positional, f"{module}.{name} moved its positional parameters: {leading}"
    for extra in params.values():
        if extra.name in expected_names or extra.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        assert extra.default is not inspect.Parameter.empty, f"{module}.{name} gained required parameter {extra.name!r}"


WEATHER_ROW = {
    "display_quote": "He sat by the fire. All that night the rain was falling on the roofs of the town.",
    "matched_text": "the rain was falling",
    "author": "A. Novelist",
    "title": "A Wet Night",
    "source_id": "1342",
    "quality_score": 80,
    "bucket": "Rain",
}


class TestWeatherBehaviour:
    def test_a_weather_phrase_counts_as_a_display_match(self):
        # Idle Weather's database test rejects any row this returns False for.
        assert has_display_match(WEATHER_ROW)

    def test_render_draws_a_weather_row(self):
        image = render_quote.render("14:30", WEATHER_ROW, 800, 480, mode="production", theme="default")
        assert image.size == (800, 480)
        assert len(distinct_inks(image)) > 1

    def test_render_sleep_frame_returns_a_panel_frame(self):
        assert render_quote.render_sleep_frame("23:00", 800, 480, theme="dark").size == (800, 480)

    def test_cleaner_and_scorer_take_a_mined_weather_row(self):
        row = {
            "source_id": "1342",
            "matched_text": "the rain was falling",
            "quote_text": "All that night the rain was falling on the roofs of the town.",
            "context_text": "He sat by the fire. All that night the rain was falling on the roofs of the town. Nobody slept.",
        }
        display, fragment, status = best_display_quote(row)
        assert "the rain was falling" in display
        assert isinstance(fragment, bool) and isinstance(status, str)
        score, flags = score_quote(display, fragment, status)
        assert isinstance(score, int) and isinstance(flags, list)

    def test_random_theme_rotation_keeps_its_shape(self):
        theme, bag = pick_next_random_theme([], recent=[])
        assert theme in random_theme_pool() and theme in THEME_ORDER
        assert isinstance(bag, list)
        assert 0 <= recent_window_size(len(random_theme_pool())) < len(random_theme_pool())

    def test_a_clock_free_rotation_remains(self):
        # Idle Weather rotates through the random pool minus these.
        assert TIME_SURFACE_THEMES <= set(THEME_ORDER)
        clock_free = [t for t in random_theme_pool() if t not in TIME_SURFACE_THEMES]
        theme, _bag = pick_next_random_theme([], pool=clock_free)
        assert theme in clock_free

    def test_pidfile_error_is_an_exception(self):
        assert issubclass(PidfileLockedError, Exception)

    def test_display_bridge_accepts_every_rotated_theme(self, monkeypatch):
        # Idle Weather runs `python -m idle_hours.display_inky IMAGE --theme THEME`.
        for theme in random_theme_pool():
            monkeypatch.setattr(sys, "argv", ["display_inky", "current.png", "--theme", theme])
            args = display_inky.parse_args()
            assert (args.image, args.theme) == ("current.png", theme)
