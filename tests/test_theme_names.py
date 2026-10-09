"""Tests for the Pillow-free theme roster (issue #393)."""
from __future__ import annotations

import subprocess
import sys

from idle_hours import theme_names
from idle_hours.render_quote import THEMES


class TestKnownThemeNames:
    def test_returns_render_quote_themes(self) -> None:
        result = theme_names.known_theme_names()
        assert isinstance(result, frozenset)
        assert result == frozenset(THEMES.keys())


class TestThemeCycle:
    def test_returns_theme_order_minus_exclusions(self) -> None:
        result = theme_names.theme_cycle()
        assert isinstance(result, tuple)
        # theme_cycle filters CYCLE_EXCLUDED_THEMES out of THEME_ORDER so a
        # registered-but-opt-in-only theme is reachable via explicit
        # ``--theme NAME`` but skipped by every rotation path.
        expected = tuple(
            name for name in theme_names.THEME_ORDER if name not in theme_names.CYCLE_EXCLUDED_THEMES
        )
        assert result == expected

    def test_excludes_cycle_excluded_themes(self, monkeypatch) -> None:
        """Exclusion happens here, not by removing a name from ``THEME_ORDER``,
        which is what keeps ``set(THEME_ORDER) == set(THEMES)`` intact."""
        monkeypatch.setattr(theme_names, "CYCLE_EXCLUDED_THEMES", frozenset({"newsprint"}))
        result = theme_names.theme_cycle()
        assert "newsprint" not in result
        assert "newsprint" in theme_names.THEME_ORDER
        assert len(result) == len(theme_names.THEME_ORDER) - 1


class TestSingleSource:
    def test_render_quote_reexports_the_same_objects(self) -> None:
        """``rq.THEME_ORDER`` is the ``theme_names`` tuple, not a copy."""
        from idle_hours import render_quote as rq
        assert rq.THEME_ORDER is theme_names.THEME_ORDER
        assert rq.CYCLE_EXCLUDED_THEMES is theme_names.CYCLE_EXCLUDED_THEMES

    def test_run_clock_theme_choices_come_from_theme_order(self) -> None:
        import argparse
        from unittest.mock import patch

        from idle_hours import run_clock

        holder: dict = {}
        real_parse = argparse.ArgumentParser.parse_args

        def capture(self, *args, **kwargs):
            holder.setdefault("parser", self)
            return real_parse(self, *args, **kwargs)

        with patch("sys.argv", ["run_clock.py", "--once"]), \
                patch.object(argparse.ArgumentParser, "parse_args", capture):
            run_clock.parse_args()
        action = next(a for a in holder["parser"]._actions if a.dest == "theme")
        assert list(action.choices) == [*theme_names.THEME_ORDER, "auto", "random"]

    def test_runtime_imports_stay_pillow_free(self) -> None:
        """The roster moved out of ``render_quote`` so these modules could read
        it without importing Pillow. Each runs in a fresh interpreter, since
        this test process has already loaded PIL."""
        for module in ("theme_names", "run_clock", "web_server", "runtime_theme"):
            code = f"import sys, idle_hours.{module}; sys.exit('PIL' in sys.modules)"
            result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
            assert result.returncode == 0, f"importing idle_hours.{module} loaded Pillow\n{result.stderr}"
