#!/usr/bin/env python3
"""Render a picked literary clock quote with a centered QOTD-inspired layout."""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import atomic_io
import pick_quote as pick_quote_module

BASE_DIR = Path(__file__).resolve().parent
_FONT_FALLBACK_WARNED = False

DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 480
SPECTRA6 = {
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "red": (255, 0, 0),
    "yellow": (255, 255, 0),
    "blue": (0, 0, 255),
    "green": (0, 255, 0),
}
SPECTRA6_PALETTE = list(SPECTRA6.values())
# Theme cycle order for button B / web dropdown. Kept as an explicit tuple so
# the cycle is stable regardless of dict-literal ordering in Python; every name
# here must also appear as a key in ``THEMES`` below (enforced in tests).
THEME_ORDER: tuple[str, ...] = (
    "default",
    "dark",
    "scholar",
    "newsprint",
    "nightvision",
    "blueprint",
    "illuminated",
    "bauhaus",
    "risograph",
    "comic",
)
THEMES = {
    "default": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    "dark": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # Scholarly journal: blue body on cream-white, red accent for the matched
    # phrase. Readable at a distance thanks to the strong blue/white contrast.
    "scholar": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["blue"],
        "subtle": SPECTRA6["blue"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["blue"],
    },
    # Pure typography: no colour accent at all. Matched phrase differentiates by
    # bold weight against the same ink colour, like an old broadsheet. Quiet.
    "newsprint": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["black"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Retro terminal / Apollo-era mission monitor. Green body on black with a
    # yellow accent for the matched phrase — reads well at night and contrasts
    # strongly enough on the Spectra 6 panel to stay legible.
    "nightvision": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["green"],
        "subtle": SPECTRA6["green"],
        "faint": SPECTRA6["green"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["green"],
        "source": SPECTRA6["green"],
    },
    # Drafting / engineering blueprint. White paper, blue ink for the body
    # text and ornaments, red for the matched time phrase (the "dimension
    # mark" pulled out of the drawing). Sits visually distinct from
    # ``scholar`` (also white/blue/red) thanks to the geometric Archivo
    # sans-serif chosen in THEME_FONTS — same palette, different family.
    "blueprint": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["blue"],
        "subtle": SPECTRA6["blue"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["blue"],
    },
    # Medieval illuminated manuscript. White vellum, red body text
    # (rubrication, the traditional mark of a liturgical or emphasised
    # passage) and lapis-blue for the matched time phrase. EB Garamond
    # handles the body at legible sizes; the blackletter
    # UnifrakturMaguntia sits in the ornament slot for the big curly
    # quotation marks, carrying the scriptorium texture without wrecking
    # body legibility.
    "illuminated": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["red"],
        "subtle": SPECTRA6["red"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["red"],
    },
    # Bauhaus poster. White ground, black body, blue for the matched time
    # phrase, red for the oversized quotation marks — the three primaries
    # used simultaneously, as in the Bauhaus palette. Jost (a Futura-adjacent
    # geometric sans) carries the architectural-typography vibe and sits
    # visually distinct from both blueprint's Archivo (grotesque) and the
    # other serif-heavy themes.
    "bauhaus": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Risograph / zine two-colour print. Red body text, blue "overprint"
    # on the matched time phrase, zero black ink anywhere — that "no
    # black" constraint is the defining aesthetic of the riso theme,
    # pinned explicitly as a test invariant so a well-meaning
    # "darken the source credit" refactor can't silently erode it.
    # ornament_dark stays on a primary (blue) so the big curly marks
    # carry the second-colour overprint texture. Rubik (chunky rounded
    # geometric sans) gives the zine / indie-print register.
    "risograph": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["red"],
        "subtle": SPECTRA6["red"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["red"],
    },
    # Golden-age comic panel. Yellow ground (the first yellow-
    # background theme — Spectra 6's flat yellow reads as a bright
    # newsprint-comic page), black body for speech-bubble legibility,
    # red accent for the matched time phrase like a sound-effect
    # callout. Bangers is an all-caps comic-book hand; body text ends
    # up shouting slightly, which is the point.
    "comic": {
        "page_bg": SPECTRA6["yellow"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["black"],
    },
}
SIDE_MARGIN = 20

QUOTE_FONT_REGULAR_CANDIDATES = [
    str(BASE_DIR / "fonts/PlayfairDisplay-Regular.ttf"),
    "/home/pi/.local/share/fonts/playfair-display/PlayfairDisplay-Regular.ttf",
    "/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-Regular.ttf",
    "/usr/share/fonts/truetype/playfair/PlayfairDisplay-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
]
QUOTE_FONT_BOLD_CANDIDATES = [
    str(BASE_DIR / "fonts/PlayfairDisplay-Bold.ttf"),
    "/home/pi/.local/share/fonts/playfair-display/PlayfairDisplay-Bold.ttf",
    "/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-Bold.ttf",
    "/usr/share/fonts/truetype/playfair/PlayfairDisplay-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
]
QUOTE_FONT_SEMIBOLD_CANDIDATES = [
    str(BASE_DIR / "fonts/PlayfairDisplay-SemiBold.ttf"),
    "/home/pi/.local/share/fonts/playfair-display/PlayfairDisplay-SemiBold.ttf",
    "/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-SemiBold.ttf",
    "/usr/share/fonts/truetype/playfair/PlayfairDisplay-SemiBold.ttf",
    str(BASE_DIR / "fonts/PlayfairDisplay-Medium.ttf"),
    "/home/pi/.local/share/fonts/playfair-display/PlayfairDisplay-Medium.ttf",
    "/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-Medium.ttf",
    "/usr/share/fonts/truetype/playfair/PlayfairDisplay-Medium.ttf",
    str(BASE_DIR / "fonts/PlayfairDisplay-Bold.ttf"),
]
ORNAMENT_FONT_CANDIDATES = [
    str(BASE_DIR / "fonts/PlayfairDisplay-Bold.ttf"),
    str(BASE_DIR / "fonts/PlayfairDisplay-Regular.ttf"),
    "/home/pi/.local/share/fonts/playfair-display/PlayfairDisplay-Bold.ttf",
    "/home/pi/.local/share/fonts/playfair-display/PlayfairDisplay-Regular.ttf",
    "/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-Bold.ttf",
    "/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-Regular.ttf",
    "/usr/share/fonts/truetype/playfair/PlayfairDisplay-Bold.ttf",
    "/usr/share/fonts/truetype/playfair/PlayfairDisplay-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]
META_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]
META_FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]

# Per-theme font candidate chains. Each role (``quote_regular``, ``quote_bold``,
# ``ornament``) resolves through the usual fallback chain; entries may be a
# plain path string or a ``(path, variation_name)`` tuple for variable fonts
# (``load_font`` calls ``set_variation_by_name`` after loading). The Playfair
# chain stays the default for ``default`` / ``dark`` so those goldens don't
# drift; each of the eight operator-choice themes picks a face from a
# different type family so the rendered frame's silhouette — not just the
# palette — shifts with the theme:
#
# * ``scholar`` → Bitter (chunky slab serif — textbook / academic journal
#   register; a different type *family* from the Playfair transitional serif,
#   so the theme reads as more than just a recoloured default). Uses one
#   variable font with Regular / Bold axis picks.
# * ``newsprint`` → Old Standard TT (vintage broadsheet / scientific-journal
#   Didone-flavoured serif, pairs with the monochrome ink aesthetic).
# * ``nightvision`` → Space Mono (retro-terminal mono that stays legible on
#   eInk at the layout's font sizes; DejaVu Sans Mono falls back when Space
#   Mono isn't installed).
# * ``blueprint`` → Archivo (geometric grotesque sans-serif — the only
#   pure-sans face in the lineup, so blueprint reads as a different *family*
#   from scholar even though both share the white/blue/red palette).
#   DejaVu Sans / Liberation Sans / Noto Sans fall back when Archivo isn't
#   installed.
# * ``illuminated`` → EB Garamond for the body (humanist old-style
#   manuscript serif — legible at the layout's font sizes unlike a full
#   blackletter body) with UnifrakturMaguntia (blackletter) in the
#   ornament slot so the oversized curly quotation marks carry the
#   scriptorium texture. DejaVu Serif falls back when EB Garamond is
#   missing; the ornament chain ends at the Playfair bold so a missing
#   blackletter downgrades to a heavy serif rather than bitmap-fallback.
# * ``bauhaus`` → Jost (Futura-adjacent modern geometric sans). Shares the
#   sans-serif family with blueprint (Archivo) but picks a face from the
#   geometric-constructed branch rather than the grotesque, so the two
#   sans themes stay visually distinguishable. Ships one variable font
#   with Regular / Bold axis picks (same pattern as Bitter for scholar);
#   a missing ``set_variation_by_name`` would render at the axis-default
#   weight (Regular).
# * ``risograph`` → Rubik (chunky rounded modern sans). Rubik's soft
#   corners sit visually distinct from both blueprint's Archivo
#   (grotesque, sharper terminals) and bauhaus's Jost (thinner,
#   neo-grotesque geometric), so the three sans-based themes stay
#   differentiable on the panel. Ships as a variable font; axis default
#   is Light (300) so the Regular / Bold instances are pinned explicitly.
# * ``comic`` → Bangers (all-caps comic-book display hand). Stands
#   alone as the only *display* / hand-lettered face in the lineup —
#   an obvious silhouette difference from every serif / sans / mono
#   sibling. Only one weight ships, so the matched time phrase falls
#   through to a heavier fallback (DejaVu Sans Bold) to keep the
#   weight differentiation readable when Bangers isn't installed.
#
# When the requested face isn't on disk, each chain ends at the Playfair /
# DejaVu defaults so a missing-fonts install still renders rather than
# bitmap-fallbacking.
BITTER_VARIABLE = str(BASE_DIR / "fonts/bitter/Bitter-Variable.ttf")
OLDSTANDARD_REGULAR = str(BASE_DIR / "fonts/old-standard-tt/OldStandard-Regular.ttf")
OLDSTANDARD_BOLD = str(BASE_DIR / "fonts/old-standard-tt/OldStandard-Bold.ttf")
SPACEMONO_REGULAR = str(BASE_DIR / "fonts/space-mono/SpaceMono-Regular.ttf")
SPACEMONO_BOLD = str(BASE_DIR / "fonts/space-mono/SpaceMono-Bold.ttf")
ARCHIVO_REGULAR = str(BASE_DIR / "fonts/archivo/Archivo-Regular.ttf")
ARCHIVO_BOLD = str(BASE_DIR / "fonts/archivo/Archivo-Bold.ttf")
EBGARAMOND_REGULAR = str(BASE_DIR / "fonts/eb-garamond/EBGaramond-Regular.ttf")
EBGARAMOND_BOLD = str(BASE_DIR / "fonts/eb-garamond/EBGaramond-Bold.ttf")
UNIFRAKTUR_BOOK = str(BASE_DIR / "fonts/unifraktur/UnifrakturMaguntia-Book.ttf")
JOST_VARIABLE = str(BASE_DIR / "fonts/jost/Jost-Variable.ttf")
RUBIK_VARIABLE = str(BASE_DIR / "fonts/rubik/Rubik-Variable.ttf")
BANGERS_REGULAR = str(BASE_DIR / "fonts/bangers/Bangers-Regular.ttf")

THEME_FONTS: dict[str, dict[str, list]] = {
    "default": {
        "quote_regular": QUOTE_FONT_SEMIBOLD_CANDIDATES,
        "quote_bold": QUOTE_FONT_BOLD_CANDIDATES,
        "ornament": ORNAMENT_FONT_CANDIDATES,
    },
    "dark": {
        "quote_regular": QUOTE_FONT_SEMIBOLD_CANDIDATES,
        "quote_bold": QUOTE_FONT_BOLD_CANDIDATES,
        "ornament": ORNAMENT_FONT_CANDIDATES,
    },
    "scholar": {
        # Bitter is a slab serif — the chunky, even-contrast silhouette sits
        # visually far from both Playfair Display (default/dark — high-contrast
        # transitional) and Old Standard TT (newsprint — Didone hairlines) so
        # the scholar theme reads as a different type *family*, not just a
        # recolour of the default. The variable font defaults to Thin weight
        # (axis minimum is 100), so every variation candidate here sets the
        # instance explicitly — a missing ``set_variation_by_name`` would
        # produce near-invisible ghost strokes on the panel.
        "quote_regular": [
            (BITTER_VARIABLE, "Regular"),
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (BITTER_VARIABLE, "Bold"),
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (BITTER_VARIABLE, "Bold"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "newsprint": {
        "quote_regular": [
            OLDSTANDARD_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            OLDSTANDARD_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            OLDSTANDARD_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "nightvision": {
        "quote_regular": [
            SPACEMONO_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            SPACEMONO_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            SPACEMONO_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "blueprint": {
        # Archivo is the only pure sans-serif primary in the rotation. Falls
        # back through the common Linux/Pi sans installs (DejaVu / Liberation
        # / Noto) before degrading to the Playfair serif chain — the latter
        # would clash with the blueprint vibe but at least keeps the panel
        # readable on a mis-configured install.
        "quote_regular": [
            ARCHIVO_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            ARCHIVO_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            ARCHIVO_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "illuminated": {
        # Humanist old-style body (EB Garamond) with a blackletter ornament
        # (UnifrakturMaguntia). The body picks a serif *family* not already
        # represented (Playfair is transitional, Bitter is slab, Old Standard
        # is Didone) so illuminated reads as a different silhouette. The
        # ornament slot — used only for the oversized curly quotation marks
        # — carries the scriptorium texture; a blackletter body would shred
        # legibility at dense-layout font sizes on a 4-bit eInk panel.
        "quote_regular": [
            EBGARAMOND_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            EBGARAMOND_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            UNIFRAKTUR_BOOK,
            EBGARAMOND_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "bauhaus": {
        # Jost is a variable font defaulting to weight 400; every
        # variation candidate below pins the instance explicitly so a
        # missing ``set_variation_by_name`` doesn't leave the bold phrase
        # visually indistinguishable from the body. Falls back through
        # the same sans chain as ``blueprint`` for install-parity before
        # degrading to the Playfair serif chain.
        "quote_regular": [
            (JOST_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (JOST_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (JOST_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "risograph": {
        # Rubik's variable-font axis minimum is Light (weight 300) — the
        # file's default instance is Light, NOT Regular — so a missing
        # set_variation_by_name call would render body text noticeably
        # too thin. Pin Regular / Bold explicitly on every candidate.
        # Shares the sans fallback chain with blueprint / bauhaus so
        # missing-font installs still land on a sans before degrading to
        # the Playfair serif default.
        "quote_regular": [
            (RUBIK_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (RUBIK_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (RUBIK_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "comic": {
        # Bangers ships only Regular — there's no true Bold companion
        # face — so the matched-phrase role re-uses the same file and
        # gains weight differentiation purely through the accent colour.
        # A sans Bold falls in behind for installs missing Bangers, so
        # the bold phrase stays visibly heavier than the body even when
        # Bangers degrades to DejaVu.
        "quote_regular": [
            BANGERS_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            BANGERS_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            BANGERS_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
}


def theme_font_candidates(theme: str, role: str) -> list:
    """Return the candidate chain for ``role`` under ``theme``.

    Unknown themes fall back to the ``default`` entry so a forgotten
    ``THEME_FONTS`` registration still renders (with the default face) rather
    than raising KeyError deep inside the layout engine.
    """
    fonts = THEME_FONTS.get(theme) or THEME_FONTS["default"]
    return fonts.get(role) or THEME_FONTS["default"][role]

LAYOUTS = {
    "hero": {
        "max_width": 640,
        "quote_height": 248,
        "font_max": 66,
        "font_min": 32,
        "line_height_mult": 1.12,
        "mark_scale": 3.0,
        "mark_min": 76,
        "mark_max": 126,
        "title_size": 17,
        "author_gap": 16,
        "title_gap": 4,
    },
    "standard": {
        "max_width": 660,
        "quote_height": 258,
        "font_max": 58,
        "font_min": 28,
        "line_height_mult": 1.14,
        "mark_scale": 2.8,
        "mark_min": 72,
        "mark_max": 118,
        "title_size": 16,
        "author_gap": 14,
        "title_gap": 4,
    },
    "dense": {
        "max_width": 680,
        "quote_height": 276,
        "font_max": 48,
        "font_min": 24,
        "line_height_mult": 1.18,
        "mark_scale": 2.5,
        "mark_min": 64,
        "mark_max": 102,
        "title_size": 15,
        "author_gap": 12,
        "title_gap": 4,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a literary clock quote for a given time.")
    parser.add_argument("--time", required=True, help="Time in HH:MM 24-hour format")
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output PNG path. Defaults to output/current.png (overwritten on every "
            "run) so repeated ad-hoc invocations don't leak one file per HH:MM into "
            "output/. Pass an explicit path when you want a persistent per-time "
            "artifact. run_clock.py always passes --output explicitly, so the "
            "runtime loop is unaffected by this default."
        ),
    )
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument(
        "--mode",
        choices=["production", "debug", "card"],
        default="debug",
        help=(
            "Render mode. 'production' hides debug UI; 'debug' shows bucket/quality/time "
            "metadata; 'card' draws a centered source card (title/author/Gutenberg ID/"
            "matched phrase) instead of the full quote — used by the source-card button."
        ),
    )
    parser.add_argument(
        "--theme",
        choices=sorted(THEMES),
        default="default",
        help="Color theme to use when rendering.",
    )
    parser.add_argument(
        "--history-path",
        default=pick_quote_module.DEFAULT_HISTORY_PATH,
        help="Path to the anti-repeat display history JSONL. Pass an empty string to disable.",
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=pick_quote_module.DEFAULT_HISTORY_DAYS,
        help="Number of days of history to consider when filtering repeats. 0 disables.",
    )
    return parser.parse_args()


def pick_quote(time_str: str, history_path: str | None = None, history_days: int = pick_quote_module.DEFAULT_HISTORY_DAYS) -> dict:
    return pick_quote_module.select_quote(
        time_str=time_str,
        history_path=history_path,
        history_days=history_days,
        database_path=pick_quote_module.DEFAULT_DATABASE_PATH,
    )


def load_font(candidates: list, size: int):
    """Load the first reachable TrueType font in ``candidates``.

    Each entry is either a plain path string or a ``(path, variation_name)``
    tuple. When the tuple form is used and the face is a variable font,
    ``set_variation_by_name`` selects the named instance (e.g. ``"Bold"``) —
    this is how per-theme weight picks for the bundled Bitter variable font
    work (its default axis instance is Thin, so the variation is load-bearing
    — a missed call would render near-invisible hairlines on the panel).
    A variation name that the file doesn't expose falls through to
    the default instance silently; the next fallback candidate only fires if
    the file itself is missing or unreadable.
    """
    global _FONT_FALLBACK_WARNED
    for candidate in candidates:
        if isinstance(candidate, tuple):
            path, variation = candidate
        else:
            path, variation = candidate, None
        if not Path(path).exists():
            continue
        try:
            font = ImageFont.truetype(path, size=size)
        except OSError:
            continue
        if variation:
            try:
                font.set_variation_by_name(variation)
            except (OSError, ValueError, AttributeError):
                pass
        return font
    if not _FONT_FALLBACK_WARNED:
        print(
            "warning: no TrueType font found; falling back to PIL bitmap default. "
            "Install fonts-noto-core or the bundled fonts/ directory.",
            file=sys.stderr,
            flush=True,
        )
        _FONT_FALLBACK_WARNED = True
    return ImageFont.load_default()


def strip_underscore_emphasis(text: str) -> str:
    if not text or "_" not in text:
        return text or ""
    return re.sub(r"(?<![A-Za-z0-9])_([^_\n]+?)_(?![A-Za-z0-9])", r"\1", text)


def normalize_dashes(text: str) -> str:
    if not text or "--" not in text:
        return text or ""
    return re.sub(r"(?<!-)--(?!-)", "\u2014", text)


def choose_layout(text: str) -> str:
    length = len((text or "").strip())
    if length <= 90:
        return "hero"
    if length <= 170:
        return "standard"
    return "dense"


TIME_PHRASE_PREFIXES = [
    "five minutes past",
    "ten minutes past",
    "quarter past",
    "twenty minutes past",
    "twenty-five minutes past",
    "half past",
    "twenty-five minutes to",
    "twenty minutes to",
    "quarter to",
    "ten minutes to",
    "five minutes to",
]


def resolve_display_match(text: str, match_text: str) -> str:
    normalized_match = " ".join((match_text or "").split()).strip()
    if not normalized_match:
        return ""

    direct = re.search(rf"(?<![A-Za-z0-9])(?<![A-Za-z0-9]-){re.escape(normalized_match)}(?![A-Za-z0-9])(?!-[A-Za-z0-9])", text, re.IGNORECASE)
    if direct:
        return direct.group(0)

    for prefix in sorted(TIME_PHRASE_PREFIXES, key=len, reverse=True):
        if not normalized_match.lower().startswith(prefix):
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9])(?<![A-Za-z0-9]-){re.escape(prefix)}(?:[ ,]+[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)?(?![A-Za-z0-9])(?!-[A-Za-z0-9])", re.IGNORECASE)
        for m in pattern.finditer(text):
            candidate = m.group(0).strip(" ,.;:!?")
            if candidate.lower().startswith(normalized_match.lower()):
                return candidate

    return normalized_match


def tokenize_quote(text: str, match_text: str) -> list[tuple[str, bool]]:
    normalized_match = resolve_display_match(text, match_text)
    if not normalized_match:
        return [(text, False)]
    pattern = re.compile(rf"(?<![A-Za-z0-9])(?<![A-Za-z0-9]-){re.escape(normalized_match)}(?![A-Za-z0-9])(?!-[A-Za-z0-9])", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return [(text, False)]

    idx = match.start()
    match_end = match.end()
    while match_end < len(text) and text[match_end] in '”"\'’.,;:!?':
        match_end += 1

    return [
        (text[:idx], False),
        (text[idx:match_end], True),
        (text[match_end:], False),
    ]


def wrap_styled_text(draw, segments, regular_font, bold_font, max_width):
    lines = []
    current = []
    current_width = 0

    for text, is_bold in segments:
        font = bold_font if is_bold else regular_font
        parts = text.split(" ")
        for i, part in enumerate(parts):
            if part:
                bbox = draw.textbbox((0, 0), part, font=font)
                token_width = bbox[2] - bbox[0]
                if current and current_width + token_width > max_width:
                    lines.append(current)
                    current = []
                    current_width = 0
                current.append((part, is_bold))
                current_width += token_width
            if i < len(parts) - 1:
                bbox = draw.textbbox((0, 0), " ", font=font)
                space_width = bbox[2] - bbox[0]
                if current and current_width + space_width > max_width:
                    lines.append(current)
                    current = []
                    current_width = 0
                else:
                    current.append((" ", is_bold))
                    current_width += space_width

    if current:
        lines.append(current)
    return lines


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = []
    for word in words:
        trial = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def fit_quote(draw, text, match_text, max_width, max_height, font_max, font_min, line_height_mult, theme: str = "default"):
    segments = tokenize_quote(text, match_text)
    regular_candidates = theme_font_candidates(theme, "quote_regular")
    bold_candidates = theme_font_candidates(theme, "quote_bold")
    for size in range(font_max, font_min - 1, -2):
        regular_font = load_font(regular_candidates, size=size)
        bold_font = load_font(bold_candidates, size=size)
        wrapped = wrap_styled_text(draw, segments, regular_font, bold_font, max_width)
        line_height = int(size * line_height_mult)
        total_height = len(wrapped) * line_height
        if total_height <= max_height:
            return regular_font, bold_font, wrapped, line_height, size
    regular_font = load_font(regular_candidates, size=font_min)
    bold_font = load_font(bold_candidates, size=font_min)
    wrapped = wrap_styled_text(draw, segments, regular_font, bold_font, max_width)
    return regular_font, bold_font, wrapped, int(font_min * line_height_mult), font_min


def line_width(draw, line, regular_font, bold_font):
    width = 0
    for chunk, is_bold in line:
        font = bold_font if is_bold else regular_font
        bbox = draw.textbbox((0, 0), chunk, font=font)
        width += bbox[2] - bbox[0]
    return width


def draw_text(draw, xy, text, font, fill):
    draw.text(xy, text, font=font, fill=fill)


def draw_faux_gray_text(image: Image.Image, xy, text, font, dark=(0, 0, 0), light=(255, 255, 255), pattern_offset=(0, 0)):
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(xy, text, font=font, fill=255)
    px = image.load()
    mx = mask.load()
    ox, oy = pattern_offset
    for y in range(image.height):
        for x in range(image.width):
            if mx[x, y]:
                px[x, y] = dark if ((x + ox) + (y + oy)) % 2 == 0 else light


def _paint_theme_border(image: Image.Image, theme: str, colors: dict) -> None:
    """Dispatch to the decorative-border helper registered for ``theme``.

    Kept as a single seam so ``render`` and ``render_source_card`` stay
    in sync — adding a future theme border means registering it in
    ``_BORDER_PAINTERS`` below and (if it paints in the top-right)
    extending ``_DEBUG_LABEL_RIGHT_INSET``. No other render paths need
    to change.
    """
    painter = _BORDER_PAINTERS.get(theme)
    if painter is not None:
        painter(image, colors)


def draw_bauhaus_border(image: Image.Image, colors: dict) -> None:
    """Paint a Bauhaus-inspired geometric frame around the canvas margin.

    A thin outer rectangle plus four corner accents — circle, square,
    triangle, circle — in the theme's three primaries (black body,
    blue accent, red ornament). Referencing the classic Bauhaus
    vocabulary of basic geometric forms in primary hues. Drawn after
    the page_bg fill and before any text, so text always sits on top
    of the border if the two were ever to overlap.

    The corner shapes sit tangent to the canvas edges and overlap the
    outer rectangle's corners, giving the "layered geometry" look of a
    Bauhaus poster frame. Sized to stay well outside the quote block
    (``SIDE_MARGIN + 18`` is the innermost text feature, and these
    shapes don't reach past x=30).
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    frame_inset = 14
    frame_color = colors["text"]
    accent_color = colors["accent"]
    ornament_color = colors["ornament_dark"]

    # Outer rectangle outline — Pillow's rectangle ``width`` kw takes care
    # of the thickness in a single draw call.
    draw.rectangle(
        (frame_inset, frame_inset, width - 1 - frame_inset, height - 1 - frame_inset),
        outline=frame_color,
        width=2,
    )

    corner_size = 22
    corner_margin = 6
    # Top-left: red filled circle.
    draw.ellipse(
        (corner_margin, corner_margin,
         corner_margin + corner_size, corner_margin + corner_size),
        fill=ornament_color,
    )
    # Top-right: blue filled square.
    draw.rectangle(
        (width - corner_margin - corner_size, corner_margin,
         width - corner_margin, corner_margin + corner_size),
        fill=accent_color,
    )
    # Bottom-left: blue filled triangle. Right-angle at the bottom-left
    # corner, hypotenuse sweeping up to the top-right of the bounding box,
    # so the shape visually points inward toward the quote block.
    bl_left = corner_margin
    bl_top = height - corner_margin - corner_size
    bl_right = corner_margin + corner_size
    bl_bottom = height - corner_margin
    draw.polygon(
        [(bl_left, bl_bottom), (bl_right, bl_bottom), (bl_right, bl_top)],
        fill=accent_color,
    )
    # Bottom-right: red filled circle, mirroring the top-left and completing
    # the diagonal colour balance.
    draw.ellipse(
        (width - corner_margin - corner_size, height - corner_margin - corner_size,
         width - corner_margin, height - corner_margin),
        fill=ornament_color,
    )


def draw_blueprint_border(image: Image.Image, colors: dict, clear_rect: tuple[int, int, int, int] | None = None) -> None:
    """Paint a drafting-sheet border and graph-paper grid over the canvas.

    A thin outer rectangle in the body-text blue plus four small red
    crosshair "registration marks" centred on the frame corners — the
    print-alignment tick used on engineering drawings and blueprints —
    with a thin blue graph-paper grid inside the frame so the ground
    reads as engineering paper rather than an empty sheet. When
    ``clear_rect`` is provided, the grid skips that quote-sized window so
    the text block gets a calmer field without losing the drafting-sheet
    frame and corner marks.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    frame_inset = 16
    frame_color = colors.get("subtle", colors["text"])
    border_color = colors["text"]
    mark_color = colors["accent"]

    grid_spacing = 20
    grid_left = frame_inset + 1
    grid_right = width - 2 - frame_inset
    grid_top = frame_inset + 1
    grid_bottom = height - 2 - frame_inset

    if clear_rect is not None:
        clear_left, clear_top, clear_right, clear_bottom = clear_rect
    else:
        clear_left = clear_top = clear_right = clear_bottom = None

    x = frame_inset + grid_spacing
    while x <= grid_right:
        if clear_rect is None or x < clear_left or x > clear_right:
            draw.line((x, grid_top, x, grid_bottom), fill=frame_color, width=1)
        else:
            if grid_top < clear_top:
                draw.line((x, grid_top, x, clear_top), fill=frame_color, width=1)
            if clear_bottom < grid_bottom:
                draw.line((x, clear_bottom, x, grid_bottom), fill=frame_color, width=1)
        x += grid_spacing

    y = frame_inset + grid_spacing
    while y <= grid_bottom:
        if clear_rect is None or y < clear_top or y > clear_bottom:
            draw.line((grid_left, y, grid_right, y), fill=frame_color, width=1)
        else:
            if grid_left < clear_left:
                draw.line((grid_left, y, clear_left, y), fill=frame_color, width=1)
            if clear_right < grid_right:
                draw.line((clear_right, y, grid_right, y), fill=frame_color, width=1)
        y += grid_spacing

    draw.rectangle(
        (frame_inset, frame_inset, width - 1 - frame_inset, height - 1 - frame_inset),
        outline=border_color,
        width=1,
    )

    arm = 8
    centres = [
        (frame_inset, frame_inset),
        (width - 1 - frame_inset, frame_inset),
        (frame_inset, height - 1 - frame_inset),
        (width - 1 - frame_inset, height - 1 - frame_inset),
    ]
    for cx, cy in centres:
        draw.line((cx - arm, cy, cx + arm, cy), fill=mark_color, width=1)
        draw.line((cx, cy - arm, cx, cy + arm), fill=mark_color, width=1)


def draw_illuminated_border(image: Image.Image, colors: dict) -> None:
    """Paint a manuscript-style border around the canvas margin.

    A double rubricated rule (two parallel thin red rectangles with a
    narrow blank band between them) plus a small blue "jewel" — a
    filled circle — centred on each outer corner. The double-rule is
    the workhorse border of medieval illuminated manuscripts, and the
    corner gem evokes the inset lapis cabochons that appear on rich
    bindings and liturgical headpieces.

    Parallels the ``draw_bauhaus_border`` / ``draw_blueprint_border``
    structural pattern (outer frame + four corner graphics) but the
    doubled rule + coloured jewel reads as scribal-margin rather than
    poster-composition or drafting-sheet.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    body = colors["text"]       # rubricated red
    accent = colors["accent"]   # lapis blue

    outer_inset = 14
    inner_inset = 22
    # Outer rule.
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=body,
        width=1,
    )
    # Inner rule — the "doubled" rubrication line.
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=body,
        width=1,
    )

    jewel_radius = 5
    centres = [
        (outer_inset, outer_inset),
        (width - 1 - outer_inset, outer_inset),
        (outer_inset, height - 1 - outer_inset),
        (width - 1 - outer_inset, height - 1 - outer_inset),
    ]
    for cx, cy in centres:
        draw.ellipse(
            (cx - jewel_radius, cy - jewel_radius, cx + jewel_radius, cy + jewel_radius),
            fill=accent,
        )


def draw_newsprint_border(image: Image.Image, colors: dict) -> None:
    """Paint a broadsheet-style Scotch-rule border around the canvas margin.

    A classic thick-thin parallel rule: a heavier outer rectangle and a
    hairline inner rectangle separated by a narrow band of white space.
    This is the signature border of 19th-century newspaper typography —
    the "Scotch rule" — and stays purely typographical: no corner
    accents, no coloured ornament, nothing but weighted ink. That
    restraint matches the newsprint theme's no-colour-accent palette
    (every theme field is black or white), so the margin reads as
    broadsheet rather than modernist poster.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    ink = colors["text"]

    # Outer heavy rule.
    outer_inset = 10
    outer_weight = 3
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=ink,
        width=outer_weight,
    )
    # Inner hairline rule, with a gap of white between the two.
    inner_inset = 18
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=ink,
        width=1,
    )


def draw_nightvision_border(image: Image.Image, colors: dict) -> None:
    """Paint HUD-style corner brackets around the canvas margin.

    Four L-shaped brackets — two perpendicular green arms meeting at
    each canvas corner, with no continuous outer frame. The bracket-
    only composition is the iconic camera-viewfinder / weapons-HUD /
    mission-monitor border motif; the absent full-rectangle frame is
    the distinctive feature (full-frame HUDs are unusual), which sets
    nightvision's border visually apart from the bauhaus / blueprint /
    illuminated / newsprint patterns.

    Drawn in the body green so brackets stay legible against the
    theme's black page background without competing with the yellow
    accent the matched time phrase already owns.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    bracket = colors["text"]  # green

    margin = 12       # canvas-edge inset of the corner point
    arm = 26          # length of each bracket arm
    thickness = 2     # weight of the bracket strokes
    right_x = width - 1 - margin
    bottom_y = height - 1 - margin

    # Each corner: one horizontal arm and one vertical arm, rendered
    # as filled rectangles so the 2px thickness is exact regardless
    # of Pillow's line-width rounding.
    # Top-left
    draw.rectangle((margin, margin, margin + arm, margin + thickness - 1), fill=bracket)
    draw.rectangle((margin, margin, margin + thickness - 1, margin + arm), fill=bracket)
    # Top-right
    draw.rectangle((right_x - arm, margin, right_x, margin + thickness - 1), fill=bracket)
    draw.rectangle((right_x - thickness + 1, margin, right_x, margin + arm), fill=bracket)
    # Bottom-left
    draw.rectangle((margin, bottom_y - thickness + 1, margin + arm, bottom_y), fill=bracket)
    draw.rectangle((margin, bottom_y - arm, margin + thickness - 1, bottom_y), fill=bracket)
    # Bottom-right
    draw.rectangle((right_x - arm, bottom_y - thickness + 1, right_x, bottom_y), fill=bracket)
    draw.rectangle((right_x - thickness + 1, bottom_y - arm, right_x, bottom_y), fill=bracket)


def draw_scholar_border(image: Image.Image, colors: dict) -> None:
    """Paint an annotated-manuscript / academic-journal margin system.

    Scholar gets a more opinionated page architecture than a plain frame:
    double blue margin rules, faint horizontal baseline guides in the outer
    margins, and small red footnote / reference glyphs that make the page
    feel edited and studied rather than merely recoloured.

    The center text column stays clear; the extra structure lives in the
    margins where it reads as apparatus, not interference.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    body = colors["text"]
    accent = colors["accent"]

    outer_inset = 18
    inner_inset = 28
    left_margin_rule = 96
    right_margin_rule = width - 96

    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=body,
        width=1,
    )
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=body,
        width=1,
    )

    draw.line((left_margin_rule, inner_inset, left_margin_rule, height - 1 - inner_inset), fill=body, width=1)
    draw.line((right_margin_rule, inner_inset, right_margin_rule, height - 1 - inner_inset), fill=body, width=1)

    for y in range(74, height - 60, 42):
        draw.line((outer_inset + 8, y, left_margin_rule - 10, y), fill=body, width=1)
        draw.line((right_margin_rule + 10, y, width - 1 - outer_inset - 8, y), fill=body, width=1)

    marker_font = load_font(theme_font_candidates("scholar", "ornament"), size=20)
    left_marks = ["1", "2", "3", "*", "†", "§"]
    right_marks = ["a", "b", "c", "¶", "‡", "#"]
    for i, y in enumerate(range(84, height - 80, 56)):
        lmark = left_marks[i % len(left_marks)]
        rmark = right_marks[i % len(right_marks)]
        lb = draw.textbbox((0, 0), lmark, font=marker_font)
        rb = draw.textbbox((0, 0), rmark, font=marker_font)
        draw_text(draw, (54 - (lb[2] - lb[0]) // 2, y), lmark, font=marker_font, fill=accent)
        draw_text(draw, (width - 54 - (rb[2] - rb[0]) // 2, y), rmark, font=marker_font, fill=accent)

    header_y = 46
    draw.line((outer_inset + 14, header_y, width // 2 - 70, header_y), fill=body, width=1)
    draw.line((width // 2 + 70, header_y, width - 1 - outer_inset - 14, header_y), fill=body, width=1)
    title_font = load_font(META_FONT_BOLD_CANDIDATES, size=15)
    header = "SCHOLARLY EDITION"
    hb = draw.textbbox((0, 0), header, font=title_font)
    hx = (width - (hb[2] - hb[0])) // 2
    draw_text(draw, (hx, header_y - (hb[3] - hb[1]) - 4), header, font=title_font, fill=body)

_COMIC_STRIPE_PALETTE = (
    SPECTRA6["blue"],
    SPECTRA6["green"],
    SPECTRA6["red"],
    SPECTRA6["black"],
)


def draw_comic_corner_stripes(image: Image.Image, colors: dict) -> None:
    """Paint retro 70s-style 45° racing stripes into the bottom-right corner.

    Parallel diagonal bands cycling through the four non-yellow palette
    accents (blue / green / red / black) sweep down-and-right at 45°,
    evoking the chromatic chevron motif of mid-century racing graphics
    and 70s/80s graphic design. The yellow page_bg shows through the
    gaps so the chevron reads as banded stripes rather than a solid
    block.

    Constrained to a 45° right-isoceles triangle pinned to the bottom-
    right canvas corner — legs of length ``height // 2`` running along
    the bottom and right edges, hypotenuse sweeping from
    ``(width - height // 2, height)`` up to ``(width, height // 2)``.
    The hypotenuse runs at exactly slope -1, parallel to the stripes
    themselves, so the boundary edge "fades in" along the stripe
    direction rather than clipping bands at an angle. Strict to the
    bottom-right corner — the bottom-left half of the lower-right
    quadrant stays yellow page_bg so the quote body never crosses the
    chevron even on the longest dense-layout lines.

    Drawn after the page_bg fill and before any text, so any glyph
    that does land inside the triangle overlays the stripes — text
    wins, the chevron shows through whitespace.

    Stripe palette is hardcoded at module scope rather than read from
    ``colors`` because the comic theme dict only carries two non-bg
    accents (text=black, accent=red); pulling the cool blue/green
    half of the chevron from anywhere else would require extending the
    THEMES schema, which the cross-theme invariant tests pin tightly.
    The yellow gap colour does come from ``colors["page_bg"]`` so a
    future palette tweak that swaps the comic ground still flows
    through.
    """
    width, height = image.size
    qx = width // 2
    qy = height // 2
    qw = width - qx
    qh = height - qy

    # Paint stripes onto a sub-image sized to the lower-right quadrant
    # so 45° bands that extend past either edge clip naturally on the
    # sub-image bounds rather than needing per-stripe polygon math.
    quadrant = Image.new("RGB", (qw, qh), color=colors["page_bg"])
    qd = ImageDraw.Draw(quadrant)

    stripe_thickness = 23
    period = 30
    palette = _COMIC_STRIPE_PALETTE

    # Bands run with slope -1 (down-and-left): each line passes through
    # (c, qh) at the sub-image's bottom edge and (c + qh, 0) at the top
    # edge, so the chevron leans up-and-to-the-right and parallels the
    # mask hypotenuse. Visible range of c is [-qh, qw]; iterate a touch
    # wider so rounded line caps still clip cleanly.
    #
    # Restrict the painted bands to the same four-stripe window in the
    # visible ``c`` sequence regardless of render size. For the default
    # 800×480 canvas this reproduces the historical [240, 330] quartet;
    # smaller canvases scale to the nearest equivalent stripe indices
    # instead of dropping the accent entirely.
    stripe_cs = list(range(-qh - period, qw + period + 1, period))
    if qh == 240 and qw == 400:
        kept_indices = {17, 18, 19, 20}
    else:
        default_qh = 240
        default_qw = 400
        default_stripe_cs = list(range(-default_qh - period, default_qw + period + 1, period))
        default_keep_indices = [
            idx for idx, c in enumerate(default_stripe_cs)
            if 240 <= c <= 330
        ]
        target_mid = sum(default_keep_indices) / len(default_keep_indices)
        scale = len(stripe_cs) / len(default_stripe_cs)
        scaled_mid = target_mid * scale
        keep_start = round(scaled_mid - 1.5)
        keep_start = max(0, min(keep_start, max(0, len(stripe_cs) - 4)))
        kept_indices = set(range(keep_start, min(len(stripe_cs), keep_start + 4)))

    for i, c in enumerate(stripe_cs):
        if i in kept_indices:
            color = palette[i % len(palette)]
            qd.line([(c, qh), (c + qh, 0)], fill=color, width=stripe_thickness)

    # 45° right-isoceles triangle mask pinned to the bottom-right of
    # the quadrant. Legs of length qh (the shorter dimension) so the
    # hypotenuse runs at exactly slope -1, parallel to the stripes.
    # Painted in mode "L" so paste() reads it as a per-pixel alpha —
    # striped pixels land on the canvas only where the mask is 255.
    mask = Image.new("L", (qw, qh), 0)
    md = ImageDraw.Draw(mask)
    md.polygon([(qw - qh, qh), (qw, 0), (qw, qh)], fill=255)

    image.paste(quadrant, (qx, qy), mask=mask)


# Registry consumed by ``_paint_theme_border``. Mapping is intentionally sparse
# — themes without a border entry paint nothing. Extend here when adding a new
# theme border (and update ``_DEBUG_LABEL_RIGHT_INSET`` below if the new graphic
# touches the top-right corner).
_BORDER_PAINTERS = {
    "bauhaus": draw_bauhaus_border,
    "blueprint": draw_blueprint_border,
    "comic": draw_comic_corner_stripes,
    "scholar": draw_scholar_border,
    "illuminated": draw_illuminated_border,
    "newsprint": draw_newsprint_border,
    "nightvision": draw_nightvision_border,
}

# Themes whose decorative border paints a graphic in the top-right corner need
# the debug-mode "DEBUG MODE" banner pushed inward past the graphic so the last
# glyph isn't clipped. Measured from the right canvas edge past the graphic's
# outer extent plus a small breathing gap. Keep in sync with the matching
# ``draw_*_border`` helper — a missing entry for a TR-painting border will
# silently clip the label; the ``test_debug_label_does_not_clip_border``
# invariant catches that class of regression.
#
# Themes in ``_BORDER_PAINTERS`` *without* an entry here have a TR graphic
# that sits outside the DEBUG MODE label's bounding rectangle by construction:
#   - newsprint: Scotch rule's right side paints x=width-13 to width-11, leaving
#     ~7px of clearance beyond the default label right edge (x=width-SIDE_MARGIN).
#   - nightvision: HUD corner bracket's TR vertical arm paints x=width-13 to
#     width-12 (y>=12), leaving ~7px of clearance; the horizontal arm sits at
#     y=12-13, a row above the label's y=14 baseline.
_DEBUG_LABEL_RIGHT_INSET = {
    "bauhaus": 38,      # past the 6+22px TR filled square
    "blueprint": 34,    # past the TR crosshair arm (frame at 16 + 8px arm)
    "illuminated": 28,  # past the TR jewel (frame at 14, radius 5 → x=width-9)
}


def snap_image_to_palette(image: Image.Image, palette: list[tuple[int, int, int]]) -> Image.Image:
    snapped = Image.new("RGB", image.size)
    src = image.load()
    dst = snapped.load()
    for y in range(image.height):
        for x in range(image.width):
            pixel = src[x, y]
            nearest = min(
                palette,
                key=lambda c: (pixel[0] - c[0]) ** 2 + (pixel[1] - c[1]) ** 2 + (pixel[2] - c[2]) ** 2,
            )
            dst[x, y] = nearest
    return snapped


def debug_quote_id(quote_row: dict) -> str | None:
    source_id = quote_row.get("source_id")
    source_path = quote_row.get("source_path") or ""
    line_number = quote_row.get("line_number")

    parts = []
    if source_id:
        parts.append(str(source_id))
    elif source_path:
        parts.append(Path(source_path).stem)

    if line_number is not None:
        parts.append(f"L{line_number}")

    if not parts and source_path:
        return Path(source_path).name
    return ":".join(parts) if parts else None


def fallback_title(quote_row: dict) -> str | None:
    source_id = quote_row.get("source_id")
    if source_id:
        return f"Project Gutenberg #{source_id}"
    source_path = quote_row.get("source_path")
    if source_path:
        return Path(source_path).stem
    return None


def render_source_card(quote_row: dict, width: int, height: int, theme: str = "default") -> Image.Image:
    """Render a centered metadata card for the current quote.

    Used by the Inky button-C handler: a viewer presses C, this card is shown for
    a few seconds, then the loop repaints the original frame. Reuses the theme
    palette and bundled fonts so it visually matches the quote frame.
    """
    colors = THEMES[theme]
    image = Image.new("RGB", (width, height), color=colors["page_bg"])
    _paint_theme_border(image, theme, colors)
    draw = ImageDraw.Draw(image)

    title_text = (quote_row.get("title") or fallback_title(quote_row) or "Unknown source").strip()
    author_text = (quote_row.get("author") or "").strip()
    source_id = quote_row.get("source_id")
    source_id_text = f"Project Gutenberg #{source_id}" if source_id else ""
    matched_text = (quote_row.get("matched_text") or "").strip()
    matched_text = normalize_dashes(strip_underscore_emphasis(matched_text))

    label_font = load_font(META_FONT_CANDIDATES, size=18)
    title_font = load_font(theme_font_candidates(theme, "quote_bold"), size=44)
    author_font = load_font(theme_font_candidates(theme, "quote_regular"), size=28)
    id_font = load_font(META_FONT_CANDIDATES, size=18)
    phrase_font = load_font(theme_font_candidates(theme, "quote_bold"), size=28)

    max_text_width = width - 2 * SIDE_MARGIN - 40
    title_lines = wrap_text(draw, title_text, title_font, max_text_width)[:3]
    author_lines = wrap_text(draw, f"by {author_text}", author_font, max_text_width)[:1] if author_text else []
    phrase_lines = wrap_text(draw, f"\u201c{matched_text}\u201d", phrase_font, max_text_width)[:2] if matched_text else []

    label_text = "Now showing"
    label_bbox = draw.textbbox((0, 0), label_text, font=label_font)
    label_h = label_bbox[3] - label_bbox[1]

    title_h = sum((draw.textbbox((0, 0), line, font=title_font)[3] - draw.textbbox((0, 0), line, font=title_font)[1]) + 6 for line in title_lines)
    author_h = sum((draw.textbbox((0, 0), line, font=author_font)[3] - draw.textbbox((0, 0), line, font=author_font)[1]) + 4 for line in author_lines)
    phrase_h = sum((draw.textbbox((0, 0), line, font=phrase_font)[3] - draw.textbbox((0, 0), line, font=phrase_font)[1]) + 4 for line in phrase_lines)
    id_bbox = draw.textbbox((0, 0), source_id_text, font=id_font) if source_id_text else (0, 0, 0, 0)
    id_h = (id_bbox[3] - id_bbox[1]) if source_id_text else 0

    block_h = label_h + 18 + title_h + (12 + author_h if author_lines else 0) + (24 + phrase_h if phrase_lines else 0) + (20 + id_h if source_id_text else 0)
    y = max(40, (height - block_h) // 2)

    def _draw_centered(text: str, font, fill):
        nonlocal y
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text(((width - w) // 2, y), text, font=font, fill=fill)
        y += h

    _draw_centered(label_text, label_font, colors["accent"])
    y += 18
    for line in title_lines:
        _draw_centered(line, title_font, colors["text"])
        y += 6
    if author_lines:
        y += 6
        for line in author_lines:
            _draw_centered(line, author_font, colors["text"])
            y += 4
    if phrase_lines:
        y += 18
        for line in phrase_lines:
            _draw_centered(line, phrase_font, colors["accent"])
            y += 4
    if source_id_text:
        y += 14
        _draw_centered(source_id_text, id_font, colors["source"])

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


def render(time_str: str, quote_row: dict, width: int, height: int, mode: str = "debug", theme: str = "default") -> Image.Image:
    if mode == "card":
        return render_source_card(quote_row, width, height, theme=theme)
    colors = THEMES[theme]
    image = Image.new("RGB", (width, height), color=colors["page_bg"])
    _paint_theme_border(image, theme, colors)
    draw = ImageDraw.Draw(image)

    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row["display_quote"]))
    layout_name = choose_layout(display_quote)
    layout = LAYOUTS[layout_name]

    debug_font = load_font(META_FONT_CANDIDATES, size=15)
    debug_label_font = load_font(META_FONT_BOLD_CANDIDATES, size=15)
    quote_font, quote_font_bold, wrapped_quote, line_height, chosen_size = fit_quote(
        draw,
        display_quote,
        quote_row.get("matched_text") or "",
        layout["max_width"],
        layout["quote_height"],
        layout["font_max"],
        layout["font_min"],
        layout["line_height_mult"],
        theme=theme,
    )
    quote_block_height = len(wrapped_quote) * line_height
    author_size = max(13, int(chosen_size * 0.52))
    source_size = max(13, int(chosen_size * 0.47))
    attribution_font = load_font(theme_font_candidates(theme, "quote_regular"), size=author_size)
    attribution_title_font = load_font(theme_font_candidates(theme, "quote_regular"), size=source_size)

    author_text = quote_row.get("author") or None
    title_text = quote_row.get("title") or fallback_title(quote_row)
    author_lines = wrap_text(draw, author_text, attribution_font, width - 160)[:1] if author_text else []
    title_lines = wrap_text(draw, title_text, attribution_title_font, width - 200)[:2] if title_text else []

    attrib_height = 0
    if author_lines:
        attrib_height += author_size
    if title_lines:
        attrib_height += layout["author_gap"] + len(title_lines) * source_size
        if len(title_lines) > 1:
            attrib_height += (len(title_lines) - 1) * layout["title_gap"]

    total_h = quote_block_height + (layout["author_gap"] if (author_lines or title_lines) else 0) + attrib_height
    block_top = max(72, (height - total_h) // 2)
    block_bottom = block_top + total_h
    quote_top = block_top

    quote_line_boxes = []
    quote_left_edge = width
    quote_right_edge = 0
    y_probe = quote_top
    total_lines = len(wrapped_quote)
    for line_index, line in enumerate(wrapped_quote):
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        drawable = line[start:end]

        current_width = 0
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            bbox = draw.textbbox((0, 0), chunk, font=font)
            current_width += bbox[2] - bbox[0]

        space_slots = sum(1 for chunk, _ in drawable if chunk == " ")
        is_last = line_index == total_lines - 1
        slack = layout["max_width"] - current_width
        distribute = []
        if not is_last and space_slots > 0 and 0 < slack <= layout["max_width"] * 0.25:
            base = slack // space_slots
            remainder = slack - base * space_slots
            distribute = [base + (1 if i < remainder else 0) for i in range(space_slots)]

        line_x = (width - layout["max_width"]) // 2
        line_left = None
        line_right = line_x
        space_idx = 0
        for chunk, is_bold in drawable:
            if line_left is None and chunk.strip():
                line_left = line_x
            font = quote_font_bold if is_bold else quote_font
            bbox = draw.textbbox((0, 0), chunk, font=font)
            line_x += bbox[2] - bbox[0]
            if chunk.strip():
                line_right = line_x
            if distribute and chunk == " ":
                line_x += distribute[space_idx]
                space_idx += 1
        if line_left is not None:
            quote_line_boxes.append((line_left, y_probe, line_right, y_probe + line_height))
            quote_left_edge = min(quote_left_edge, line_left)
            quote_right_edge = max(quote_right_edge, line_right)
        y_probe += line_height

    clear_rect = None
    if theme == "blueprint" and quote_line_boxes:
        clear_pad_x = 2
        clear_pad_top = 2
        clear_pad_bottom = 2
        clear_top = max(0, quote_line_boxes[0][1] - clear_pad_top)
        clear_bottom = min(height - 1, block_bottom + clear_pad_bottom)
        clear_rect = (
            max(0, quote_left_edge - clear_pad_x),
            clear_top,
            min(width - 1, quote_right_edge + clear_pad_x),
            clear_bottom,
        )

    if theme == "blueprint":
        _paint_theme_border(image, theme, colors)
        if clear_rect is not None:
            clear_draw = ImageDraw.Draw(image)
            clear_draw.rectangle(clear_rect, fill=colors["page_bg"])
            draw_blueprint_border(image, colors, clear_rect=clear_rect)
    else:
        _paint_theme_border(image, theme, colors)

    draw = ImageDraw.Draw(image)
    show_debug = mode == "debug"

    mark_size = min(layout["mark_max"], max(layout["mark_min"], int(chosen_size * layout["mark_scale"])))
    mark_font = load_font(theme_font_candidates(theme, "ornament"), size=mark_size)

    open_bb = draw.textbbox((0, 0), "“", font=mark_font)
    open_h = open_bb[3] - open_bb[1]
    open_x = SIDE_MARGIN + 18
    open_y = quote_top - open_h // 3
    draw_faux_gray_text(
        image,
        (open_x - open_bb[0], open_y - open_bb[1]),
        "“",
        font=mark_font,
        dark=colors["ornament_dark"],
        light=colors["ornament_light"],
        pattern_offset=(0, 0),
    )

    y = quote_top
    total_lines = len(wrapped_quote)
    for line_index, line in enumerate(wrapped_quote):
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        drawable = line[start:end]

        current_width = 0
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            bbox = draw.textbbox((0, 0), chunk, font=font)
            current_width += bbox[2] - bbox[0]

        space_slots = sum(1 for chunk, _ in drawable if chunk == " ")
        is_last = line_index == total_lines - 1
        slack = layout["max_width"] - current_width

        distribute = []
        # Only full-justify when the line is at least 75% full; looser lines look
        # worse justified than ragged-right due to excessive inter-word gaps.
        if not is_last and space_slots > 0 and 0 < slack <= layout["max_width"] * 0.25:
            base = slack // space_slots
            remainder = slack - base * space_slots
            distribute = [base + (1 if i < remainder else 0) for i in range(space_slots)]

        x = (width - layout["max_width"]) // 2
        space_idx = 0
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            fill = colors["accent"] if is_bold else colors["text"]
            draw_text(draw, (x, y), chunk, font=font, fill=fill)
            bbox = draw.textbbox((0, 0), chunk, font=font)
            x += bbox[2] - bbox[0]
            if distribute and chunk == " ":
                x += distribute[space_idx]
                space_idx += 1
        y += line_height

    close_bb = draw.textbbox((0, 0), "”", font=mark_font)
    close_w = close_bb[2] - close_bb[0]
    close_h = close_bb[3] - close_bb[1]
    close_x = width - SIDE_MARGIN - 18 - close_w
    close_y = block_bottom - close_h * 2 // 3
    draw_faux_gray_text(
        image,
        (close_x - close_bb[0], close_y - close_bb[1]),
        "”",
        font=mark_font,
        dark=colors["ornament_dark"],
        light=colors["ornament_light"],
        pattern_offset=(1, 0),
    )

    y = quote_top + quote_block_height + layout["author_gap"]
    if author_lines:
        author_text_line = author_lines[0]
        author_x = (width - layout["max_width"]) // 2
        draw_text(draw, (author_x, y), author_text_line, font=attribution_font, fill=colors["text"])
        y += author_size + layout["title_gap"]

    for line in title_lines:
        title_x = (width - layout["max_width"]) // 2
        draw_text(draw, (title_x, y), line, font=attribution_title_font, fill=colors["source"])
        y += source_size + layout["title_gap"]

    if show_debug:
        debug_label = "DEBUG MODE"
        label_bbox = draw.textbbox((0, 0), debug_label, font=debug_label_font)
        label_w = label_bbox[2] - label_bbox[0]
        # Themes that paint a decorative top-right corner element push the
        # debug label inward past the graphic so it isn't clipped. Keep in
        # sync with the border helpers (``draw_bauhaus_border`` /
        # ``draw_blueprint_border``) — inset is measured past the outer edge
        # of the corner graphic with a small breathing gap.
        label_right_inset = _DEBUG_LABEL_RIGHT_INSET.get(theme, SIDE_MARGIN)
        label_x = width - label_right_inset - label_w
        label_y = 14

        draw_text(draw, (label_x, label_y), debug_label, font=debug_label_font, fill=colors["accent"])

        bucket_value = quote_row.get("bucket") or ""
        resolved = quote_row.get("resolved_bucket") or bucket_value
        if quote_row.get("used_fallback") and resolved and bucket_value and resolved != bucket_value:
            bucket_piece = f"{bucket_value} → {resolved}"
        else:
            bucket_piece = resolved or bucket_value

        debug_parts = [time_str]
        if bucket_piece:
            debug_parts.append(bucket_piece)
        debug_parts.append(f"layout {layout_name}")
        if quote_row.get("quality_score") is not None:
            debug_parts.append(f"quality {quote_row['quality_score']}")
        quote_id = debug_quote_id(quote_row)
        if quote_id:
            debug_parts.append(f"id {quote_id}")
        debug_strip = " · ".join(debug_parts)

        strip_bbox = draw.textbbox((0, 0), debug_strip, font=debug_font)
        strip_w = strip_bbox[2] - strip_bbox[0]
        strip_h = strip_bbox[3] - strip_bbox[1]
        strip_y = height - 14 - strip_h
        strip_x = (width - strip_w) // 2

        rule_y = strip_y - 8
        rule_left = max(SIDE_MARGIN, (width - strip_w) // 2 - 24)
        rule_right = min(width - SIDE_MARGIN, (width + strip_w) // 2 + 24)
        for x in range(rule_left, rule_right, 5):
            draw.point((x, rule_y), fill=colors["faint"])

        draw_text(draw, (strip_x, strip_y), debug_strip, font=debug_font, fill=colors["faint"])

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


def main() -> int:
    args = parse_args()
    quote_row = pick_quote(args.time, history_path=args.history_path, history_days=args.history_days)
    output_path = Path(args.output) if args.output else Path("output/current.png")
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = render(args.time, quote_row, args.width, args.height, mode=args.mode, theme=args.theme)
    try:
        # Encode to an in-memory buffer first so a mid-save exception can't leave
        # ``output/current.png`` truncated — display_inky.py loads that path every
        # tick, and a torn PNG there blocks the panel until the next bucket change.
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        atomic_io.atomic_write_bytes(output_path, buffer.getvalue())
    finally:
        image.close()
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
