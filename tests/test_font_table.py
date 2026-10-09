"""docs/themes.md's bundled-font table must match what the themes load.

The table replaced a hand-written paragraph in CLAUDE.md that nothing kept
true (issue #352); ``scripts/generate_font_table.py`` derives it from
``THEME_FONTS`` and the theme modules, and this test runs its ``--check``.
"""

from __future__ import annotations

import importlib.util
import struct
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "generate_font_table.py"
FONTS_DIR = REPO_ROOT / "idle_hours" / "fonts"


def _postscript_name(path: Path) -> str:
    """Name id 6 from a TrueType ``name`` table, read with the stdlib only."""
    data = path.read_bytes()
    num_tables = struct.unpack_from(">H", data, 4)[0]
    for i in range(num_tables):
        tag, _checksum, offset, _length = struct.unpack_from(">4sIII", data, 12 + 16 * i)
        if tag != b"name":
            continue
        _fmt, count, strings = struct.unpack_from(">HHH", data, offset)
        for j in range(count):
            platform, encoding, _lang, name_id, length, str_off = struct.unpack_from(">6H", data, offset + 6 + 12 * j)
            if name_id != 6:
                continue
            raw = data[offset + strings + str_off : offset + strings + str_off + length]
            if platform == 3 or (platform == 0 and encoding != 5):
                return raw.decode("utf-16-be")
            if platform == 1:
                return raw.decode("latin-1")
    raise AssertionError(f"{path} has no PostScript name")


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


class TestBundledFontNames:
    def test_no_two_bundled_fonts_share_a_postscript_name(self):
        # Pillow loads by path, so a duplicate is invisible on the panel, but a
        # consumer that registers faces by name keeps only one of them (issue #410).
        owners: dict[str, list[str]] = defaultdict(list)
        fonts = sorted(FONTS_DIR.rglob("*.ttf"))
        assert fonts
        for path in fonts:
            owners[_postscript_name(path)].append(str(path.relative_to(FONTS_DIR)))
        assert {name: paths for name, paths in owners.items() if len(paths) > 1} == {}
