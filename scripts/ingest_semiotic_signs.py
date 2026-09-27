#!/usr/bin/env python3
"""Build the ``semiotic`` theme's sign sprite sheet from LouH's Semiotic
Standard vector set.

Source: https://github.com/louh/semiotic-standard (CC BY 4.0) — vector
adaptations by LouH of Ron Cobb's Semiotic Standard for *Alien* (1979), via
Brandon Gamm's recreations on The Noun Project. The PNGs are 1000x1050 flat
colour on a transparent ground: Cobb red, black, white, amber, navy, dark
green and one mid grey. Each of those lands on one Spectra 6 ink (the grey on
the K+W 50/50 stipple), so the signs need no dithering at all.

The sheet keeps them ANTIALIASED, at ``TILE`` px wide, in the legend order of
``SIGNS``. Classification onto the inks happens at render time, AFTER the
tile is resized to the size it is painted at: downsampling an already
separated image blends inks and lands off-palette (the ``ingest_tarot_plates``
rule).

The changes made to the source (CC BY 4.0 asks that they be indicated): the
signs are downscaled and packed into one sheet; at render time their colours
are re-mapped onto the panel's six inks.

Usage:
    python3 scripts/ingest_semiotic_signs.py                  # fetch pinned commit
    python3 scripts/ingest_semiotic_signs.py --source DIR     # local PNG folder
"""
from __future__ import annotations

import argparse
import io
import sys
import urllib.request
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "idle_hours" / "assets" / "semiotic_signs.png"

# Pinned so a re-ingest is reproducible even if the upstream repo changes.
COMMIT = "21a46f6d2c57a02449083ede0c98818f7bfe11b6"
RAW = f"https://raw.githubusercontent.com/louh/semiotic-standard/{COMMIT}/"

# Legend order. Must match ``render_quote._SEMIOTIC_SIGNS`` one for one.
SIGNS = (
    "001.PRESSURISED.AREA",
    "002.PRESSURISED.WITH.ARTIFICIAL.GRAVITY",
    "003.ARTIFICIAL.GRAVITY.ABSENT",
    "004.CRYOGENIC.VAULT",
    "005.AIRLOCK",
    "006.BULKHEAD.DOOR",
    "007.NON-PRESSURISED.AREA.BEYOND",
    "008.PRESSURE.SUIT.LOCKER",
    "009.PHOTONIC.SYSTEM.(FIBRE.OPTICS)",
    "010.LASER",
    "011.ASTRONIC.SYSTEM.(ELECTRONICS)",
    "012.HAZARD.WARNING",
    "013.ARTIFICIAL.GRAVITY.AREA.NON-PRESSURISED.SUIT.REQUIRED",
    "014.NO.PRESSURE.GRAVITY.SUIT.REQUIRED",
    "015.EXHAUST",
    "016.AREA.SHIELDED.FROM.RADIATION",
    "017.RADIATION.HAZARD",
    "018.HIGH.RADIOACTIVITY",
    "019.REFRIGERATION",
    "020.DIRECTION",
    "020A.DIRECTION.DOWN",
    "020B.DIRECTION.RIGHT",
    "020C.DIRECTION.LEFT",
    "021.LIFE.SUPPORT.SYSTEM",
    "022.GALLEY",
    "023.COFFEE",
    "024.BRIDGE",
    "025.AUTODOC",
    "026.MAINTENANCE",
    "027.LADDERWAY",
    "028.INTERCOM",
    "029.STORAGE.NON-ORGANIC",
    "029A.STORAGE.ORGANIC.(FOODSTUFFS)",
    "030.COMPUTER.TERMINAL",
)
COLS = 6
TILE = (250, 262)  # the source's 1000:1050 aspect


def _load(name: str, source: Path | None) -> Image.Image:
    if source is not None:
        return Image.open(source / f"{name}.png")
    url = RAW + urllib.request.quote(f"{name}.png")
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 - fixed https host
        return Image.open(io.BytesIO(resp.read()))


def build(source: Path | None) -> Image.Image:
    rows = (len(SIGNS) + COLS - 1) // COLS
    sheet = Image.new("RGBA", (COLS * TILE[0], rows * TILE[1]), (0, 0, 0, 0))
    for i, name in enumerate(SIGNS):
        tile = _load(name, source).convert("RGBA").resize(TILE, Image.Resampling.LANCZOS)
        sheet.paste(tile, ((i % COLS) * TILE[0], (i // COLS) * TILE[1]))
    return sheet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, help="local folder of the upstream PNGs (default: fetch)")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    sheet = build(args.source)
    sheet.save(args.output, optimize=True)
    print(f"wrote {args.output} ({len(SIGNS)} signs, {sheet.size[0]}x{sheet.size[1]})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
