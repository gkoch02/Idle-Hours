"""Every bundled font ships with the license that permits bundling it.

The tree carried one face that did not: ``idle_hours/fonts/TFoust.ttf``, whose
name table declared ``© 2025 myfont All rights reserved`` with no grant of any
kind, sitting at the top level with no license file beside it. The README
flagged it, but flagging is not permission — the file still shipped inside every
wheel (``package-data`` sweeps ``fonts/**/*``) and every Docker image, under a
LICENSE that offers recipients the right to redistribute and sublicense it. It
was replaced by Eagle Lake rather than documented further.

Both licences in this bundle require their text to travel with the work — SIL
OFL 1.1 §2 and Apache-2.0 §4(a) — so a face bundled without its license file is
a compliance failure that ships to every user, not a cosmetic omission.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

FONTS = Path(__file__).resolve().parent.parent / "idle_hours" / "fonts"

FONT_SUFFIXES = (".ttf", ".otf", ".ttc")

# Playfair Display sits at the top level of fonts/ and is covered by the
# top-level OFL.txt; every other family lives in its own subdirectory with its
# license file beside it.
TOP_LEVEL_LICENSE = FONTS / "OFL.txt"

_LICENCE_MARKERS = ("SIL OPEN FONT LICENSE", "APACHE LICENSE")


def _fonts() -> list[Path]:
    return sorted(p for p in FONTS.rglob("*") if p.suffix.lower() in FONT_SUFFIXES)


def _licence_for(font: Path) -> Path | None:
    """The license file governing *font*: its own directory's, else top level."""
    for candidate in sorted(font.parent.glob("*.txt")):
        text = candidate.read_text(encoding="utf-8", errors="replace").upper()
        if any(marker in text for marker in _LICENCE_MARKERS):
            return candidate
    return None


def test_the_bundle_is_not_empty():
    """Guard against the sweeps below passing because they found nothing."""
    assert len(_fonts()) >= 40


@pytest.mark.parametrize("font", _fonts(), ids=lambda p: str(p.relative_to(FONTS)))
def test_every_bundled_font_ships_its_licence(font: Path):
    licence = _licence_for(font)
    rel = font.relative_to(FONTS)
    assert licence is not None, (
        f"{rel} is bundled with no license file in its directory. Drop the "
        f"upstream OFL.txt (or LICENSE.txt for an Apache-licensed face) beside "
        f"it. If upstream grants no redistribution licence, the font cannot "
        f"ship here at all — see the TFoust note in this module's docstring."
    )


@pytest.mark.parametrize("font", _fonts(), ids=lambda p: str(p.relative_to(FONTS)))
def test_every_bundled_font_declares_terms_in_its_own_metadata(font: Path):
    """The font's own name table must assert terms, not just a sibling file.

    This is the check that catches the real failure mode. A sibling ``OFL.txt``
    only proves someone put a file in the directory; the embedded record is the
    font's own claim about its terms, and it is where TFoust gave itself away —
    ``All rights reserved``, no license description, no license URL. A face
    found on a design-portfolio site will look every bit as good as an OFL one
    and will usually be silent here.
    """
    names = _name_table(font)
    rel = font.relative_to(FONTS)
    declared = {nid: names.get(nid, "").strip() for nid in (0, 13, 14)}
    assert any(declared.values()), (
        f"{rel} carries no copyright, license description, or license URL in "
        f"its name table — the font asserts no terms about itself. Verify its "
        f"provenance before bundling it; do not rely on a sibling license file."
    )
    combined = " ".join(declared.values()).lower()
    assert "all rights reserved" not in combined or "licen" in combined, (
        f"{rel} declares 'all rights reserved' with no accompanying licence "
        f"grant in its metadata. That is a reservation of rights, not a "
        f"permission — it cannot be redistributed under this project's MIT "
        f"licence. This is exactly what TFoust declared."
    )


def _name_table(path: Path) -> dict[int, str]:
    """Minimal OpenType ``name`` table reader.

    Hand-rolled rather than pulled from fontTools: the suite should not grow a
    dependency to assert a licensing invariant, and this is a fixed-layout walk.
    """
    data = path.read_bytes()
    (num_tables,) = struct.unpack(">H", data[4:6])
    offset = None
    for i in range(num_tables):
        rec = 12 + 16 * i
        tag, _checksum, off, _len = struct.unpack(">4sIII", data[rec : rec + 16])
        if tag == b"name":
            offset = off
            break
    if offset is None:
        return {}

    _fmt, count, string_offset = struct.unpack(">HHH", data[offset : offset + 6])
    out: dict[int, str] = {}
    for i in range(count):
        rec = offset + 6 + 12 * i
        platform, _enc, _lang, name_id, ln, str_off = struct.unpack(">HHHHHH", data[rec : rec + 12])
        start = offset + string_offset + str_off
        raw = data[start : start + ln]
        try:
            value = raw.decode("utf-16-be") if platform == 3 else raw.decode("latin-1")
        except UnicodeDecodeError:
            continue
        out.setdefault(name_id, value)
    return out


def test_top_level_licence_covers_the_top_level_faces():
    """LICENSE says fonts/OFL.txt covers the Playfair files; hold it to that."""
    top = [p for p in FONTS.iterdir() if p.suffix.lower() in FONT_SUFFIXES]
    assert top, "expected Playfair Display at the top level of fonts/"
    assert TOP_LEVEL_LICENSE.exists()
    text = TOP_LEVEL_LICENSE.read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE" in text.upper()
    assert "Playfair Display" in text, (
        "fonts/OFL.txt no longer names Playfair Display, but LICENSE tells "
        "readers it covers the top-level faces. Update whichever is now wrong."
    )
    for font in top:
        assert font.stem.startswith("PlayfairDisplay"), (
            f"{font.name} sits at the top level of fonts/, where the only "
            f"licence on offer is Playfair Display's. Give it its own "
            f"subdirectory with its own licence file."
        )
