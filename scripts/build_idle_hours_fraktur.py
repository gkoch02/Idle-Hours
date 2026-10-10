#!/usr/bin/env python3
"""Build Idle Hours Fraktur: UnifrakturMaguntia with Manufacturing Consent's lowercase k.

``gothic`` sets its matched phrase in UnifrakturMaguntia, whose ``k`` is the
historical Fraktur form: its arm closes into a loop, so it reads as an ``f`` or a
``t`` to anyone who isn't fluent in blackletter. Time phrases lean on the letter
("o'clock"), so the gothic phrase misread every hour. This script grafts the
``k`` from Manufacturing Consent (another OFL blackletter, whose ``k`` is the
modern open form) into a copy of UnifrakturMaguntia:

* Horizontally the glyph is scaled so its stem matches Unifraktur's
  (204 units at 2048 upm against Manufacturing Consent's 134 at 1200).
* Vertically it is scaled piecewise: the bowl region maps x-height to x-height
  (510 -> 1037) and the ascender above it is compressed to land on Unifraktur's
  ``l``/``h`` top (767 -> 1427), so neither the arm nor the stem sticks out.
* Every GSUB ligature built on ``k`` (``c_k``, ``longs_k``, ...) is dropped:
  they draw the old ``k``, and "o'clock" would otherwise keep it via ``c_k``.

UnifrakturMaguntia carries the Reserved Font Name "UnifrakturMaguntia", which
OFL 1.1 §3 forbids on a modified version, hence the new family name.

The k source is Manufacturing Consent 3.000
(https://github.com/googlefonts/manufacturing-consent-font), not bundled here.

Needs FontTools, which the ``dev`` extra installs (``pip install -e ".[dev]"``).

Usage::

    python3 scripts/build_idle_hours_fraktur.py path/to/ManufacturingConsent-Regular.ttf
"""

from __future__ import annotations

import argparse
from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

FONTS = Path(__file__).resolve().parent.parent / "idle_hours" / "fonts"
BASE = FONTS / "unifraktur" / "UnifrakturMaguntia-Book.ttf"
OUT = FONTS / "idle-hours-fraktur" / "IdleHoursFraktur-Book.ttf"

FAMILY = "Idle Hours Fraktur"
POSTSCRIPT = "IdleHoursFraktur-Book"

# Stem-matched horizontal scale, Manufacturing Consent -> Unifraktur units.
X_SCALE = 204 / 134
# Manufacturing Consent (1200 upm) and Unifraktur (2048 upm) x-height and ascender tops.
SRC_XHEIGHT, SRC_ASCENDER = 510, 767
DST_XHEIGHT, DST_ASCENDER = 1037, 1427


def _map_y(y: float) -> float:
    if y <= SRC_XHEIGHT:
        return y * DST_XHEIGHT / SRC_XHEIGHT
    return DST_XHEIGHT + (y - SRC_XHEIGHT) * (DST_ASCENDER - DST_XHEIGHT) / (SRC_ASCENDER - SRC_XHEIGHT)


def build(k_source: Path, out: Path = OUT) -> None:
    # recalcBBoxes=False: recomputing every glyph's stored bbox moves Unifraktur's
    # hinted rendering of letters this script never touches (enough to fail the
    # gothic golden on "five minutes to nine"). Only the new k gets a fresh bbox.
    base, donor = TTFont(BASE, recalcBBoxes=False), TTFont(k_source)
    donor_glyphs = donor.getGlyphSet()

    outline = DecomposingRecordingPen(donor_glyphs)
    donor_glyphs["k"].draw(outline)
    src_advance, _ = donor["hmtx"]["k"]

    # Scaling about x=0 keeps the donor's sidebearings, scaled with the outline.
    pen = TTGlyphPen(None)
    for op, points in outline.value:
        getattr(pen, op)(*[(round(x * X_SCALE), round(_map_y(y))) for x, y in points])
    glyph = pen.glyph()
    glyph.recalcBounds(None)
    base["glyf"]["k"] = glyph
    base["hmtx"]["k"] = (round(src_advance * X_SCALE), glyph.xMin)

    for lookup in base["GSUB"].table.LookupList.Lookup:
        for subtable in lookup.SubTable:
            ligatures = getattr(subtable, "ligatures", None)
            if ligatures is None:
                continue
            for first in list(ligatures):
                kept = [lig for lig in ligatures[first] if "k" not in [first, *lig.Component]]
                if kept:
                    ligatures[first] = kept
                else:
                    del ligatures[first]

    name = base["name"]
    copyright_ = (
        name.getDebugName(0)
        + "\nCopyright 2019 The Manufacturing Consent Project Authors (lowercase k)."
    )
    for name_id in (1, 3, 4, 6, 16, 17, 21, 22):
        name.removeNames(nameID=name_id)
    for name_id, value in (
        (0, copyright_),
        (1, FAMILY),
        (2, "Book"),
        (3, POSTSCRIPT),
        (4, f"{FAMILY} Book"),
        (5, "UnifrakturMaguntia with the lowercase k from Manufacturing Consent 3.000"),
        (6, POSTSCRIPT),
    ):
        name.setName(value, name_id, 3, 1, 0x409)
        name.setName(value, name_id, 1, 0, 0)

    out.parent.mkdir(parents=True, exist_ok=True)
    base.save(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("k_source", type=Path, help="ManufacturingConsent-Regular.ttf (3.000)")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    build(args.k_source, args.output)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
