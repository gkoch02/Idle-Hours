"""Tests for the PIL-free theme-name shim."""
from __future__ import annotations

import sys

import pytest

from idle_hours import theme_names


class TestKnownThemeNames:
    def test_returns_render_quote_themes(self) -> None:
        # The shim is designed to stay importable without Pillow; the
        # render_quote-path branch obviously can't be exercised without it.
        pytest.importorskip("PIL")
        from idle_hours.render_quote import THEMES

        result = theme_names.known_theme_names()
        assert isinstance(result, frozenset)
        assert result == frozenset(THEMES.keys())

    def test_falls_back_when_render_quote_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If ``render_quote`` cannot be imported, fall back to the legacy pair."""
        monkeypatch.setitem(sys.modules, "idle_hours.render_quote", None)
        result = theme_names.known_theme_names()
        assert result == frozenset(("default", "dark"))


class TestThemeCycle:
    def test_returns_render_quote_order(self) -> None:
        pytest.importorskip("PIL")
        from idle_hours.render_quote import CYCLE_EXCLUDED_THEMES, THEME_ORDER

        result = theme_names.theme_cycle()
        assert isinstance(result, tuple)
        # theme_cycle filters CYCLE_EXCLUDED_THEMES out of THEME_ORDER so a
        # registered-but-opt-in-only theme (e.g. ``tarot``) is reachable via
        # explicit ``--theme NAME`` but skipped by every rotation path.
        expected = tuple(name for name in THEME_ORDER if name not in CYCLE_EXCLUDED_THEMES)
        assert result == expected

    def test_excludes_cycle_excluded_themes(self) -> None:
        """Themes listed in ``CYCLE_EXCLUDED_THEMES`` are stripped from the
        cycle. Pins the contract that exclusion happens here (not by removing
        from ``THEME_ORDER``), which is what keeps the
        ``set(THEME_ORDER) == set(THEMES.keys())`` registration invariant
        intact."""
        pytest.importorskip("PIL")
        from idle_hours.render_quote import CYCLE_EXCLUDED_THEMES

        result = theme_names.theme_cycle()
        for name in CYCLE_EXCLUDED_THEMES:
            assert name not in result

    def test_falls_back_when_render_quote_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "idle_hours.render_quote", None)
        result = theme_names.theme_cycle()
        assert result == ("default", "dark")
