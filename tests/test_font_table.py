"""docs/themes.md's bundled-font table must match what the themes load.

The table replaced a hand-written paragraph in CLAUDE.md that nothing kept
true (issue #352); ``scripts/generate_font_table.py`` derives it from
``THEME_FONTS`` and the theme modules, and this test runs its ``--check``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "generate_font_table.py"


def _load():
    spec = importlib.util.spec_from_file_location("generate_font_table", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestFontTable:
    def test_table_is_current(self, capsys):
        assert _load().main(["--check"]) == 0, capsys.readouterr().err

    def test_every_bundled_directory_is_loaded_by_a_theme(self):
        assert _load().unused_dirs() == []

    def test_table_has_a_row_per_directory(self):
        gen = _load()
        table = gen.render_table()
        for family in gen.bundled_dirs():
            label = "`fonts/*.ttf`" if family == gen.ROOT_LABEL else f"`{family}/`"
            assert f"| {label} |" in table, family

    def test_a_face_loaded_only_by_a_theme_module_is_attributed(self):
        # noto-music never appears in THEME_FONTS; lieder imports it directly.
        assert "lieder" in _load().font_usage()["noto-music"]

    def test_fallback_faces_are_not_attributed(self):
        # Playfair backs nearly every chain; only the themes that set it count.
        assert "swiss" not in _load().font_usage()["(top level)"]

    def test_a_face_only_listed_after_another_is_fallback_only(self):
        # control and semiotic set Jost / Archivo / Barlow Condensed and name
        # Oswald second in each chain, in THEME_FONTS and in their own modules.
        sets, falls_back = _load().font_usage_by_role()
        assert not sets.get("oswald")
        assert {"control", "semiotic"} <= falls_back["oswald"]

    def test_a_theme_that_sets_a_face_is_not_also_its_fallback(self):
        sets, falls_back = _load().font_usage_by_role()
        for family, themes in falls_back.items():
            assert not themes & sets.get(family, set()), family
