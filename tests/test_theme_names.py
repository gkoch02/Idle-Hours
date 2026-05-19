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
        from idle_hours.render_quote import THEME_ORDER

        result = theme_names.theme_cycle()
        assert isinstance(result, tuple)
        assert result == tuple(THEME_ORDER)

    def test_falls_back_when_render_quote_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "idle_hours.render_quote", None)
        result = theme_names.theme_cycle()
        assert result == ("default", "dark")
