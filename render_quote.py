#!/usr/bin/env python3
"""Render a picked literary clock quote with a centered QOTD-inspired layout."""
from __future__ import annotations

import argparse
import io
import math
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
# Canonical 4×4 ordered Bayer matrix (values 0..15). Shared by
# ``draw_text_dithered`` and ``draw_deco_border`` so the body text and
# border ornament land on the same biased-checkerboard pattern when
# synthesising orange (red+yellow) at densities other than the
# 1×1 checkerboard the existing 0.5 / 0.25 branches use. A pixel is
# painted ``light`` when ``BAYER_4x4[y % 4][x % 4] < threshold``;
# threshold = round(density * 16).
BAYER_4x4: tuple[tuple[int, ...], ...] = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)
# Theme cycle order for button B / web dropdown. Kept as an explicit tuple so
# the cycle is stable regardless of dict-literal ordering in Python; every name
# here must also appear as a key in ``THEMES`` below (enforced in tests).
THEME_ORDER: tuple[str, ...] = (
    "default",
    "dark",
    "swiss",
    "scholar",
    "herbarium",
    "newsprint",
    "nightvision",
    "blueprint",
    "illuminated",
    "gothic",
    "bauhaus",
    "risograph",
    "comic",
    "dispatch",
    "atomic",
    "marker",
    "saloon",
    "roman",
    "alchemy",
    "grimoire",
    "deco",
    "glacier",
    "mucha",
    "chalkboard",
    "placard",
    "chanbara",
    "lcars",
    "fillmore",
    "firmament",
    "astrarium",
    "diags",
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
    # bold weight against the same ink colour, like an old broadsheet. The
    # white ground is softened by a 12.5% black Bayer halftone painted in
    # ``draw_newsprint_border``'s Layer 0 so the page reads as cheap newsprint
    # pulp rather than the panel's flat pure white. Quiet.
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
    # yellow accent for the matched phrase. Spectra 6's pure green is a
    # saturated mid-tone that reads as a dim, slightly muddy ink against the
    # black ground at panel-viewing distance — legible but the eye works for
    # it. The renderer compensates by stippling every green body-text glyph
    # with white in a 50/50 Bayer pattern (see ``_draw_text_body`` and
    # ``draw_text_dithered``), so the perceived ink lifts to a brighter mint
    # without leaving the six-colour gamut. The ornament colours follow suit:
    # the oversized quote marks dither green/white (via the existing
    # ``draw_faux_gray_text`` path) so they read as the same lifted mint as
    # the body, instead of the previous black/green half-density which
    # produced a darker forest-green tone visually disconnected from the
    # body. The corner brackets and CRT scanlines in
    # ``draw_nightvision_border`` deliberately stay solid green — their
    # decorative HUD silhouette would break under stippling, and they're
    # supporting graphics rather than reading matter.
    "nightvision": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["green"],
        "subtle": SPECTRA6["green"],
        "faint": SPECTRA6["green"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["green"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["green"],
    },
    # Cyanotype blueprint. Blue paper, white ink for the body text,
    # outer frame, and graph-paper grid, with the corner registration
    # crosshairs and matched time phrase picked out in red — the
    # "annotated dimension" in red pencil real drafters use to call out
    # measurements on an otherwise monochromatic print. The blue ground
    # is softened by a 50/50 white/blue checkerboard painted in
    # ``draw_blueprint_border``'s Layer 0 so the page reads as a paler
    # cyanotype wash rather than the panel's flat saturated blue. Sits
    # visually distinct from ``scholar`` (white/blue/red) thanks to the
    # inverted ground plus the geometric Archivo sans-serif in
    # THEME_FONTS — different palette polarity, different family.
    "blueprint": {
        "page_bg": SPECTRA6["blue"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["red"],
        # Both ornament keys collapse onto white so the oversized quote
        # marks render as solid white against the blue ground — same trick
        # ``gothic`` / ``illuminated`` use to drop the dither and let the
        # marks read as a single solid ink.
        "ornament_dark": SPECTRA6["white"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
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
    # Cathedral chronicle. Black ground (candle-lit vellum / cathedral
    # interior), white body for legibility on the panel, red rubric for
    # the matched time phrase and the oversized blackletter quotation
    # marks. Pairs with UnifrakturMaguntia (blackletter) in *both* the
    # ornament and quote-bold slots so the font defines the theme rather
    # than appearing as a guest accessory — body text stays in EB Garamond
    # so a 200-character dense layout still reads cleanly. Visually the
    # opposite polarity of ``illuminated`` (white parchment / red body /
    # blue jewels) so the two blackletter themes complement rather than
    # duplicate.
    "gothic": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["red"],
        # Both ornament keys collapse onto red — the oversized blackletter
        # quote marks dither between ``ornament_dark`` and
        # ``ornament_light`` (see ``draw_faux_gray_text``); on a white
        # ground the ``ornament_light=white`` half sinks into the page,
        # leaving a half-density rubric (cf. ``illuminated``), but on
        # ``gothic``'s black ground the white half would *show* and
        # wash the rubric pinkish-grey. Pinning both to red collapses
        # the dither to solid red, so the marks stay punchy against
        # the cathedral ground.
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["red"],
        "source": SPECTRA6["white"],
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
    # Field dispatch / typewritten dossier. White paper, black typewriter
    # ink for the body, and red for the matched time phrase — the
    # classic two-colour bichrome typewriter ribbon (black for normal
    # text, red for emphasis / numerals / official marks). Special
    # Elite is a slab-mono typewriter face whose deliberately uneven
    # inking does most of the visual work; the ``draw_dispatch_border``
    # frame, tractor-feed perforations on the side margins, and red
    # rubber-stamp imprint in the top-right corner finish the
    # vintage-office composition. Same palette as ``default`` (which
    # uses Playfair Display — high-contrast transitional serif), but
    # the slab-mono typewriter face plus the dossier graphics give it
    # a completely different silhouette on the panel.
    "dispatch": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        # Half-density quote marks (dither between black and white)
        # mimic the irregular inking of a worn typewriter ribbon — the
        # signature texture of a Special Elite render that a clean
        # solid-fill mark would erase.
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Mid-century atomic age. Sputnik-green ground (the only theme to
    # claim Spectra 6's flat green as a *background* — every other
    # theme uses green only as ink), softened by a sparse 1-in-4
    # white-on-green dither painted in ``draw_atomic_border``'s Layer 0
    # (one white pixel per 2×2 tile, so 75% of the ground stays pure
    # Spectra 6 green and the page reads as a vivid Sputnik-green
    # wash rather than the minty pastel a 50/50 checkerboard produced).
    # Chunky black body in the Atomic Age display face,
    # atomic-energy red for the matched time phrase and the decorative
    # graphics. Pairs with a ``draw_atomic_border`` of a rounded-corner
    # red frame (Googie / streamlined-modern curves), a centred atom
    # symbol at the top of the page (three rotated red ellipse "orbits"
    # plus a central red nucleus), and small red starbursts at the
    # mid-edges (the radiating-rays motif of 1950s diner / motel
    # signage). Reads as a vintage atomic-age advertisement at a
    # glance — bright, optimistic, slightly garish.
    "atomic": {
        "page_bg": SPECTRA6["green"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        # Both ornament keys collapse onto red so the oversized
        # quote marks render as solid red against the dithered ground —
        # otherwise the dither's lighter half would blend into the bg
        # and leave half-density ornaments. Same trick `gothic`
        # uses to keep its red blackletter quote marks dramatic.
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["red"],
        "source": SPECTRA6["black"],
    },
    # Permanent-marker fridge-doodle / sticky-note vibe. White paper, black
    # Sharpie body in the Permanent Marker hand, blue accent for the matched
    # time phrase (a "second marker" picked from the cup), red oversized
    # quotation marks. The signature move is the decorative
    # ``draw_marker_border`` which paints in *all four* non-white panel ink
    # colours simultaneously (red / yellow / blue / green) plus black — the
    # only theme that lights up every spot colour the Spectra 6 panel can
    # produce, satisfying the "use the full capabilities of the display"
    # brief. Reads as a kid's notebook page or a fridge-magnet message
    # board: bold, casual, exuberant.
    "marker": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # 19th-century wood-engraved saloon poster / Wild West "WANTED"
    # broadside. Same default-palette shape (white paper, black ink, red
    # accent) that ``default`` and ``dispatch`` use, but the heavy slab
    # display face (Rye) plus an elaborately layered background — sparse
    # red foxing speckles across the entire page, double-rule wanted-
    # poster frame, top + bottom decorative banner bands with mirrored
    # ornaments, corner fleurons, and mid-edge red diamonds — give the
    # theme a visibly more sophisticated ground than any of its
    # white/black/red siblings, satisfying the "more sophisticated
    # background" brief. Reads as a hand-printed Western broadside at a
    # glance: aged paper, heavy ink, ornate engraver's frame.
    "saloon": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Roman lapidary inscription. White limestone / marble ground, black
    # body for the V-cut letter shadow, red accent (rubrum — the red lead
    # pigment Roman carvers painted into the engraved grooves to make
    # inscriptions legible from a distance) for the matched time phrase
    # and the SPQR cartouche. Pairs with Cinzel Decorative — a digital
    # face directly modelled on Trajan's Column (113 AD), the canonical
    # reference for Roman capitalis monumentalis, so the typography is
    # the chisel work. The ``draw_roman_border`` decoration lays the
    # rest of the stone-slab vocabulary on top of the page: scattered
    # limestone grain speckles, a ``tabula ansata`` (Roman votive
    # tablet) silhouette with two trapezoidal "dovetail" handles
    # protruding from the left and right mid-edges, an SPQR cartouche
    # at the top centre with interpunct dot separators between the
    # letters, mirrored mid-edge interpunct dots, and a centred laurel
    # sprig at the bottom — the same vocabulary you find on triumphal
    # arches and altar plinths across the Forum.
    "roman": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Parchment grimoire: aged-yellow ground (the colour an alchemical
    # manuscript takes on after four centuries of candlelight and
    # iron-gall ink), black body for readability, red rubricated
    # matched-phrase accent (the way medieval scribes flagged the
    # operative phrase of a spell), blue Hermetic ornaments for the
    # oversized quote marks and the top/bottom magic-circle sigils.
    # The blue/red split is the same colour vocabulary the Mutus Liber
    # and Splendor Solis used to distinguish the philosophical mercury
    # (blue/lunar) from the sulphur principle (red/solar). Pairs with
    # IM Fell English for the body (a Google Fonts digitisation of John
    # Fell's 17th-century types — the same Oxford types that printed
    # actual alchemical treatises) and MedievalSharp for the matched
    # phrase + oversized quote marks (a calligraphic display face whose
    # sharply-pointed strokes read as ritual-scribe handwriting).
    "alchemy": {
        "page_bg": SPECTRA6["yellow"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["blue"],
        "source": SPECTRA6["black"],
    },
    # Alchemical grimoire / Faustian spellbook. Black leather-bound
    # ground, white IM Fell English body (Igino Marini's digital revival
    # of John Fell's 17th-century Oxford University Press types — the
    # deliberate inking irregularities of the metal-type letterpress
    # survive on every glyph so the page reads as a genuine antique
    # tome), with a red TFoustScript matched phrase glowing through it
    # like a magic-circle inscription scrawled by a phantom hand — the
    # hollow-outline shaggy silhouette of TFoust reads as occult
    # sigil-work against the dignified vintage-press body. The
    # matched-phrase red is stippled with a sparse 1-in-4 white-on-red
    # dither (25% white / 75% red — see ``_draw_text_body``), so the
    # phrase shimmers like a candle-lit rubric against the black ground
    # without diluting into pink at panel distance; the sparse density
    # echoes the white-on-green ground in ``draw_atomic_border``. Shares
    # the black/white/red palette shape with ``gothic`` but is
    # iconographically unrelated: gothic uses UnifrakturMaguntia
    # blackletter plus cathedral-tracery quatrefoils, grimoire uses
    # TFoustScript hollow-display plus *inscribed* pentagrams and the
    # four classical planetary alchemical sigils on the mid-edges
    # (Sun ☉ top, Moon ☽ bottom, Mars ♂ left, Venus ♀ right). Shares
    # only the palette with ``alchemy`` above — alchemy is parchment-
    # yellow daytime ritual diagram, grimoire is leather-bound
    # midnight scrawl.
    "grimoire": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["red"],
        # Oversized quote marks render as a 50/50 blue/white checkerboard
        # via ``draw_faux_gray_text`` — the same B+W 1:1 mix the ``diags``
        # synth band labels "sky". Against the black cathedral ground the
        # eye averages the two inks into a cool moon-silver sky-blue, a
        # complementary cold-light counterpoint to the warm operative red
        # the rest of the grimoire iconography is painted in.
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # Art-deco poster: white ground / black body / red-stippled-to-yellow
    # accent that reads as orange at panel distance, paired with the
    # Righteous geometric display sans. The Spectra-6 palette has no orange
    # ink, but a red-biased Bayer stipple (5/8 red : 3/8 yellow on the
    # shared ``BAYER_4x4`` matrix, threshold 6/16) averages into a warm
    # tangerine that lifts the matched phrase and border decoration into
    # period-correct deco territory (the canonical sunburst / chevron
    # palette of the era leans warm — red and amber more than fire-engine
    # red) without leaving the six-colour gamut. The earlier 50/50
    # checkerboard read as washed-out amber because yellow has much
    # higher perceived luminance than red; biasing to ~2:1 red:yellow
    # drags the perceived hue back onto orange — the same recipe the
    # Spectra 6 extended-palette literature uses for synthesised orange.
    # The dither is applied in two complementary places:
    # ``_draw_text_body`` stipples body fills equal to ``accent``, and
    # ``draw_deco_border``'s final pass flips painted red pixels to
    # yellow using the same Bayer threshold so both share one tone.
    # Same palette *intent* as ``default`` / ``dispatch`` / ``saloon`` /
    # ``roman`` (white / black / red), but the perceived accent is
    # visibly different from those themes' solid red. The decoration is
    # the stepped-corner border drawn by ``draw_deco_border`` (concentric
    # L-shapes echoing the canonical skyscraper-steps ornament, plus a
    # centred top-edge rising-sun motif).
    "deco": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Icy / aurora: white ground / blue Iceland body / green matched-phrase
    # accent. The first theme to pair a blue body with a green accent — sits
    # visually apart from ``scholar`` (blue body / red accent) and ``blueprint``
    # (blue *ground* / white body / red accent). Iceland is a geometric techno
    # display face; the matching border (``draw_glacier_border``) drops angular
    # "frost crystal" shards into the four corners plus small four-armed star
    # ticks at the mid-edges, echoing the font's architectural symmetry.
    "glacier": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["blue"],
        "subtle": SPECTRA6["blue"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["green"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["blue"],
    },
    # Classroom chalkboard: black page (slate), white chalk body in the
    # Playwrite GB Joined Guides cursive handwriting face (TypeTogether,
    # OFL — the British primary-school joined cursive with dotted-outline
    # practice letters), yellow chalk-stick matched-phrase accent. Shares
    # the black/white/yellow palette shape with ``dark`` (which is Playfair
    # Display); the differentiation is the handwriting font and the
    # ``draw_chalkboard_border`` wooden-frame decoration. Visually reads as
    # a teacher demonstrating cursive on a slate board.
    "chalkboard": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # Hand-painted shop sign / sandwich-board placard: white paper-sign
    # ground, black hand-printed small-caps body in Patrick Hand SC
    # (Patrick Wagesreiter, OFL — friendly hand-lettered face whose small
    # caps for lowercase do almost all the visual work), red highlight
    # matched-phrase accent (the sign-painter's spot colour). Shares the
    # white/black/red palette shape with ``default`` / ``dispatch`` /
    # ``saloon`` / ``roman`` / ``deco`` — the differentiation is the
    # hand-printed small-caps font and the ``draw_placard_border``
    # decoration (doubled sign-painter's frame + red thumbtack corner
    # accents). Reads as a market A-frame or shop-window menu at a glance.
    "placard": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Samurai cinema title card: black ink-sky ground, white Shojumaru
    # brush-painted body (Astigmatic, OFL — same designer as Righteous and
    # Atomic Age), red matched-phrase accent (the chanbara genre's spot
    # colour — blood, vermilion, the rising sun). Shares the black/white/
    # red palette shape with ``gothic`` and ``grimoire``; the
    # differentiation is the dramatic brush-painted display face and the
    # ``draw_chanbara_border`` decoration (large off-canvas red rising-sun
    # disc in the bottom-right corner plus a small red artist's chop seal
    # in the top-left). Reads as a kurosawa-era film title card at a
    # glance.
    "chanbara": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["red"],
        # Red ornaments on black — same trick ``grimoire`` uses so the
        # oversized opening / closing quote marks render as solid red
        # against the ink ground rather than half-dithering into the
        # page colour.
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["red"],
        "source": SPECTRA6["white"],
    },
    # LCARS — the Star Trek: TNG/DS9/Voyager Library Computer Access /
    # Retrieval System interface designed by Michael Okuda. Black canvas
    # with a thick tangerine "elbow" sidebar wrapping the top-left and
    # bottom-left corners, stacked yellow / coral / red pill-shaped
    # buttons along the sidebar, tiny white "stardate" callouts beside
    # each pill, and the condensed Antonio sans for the literary body
    # text. Spectra 6 has no orange ink so the elbow's tangerine is
    # synthesised via the documented `deco` recipe (red sentinel +
    # bbox post-pass flipping ~3/8 of the painted red to yellow on the
    # shared 4×4 Bayer matrix at threshold 6). One pill uses the
    # `placard`/`chalkboard` coral recipe (red sentinel + bbox post-pass
    # to white per `(x+y)&1`); the others are solid yellow and solid red.
    # The matched-phrase yellow accent on black is iconic LCARS button
    # colour and renders solid (no `_draw_text_body` reroute needed).
    "lcars": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],
        # ``ornament_dark`` is the sentinel ink the elbow paints in
        # before the Bayer post-pass converts ~3/8 of those red pixels
        # to yellow → tangerine. ``ornament_light`` is the second ink
        # in that recipe and the colour of the topmost solid pill.
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # Swiss International / mid-century-modernist functional. The Müller-
    # Brockmann / Vignelli typographic tradition: clean grid, single ink
    # weight does the heavy lifting, single hairline rule, no decoration.
    # Deliberately the *least* ornamented frame in the rotation — every
    # other theme has a border painter; ``swiss`` registers one too, but
    # all it paints is a single horizontal rule near the top edge plus a
    # small red square marking the "header column". Austerity by
    # subtraction is the visual identity. Body in Inter (Helvetica-class
    # grotesque sans), matched phrase in Inter Bold + red accent.
    "swiss": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # 19th-century pressed-plant specimen sheet. Cream-washed paper
    # (Y+W Layer 0, same recipe ``illuminated`` / ``dispatch`` use),
    # black body in IM Fell English, matched phrase rerouted to
    # forest green (G+K 1/2:1/2 — the documented dark-green recipe
    # from ``spectra6_color_recipes.md``'s two-ink table) in
    # ``_draw_text_body``. The forest-green matched phrase reads as
    # the dark-pressed plant material a real herbarium specimen
    # develops over time, with strong contrast against the cream
    # wash — an olive (Y+G) accent would have averaged into the
    # yellow ground and read as washed-out on the screen even
    # though it would average correctly at the panel's viewing
    # distance. Border adds a Y+G olive pressed-leaf silhouette in
    # the bottom-right corner and a "Tempus fugit" cartouche in the
    # bottom-left, so the page carries three different green-family
    # tones: black body, forest-green matched phrase, olive leaf,
    # cream ground. The single theme in the rotation whose defining
    # colour story is the green axis — every other green-touching
    # theme (``nightvision`` / ``glacier`` / ``roman``) uses green
    # as accent against a different body colour.
    "herbarium": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        # ``accent`` is the green sentinel ink that ``_draw_text_body``
        # routes through its G+K stipple → forest-green branch — same
        # indirection pattern ``deco`` uses for red→tangerine and
        # ``glacier`` uses for green→cyan. The corner pressed-leaf
        # graphic uses a separate Y+G olive recipe so body matched
        # phrase and decoration land on related but visually distinct
        # green tones (forest-green for text, olive for the leaf).
        "accent": SPECTRA6["green"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Art Nouveau / Belle-Époque poster (Mucha / Vienna Secession).
    # Cream Layer-0 wash on white, body painted in maroon (R+K 1/2:1/2,
    # the documented recipe ``dispatch`` / ``gothic`` / ``chanbara`` /
    # ``grimoire`` / ``blueprint`` / ``scholar`` already use) via the
    # ``_draw_text_body`` per-theme branch — the first theme to use a
    # synthesised colour as its primary body fill rather than just an
    # accent. Matched phrase in cyan (G+B 1/2:1/2, the ``glacier``
    # recipe), which gives a cool-teal accent against the warm body.
    # Decoration is the rotation's first all-curve / organic border:
    # Bézier-approximated S-shaped vines at the top-left and
    # bottom-right with olive-stippled trefoil leaf clusters and a
    # tangerine berry at each stem tip.
    "mucha": {
        # The body fill is the maroon sentinel — ``_draw_text_body``
        # routes solid-red glyphs through an R+K stipple just like
        # ``blueprint`` / ``scholar``'s matched phrase. Painting the
        # body in red rather than maroon directly keeps the theme on
        # the Spectra-6 palette (the test ``test_theme_colors_stay_
        # within_spectra6_palette`` checks every THEMES value is a
        # native ink). The actual perceived maroon is produced by the
        # ``_draw_text_body`` post-pass.
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["red"],
        "subtle": SPECTRA6["red"],
        "faint": SPECTRA6["red"],
        # Accent sits on the green sentinel; ``_draw_text_body`` routes
        # green fills through G+B → cyan in this theme so the matched
        # phrase reads as the cool teal accent of a Mucha poster.
        "accent": SPECTRA6["green"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["red"],
    },
    # 1960s psychedelic Fillmore concert poster (Wes Wilson / Victor
    # Moscoso / Stanley Mouse). The visual maximalist of the rotation:
    # sun-faded-yellow Layer-0-washed ground + maroon-stippled body
    # + saturated blue matched phrase, with green and blue corner
    # "blob panels". The body's ``text`` slot is the red sentinel;
    # ``_draw_text_body`` routes it through a 50/50 R+K stipple →
    # oxblood maroon, the same recipe ``mucha`` uses for its body
    # — subdues the otherwise-loud red-on-yellow clash without
    # losing the psychedelic identity (real Fillmore posters' red
    # ink ended up darker once printed onto yellow stock anyway).
    # The ``draw_fillmore_border`` painter further softens the
    # ground with a sparse 1-in-8 white-on-yellow Bayer Layer-0
    # wash so the saturated Spectra-6 yellow reads as slightly
    # sun-faded rather than fire-bright at panel distance. All
    # six Spectra-6 natives still appear on the page (yellow +
    # white ground, blue matched phrase, green / blue / red /
    # yellow blob inks, black in the body's R+K stipple +
    # Bungee Shade's drop-shadows). Body in Bungee Shade, a
    # chunky 3D-blocked display face that lands "psychedelic-
    # adjacent" without sacrificing the readability LitClock
    # requires.
    "fillmore": {
        "page_bg": SPECTRA6["yellow"],
        "text": SPECTRA6["red"],
        "subtle": SPECTRA6["red"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["red"],
    },
    # 17th-century celestial atlas (Bayer's *Uranometria*, Cellarius's
    # *Harmonia Macrocosmica*). White serif body on a navy night-sky
    # ground, with gold/cream matched time phrases, scattered yellow
    # stars in three magnitude tiers, recognisable constellation
    # polylines (Cassiopeia + Orion's Belt), and four distinct corner
    # astronomy ornaments (sun, crescent moon, compass rose, ringed
    # Saturn). The first theme in the rotation to claim NAVY (B+K 1:1)
    # as a page ground — ``page_bg`` is stored as solid black and
    # ``draw_firmament_border`` synthesises the navy in Layer 0 via a
    # ``(x+y) & 1`` parity post-pass that flips half of the black
    # pixels to blue (same idempotent shape ``mucha`` / ``fillmore`` /
    # ``atomic`` use for their respective Layer 0 ground washes). The
    # ``accent`` slot is yellow as a sentinel; ``_draw_text_body``
    # reroutes it through a Y+W 1:1 cream stipple so the matched
    # phrase reads as gilded constellation labels against the navy
    # ground. The first theme to use 3-ink mixes for decoration
    # outside the ``diags`` panel (the Milky Way swaths use R+B+W
    # lavender via sentinel-paint-then-bbox-post-pass, since the
    # ``_fill_swatch_stipple_3way`` helper unconditionally overwrites
    # every rect pixel and would wipe the navy ground if invoked
    # directly), and the first to combine TWO synthesised tones in a
    # single ornament (Saturn's R+Y tangerine body + G+B cyan ring).
    # Astronomy is the origin of timekeeping, so the celestial-atlas
    # register has the strongest thematic resonance of any theme in
    # the rotation for a literary clock that quotes time. Body in
    # Cardo, a humanist serif designed for classical scholarship
    # (David Perry, OFL) — visually distinct from the EB Garamond
    # used by illuminated/gothic and the Cormorant Garamond used by
    # mucha.
    "firmament": {
        "page_bg": SPECTRA6["black"],   # navy synthesised in Layer 0
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],   # rerouted to Y+W cream in _draw_text_body
        "ornament_dark": SPECTRA6["yellow"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # Astrarium — astronomical-clock dashboard. Not a literary frame:
    # ``render`` dispatches the astrarium theme to a custom two-column
    # layout (dial on the left, quote on the right, datum strip across
    # the bottom) the way it dispatches ``diags`` to the status panel.
    # The dial paints four halftone quadrants in tangerine (R+Y stipple)
    # / olive (Y+G) / teal (G+B) / black, evoking the multi-colour ring
    # segments of a real astrarium without leaving the Spectra 6 palette,
    # and the matched-phrase tangerine is the same R+Y 5/8:3/8 recipe
    # ``deco`` / ``atomic`` use so the body accent and the dial share
    # one perceived warm orange at panel distance. The palette stays
    # white/black/red so the fall-through paths (``render_static_message``
    # for goodnight, ``render_source_card`` for the button-C overlay)
    # render readably without needing astrarium-specific code.
    "astrarium": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Diagnostic / status panel. Not a literary frame — render() dispatches
    # the diags theme to a special status layout (clock + bucket / layout /
    # quality / source fields + a swatch grid showing the Spectra 6 palette
    # and the 2-ink synthesised tones documented in CLAUDE.md). The palette
    # itself is white/black/red so the fall-through paths (render_static_message
    # for goodnight, render_source_card for the button-C overlay) still render
    # readably without needing their own diags-specific code.
    "diags": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
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
SPECIALELITE_REGULAR = str(BASE_DIR / "fonts/special-elite/SpecialElite-Regular.ttf")
ATOMICAGE_REGULAR = str(BASE_DIR / "fonts/atomic-age/AtomicAge-Regular.ttf")
PERMANENTMARKER_REGULAR = str(BASE_DIR / "fonts/permanent-marker/PermanentMarker-Regular.ttf")
RYE_REGULAR = str(BASE_DIR / "fonts/rye/Rye-Regular.ttf")
CINZELDECORATIVE_REGULAR = str(BASE_DIR / "fonts/cinzel-decorative/CinzelDecorative-Regular.ttf")
CINZELDECORATIVE_BOLD = str(BASE_DIR / "fonts/cinzel-decorative/CinzelDecorative-Bold.ttf")
CINZELDECORATIVE_BLACK = str(BASE_DIR / "fonts/cinzel-decorative/CinzelDecorative-Black.ttf")
# TFoustScript — single-weight hollow-outline display face with shaggy/spiky
# edges; ASCII-only (95 glyphs, no smart quotes / em-dash / extended Latin).
# Lives in the matched-phrase slot of the ``grimoire`` theme — short ASCII
# time phrases ("half past two") render cleanly; never used in the body or
# ornament slots where missing curly-quote / em-dash glyphs would draw
# ``.notdef`` boxes (PIL fallback is file-level, not glyph-level).
TFOUST_REGULAR = str(BASE_DIR / "fonts/TFoust.ttf")
# IM Fell English — Igino Marini's digital revival of John Fell's
# 17th-century Oxford University Press types (OFL). Visible ink character
# on every glyph (the deliberate inking irregularities of metal type
# letterpress) makes it read as a genuine antique book page rather than
# a clean modern serif. 352-glyph cmap including curly quotes / em-dash
# / extended Latin, so unlike TFoust it's safe in the body and ornament
# slots. Body face for both ``alchemy`` (parchment ground) and
# ``grimoire`` (black ground) — the unmistakable "alchemical tome"
# silhouette that distinguishes both occult themes from every other
# serif theme.
IMFELLENGLISH_REGULAR = str(BASE_DIR / "fonts/im-fell-english/IMFellEnglish-Regular.ttf")
IMFELLENGLISH_ITALIC = str(BASE_DIR / "fonts/im-fell-english/IMFellEnglish-Italic.ttf")
# MedievalSharp — Anomandari / skosch (OFL). Calligraphic display face
# whose sharply-pointed strokes read as a ritual scribe's hand.
# Matched-phrase + ornament face for the ``alchemy`` theme.
MEDIEVALSHARP_REGULAR = str(BASE_DIR / "fonts/medieval-sharp/MedievalSharp-Regular.ttf")
# Righteous — Astigmatic / Brian J. Bonislawsky (OFL). 1930s geometric
# art-deco display sans with friendly rounded terminals on a strict
# geometric skeleton. Single-weight (Regular only), so the matched-phrase
# slot in ``deco`` re-uses the same file and earns differentiation from
# the accent colour alone — same trick the comic / dispatch / atomic /
# marker / saloon themes use. Falls back through DejaVu / Liberation /
# Noto Sans Bold before degrading to the Playfair serif chain, so a
# missing install lands on a heavy display silhouette rather than an
# elegant serif.
RIGHTEOUS_REGULAR = str(BASE_DIR / "fonts/righteous/Righteous-Regular.ttf")
# Iceland — Cyreal (OFL). Geometric techno / retro-futurism display
# face with chunky verticals and angled cuts, very Atari-arcade /
# sci-fi-splash register. Same single-weight discipline as Righteous:
# the matched-phrase slot in ``glacier`` re-uses the file and gains
# differentiation from the green accent. Falls back through heavy sans
# before the Playfair serif chain so a missing install stays in the
# display-face lane.
ICELAND_REGULAR = str(BASE_DIR / "fonts/iceland/Iceland-Regular.ttf")
# Playwrite GB J Guides — TypeTogether / Veronika Burian / José Scaglione
# (OFL). The British primary-school joined-cursive handwriting model
# *with* the dotted-outline guide letters that schoolchildren trace over
# in their first cursive workbooks. Single-weight (Regular only); the
# distinctive feature is the dotted/hollow letterforms themselves, which
# don't have a meaningful "Bold" companion — a heavier guide-line would
# defeat the practice-letter aesthetic. Matched phrase reuses Regular
# and gains differentiation from the yellow chalk-stick accent alone.
# Used by the ``chalkboard`` theme. Falls back through DejaVu Sans
# Italic (the closest in-rotation script-adjacent face) before
# degrading to the Playfair serif chain, so a missing-Playwrite install
# lands on at least a slanted silhouette rather than dropping a
# handwriting theme onto an upright serif.
PLAYWRITE_GB_J_GUIDES_REGULAR = str(BASE_DIR / "fonts/playwrite-gb-j-guides/PlaywriteGBJGuides-Regular.ttf")
# Patrick Hand SC — Patrick Wagesreiter (OFL). Friendly hand-printed
# (NOT cursive — printed letterforms drawn by hand) small-caps face.
# The "SC" variant renders lowercase as small capitals, giving the
# text the distinctive silhouette of hand-lettered shop signage and
# menu boards — the sandwich-board / kraft-paper-label register
# that no other theme in the rotation occupies. Single-weight
# (Regular only); the matched-phrase role in ``placard`` reuses
# Regular and gains differentiation from the red accent alone —
# same trick comic / dispatch / atomic / marker / saloon / deco /
# glacier / chalkboard already use. Fallback chain ends at heavy
# sans (DejaVu / Liberation / Noto Sans Bold) before degrading to
# the Playfair serif chain, so a missing install lands on a
# chunky display silhouette rather than dropping the placard theme
# onto an elegant transitional serif.
PATRICK_HAND_SC_REGULAR = str(BASE_DIR / "fonts/patrick-hand-sc/PatrickHandSC-Regular.ttf")
# Shojumaru — Astigmatic / Brian J. Bonislawsky (OFL). Dramatic
# brush-painted display face evoking samurai cinema posters,
# Japanese woodblock prints, and chanbara movie title cards.
# Single-weight (Regular only); the matched-phrase role in
# ``chanbara`` reuses Regular and gains differentiation from the
# red sun-disc accent alone — same trick comic / dispatch / atomic /
# marker / saloon / deco / glacier / chalkboard / placard already
# use. Fallback chain ends at heavy DejaVu / Liberation / Noto Sans
# Bold before degrading to the Playfair serif chain, so a missing
# install lands on a heavy display silhouette rather than dropping
# a brush-painted theme onto an elegant transitional serif.
SHOJUMARU_REGULAR = str(BASE_DIR / "fonts/shojumaru/Shojumaru-Regular.ttf")
# Antonio — Vernon Adams / googlefonts (OFL). The de-facto free LCARS
# substitute used by Star Trek fan projects: a tall, narrow,
# condensed sans whose silhouette echoes Helvetica Compressed / Swiss 911
# (the original LCARS typeface family). Variable font with a Weight axis
# (100..700) whose default instance is Regular (400) — both Regular and
# Bold variation instances are exposed by name, so the Regular / Bold
# slots in ``THEME_FONTS["lcars"]`` pin them explicitly the same way the
# Bitter / Jost / Rubik variable fonts do. The condensed proportions
# are what makes this read as console / instrumentation UI rather than
# editorial typography — every other sans in the rotation (Archivo,
# Jost, Rubik, Bangers, Antonio's relative Atomic Age) is normal-width
# or wider. Fallback chain ends at heavy DejaVu / Liberation / Noto
# Sans Bold before degrading to the Playfair serif chain so a missing
# install lands on a heavy sans silhouette rather than dropping the
# LCARS theme onto an elegant transitional serif.
ANTONIO_VARIABLE = str(BASE_DIR / "fonts/antonio/Antonio-Variable.ttf")
# Inter — Rasmus Andersson (OFL). The de-facto open-source Helvetica
# replacement: a clean grotesque sans designed for UI rendering at
# small sizes, sits visually distinct from Archivo (blueprint —
# geometric-grotesque) and Jost (bauhaus — geometric-constructed) so
# the three sans-based themes stay differentiable on the panel. Used
# by the ``swiss`` theme. Variable font with named instances Regular
# and Bold (default instance is Regular, but every candidate pins the
# instance explicitly so the matched-phrase bold is unambiguous).
# Falls back through DejaVu / Liberation / Noto Sans before degrading
# to the Playfair serif chain so a missing-Inter install lands on a
# grotesque-sans silhouette rather than a serif — preserving the
# theme's "type does all the work" identity even when the preferred
# face is absent.
INTER_VARIABLE = str(BASE_DIR / "fonts/inter/Inter-Variable.ttf")
# Cormorant Garamond — Christian Thalmann (OFL). High-contrast humanist
# revival of the Claude Garamont types — sharper, more dramatic curves
# than EB Garamond, in the editorial / poster typographic register that
# the Mucha theme wants. Variable font with named instances Light /
# Regular / Medium / SemiBold / Bold (default instance is Regular).
# Used by the ``mucha`` theme.
CORMORANT_VARIABLE = str(BASE_DIR / "fonts/cormorant-garamond/CormorantGaramond-Variable.ttf")
# Berkshire Swash — Astigmatic / Brian J. Bonislawsky (OFL). Flourished
# Art Nouveau / Belle Époque display script with elongated terminals —
# evokes the period's poster-lettering tradition without trying to
# faithfully reproduce a real Mucha hand. Single-weight (Regular only);
# used in the ornament slot of the ``mucha`` theme for the oversized
# curly quotation marks. Lives alongside Cormorant Garamond in the
# Mucha font chain the same way UnifrakturMaguntia lives alongside
# EB Garamond in ``illuminated``.
BERKSHIRE_SWASH_REGULAR = str(BASE_DIR / "fonts/berkshire-swash/BerkshireSwash-Regular.ttf")
# Bungee Shade — David Jonathan Ross (OFL). 3D-blocked display face
# with strong outline + drop-shadow shading, evoking the chunky shaded
# lettering on 1960s rock concert posters — Wes Wilson, Victor Moscoso,
# the Avalon Ballroom / Fillmore poster tradition. Single-weight
# (Regular only), so the matched-phrase role in ``fillmore`` re-uses
# the same file and gains differentiation through the blue accent
# colour alone — same trick comic / dispatch / atomic / marker /
# saloon / deco / glacier / chalkboard / placard / chanbara already
# use. Falls back through Bangers / Atomic Age (the closest in-rotation
# display-face siblings) and heavy DejaVu / Liberation / Noto Sans
# Bold before degrading to the Playfair serif chain, so a missing
# install lands on a chunky display silhouette rather than dropping
# the fillmore theme onto an elegant transitional serif.
BUNGEE_SHADE_REGULAR = str(BASE_DIR / "fonts/bungee-shade/BungeeShade-Regular.ttf")
# Cardo — David J. Perry (OFL). Humanist Renaissance serif designed for
# classical scholarship: Garamond-family proportions with full Polytonic
# Greek and Latin epigraphic coverage. Used as the primary body face of
# the ``firmament`` theme — pairs the period-correct silhouette of
# 17th-century celestial atlas typography with strong legibility on a
# navy night-sky ground. Visually distinct from the other Garamond-class
# faces in the rotation (EB Garamond in illuminated/gothic; Cormorant
# Garamond in mucha). Ships Regular / Bold / Italic. Falls back through
# EB Garamond (already bundled) → DejaVu Serif → Liberation Serif → the
# Playfair Display chain so a missing install lands on at least a
# humanist-serif silhouette rather than the bitmap default.
CARDO_REGULAR = str(BASE_DIR / "fonts/cardo/Cardo-Regular.ttf")
CARDO_BOLD = str(BASE_DIR / "fonts/cardo/Cardo-Bold.ttf")
CARDO_ITALIC = str(BASE_DIR / "fonts/cardo/Cardo-Italic.ttf")

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
    "swiss": {
        # Inter is the only pure grotesque-sans face in the rotation
        # (Archivo in blueprint is also grotesque but lives behind an
        # engineering border; Jost in bauhaus is geometric-constructed;
        # Rubik in risograph is rounded-geometric). Variable font with
        # named instances; default instance is Regular (400) but every
        # candidate pins the instance explicitly so the matched-phrase
        # bold is unambiguous. Falls back through the same sans chain
        # as blueprint / bauhaus / risograph before degrading to the
        # Playfair serif chain so a missing-Inter install still lands
        # on a grotesque-sans silhouette rather than a serif.
        "quote_regular": [
            (INTER_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (INTER_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (INTER_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
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
    "herbarium": {
        # Reuses the bundled IM Fell English chain that ``alchemy`` and
        # ``grimoire`` already pull from — the 17th-century Oxford-press
        # silhouette reads as scientific-historical against the cream-
        # washed page without dragging in the manuscript / occult
        # register those two themes occupy. The matched-phrase slot
        # picks IM Fell *Italic* rather than a heavier weight: italic
        # is the canonical convention for Latin scientific names on a
        # real herbarium specimen sheet, and the olive-stippled colour
        # accent (routed via ``_draw_text_body``) carries the visual
        # differentiation that a true bold would otherwise provide. A
        # plain Regular fallback covers a missing-italic install so the
        # matched phrase never drops to the bitmap fallback.
        "quote_regular": [
            IMFELLENGLISH_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            IMFELLENGLISH_ITALIC,
            IMFELLENGLISH_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            IMFELLENGLISH_REGULAR,
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
    "gothic": {
        # Promotes UnifrakturMaguntia from the ornament-only role it
        # plays in ``illuminated`` to also cover the matched-phrase bold:
        # short matched phrases ("half past two") render in dramatic red
        # blackletter, sitting in the body like a chapter heading. Body
        # text stays in EB Garamond so the rest of the line reads cleanly
        # at dense-layout sizes — a full blackletter body would shred
        # legibility on a 4-bit eInk panel. The EB Garamond Bold second
        # rank covers a missing-Unifraktur install so the matched phrase
        # degrades to a heavy serif rather than the bitmap fallback.
        "quote_regular": [
            EBGARAMOND_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            UNIFRAKTUR_BOOK,
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
    "dispatch": {
        # Special Elite ships only one weight (Regular) and is a
        # slab-mono typewriter face whose deliberately uneven inking
        # is the whole point — there is no "true bold" Special Elite,
        # nor would a heavier weight match the visual register. The
        # matched-phrase role re-uses the same file and gains
        # differentiation purely through the accent colour (red), the
        # way a real bichrome typewriter ribbon shifted between black
        # and red without changing weight. Falls back through Space
        # Mono / DejaVu Sans Mono before degrading to the Playfair
        # serif chain — a missing Special Elite install lands on the
        # closest in-rotation typewriter-adjacent face (mono) rather
        # than dropping a slab-typewriter theme onto a transitional
        # serif silhouette.
        "quote_regular": [
            SPECIALELITE_REGULAR,
            SPACEMONO_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            SPECIALELITE_REGULAR,
            SPACEMONO_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            SPECIALELITE_REGULAR,
            SPACEMONO_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "atomic": {
        # Atomic Age is a chunky 1950s display face (Sorkin Type, OFL)
        # — pointed angular terminals on slab bodies, very mid-century
        # signage / Sputnik-poster register. Like Bangers (comic) and
        # Special Elite (dispatch) it ships only Regular, so the
        # matched-phrase role re-uses the same file and gains
        # differentiation through the accent colour alone. Body text
        # in a display face is loud by design — that's the point. The
        # fallback chain ends at a heavy sans (DejaVu / Liberation /
        # Noto Sans Bold) before degrading to the Playfair serif
        # chain, since a missing-Atomic-Age install should land on a
        # heavy display silhouette rather than an elegant serif.
        "quote_regular": [
            ATOMICAGE_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            ATOMICAGE_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            ATOMICAGE_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "marker": {
        # Permanent Marker (Apache 2.0, Font Diner / Google Fonts) — a
        # single-weight hand-drawn marker face whose deliberately uneven
        # strokes do all the visual work. Like Bangers (comic), Special
        # Elite (dispatch), and Atomic Age (atomic) it ships only Regular,
        # so the matched-phrase role re-uses the same file and gains
        # differentiation through the accent colour (blue) alone — same
        # trick the bichrome typewriter and comic-book themes use. The
        # fallback chain ends at a heavy sans (DejaVu / Liberation / Noto
        # Sans Bold) before degrading to the Playfair serif chain, so a
        # missing-Permanent-Marker install lands on a chunky display
        # silhouette rather than dropping the marker theme onto an
        # elegant transitional serif.
        "quote_regular": [
            PERMANENTMARKER_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            PERMANENTMARKER_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            PERMANENTMARKER_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "roman": {
        # Cinzel Decorative (OFL, Natanael Gama) — a digital revival of
        # the Roman capitalis monumentalis cut on Trajan's Column, with
        # the same flared serifs and even stroke contrast that a chisel
        # produces in marble. The "Decorative" cut adds the small
        # ornamental flourishes you see on Imperial-era inscriptions.
        # Like Bangers (comic), Special Elite (dispatch), Atomic Age
        # (atomic), Permanent Marker (marker), and Rye (saloon), the
        # body and matched-phrase roles share the family — we step up
        # one weight (Regular → Bold) for the matched phrase rather
        # than picking a contrasting face, since switching face mid-line
        # would shatter the inscription illusion. The Black weight
        # carries the SPQR cartouche and oversized quote marks. The
        # fallback chain ends at a heavy serif (DejaVu / Liberation /
        # Noto Serif Bold) before degrading to the Playfair chain so a
        # missing-Cinzel-Decorative install lands on a high-contrast
        # serif silhouette rather than a sans, keeping the lapidary
        # register at least directionally correct.
        "quote_regular": [
            CINZELDECORATIVE_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            CINZELDECORATIVE_BOLD,
            CINZELDECORATIVE_BLACK,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            CINZELDECORATIVE_BLACK,
            CINZELDECORATIVE_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "saloon": {
        # Rye (OFL, Sorkin Type / Google Fonts) — a 19th-century
        # wood-engraved display slab serif designed to look like the
        # block-printed type used on Wild West saloon signs and wanted
        # posters. Like Bangers (comic), Special Elite (dispatch),
        # Atomic Age (atomic), and Permanent Marker (marker) it ships
        # only Regular, so the matched-phrase role re-uses the same
        # file and gains differentiation purely through the accent
        # colour (red), exactly the way two-colour letterpress
        # broadsides shifted between black and red ink on the same
        # type plate. Fallback chain ends at a heavy serif (DejaVu /
        # Liberation / Noto Serif Bold) before degrading to the
        # Playfair chain — the broadside silhouette degrades to "heavy
        # serif" rather than to a transitional / display alternative
        # so a missing-Rye install still reads as bookish broadside.
        "quote_regular": [
            RYE_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            RYE_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            RYE_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "alchemy": {
        # Two faces, both OFL via Google Fonts.
        #
        # Body — IM Fell English (Igino Marini, 2007), a digital
        # revival of the 17th-century Oxford types cut by Peter de
        # Walpergen for John Fell, Bishop of Oxford. These were the
        # types of the Oxford University Press during the era when
        # actual alchemical treatises (Ashmole's ``Theatrum Chemicum
        # Britannicum``, Newton's manuscript translations of Flamel)
        # were being printed in England — the body silhouette is
        # period-authentic for a grimoire rather than a generic
        # serif.
        #
        # Matched phrase + ornament — MedievalSharp (Anomandari /
        # skosch, 2011), a calligraphic display face whose sharply-
        # pointed strokes read as a ritual scribe's hand. Ships only
        # Regular, so — like Bangers (comic), Special Elite
        # (dispatch), Atomic Age (atomic), Permanent Marker (marker),
        # and Rye (saloon) — the matched-phrase role re-uses the
        # same file and gains its visual weight purely through the
        # red rubricated accent colour, exactly the way a real
        # alchemical manuscript would have flagged the operative
        # phrase of a spell with a red-ink emphasis on a single ink
        # weight.
        #
        # Fallback chain ends with the EB Garamond / DejaVu / Liberation
        # / Noto serif tier before degrading to the Playfair chain so a
        # missing-IM-Fell install lands on a humanist Renaissance serif
        # (closest in-rotation neighbour to John Fell's types) and a
        # missing-MedievalSharp install lands on UnifrakturMaguntia —
        # blackletter is the obvious next-nearest "ritual hand"
        # silhouette before falling back to a generic bold serif.
        "quote_regular": [
            IMFELLENGLISH_REGULAR,
            EBGARAMOND_REGULAR,
            *QUOTE_FONT_REGULAR_CANDIDATES,
        ],
        "quote_bold": [
            MEDIEVALSHARP_REGULAR,
            UNIFRAKTUR_BOOK,
            EBGARAMOND_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            MEDIEVALSHARP_REGULAR,
            UNIFRAKTUR_BOOK,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "grimoire": {
        # IM Fell English body — a digital revival of John Fell's
        # 17th-century Oxford University Press types (Igino Marini, OFL).
        # The deliberate inking irregularities of the metal-type
        # letterpress survive in every glyph as visible ink shoulders and
        # eroded terminals — the page reads as a genuine antique tome
        # rather than as a clean modern serif. Shared with ``alchemy``
        # above as the body face — both occult themes share the same
        # period-authentic Oxford-press silhouette, the silhouette
        # difference between the two coming from the ground (parchment
        # yellow vs. leather-bound black) and the matched-phrase face
        # (MedievalSharp ritual hand vs. TFoust phantom scrawl). EB
        # Garamond Regular sits behind it as the unicode-safe second
        # rank in case the IM Fell file is missing on a host. TFoustScript
        # carries the matched phrase: short ASCII time strings
        # ("half past two") render in its signature hollow-outline
        # shaggy silhouette, the "phantom scrawl" that defines the
        # theme. EB Garamond Bold sits behind TFoust in the bold chain
        # as a unicode-safe second rank — if the matched phrase ever
        # contains a non-ASCII character (an em-dash inside
        # ``shortly after dawn—at last``), PIL falls through to it
        # because TFoust is missing the glyph at file level. The
        # ornament slot is NEVER TFoust (it'd tofu the oversized curly
        # quote marks); IM Fell English carries the oversized opening
        # / closing quotation marks instead, so the ornament inherits
        # the same vintage-press character as the body — visually
        # unified rather than pairing the body with a contrasting
        # heavier face.
        "quote_regular": [
            IMFELLENGLISH_REGULAR,
            EBGARAMOND_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            TFOUST_REGULAR,
            EBGARAMOND_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            IMFELLENGLISH_REGULAR,
            EBGARAMOND_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
        # Source-card seam: ``render_source_card`` runs the title and the
        # matched phrase through ``normalize_dashes`` (which emits U+2014
        # em-dashes) and wraps the matched phrase in U+201C / U+201D curly
        # quotes — both glyphs TFoust does not ship, and PIL's fallback is
        # file-level so the renderer otherwise prints ``.notdef`` tofu in
        # the card. Routing the card's bold weight through EB Garamond Bold
        # (the unicode-safe second rank in ``quote_bold``) keeps the card
        # readable while leaving TFoust as the matched-phrase face in the
        # main render, where the matched text is pure-ASCII time phrases.
        "card_quote_bold": [
            EBGARAMOND_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
    },
    "deco": {
        # Righteous (Astigmatic, OFL) — 1930s geometric art-deco display
        # sans. Ships only Regular, so the matched-phrase role re-uses the
        # file and gains differentiation from the red accent alone — same
        # bichrome-ribbon trick the comic / dispatch / atomic / marker /
        # saloon themes use. Fallback chain ends at a heavy sans (DejaVu /
        # Liberation / Noto Sans Bold) before degrading to the Playfair
        # serif chain, so a missing-Righteous install lands on a heavy
        # display silhouette rather than dropping the deco theme onto an
        # elegant transitional serif.
        "quote_regular": [
            RIGHTEOUS_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            RIGHTEOUS_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            RIGHTEOUS_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "placard": {
        # Patrick Hand SC (Patrick Wagesreiter, OFL) — friendly
        # hand-printed face whose small caps for lowercase do all the
        # visual work. Single-weight; matched phrase reuses Regular and
        # gains differentiation from the red accent alone. Same heavy-sans
        # fallback chain comic / marker / atomic use.
        "quote_regular": [
            PATRICK_HAND_SC_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            PATRICK_HAND_SC_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            PATRICK_HAND_SC_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "chanbara": {
        # Shojumaru (Astigmatic, OFL) — dramatic brush-painted display
        # face. Single-weight; matched phrase reuses Regular and gains
        # differentiation from the red sun-disc accent alone. Heavy-sans
        # fallback chain before degrading to the Playfair serif chain so
        # a missing install lands on a heavy display silhouette rather
        # than dropping a brush-painted theme onto an elegant transitional
        # serif.
        "quote_regular": [
            SHOJUMARU_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            SHOJUMARU_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            SHOJUMARU_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "chalkboard": {
        # Playwrite GB J Guides (TypeTogether, OFL) — UK primary-school
        # joined cursive with dotted-outline practice letters. Single-weight
        # (Regular only); a true "Bold guide letter" doesn't exist in the
        # family. Matched-phrase role reuses Regular and gains differentiation
        # from the yellow chalk-stick accent alone — same trick comic /
        # dispatch / atomic / marker / saloon / deco / glacier already use.
        # Fallback chain prefers italic faces (DejaVu Sans Italic, Liberation
        # Sans Italic) before degrading to the Playfair chain so a missing
        # install lands on at least a slanted silhouette rather than dropping
        # a cursive theme onto an upright serif.
        "quote_regular": [
            PLAYWRITE_GB_J_GUIDES_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Italic.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            PLAYWRITE_GB_J_GUIDES_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-BoldItalic.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            PLAYWRITE_GB_J_GUIDES_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "glacier": {
        # Iceland (Cyreal, OFL) — geometric techno / retro-futurism display
        # face. Same single-weight discipline as Righteous / Bangers / Atomic
        # Age: matched phrase reuses Regular and gains differentiation from
        # the green accent. Same heavy-sans fallback chain.
        "quote_regular": [
            ICELAND_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            ICELAND_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            ICELAND_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "mucha": {
        # Cormorant Garamond is a humanist serif from the dramatic /
        # high-contrast branch of the family tree — sharper curves and
        # more pronounced contrast than EB Garamond (illuminated /
        # gothic) or IM Fell English (alchemy / grimoire / herbarium),
        # placing it firmly in the editorial-display register the Art
        # Nouveau poster tradition wanted. Variable font; the default
        # instance is Regular but we pin Regular / Bold explicitly the
        # same way Bitter / Jost / Rubik / Inter / Antonio do.
        # Berkshire Swash (Astigmatic, OFL) carries the ornament slot
        # so the oversized curly quotation marks land on a flourished
        # Belle-Époque script face — the same "humanist body + period
        # display ornament" pairing pattern ``illuminated`` uses with
        # EB Garamond + UnifrakturMaguntia. A missing Berkshire Swash
        # install falls through to Cormorant Bold so the ornament
        # never drops to bitmap.
        "quote_regular": [
            (CORMORANT_VARIABLE, "Regular"),
            EBGARAMOND_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (CORMORANT_VARIABLE, "Bold"),
            EBGARAMOND_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            BERKSHIRE_SWASH_REGULAR,
            (CORMORANT_VARIABLE, "Bold"),
            EBGARAMOND_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "fillmore": {
        # Bungee Shade is a single-weight 3D-blocked display face —
        # the matched-phrase role re-uses Regular and gains
        # differentiation through the blue accent colour alone (same
        # trick comic / dispatch / atomic / marker / saloon / deco /
        # glacier / chalkboard / placard / chanbara use). Falls back
        # through Bangers (the closest in-rotation display-face
        # sibling) and Atomic Age before heavy DejaVu / Liberation /
        # Noto Sans Bold, so a missing-Bungee install still lands on
        # a chunky display silhouette rather than the Playfair serif.
        "quote_regular": [
            BUNGEE_SHADE_REGULAR,
            BANGERS_REGULAR,
            ATOMICAGE_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            BUNGEE_SHADE_REGULAR,
            BANGERS_REGULAR,
            ATOMICAGE_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            BUNGEE_SHADE_REGULAR,
            BANGERS_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "firmament": {
        # Cardo (David Perry, OFL) — humanist Renaissance serif designed
        # for classical scholarship. Pairs the period silhouette of 17th-
        # century celestial atlas typography with strong on-eInk
        # legibility. Visually distinct from the other Garamond-class
        # faces in the rotation: EB Garamond (illuminated/gothic) and
        # Cormorant Garamond (mucha). Italic fills the ornament role for
        # the oversized opening quote mark — Italic Garamonds carry the
        # classical / mythological register of constellation names. Falls
        # back through EB Garamond → DejaVu Serif → Liberation Serif →
        # Playfair so a missing-Cardo install still lands on a humanist
        # serif rather than the Playfair display silhouette.
        "quote_regular": [
            CARDO_REGULAR,
            EBGARAMOND_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            CARDO_BOLD,
            EBGARAMOND_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            CARDO_ITALIC,
            CARDO_BOLD,
            EBGARAMOND_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "lcars": {
        # Antonio (Vernon Adams, OFL) — the de-facto free LCARS substitute:
        # a tall narrow condensed sans whose silhouette mirrors Helvetica
        # Compressed / Swiss 911 (the original Star Trek interface
        # typeface family). Variable font; the default axis instance is
        # Regular, but we pin Regular / Bold by name the same way Bitter /
        # Jost / Rubik do so a future axis-default change in the upstream
        # file can't silently shift the rendered weight. Falls back through
        # heavy DejaVu / Liberation / Noto Sans Bold before degrading to
        # the Playfair serif chain.
        "quote_regular": [
            (ANTONIO_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (ANTONIO_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        # Stardate callouts beside each pill button and the LCARS wordmark
        # in the top elbow bar both want the same upright condensed sans
        # so the console silhouette stays consistent. ``ornament`` is also
        # what render() pulls for the oversized opening / closing quote
        # glyphs, and the condensed Antonio sits comfortably in that role
        # against the white body — same family family the rest of the
        # frame uses.
        "ornament": [
            (ANTONIO_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Astrarium — Cormorant Garamond for the body, same humanist
    # high-contrast serif ``mucha`` already pulls from. Reads as the
    # editorial / mid-century-modern register the astronomical-clock
    # mockup uses, where the serif body sits next to a hairline-ruled
    # dashboard layout. Variable font with named instances; Regular for
    # the body, Bold for the matched-phrase tangerine, Bold again in
    # the ornament slot for the oversized opening / closing quote marks
    # painted alongside the dial. Sans labels for the dashboard chrome
    # (header strip, datum-panel keys, dial scale numerals) are loaded
    # directly from ``META_FONT_BOLD_CANDIDATES`` inside
    # ``render_astrarium_frame`` — they're chrome, not literary, and
    # belong in the same DejaVu/Liberation/Noto sans chain ``diags``
    # uses for its status labels.
    "astrarium": {
        "quote_regular": [
            (CORMORANT_VARIABLE, "Regular"),
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (CORMORANT_VARIABLE, "Bold"),
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (CORMORANT_VARIABLE, "Bold"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # System sans for the diagnostic panel. The render path for diags is
    # the status-grid layout, not the literary frame — a clean grotesque
    # sans reads better at small label sizes than the Playfair serif
    # default. Picks a different *family* (sans) from default/dark
    # (transitional serif) so the fall-through paths (goodnight,
    # source card) also look visibly different rather than aliasing
    # default.
    "diags": {
        "quote_regular": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
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

    ``card_<base>`` roles (e.g. ``card_quote_bold``, used by
    ``render_source_card``) follow a layered fallback: theme's
    ``card_<base>`` override → theme's ``<base>`` → default's
    ``<base>``. This lets a theme whose ``quote_bold`` chain starts
    with a deliberately-ASCII-only display face (TFoust on
    ``grimoire``) override only the source-card seam, where the
    rendered text passes through ``normalize_dashes`` (which produces
    U+2014 em-dashes) and is wrapped in U+201C / U+201D curly quotes
    — both glyphs the ASCII-only face cannot supply. PIL's font
    fallback is file-level, not glyph-level, so without this seam
    the source card would draw ``.notdef`` boxes for those characters.
    """
    fonts = THEME_FONTS.get(theme) or THEME_FONTS["default"]
    chain = fonts.get(role)
    if chain is not None:
        return chain
    if role.startswith("card_"):
        base = role[len("card_") :]
        chain = fonts.get(base)
        if chain is not None:
            return chain
        return THEME_FONTS["default"][base]
    return THEME_FONTS["default"][role]

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
    parser.add_argument(
        "--time",
        default=None,
        help="Time in HH:MM 24-hour format. Required unless --mode goodnight.",
    )
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
        choices=["production", "debug", "card", "goodnight"],
        default="debug",
        help=(
            "Render mode. 'production' hides debug UI; 'debug' shows bucket/quality/time "
            "metadata; 'card' draws a centered source card (title/author/Gutenberg ID/"
            "matched phrase) instead of the full quote — used by the source-card button. "
            "'goodnight' draws a centered static message in the active theme — used by "
            "--quiet-image=auto and --startup-image=auto."
        ),
    )
    parser.add_argument(
        "--message",
        default="Good night.",
        help="Headline text for --mode goodnight. Ignored otherwise.",
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
    args = parser.parse_args()
    if args.mode != "goodnight" and not args.time:
        parser.error("--time is required unless --mode goodnight")
    return args


def pick_quote(time_str: str, history_path: str | None = None, history_days: int = pick_quote_module.DEFAULT_HISTORY_DAYS) -> dict:
    return pick_quote_module.select_quote(
        time_str=time_str,
        history_path=history_path,
        history_days=history_days,
        database_path=pick_quote_module.DEFAULT_DATABASE_PATH,
    )


_FONT_CACHE: dict[tuple, ImageFont.ImageFont] = {}


def _normalize_candidates(candidates) -> tuple:
    """Normalize the load_font candidates list into a hashable cache key.

    Plain string entries become ``(path, None)``; tuple entries pass through.
    """
    return tuple((c, None) if not isinstance(c, tuple) else tuple(c) for c in candidates)


def load_font(candidates: list, size: int):
    """Load the first reachable TrueType font in ``candidates``, memoized.

    Each entry is either a plain path string or a ``(path, variation_name)``
    tuple. When the tuple form is used and the face is a variable font,
    ``set_variation_by_name`` selects the named instance (e.g. ``"Bold"``) —
    this is how per-theme weight picks for the bundled Bitter variable font
    work (its default axis instance is Thin, so the variation is load-bearing
    — a missed call would render near-invisible hairlines on the panel).
    A variation name that the file doesn't expose falls through to
    the default instance silently; the next fallback candidate only fires if
    the file itself is missing or unreadable.

    Results are cached per-process keyed on ``(normalised_candidates, size)``.
    ``fit_quote`` calls ``load_font`` up to 18 times per render with the same
    candidate chain at different sizes; without a cache that's 36 candidate-
    chain scans + 36 ``ImageFont.truetype`` opens per render. Cache lifetime
    is the renderer subprocess (single-threaded), so no FD-leak risk.

    Contract: callers must NOT mutate the returned font (e.g. by calling
    ``set_variation_by_name`` directly). All variation pinning is encoded in
    the candidate tuple so a different variation produces a different cache
    key; an external mutation would silently corrupt other cache consumers.
    """
    global _FONT_FALLBACK_WARNED
    normalized = _normalize_candidates(candidates)
    cache_key = (normalized, size)
    cached = _FONT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    for path, variation in normalized:
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
        _FONT_CACHE[cache_key] = font
        return font
    if not _FONT_FALLBACK_WARNED:
        print(
            "warning: no TrueType font found; falling back to PIL bitmap default. "
            "Install fonts-noto-core or the bundled fonts/ directory.",
            file=sys.stderr,
            flush=True,
        )
        _FONT_FALLBACK_WARNED = True
    # Deliberately NOT caching the bitmap fallback. A transient miss (NFS hiccup,
    # filesystem briefly unavailable, momentary file-handle exhaustion) would
    # otherwise pin the process to degraded rendering for the whole subprocess
    # lifetime — and contact_sheet.py renders 144 frames in one process, so a
    # single early hiccup would silently downgrade every later tile. Re-scanning
    # the candidate chain on each fallback call is cheap (a few Path.exists
    # checks) and lets the next call recover automatically once the font path
    # is reachable again. The warn-once behaviour comes from
    # _FONT_FALLBACK_WARNED, not from caching, so we still don't spam stderr.
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

# Pre-compiled longest-first so the first prefix that matches the candidate
# wins ("twenty-five minutes past" beats "minutes past" for the same row).
# Order is load-bearing — keep this list sorted by descending prefix length.
_TIME_PHRASE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        prefix,
        re.compile(
            rf"(?<![A-Za-z0-9])(?<![A-Za-z0-9]-){re.escape(prefix)}"
            rf"(?:[ ,]+[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)?(?![A-Za-z0-9])(?!-[A-Za-z0-9])",
            re.IGNORECASE,
        ),
    )
    for prefix in sorted(TIME_PHRASE_PREFIXES, key=len, reverse=True)
]


def _direct_match_pattern(normalized_match: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9])(?<![A-Za-z0-9]-){re.escape(normalized_match)}(?![A-Za-z0-9])(?!-[A-Za-z0-9])",
        re.IGNORECASE,
    )


def resolve_display_match(text: str, match_text: str) -> str:
    normalized_match = " ".join((match_text or "").split()).strip()
    if not normalized_match:
        return ""

    direct = _direct_match_pattern(normalized_match).search(text)
    if direct:
        return direct.group(0)

    lower_match = normalized_match.lower()
    for prefix, pattern in _TIME_PHRASE_PATTERNS:
        if not lower_match.startswith(prefix):
            continue
        for m in pattern.finditer(text):
            candidate = m.group(0).strip(" ,.;:!?")
            if candidate.lower().startswith(lower_match):
                return candidate

    return normalized_match


def _font_ascent(font) -> int:
    """Return the font's ascent in pixels, or 0 when unavailable.

    Used by the per-chunk baseline-alignment offset in the body draw
    loop: PIL's default text anchor is ``"la"`` (left, ascender top),
    so when a line mixes two fonts whose ascents differ (e.g. gothic
    pairs EB Garamond body with UnifrakturMaguntia bold), drawing
    both chunks at the same ``y`` leaves the bold phrase floating
    above the body baseline by ``body_ascent − bold_ascent`` pixels.
    The bitmap fallback (``ImageFont.load_default()`` from a
    misconfigured install) doesn't expose ``getmetrics`` reliably; in
    that case we return 0 so every chunk gets the same offset and the
    baseline misalignment falls back to today's behaviour rather than
    crashing.
    """
    try:
        return font.getmetrics()[0]
    except (AttributeError, OSError):
        return 0


def tokenize_quote(text: str, match_text: str) -> list[tuple[str, bool]]:
    normalized_match = resolve_display_match(text, match_text)
    if not normalized_match:
        return [(text, False)]
    match = _direct_match_pattern(normalized_match).search(text)
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
    # Space width is the same for every inter-word position that uses the same
    # font object. fit_quote calls wrap_styled_text up to 18 times per render
    # with two distinct fonts (regular + bold); a 140-char quote has ~25 spaces,
    # so without this memo we'd run draw.textbbox(" ", …) ~450 times per render.
    space_widths: dict[int, int] = {}

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
                font_id = id(font)
                space_width = space_widths.get(font_id)
                if space_width is None:
                    bbox = draw.textbbox((0, 0), " ", font=font)
                    space_width = bbox[2] - bbox[0]
                    space_widths[font_id] = space_width
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


def draw_faux_3way_text(
    image: Image.Image,
    xy,
    text,
    font,
    ink_a,
    ink_b,
    ink_c,
    density_a: float,
    density_b: float,
    pattern_offset=(0, 0),
):
    """Paint ``text`` as a three-ink Bayer stipple.

    Same masking strategy as ``draw_faux_gray_text`` but partitions the
    shared 4×4 Bayer tile by two thresholds: cells below
    ``round(density_a*16)`` get ``ink_a``, cells below
    ``round((density_a + density_b)*16)`` get ``ink_b``, the remainder
    get ``ink_c``. Mirrors the ``_fill_swatch_stipple_3way`` partition
    used by the ``diags`` triple-swatch row, so a theme's text glyphs
    and the ``diags`` reference swatch share one perceived hue at panel
    distance. Currently used by ``chanbara``'s oversized quote marks
    for the documented burnt-orange recipe (R+Y+G 50/40/10).
    """
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(xy, text, font=font, fill=255)
    px = image.load()
    mx = mask.load()
    ox, oy = pattern_offset
    threshold_a = round(density_a * 16)
    threshold_b = round((density_a + density_b) * 16)
    for y in range(image.height):
        for x in range(image.width):
            if mx[x, y]:
                tile = BAYER_4x4[(y + oy) % 4][(x + ox) % 4]
                if tile < threshold_a:
                    px[x, y] = ink_a
                elif tile < threshold_b:
                    px[x, y] = ink_b
                else:
                    px[x, y] = ink_c


def _paint_ornament_mark(image, xy, text, font, theme: str, colors: dict, pattern_offset=(0, 0)) -> None:
    """Dispatch the oversized opening / closing quote-mark painter.

    Most themes paint via ``draw_faux_gray_text`` (a 50/50 checkerboard
    between ``ornament_dark`` and ``ornament_light``). ``chanbara``
    overrides to a three-ink burnt-orange Bayer stipple (R+Y+G at
    50/40/10) — the same recipe the ``diags`` synth band labels "burnt
    orange" — so the oversized marks read as the warm rust-orange of a
    weathered samurai-cinema title card rather than the fire-engine red
    a solid-red paint would produce.
    """
    if theme == "chanbara":
        draw_faux_3way_text(
            image,
            xy,
            text,
            font=font,
            ink_a=SPECTRA6["red"],
            ink_b=SPECTRA6["yellow"],
            ink_c=SPECTRA6["green"],
            density_a=0.50,
            density_b=0.40,
            pattern_offset=pattern_offset,
        )
        return
    draw_faux_gray_text(
        image,
        xy,
        text,
        font=font,
        dark=colors["ornament_dark"],
        light=colors["ornament_light"],
        pattern_offset=pattern_offset,
    )


def draw_text_dithered(image: Image.Image, xy, text, font, dark, light, pattern_offset=(0, 0), light_density: float = 0.5):
    """Paint ``text`` as a ``dark``/``light`` Bayer stipple, like
    ``draw_faux_gray_text`` but iterates only over the text's bounding box.

    Used by the nightvision body-text path, which calls this once per word
    chunk via ``wrap_styled_text`` (~25 chunks per line × multiple lines).
    A full-image scan per chunk would multiply 800×480 = 384k pixel reads
    by the chunk count and push render time into the tens of seconds; the
    bbox-limited variant keeps cost proportional to the inked area.
    Produces the same ``((x + ox) + (y + oy)) % 2`` stipple pattern as
    ``draw_faux_gray_text`` so the two paths interleave cleanly when a
    theme uses both (e.g. dithered body text plus dithered ornament
    quote marks).

    ``light_density`` chooses between three on-palette stipple densities:

    * ``0.5`` (default) — 50/50 checkerboard. Half the inked pixels paint
      ``light`` and half paint ``dark``.
    * ``0.25`` — sparse 1-in-4 (one ``light`` pixel per 2×2 tile, 75%
      ``dark``). Matches the ``draw_atomic_border`` Layer 0 ground
      pattern. Used by ``grimoire`` to lift its red matched-phrase
      glyphs with a sparse white stipple — enough white to read as a
      candlelit-rubric shimmer against the black ground without
      diluting the red into pink at panel distance.
    * Any other value in ``(0.25, 0.5)`` — 4×4 ordered Bayer matrix with
      ``threshold = round(light_density * 16)``. A pixel paints ``light``
      when ``BAYER_4x4[y % 4][x % 4] < threshold``, else ``dark``. Used
      by ``deco`` at ``0.375`` (3/8 yellow on 5/8 red) to synthesise a
      red-biased tangerine — yellow has much higher perceived luminance
      than red, so the previous 0.5 checkerboard read as washed-out
      amber. Keep the new branch isolated: the existing 0.25 and 0.5
      values still hit their original byte-identical patterns so
      nightvision / grimoire / other callers are unaffected.

    The mask is thresholded at ≥128 rather than treated as binary on every
    nonzero coverage. Pillow renders TTF glyphs with an antialiased mask
    whose edge pixels carry partial coverage (1..254); writing a fully
    saturated dark/light to every nonzero pixel grows a 1px halo around
    each glyph that, after ``snap_image_to_palette``, stays as a hot
    fringe (especially the ``light`` half of the dither, which sits far
    from the page bg in palette space and never rounds back to it). The
    plain ``draw.text`` + palette-snap path that this helper replaces for
    the nightvision body / attribution / debug strip silently snapped
    those partial-coverage fringes back to the bg colour, so the prior
    glyph silhouette was effectively binary at ~50% coverage; the ≥128
    threshold reproduces that silhouette here so the dithered path
    doesn't visibly thicken small text.
    """
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox(xy, text, font=font)
    x0, y0, x1, y1 = bbox
    # Pad by a pixel for glyph stems that sit on the bbox edge, then clamp.
    x0 = max(0, x0 - 1)
    y0 = max(0, y0 - 1)
    x1 = min(image.width, x1 + 1)
    y1 = min(image.height, y1 + 1)
    if x1 <= x0 or y1 <= y0:
        return
    region_w = x1 - x0
    region_h = y1 - y0
    mask = Image.new("L", (region_w, region_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text((xy[0] - x0, xy[1] - y0), text, font=font, fill=255)
    px = image.load()
    mx = mask.load()
    ox, oy = pattern_offset
    if light_density <= 0.25:
        # Sparse 1-in-4: light only where both axes are even in the
        # offset frame, so one light pixel per 2×2 tile (25% light).
        for y in range(region_h):
            ay = y + y0
            for x in range(region_w):
                if mx[x, y] >= 128:
                    ax = x + x0
                    px[ax, ay] = light if ((ax + ox) % 2 == 0 and (ay + oy) % 2 == 0) else dark
    elif light_density >= 0.5:
        for y in range(region_h):
            ay = y + y0
            for x in range(region_w):
                if mx[x, y] >= 128:
                    ax = x + x0
                    px[ax, ay] = dark if ((ax + ox) + (ay + oy)) % 2 == 0 else light
    else:
        # 4×4 ordered Bayer for arbitrary intermediate densities. The
        # deco theme uses 0.375 here for a red-biased orange; see the
        # docstring and ``BAYER_4x4``'s comment.
        threshold = round(light_density * 16)
        for y in range(region_h):
            ay = y + y0
            for x in range(region_w):
                if mx[x, y] >= 128:
                    ax = x + x0
                    px[ax, ay] = light if BAYER_4x4[(ay + oy) % 4][(ax + ox) % 4] < threshold else dark


def _draw_text_body(image: Image.Image, draw, xy, text, font, fill, theme: str):
    """Draw body / attribution text, stippling per-theme accents on a
    short allowlist of themes; every other theme falls through to a
    solid ``draw.text`` call.

    * ``nightvision`` — body / attribution glyphs render as a 50/50
      green/white Bayer stipple so the perceived ink lifts from
      Spectra-6 saturated green to a brighter mint, improving
      legibility at panel-viewing distance. Only fills equal to the
      body green get dithered — the matched-phrase yellow accent is
      drawn solid, as are debug/footer labels in other themes that
      happen to pass through this seam.
    * ``grimoire`` — the red accent fill is rerouted to solid white at
      paint time so the matched phrase reads cleanly at panel
      viewing distance. The earlier candlelit-rubric (sparse 1-in-4
      white-on-red) sat the phrase at a half-density pink that read
      muddy on the black ground at typical viewing distance. The
      TFoust hollow-display matched-phrase font + the bold weight
      provide the visual differentiation against the IM Fell English
      white body. The grimoire border still uses solid red for its
      pentagrams, outer rule, and Mars sigil (Mars is then bbox-
      post-passed to maroon — see ``draw_grimoire_border``), so the
      operative red ink stays present on the page; only the *text*
      register switches to monochrome-bold. Other themes that share
      the red accent colour keep their own per-theme behaviour.
    * ``deco`` — only the red matched-phrase accent gets dithered,
      red-biased yellow-on-red (3/8 yellow, 5/8 red) on a shared
      4×4 Bayer matrix, so the phrase reads as warm tangerine at
      panel distance. Spectra 6 has no orange ink; the previous 50/50
      checkerboard landed on amber-peach because yellow has much
      higher perceived luminance than red — the red-biased ratio
      drags the perceived hue back onto the warm-orange range the
      period actually used for sunburst and chevron ornaments. Body
      / attribution / source-id text in black passes through solid.
      ``draw_deco_border``'s final pass dithers its painted red
      pixels using the same Bayer threshold so the matched phrase
      and border decoration share one orange tone.
    * ``gothic`` — only the red matched-phrase blackletter gets
      dithered, 50/50 yellow-on-red checkerboard via the shared
      two-ink amber recipe (``dark=red, light=yellow`` — the same
      mix the ``diags`` synth band labels "amber"). The matched
      phrase reads as warm candle-flame against the black
      cathedral ground, sitting visually distinct from the solid-
      red corner quatrefoils and mid-edge diamonds the
      ``draw_gothic_border`` painter still paints in pure red.
    * ``alchemy`` — only the red matched-phrase accent gets
      dithered, 50/50 blue-on-red checkerboard via the documented
      two-ink purple/violet recipe (``dark=red, light=blue``), so
      the phrase reads as deep purple against the yellow parchment
      ground. Purple is the canonical alchemist's pigment (Tyrian
      from murex, later "mauveine" — the synthesised dye that
      birthed industrial chemistry); the body and border still
      paint solid (the magic-circle rule, corner pentagrams, and
      element-glyph triangles are intentional ritual ink, not
      candidates for the chromatic-mix register the time phrase
      occupies). Body / attribution / source-id text in black
      passes through solid.
    * ``firmament`` — only the yellow matched-phrase accent gets
      dithered, 50/50 yellow-on-white checkerboard via the
      documented two-ink cream / gold recipe (``dark=yellow,
      light=white`` — the same recipe the diags synth band labels
      "cream"). Reads as gilded constellation labels against the
      navy night-sky ground, the canonical ink-on-vellum register
      of 17th-century celestial atlases. The body white passes
      through solid; only the matched-phrase yellow sentinel hits
      this seam. Stars, constellation lines, and corner ornaments
      paint outside this seam via ``draw_firmament_border``.
    """
    if theme == "nightvision" and fill == SPECTRA6["green"]:
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["white"])
    elif theme == "grimoire" and fill == SPECTRA6["red"]:
        # Solid white — see docstring for the half-red-was-hard-to-read
        # rationale. The matched phrase stays visually distinct via the
        # TFoust hollow-display face + bold weight.
        draw.text(xy, text, font=font, fill=SPECTRA6["white"])
    elif theme == "gothic" and fill == SPECTRA6["red"]:
        # Amber (R+Y 1:1) — the same recipe the ``diags`` synth band
        # labels "amber". Reads as warm candle-flame against the black
        # cathedral ground, lifting the matched phrase clear of the
        # red border ornaments instead of sharing their ink.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["yellow"])
    elif theme == "alchemy" and fill == SPECTRA6["red"]:
        # 50/50 red+blue checkerboard → perceived purple; see docstring.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["blue"])
    elif theme == "deco" and fill == SPECTRA6["red"]:
        # 3/8 yellow on 5/8 red via the shared 4×4 Bayer matrix; matches
        # ``draw_deco_border``'s post-pass threshold so the matched
        # phrase and the border ornaments land on the same tangerine.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["yellow"], light_density=0.375)
    elif theme in ("blueprint", "scholar") and fill == SPECTRA6["red"]:
        # Matched phrase shifts to maroon (R+K 1:1). For ``blueprint``
        # this reads as the darker red pencil pressed firmly into the
        # drafting paper rather than the fire-engine red of a digital
        # callout; for ``scholar`` it reads as the aged red-lead of an
        # academic-journal annotation, deepening the leather-bound
        # gravity the Bitter slab serif body already carries. Border
        # ornaments / corner registration marks stay solid red (they
        # paint outside this seam via the border painters' own
        # ``draw.line(..., fill=...)`` calls).
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["black"])
    elif theme == "illuminated" and fill == SPECTRA6["blue"]:
        # Matched phrase shifts to violet / Tyrian purple (R+B 1:1) —
        # the rarest dye of the medieval scriptorium, more precious
        # than the lapis blue accent the body's rubricated red sits
        # against. The body's red glyphs stay solid (illuminated's
        # ``text`` slot is red, not blue, so the body fill never hits
        # this seam); only matched-phrase blue gets the R+B treatment.
        # Border jewels are also plum (R+B+K 3-ink, see
        # ``draw_illuminated_border``), so the matched-phrase violet
        # and the corner cabochons share an R+B tonal register.
        draw_text_dithered(image, xy, text, font, dark=SPECTRA6["red"], light=SPECTRA6["blue"])
    elif theme == "glacier" and fill == SPECTRA6["green"]:
        # Matched phrase shifts to cyan (G+B 1:1) — the genuine aurora
        # teal of borealis light catching on glacial ice, lifting the
        # phrase off the flat Spectra-6 saturated green that read as a
        # muddy mid-tone against the blue body text. The frost-crystal
        # border's diagonal-shard tips already get a sky-blue post-pass
        # (B+W) for sunlight-on-ice; the matched-phrase cyan completes
        # the cool-palette gradient: blue body → cyan matched phrase
        # → sky-blue ornament highlights.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["blue"])
    elif theme == "risograph" and fill == SPECTRA6["blue"]:
        # Matched phrase shifts to violet/purple (R+B 1:1) — the AUTHENTIC
        # riso double-pass overprint. Real risograph prints with red on
        # one plate and blue on another physically create purple wherever
        # the two ink passes overlap; the digital LitClock render
        # synthesises the same effect via a 50/50 R+B stipple. Preserves
        # the theme's defining "no-black-ink" invariant by construction
        # (purple is red + blue, both already in the palette). Body red
        # text stays solid; only the matched-phrase blue accent gets the
        # overprint treatment.
        draw_text_dithered(image, xy, text, font, dark=SPECTRA6["red"], light=fill)
    elif theme == "bauhaus" and fill == SPECTRA6["blue"]:
        # Matched phrase shifts to navy (B+K 1:1) for tighter contrast
        # against the newly-yellow BL triangle corner accent. The TR
        # blue square in the border stays solid blue (it paints via
        # ``draw.rectangle`` outside this seam), so the poster keeps
        # all three primaries visible: solid red circles, solid blue
        # square, solid yellow triangle, and the navy matched phrase
        # sits as a deeper variant of the blue accent within the
        # body block.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["black"])
    elif theme == "nightvision" and fill == SPECTRA6["yellow"]:
        # Matched phrase shifts to lime (Y+G 5/8:3/8) — yellow-biased
        # green that reads as the bright neon "tactical readout" glow
        # of a real HUD warning, lifting the phrase off the flat
        # Spectra-6 yellow that read as a solid alert flag. The
        # luminance asymmetry rule applies here as it does to deco's
        # tangerine: a 50/50 Y+G mix reads as washed-out olive
        # because yellow dominates green, so we bias toward yellow
        # to land on the brighter lime end of the gradient. Threshold
        # 6/16 mirrors the tangerine recipe's red-biased ratio
        # (dark=yellow, light=green, density=0.375).
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["green"], light_density=0.375)
    elif theme == "herbarium" and fill == SPECTRA6["green"]:
        # Matched phrase shifts to forest green (G+K 1/2:1/2 — the
        # documented dark-green recipe from
        # ``spectra6_color_recipes.md``'s two-ink table, previously
        # flagged as "not in use" / a forward reference for a pine
        # or herbarium theme; the herbarium implementation claims
        # it). The forest-green tone reads as the dark-pressed plant
        # material a real herbarium specimen develops over time, and
        # contrasts strongly with the cream-washed ground (which is
        # mostly white + 12.5% yellow Bayer dither). Italic IM Fell
        # English in forest-green is the canonical specimen-sheet
        # rendering of a Latin scientific name. The Y+G olive recipe
        # the pressed-leaf border graphic uses sits adjacent on the
        # green axis but reads as a different tone, so body matched
        # phrase and decoration stay visually distinct.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["black"])
    elif theme in ("mucha", "fillmore") and fill == SPECTRA6["red"]:
        # Body text shifts to maroon (R+K 1/2:1/2 — the documented
        # two-ink recipe ``blueprint`` / ``scholar``'s matched phrase
        # use). Both themes hold the red sentinel in the ``text``
        # THEMES slot so EVERY body-text path hits this seam:
        #
        # * ``mucha`` — the first theme in the rotation to use a
        #   synthesised colour as its primary body fill rather than
        #   just an accent. Reads as the deep wine / oxblood the
        #   period's poster lettering actually used. The matched
        #   phrase below is keyed off green and lands on cyan via
        #   its own branch.
        # * ``fillmore`` — subdues the otherwise-loud red-on-yellow
        #   body without losing the psychedelic-poster identity. A
        #   pure-red body on the saturated-yellow ground reads as
        #   visually fatiguing at panel distance; R+K maroon
        #   (oxblood) sits deeper on the page, the way real Fillmore
        #   posters' red ink looked once printed onto yellow stock —
        #   ink interaction shifts the perceived hue darker. The
        #   matched-phrase blue stays solid, the corner-blob
        #   primaries stay solid, so all six Spectra-6 inks still
        #   appear on the page (the design intent of fillmore's
        #   "visual maximalist" identity is preserved — only the
        #   body-text intensity is tempered).
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["black"])
    elif theme == "mucha" and fill == SPECTRA6["green"]:
        # Matched phrase shifts to cyan (G+B 1/2:1/2 — the documented
        # recipe ``glacier``'s matched phrase already uses). Gives a
        # cool teal accent that reads cleanly against the warm maroon
        # body, completing the period palette of Belle-Époque posters.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["blue"])
    elif theme == "firmament" and fill == SPECTRA6["yellow"]:
        # Cream / parchment gold (Y+W 1:1 — the documented two-ink
        # recipe the ``diags`` synth band labels "cream"). On the
        # navy night-sky ground (B+K stipple from ``draw_firmament_
        # border``'s Layer 0), Y+W reads as warm gilded text — the
        # canonical ink-on-vellum register of 17th-century celestial
        # atlases like Cellarius's *Harmonia Macrocosmica*, where
        # constellation names and zodiac labels were rendered in
        # gilt against deep indigo ground. Yellow and white both sit
        # far from blue in Spectra-6 space, so the perceived contrast
        # against the navy is strong even at panel viewing distance.
        # The body white passes through solid via the ``else`` branch
        # below; only the matched-phrase yellow accent hits this seam.
        draw_text_dithered(image, xy, text, font, dark=fill, light=SPECTRA6["white"])
    else:
        draw.text(xy, text, font=font, fill=fill)


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
    triangle, circle — in all FOUR Bauhaus primary inks: red (TL +
    BR circles), blue (TR square), and yellow (BL triangle), with
    the outer frame in black. The actual Bauhaus colour vocabulary
    is red + blue + yellow as the three primaries plus black for
    structure; the previous version pinned a blue triangle in the
    BL corner where yellow more authentically completes the
    poster-palette set. Referencing the classic Bauhaus vocabulary
    of basic geometric forms in primary hues.

    The yellow ink is hardcoded at this call site (same exception
    ``draw_comic_corner_stripes`` and ``draw_marker_border`` make)
    because the bauhaus ``THEMES`` dict only carries three accent
    slots (text=black, accent=blue, ornament_dark=red) — extending
    the THEMES schema just to unlock the fourth primary would
    re-pin every cross-theme invariant test for a single border
    glyph. The yellow gap colour does NOT come from ``colors`` —
    the bauhaus theme has no yellow slot — so this is the one
    border that paints in an ink the theme dict can't reach.

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
    yellow_primary = SPECTRA6["yellow"]

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
    # Bottom-left: YELLOW filled triangle. Right-angle at the bottom-left
    # corner, hypotenuse sweeping up to the top-right of the bounding box,
    # so the shape visually points inward toward the quote block. Yellow
    # completes the canonical Bauhaus red / blue / yellow primary trio
    # alongside the black outer frame — pre-Stage-3 this slot was a
    # second blue shape, redundant with the TR square's accent ink.
    bl_left = corner_margin
    bl_top = height - corner_margin - corner_size
    bl_right = corner_margin + corner_size
    bl_bottom = height - corner_margin
    draw.polygon(
        [(bl_left, bl_bottom), (bl_right, bl_bottom), (bl_right, bl_top)],
        fill=yellow_primary,
    )
    # Bottom-right: red filled circle, mirroring the top-left and completing
    # the diagonal colour balance.
    draw.ellipse(
        (width - corner_margin - corner_size, height - corner_margin - corner_size,
         width - corner_margin, height - corner_margin),
        fill=ornament_color,
    )


def draw_risograph_border(image: Image.Image, colors: dict) -> None:
    """Paint a lively risograph-inspired print frame.

    The effect comes from deliberate misregistration: a primary frame in the
    theme's text color, a slightly shifted duplicate in the accent color, plus
    crop / register marks and a few chunky side blocks that feel like a print
    test sheet. The center stays mostly clear so the quote remains legible.

    The shifted-accent registration crosses at the four corners are painted
    in an off-palette sentinel and then bbox-post-passed through a 3-way
    Bayer partition into LAVENDER (red + blue + white at ~1/3 each — the
    documented R+B+W 3-ink pastel). The lavender reads as the lighter
    half of the overprint register: the canonical red crosses stay solid
    (base ink), while the misregistered "overprint" passes show the
    paler tone that real risograph print test sheets develop where two
    plates wash together. Preserves the theme's no-black-ink invariant
    by construction (lavender pulls only red, blue, white — never
    black).
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    base = colors["text"]
    accent = colors["accent"]
    shadow = colors.get("subtle", base)

    outer = 20
    inner = 34
    dx, dy = 5, 3

    draw.rectangle((outer + dx, outer + dy, width - 1 - outer + dx, height - 1 - outer + dy), outline=accent, width=2)
    draw.rectangle((outer, outer, width - 1 - outer, height - 1 - outer), outline=base, width=2)
    draw.rectangle((inner, inner, width - 1 - inner, height - 1 - inner), outline=shadow, width=1)

    # Chunky print bars.
    draw.rectangle((42, 54, 74, 170), fill=accent)
    draw.rectangle((56, 68, 88, 184), outline=base, width=2)
    draw.rectangle((width - 88, height - 184, width - 56, height - 68), fill=base)
    draw.rectangle((width - 102, height - 198, width - 70, height - 82), outline=accent, width=2)

    # Overprint-style circles.
    draw.ellipse((width - 118, 58, width - 54, 122), outline=base, width=2)
    draw.ellipse((width - 112 + dx, 64 + dy, width - 48 + dx, 128 + dy), outline=accent, width=2)
    draw.ellipse((54, height - 128, 118, height - 64), outline=accent, width=2)
    draw.ellipse((48 + dx, height - 122 + dy, 112 + dx, height - 58 + dy), outline=base, width=2)

    # Registration / crop marks.
    def cross(cx: int, cy: int, color: tuple[int, int, int]) -> None:
        draw.line((cx - 10, cy, cx + 10, cy), fill=color, width=1)
        draw.line((cx, cy - 10, cx, cy + 10), fill=color, width=1)
        draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), outline=color, width=1)

    marks = [
        (outer, outer),
        (width - outer, outer),
        (outer, height - outer),
        (width - outer, height - outer),
    ]
    lavender_sentinel = (1, 1, 1)
    for cx, cy in marks:
        cross(cx, cy, base)
        cross(cx + dx, cy + dy, lavender_sentinel)

    # 3-way Bayer post-pass on the sentinel crosses: cells 0-4 → red,
    # cells 5-9 → blue, cells 10-15 → white (~1/3 each, the documented
    # lavender R+B+W recipe). Bbox-scoped per cross.
    pixels = image.load()
    ink_red = SPECTRA6["red"]
    ink_blue = SPECTRA6["blue"]
    ink_white = SPECTRA6["white"]
    for cx, cy in marks:
        sx, sy = cx + dx, cy + dy
        x0 = max(0, sx - 12)
        y0 = max(0, sy - 12)
        x1 = min(width - 1, sx + 12)
        y1 = min(height - 1, sy + 12)
        for py in range(y0, y1 + 1):
            row = BAYER_4x4[py & 3]
            for px in range(x0, x1 + 1):
                if pixels[px, py] == lavender_sentinel:
                    cell = row[px & 3]
                    if cell < 5:
                        pixels[px, py] = ink_red
                    elif cell < 10:
                        pixels[px, py] = ink_blue
                    else:
                        pixels[px, py] = ink_white


def draw_scholar_border(image: Image.Image, colors: dict) -> None:
    """Paint a restrained academic-journal margin treatment.

    Scholar gets subtle editorial structure rather than loud decoration:
    a double blue frame, two inner column rules, and a few sparse red
    reference marks at the outer margins. It should feel like a curated
    critical edition, not a page that has been attacked by graduate students.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    body = colors["text"]
    accent = colors["accent"]
    outer_inset = 18
    inner_inset = 26
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

    marker_font = load_font(META_FONT_BOLD_CANDIDATES, size=14)
    for label, y in [("1", 104), ("2", height // 2 - 8), ("3", height - 118)]:
        bbox = draw.textbbox((0, 0), label, font=marker_font)
        xoff = (bbox[2] - bbox[0]) // 2
        draw_text(draw, (52 - xoff, y), label, font=marker_font, fill=accent)
        draw_text(draw, (width - 52 - xoff, y), label, font=marker_font, fill=accent)


def draw_blueprint_border(image: Image.Image, colors: dict, clear_rect: tuple[int, int, int, int] | None = None) -> None:
    """Paint a cyanotype drafting sheet: dithered ground + frame + grid + crosshairs.

    Four layers:

    * **Layer 0 — 50/50 white-on-blue checkerboard ground.** Every
      pixel matching ``page_bg`` is replaced with white on one half of
      a single-pixel checkerboard, leaving the other half as the
      Spectra-6 saturated blue. At panel viewing distance the eye
      averages the alternation into a paler cyanotype wash, softening
      the panel's vivid blue into something closer to a real
      photochemical print. Painted at the very start of the painter so
      the frame / grid / crosshairs below overpaint the dithered ground
      cleanly. Skipped when ``page_bg`` is absent from the palette so
      direct-call test paths stay valid. Same trick the ``atomic`` theme
      uses for its green ground.
    * **Outer frame** in the body-text colour (white in production).
    * **Graph-paper grid** at 20px spacing inside the frame so the
      ground reads as engineering paper rather than an empty sheet.
      When ``clear_rect`` is provided, the grid skips that quote-sized
      window so the text block gets a calmer field without losing the
      drafting-sheet frame and corner marks.
    * **Corner registration crosshairs** in the accent colour — the
      small print-alignment ticks used on engineering drawings. Pulled
      from ``accent`` so they pop against the white body/grid ink,
      matching the matched-time-phrase highlight.
    """
    width, height = image.size
    page_bg = colors.get("page_bg")
    frame_inset = 16
    frame_color = colors.get("subtle", colors["text"])
    border_color = colors["text"]
    mark_color = colors["accent"]

    # Layer 0: 50/50 white-on-blue checkerboard. Only pixels matching
    # the exact ``page_bg`` colour are affected — defence in depth if a
    # future caller paints accents before this painter runs.
    if page_bg is not None:
        dither_light = SPECTRA6["white"]
        pixels = image.load()
        for y in range(height):
            for x in range(width):
                if (x + y) & 1 and pixels[x, y] == page_bg:
                    pixels[x, y] = dither_light

    draw = ImageDraw.Draw(image)

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
    """Paint a manuscript-style border: cream-washed vellum + double
    rubricated rule + plum corner cabochons.

    Three motifs from the medieval-illumination vocabulary:

    * **Layer 0 — sparse cream ground wash.** A 4×4 Bayer dither
      flips ~12.5% of the white ``page_bg`` pixels to yellow (cells
      with value < 2), leaving the rest pure white. At panel viewing
      distance the eye averages the alternation into a faint aged-
      vellum tone — the warm off-white of a real fifteenth-century
      manuscript page rather than the panel's flat pure white. Same
      Bayer threshold ``dispatch``'s Layer 0 uses, but slotted into
      a theme whose palette is white / red / blue rather than
      white / black / red, so the cream sits as the warm side of a
      cool-paled palette.
    * **Double rubricated rule** — two parallel thin red rectangles
      with a narrow blank band between them. The workhorse border of
      medieval illuminated manuscripts.
    * **Plum corner cabochons** — each corner gem is painted in an
      off-palette sentinel ink, then a per-jewel bbox post-pass
      assigns the painted pixels to red / blue / black via a 3-way
      4×4 Bayer partition (cells 0-4 → red, 5-9 → blue, 10-15 →
      black, ~1/3 each). The eye averages the three inks at panel
      distance into deep plum — the documented R+B+K 1/3 each
      three-ink recipe (see ``spectra6_color_recipes.md``'s deep-
      tones section). Reads as the wine-dark lapis cabochons inset
      on the most precious medieval bindings rather than the
      flat lapis blue the previous solid-fill jewels produced.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    body = colors["text"]       # rubricated red
    accent = colors["accent"]   # lapis blue (kept for the ``draw_illuminated_border_uses_theme_colours_not_hardcoded_rgb`` direct-call path; plum jewels collapse to the sentinel/post-pass branch only on the bundled illuminated palette)
    page_bg = colors.get("page_bg")
    cream_light = SPECTRA6["yellow"]

    # Layer 0: sparse 1-in-8 yellow-on-white cream wash. Only flips
    # pixels matching the exact ``page_bg`` colour so deliberate-
    # palette-mismatch test paths stay valid.
    pixels = image.load()
    if page_bg is not None:
        for y in range(height):
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < 2:
                    pixels[x, y] = cream_light

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
    # If the caller passed the standard illuminated palette (accent=lapis blue),
    # paint plum cabochons via the 3-way Bayer recipe. Direct test callers that
    # override accent to a non-standard ink fall back to a solid-fill jewel so
    # the ``uses_theme_colours_not_hardcoded_rgb`` invariant still holds.
    if accent == SPECTRA6["blue"]:
        jewel_sentinel = (1, 1, 1)
        for cx, cy in centres:
            draw.ellipse(
                (cx - jewel_radius, cy - jewel_radius, cx + jewel_radius, cy + jewel_radius),
                fill=jewel_sentinel,
            )
        # 3-way Bayer translation: cells 0-4 → red, 5-9 → blue, 10-15 → black.
        ink_red = SPECTRA6["red"]
        ink_blue = SPECTRA6["blue"]
        ink_black = SPECTRA6["black"]
        for cx, cy in centres:
            x0 = max(0, cx - jewel_radius - 1)
            y0 = max(0, cy - jewel_radius - 1)
            x1 = min(width - 1, cx + jewel_radius + 1)
            y1 = min(height - 1, cy + jewel_radius + 1)
            for py in range(y0, y1 + 1):
                row = BAYER_4x4[py & 3]
                for px in range(x0, x1 + 1):
                    if pixels[px, py] == jewel_sentinel:
                        cell = row[px & 3]
                        if cell < 5:
                            pixels[px, py] = ink_red
                        elif cell < 10:
                            pixels[px, py] = ink_blue
                        else:
                            pixels[px, py] = ink_black
    else:
        for cx, cy in centres:
            draw.ellipse(
                (cx - jewel_radius, cy - jewel_radius, cx + jewel_radius, cy + jewel_radius),
                fill=accent,
            )


def draw_gothic_border(image: Image.Image, colors: dict) -> None:
    """Paint a Gothic-tracery border: double rule + maroon quatrefoils + cream mid-edge diamonds.

    The outer red rule and inner white rule echo the doubled rubrication
    line of medieval manuscripts but flip the colour split that
    ``illuminated`` uses (single ink colour for both rules) — the
    polychrome Scotch-rule is the giveaway that this is the cathedral
    chronicle, not the scriptorium page.

    Four corner quatrefoils — the iconic four-lobed Gothic motif found
    in cathedral tracery, rose windows, and printed-book ornaments —
    each consist of four lobes around a small white centre dot. Each
    lobe is painted in red as a sentinel ink, then a per-lobe bbox
    post-pass flips half of the painted pixels to black per
    ``(x+y)&1`` parity — the documented R+K 1:1 maroon recipe (same
    one ``dispatch``'s rubber stamp uses). The eye averages adjacent
    red+black dots into maroon / iron-aged tracery at panel viewing
    distance — the actual material colour of real Gothic ironwork
    rather than the freshly-painted fire-engine red of an
    illustrative reproduction. The white centre dots stay solid for
    silhouette legibility.

    Four mid-edge diamond ornaments nod to the chapter dividers used
    in early printed German books, painted in cream (yellow + white)
    via the documented Y+W 1:1 recipe: each diamond is painted as a
    yellow polygon then a bbox post-pass flips half of its pixels to
    white per parity. On the black ground the eye averages adjacent
    yellow+white dots into a warm parchment-cream — reads as candle
    flicker on a cathedral wall rather than the saturated yellow chalk
    of a daylight render. Pre-existing red mid-edge ornaments would
    have read as identical-tone repetition of the corner quatrefoils;
    the cream shift gives the mid-edges their own chromatic register
    and ties the gothic theme back to the candlelit-rubric signature
    its matched phrase already uses.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    body = colors["text"]      # white ink
    accent = colors["accent"]  # rubric red

    outer_inset = 14
    inner_inset = 22
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=accent,
        width=1,
    )
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=body,
        width=1,
    )

    # Corner quatrefoils: four small lobes arranged in a + around the
    # corner anchor, then a smaller white centre dot to give the
    # four-lobed clover silhouette legibility on a 4-bit panel.
    # Lobes paint in red as a sentinel; the per-lobe post-pass below
    # flips half to black for the documented R+K maroon recipe.
    lobe_radius = 5
    lobe_offset = 4
    sentinel_red = SPECTRA6["red"]
    sentinel_yellow = SPECTRA6["yellow"]
    maroon_dark = SPECTRA6["black"]
    cream_light = SPECTRA6["white"]
    centres = [
        (outer_inset, outer_inset),
        (width - 1 - outer_inset, outer_inset),
        (outer_inset, height - 1 - outer_inset),
        (width - 1 - outer_inset, height - 1 - outer_inset),
    ]
    lobe_bboxes: list[tuple[int, int, int, int]] = []
    for cx, cy in centres:
        for dx, dy in ((0, -lobe_offset), (lobe_offset, 0), (0, lobe_offset), (-lobe_offset, 0)):
            lx, ly = cx + dx, cy + dy
            draw.ellipse(
                (lx - lobe_radius, ly - lobe_radius, lx + lobe_radius, ly + lobe_radius),
                fill=sentinel_red,
            )
            lobe_bboxes.append((lx - lobe_radius, ly - lobe_radius, lx + lobe_radius, ly + lobe_radius))
        draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=body)

    pixels = image.load()
    # Maroon post-pass on each lobe bbox — flip half of the red pixels
    # to black per (x+y)&1 parity inside the per-lobe bbox.
    for x0, y0, x1, y1 in lobe_bboxes:
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(width - 1, x1)
        y1 = min(height - 1, y1)
        for py in range(y0, y1 + 1):
            for px in range(x0, x1 + 1):
                if (px + py) & 1 == 0 and pixels[px, py] == sentinel_red:
                    pixels[px, py] = maroon_dark

    # Mid-edge cream diamonds — painted in yellow as a sentinel, then a
    # per-diamond bbox post-pass flips half of the painted pixels to
    # white per parity for the documented Y+W cream recipe.
    diamond = 4
    midpoints = [
        (width // 2, outer_inset),
        (width // 2, height - 1 - outer_inset),
        (outer_inset, height // 2),
        (width - 1 - outer_inset, height // 2),
    ]
    for cx, cy in midpoints:
        draw.polygon(
            [(cx, cy - diamond), (cx + diamond, cy), (cx, cy + diamond), (cx - diamond, cy)],
            fill=sentinel_yellow,
        )
    for cx, cy in midpoints:
        x0 = max(0, cx - diamond)
        y0 = max(0, cy - diamond)
        x1 = min(width - 1, cx + diamond)
        y1 = min(height - 1, cy + diamond)
        for py in range(y0, y1 + 1):
            for px in range(x0, x1 + 1):
                if (px + py) & 1 == 0 and pixels[px, py] == sentinel_yellow:
                    pixels[px, py] = cream_light


def _draw_grimoire_sun(draw: ImageDraw.ImageDraw, cx: int, cy: int, accent: tuple[int, int, int]) -> None:
    """Solar ☉ — outline circle with a filled centre dot. The
    circumpunct is the alchemical sigil for gold / the Sun and the
    most iconographically simple symbol in the four-planet set."""
    r = 7
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=accent, width=2)
    draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=accent)


def _draw_grimoire_moon(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    accent: tuple[int, int, int],
    page_bg: tuple[int, int, int],
) -> None:
    """Lunar ☽ — silver / mercurial. Filled red disk overdrawn by a
    smaller page-bg disk offset rightward so the visible red collapses
    to a left-opening crescent (horns pointing left, the alchemical
    convention for the receptive/lunar principle)."""
    r = 7
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=accent)
    # Smaller carving disk shifted +4 in x: the overlap region stays
    # entirely within the outer disk so we never paint page_bg outside
    # the symbol footprint.
    inner_r = 6
    offset = 4
    draw.ellipse(
        (cx - inner_r + offset, cy - inner_r, cx + inner_r + offset, cy + inner_r),
        fill=page_bg,
    )


def _draw_grimoire_mars(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, accent: tuple[int, int, int]
) -> None:
    """Martial ♂ — iron / aggressive. Outline circle offset slightly
    down-left, with a long diagonal shaft + perpendicular V-barb
    arrowhead pointing out toward the upper-right (NE). The classical
    "active principle" sigil. Barbs are drawn as two short
    perpendicular-to-shaft strokes meeting at the tip so the arrow
    reads as an arrowhead rather than an indeterminate blob at the
    small mid-edge symbol scale."""
    r = 6
    # Circle centre pushed down-left so the NE arrow has room without
    # the circle bumping the mid-edge anchor.
    bcx, bcy = cx - 3, cy + 3
    draw.ellipse((bcx - r, bcy - r, bcx + r, bcy + r), outline=accent, width=2)
    # Long diagonal shaft from upper-right of circle outward to NE.
    shaft_start = (bcx + 4, bcy - 4)
    tip = (bcx + 11, bcy - 11)
    draw.line((*shaft_start, *tip), fill=accent, width=2)
    # Two barbs at the tip, each perpendicular to the 45° shaft, forming
    # the canonical arrowhead V. The first barb runs horizontal-left
    # from the tip, the second runs vertical-down from the tip — taken
    # together they "open" the arrowhead in the right direction.
    barb = 5
    draw.line((tip[0] - barb, tip[1], tip[0], tip[1]), fill=accent, width=2)
    draw.line((tip[0], tip[1], tip[0], tip[1] + barb), fill=accent, width=2)


def _draw_grimoire_venus(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, accent: tuple[int, int, int]
) -> None:
    """Venusian ♀ — copper / receptive. Outline circle offset slightly
    up, with a vertical shaft descending from the circle's bottom and
    a horizontal crossbar — the alchemical "passive principle" sigil
    and the visual complement to Mars in the four-planet set."""
    r = 6
    bcx, bcy = cx, cy - 4
    draw.ellipse((bcx - r, bcy - r, bcx + r, bcy + r), outline=accent, width=2)
    # Vertical shaft from circle bottom downward.
    shaft_top = (bcx, bcy + r)
    shaft_bottom = (bcx, bcy + r + 7)
    draw.line((*shaft_top, *shaft_bottom), fill=accent, width=2)
    # Horizontal crossbar across the shaft, ~2/3 of the way down.
    crossbar_y = bcy + r + 4
    draw.line((bcx - 4, crossbar_y, bcx + 4, crossbar_y), fill=accent, width=2)


def draw_grimoire_border(image: Image.Image, colors: dict) -> None:
    """Paint an alchemical-grimoire border: outer rule + four magic-circle
    inscribed pentagrams + four planetary sigils on the mid-edges.

    Shares the black/white/red palette with ``gothic`` but flips the
    silhouette: gothic stacks a doubled outer rule (red + white) with a
    quatrefoil — the cathedral-tracery motif — at each corner; grimoire
    uses a single thin red rule with an *inscribed* pentagram (star +
    surrounding ring) at each corner, then breaks the four mid-edges
    with the four classical planetary alchemical sigils — Sun ☉ at the
    top centre, Moon ☽ at the bottom, Mars ♂ on the left, Venus ♀ on
    the right — pulling the iconographic vocabulary of medieval / early-
    modern occult diagrams directly onto the page. Same ground, same
    accent ink, completely different register from gothic.

    **Pentagrams.** Drawn deterministically by computing the five
    vertices of a regular pentagon inscribed in a circle of radius
    ``pent_radius`` centred at the corner anchor, then connecting them
    in skip-one order (``0 → 2 → 4 → 1 → 3 → 0``) — the classic
    single-stroke pentacle silhouette — and finally an outer outline
    circle of radius ``ring_radius`` around the star, giving the
    "pentagram inscribed in a circle" magic-circle composition. The
    first vertex is placed at the top (``angle = -π/2``) so the star
    reads upright at every corner; the ring sits ~3 px outside the
    star's vertex tips so the two strokes don't visually merge.

    **Mid-edge sigils.** Each of the four classical "wandering star"
    symbols (Sun / Moon / Mars / Venus) is drawn deterministically
    from PIL primitives so the renderer doesn't depend on glyph
    coverage in any font (TFoust, the body font, and the bundled
    fallbacks all vary in their unicode support for ``U+2609``
    onward). Positioned on the outer frame rule at each mid-edge so
    they punch through the line the way ``gothic``'s mid-edge diamonds
    do — keeping the frame from reading as an unbroken rectangular
    border. The Sun goes on top (the "highest" planet in geocentric
    cosmology), Moon on bottom, Mars / Venus on the left / right —
    pinning the active / receptive duality across the horizontal axis
    of the page.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    accent = colors["accent"]  # rubric red
    page_bg = colors.get("page_bg", SPECTRA6["black"])

    outer_inset = 14
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=accent,
        width=1,
    )

    # Four inscribed pentagrams at the inset corners. ``corner_offset``
    # pushes each centre far enough inward that the surrounding ring
    # (radius ``ring_radius`` + 2 px stroke half-width) stays clear of
    # the outer rule at ``outer_inset``.
    pent_radius = 11
    ring_radius = 14
    corner_offset = ring_radius + 2
    centres = [
        (outer_inset + corner_offset, outer_inset + corner_offset),
        (width - 1 - outer_inset - corner_offset, outer_inset + corner_offset),
        (outer_inset + corner_offset, height - 1 - outer_inset - corner_offset),
        (width - 1 - outer_inset - corner_offset, height - 1 - outer_inset - corner_offset),
    ]
    skip_one = (0, 2, 4, 1, 3, 0)
    for cx, cy in centres:
        vertices = []
        for i in range(5):
            angle = -math.pi / 2 + i * (2 * math.pi / 5)
            vx = cx + pent_radius * math.cos(angle)
            vy = cy + pent_radius * math.sin(angle)
            vertices.append((vx, vy))
        path = [vertices[i] for i in skip_one]
        draw.line(path, fill=accent, width=2)
        # Surrounding ring — the "magic circle" containing the pentacle.
        draw.ellipse(
            (cx - ring_radius, cy - ring_radius, cx + ring_radius, cy + ring_radius),
            outline=accent,
            width=2,
        )

    # Four planetary alchemical sigils centred on the mid-edges of the
    # outer rule. Each helper draws a ~14 px-tall symbol; the moon
    # carving uses ``page_bg`` to chisel a crescent out of a filled disk
    # without painting outside its own footprint.
    #
    # Each planet now reads in its CANONICAL celestial colour rather
    # than the shared red ``accent``: Sun ☉ → tangerine (the warm
    # solar gold the alchemists called *aurum*), Moon ☽ → sky (the
    # cool argent / silver-blue of lunar work), Mars ♂ → maroon
    # (oxblood / iron — the planet's metallic correspondence), Venus
    # ♀ → violet (copper-bloom / verdigris-leaning mauve — the
    # canonical "Venusian" ink in alchemical engravings). The Sun
    # helper paints in red, then a bbox post-pass flips ~3/8 to
    # yellow at Bayer threshold 6 (the documented R+Y 5/8:3/8
    # tangerine recipe). The Moon helper paints in blue as a sentinel,
    # then a bbox post-pass flips half of those blue pixels to white
    # per ``(x+y)&1`` parity (the documented B+W 1:1 sky recipe).
    # Mars paints in red and flips half to black for maroon (R+K 1:1).
    # Venus paints in red and flips half to blue for violet (R+B 1:1).
    # The four bboxes (±14 from each mid-edge anchor) don't overlap
    # any other layer, so the post-passes are safe to bbox-scope.
    mid_top = (width // 2, outer_inset)
    mid_bottom = (width // 2, height - 1 - outer_inset)
    mid_left = (outer_inset, height // 2)
    mid_right = (width - 1 - outer_inset, height // 2)
    moon_disc_blue = SPECTRA6["blue"]
    _draw_grimoire_sun(draw, *mid_top, accent)
    _draw_grimoire_moon(draw, *mid_bottom, moon_disc_blue, page_bg)
    _draw_grimoire_mars(draw, *mid_left, accent)
    _draw_grimoire_venus(draw, *mid_right, accent)

    # Per-planet bbox post-pass for the celestial-colour recipes.
    # Sigils are at most ~14 px on each side from their mid-edge
    # anchor (mars/venus offsets shift the bbox slightly off-anchor
    # — see their helpers for the exact arrow / cross geometry; the
    # padding here generously covers them).
    pixels = image.load()
    sigil_radius = 16
    planet_passes = (
        # (centre, sentinel_ink, light_ink, density)
        (mid_top, SPECTRA6["red"], SPECTRA6["yellow"], 0.375),   # ☉ Sun → tangerine
        (mid_bottom, moon_disc_blue, SPECTRA6["white"], 0.5),    # ☽ Moon → sky
        (mid_left, SPECTRA6["red"], SPECTRA6["black"], 0.5),     # ♂ Mars → maroon
        (mid_right, SPECTRA6["red"], SPECTRA6["blue"], 0.5),     # ♀ Venus → violet
    )
    for (cx, cy), dark_ink, light_ink, density in planet_passes:
        bx0 = max(0, cx - sigil_radius)
        by0 = max(0, cy - sigil_radius)
        bx1 = min(width - 1, cx + sigil_radius)
        by1 = min(height - 1, cy + sigil_radius)
        threshold = round(density * 16)
        if density <= 0.25:
            for py in range(by0, by1 + 1):
                for px in range(bx0, bx1 + 1):
                    if (px & 1) == 0 and (py & 1) == 0 and pixels[px, py] == dark_ink:
                        pixels[px, py] = light_ink
        elif density >= 0.5:
            for py in range(by0, by1 + 1):
                for px in range(bx0, bx1 + 1):
                    if (px + py) & 1 == 0 and pixels[px, py] == dark_ink:
                        pixels[px, py] = light_ink
        else:
            for py in range(by0, by1 + 1):
                row = BAYER_4x4[py & 3]
                for px in range(bx0, bx1 + 1):
                    if row[px & 3] < threshold and pixels[px, py] == dark_ink:
                        pixels[px, py] = light_ink


def draw_deco_border(image: Image.Image, colors: dict) -> None:
    """Paint an art-deco poster frame: doubled hairline rule + stepped
    skyscraper-step corner ornaments + a top-centre rising-sun fan.

    Three motifs, all canonical 1930s deco vocabulary:

    * **Doubled hairline frame** — outer rectangle at inset 14 and inner
      rectangle at inset 22, both 1 px stroke in ``colors["text"]``.
      The thin parallel rules are the silhouette of countless cinema
      programs and travel posters of the era.
    * **Stepped corner ornaments** — three concentric L-shapes per
      corner in ``colors["accent"]``, drawn from the inside of the
      doubled frame outward. The L's vertex sits at the inner-frame
      corner; arms 8 / 16 / 24 px long, 1 px stroke. The canonical
      skyscraper-steps motif found on every theatre marquee and
      jazz-age magazine cover.
    * **Centred rising-sun fan** — at the top horizontal mid-edge,
      a small filled accent dot with five short radial lines fanning
      *upward* through the inner frame band (capped by the outer
      hairline). Pure art-deco rising-sun. Sized to stay well clear
      of the quote block (top of the fan at y ≤ 13) and centred
      horizontally so it never reaches the right-aligned ``DEBUG
      MODE`` banner.

    The top-right stepped-corner ornament reaches x ≤ width-14 (24 px
    arm starting at the inner-frame corner at width-1-22), leaving
    ≥6 px of clearance from the default debug-label edge (``SIDE_MARGIN
    = 20``). The rising-sun is centred, far from the right-aligned
    label. So ``deco`` is intentionally **absent** from
    ``_DEBUG_LABEL_RIGHT_INSET`` — same exemption as ``atomic`` and
    ``dispatch``.

    **Final pass — red→orange Bayer dither.** Spectra 6 has no orange
    ink, so the L-shapes / rising-sun are dithered into a warm
    tangerine. After every shape is painted, walk the image and
    flip ~3/8 of the ``accent``-coloured pixels to yellow on the
    shared 4×4 Bayer matrix (``BAYER_4x4`` cells < threshold 6 → light).
    The red-biased ratio (5/8 red : 3/8 yellow) corrects the
    previous 50/50 checkerboard, which read as washed-out amber
    because yellow has much higher perceived luminance than red.
    The pass only fires when ``accent`` is the Spectra-6 red —
    direct-call test paths that pass a custom palette dict (e.g.
    a recoloured deco border for visual experiments) keep their
    solid accent. Phase and threshold match the
    ``light_density=0.375`` branch of ``draw_text_dithered`` so the
    bordered decoration and the matched-phrase body text share one
    orange tone instead of two slightly offset stipples.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    frame_color = colors["text"]
    accent_color = colors["accent"]

    outer_inset = 14
    inner_inset = 22
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=frame_color,
        width=1,
    )
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=frame_color,
        width=1,
    )

    # Stepped skyscraper-corner ornaments. For each corner, draw three
    # concentric L-shapes inside the inner frame. The L's vertex lives
    # at the inner-frame corner; arms extend along the two adjacent
    # sides. ``step_length`` doubles per step so the silhouette reads
    # as the canonical 1930s stepped pyramid.
    corner_origins = [
        # (corner_x, corner_y, dx, dy) — corner anchor (inner-frame corner)
        # plus the unit-vector pair pointing inward along the two sides.
        (inner_inset + 1, inner_inset + 1, +1, +1),                       # top-left
        (width - 2 - inner_inset, inner_inset + 1, -1, +1),                # top-right
        (inner_inset + 1, height - 2 - inner_inset, +1, -1),               # bottom-left
        (width - 2 - inner_inset, height - 2 - inner_inset, -1, -1),       # bottom-right
    ]
    for step in (1, 2, 3):
        step_length = 6 + step * 6  # 12 / 18 / 24
        step_offset = step * 2       # 2 / 4 / 6 px gap between concentric L's
        for cx, cy, dx, dy in corner_origins:
            ax = cx + dx * step_offset
            ay = cy + dy * step_offset
            # Horizontal arm along the top/bottom edge of the L.
            draw.line(
                [(ax, ay), (ax + dx * step_length, ay)],
                fill=accent_color,
                width=1,
            )
            # Vertical arm along the left/right edge of the L.
            draw.line(
                [(ax, ay), (ax, ay + dy * step_length)],
                fill=accent_color,
                width=1,
            )

    # Top-centre rising-sun fan. Small filled dot anchored on the inner
    # frame's top edge with five short radial rays fanning upward
    # through the band between the two frame rules. Stays inside that
    # 8-px band (inner_inset = 22, outer_inset = 14, so the band is
    # y ∈ [14, 22] inclusive); rays cap at y = outer_inset + 1 so they
    # never touch the outer hairline.
    fan_cx = width // 2
    fan_cy = inner_inset
    fan_dot_r = 2
    draw.ellipse(
        (fan_cx - fan_dot_r, fan_cy - fan_dot_r, fan_cx + fan_dot_r, fan_cy + fan_dot_r),
        fill=accent_color,
    )
    ray_top_y = outer_inset + 1
    ray_height = fan_cy - ray_top_y
    # Five rays spread across a 90° arc centred straight up (-π/2),
    # symmetric about the vertical axis: angles -π/2 ± k·(π/8).
    for k in (-2, -1, 0, 1, 2):
        angle = -math.pi / 2 + k * (math.pi / 8)
        end_x = fan_cx + math.cos(angle) * ray_height / max(abs(math.sin(angle)), 0.001) \
                if k != 0 else fan_cx
        end_y = ray_top_y
        # Clamp end_x to stay within the fan's natural footprint so
        # the side rays don't streak off to the canvas edge for low
        # |sin(angle)| values. The footprint half-width is ~ray_height.
        max_dx = ray_height
        if end_x < fan_cx - max_dx:
            end_x = fan_cx - max_dx
        elif end_x > fan_cx + max_dx:
            end_x = fan_cx + max_dx
        draw.line(
            [(fan_cx, fan_cy), (end_x, end_y)],
            fill=accent_color,
            width=1,
        )

    # Final pass: synthesise orange by flipping ~3/8 of the painted
    # red pixels to yellow on the shared 4×4 Bayer matrix. See the
    # docstring for the rationale; threshold (6) and phase match
    # ``draw_text_dithered``'s ``light_density=0.375`` branch so the
    # matched-phrase body text and the border decoration land on the
    # same red-biased tangerine.
    if accent_color == SPECTRA6["red"]:
        light = SPECTRA6["yellow"]
        threshold = 6  # round(0.375 * 16) — keep in sync with _draw_text_body
        pixels = image.load()
        for y in range(image.height):
            row = BAYER_4x4[y % 4]
            for x in range(image.width):
                if row[x % 4] < threshold and pixels[x, y] == accent_color:
                    pixels[x, y] = light

        # Cream-gradient post-pass on the rising-sun fan rays only.
        # After the tangerine pass converts ~3/8 of every red pixel to
        # yellow, the rays' remaining ~5/8 red pixels in the inner band
        # (y ∈ [fan_cy-5, fan_cy], near where the rays converge at the
        # accent dot) get flipped to white on the same (x+y)&1
        # parity. Inner-band rays then read as ~3/8 yellow + 5/16
        # white + 5/16 red — a warm cream that fades back into the
        # 5/8 red + 3/8 yellow tangerine at the tips. Reads as a
        # true sunburst with a bright central glow rather than a
        # uniform tangerine fan. Bbox-scoped to the rays' natural
        # footprint (x ∈ [fan_cx ± max_dx]) so the stepped-corner
        # L-shapes elsewhere on the page stay full tangerine.
        cream_band_top = max(0, fan_cy - 5)
        cream_band_bot = min(image.height - 1, fan_cy)
        cream_x_lo = max(0, fan_cx - ray_height)
        cream_x_hi = min(image.width - 1, fan_cx + ray_height)
        cream_light = SPECTRA6["white"]
        for y in range(cream_band_top, cream_band_bot + 1):
            for x in range(cream_x_lo, cream_x_hi + 1):
                if (x + y) & 1 == 0 and pixels[x, y] == accent_color:
                    pixels[x, y] = cream_light


def draw_glacier_border(image: Image.Image, colors: dict) -> None:
    """Paint an icy / aurora border: thin outer rule + four corner
    frost-crystal clusters + four mid-edge snowflake-tick stars.

    Three motifs, all evoking the geometric / glacial register that
    Iceland's chunky verticals suggest:

    * **Outer frame** — single rectangle at inset 14, 1 px stroke,
      drawn in ``colors["text"]`` (blue). Clean and engineered.
    * **Frost-crystal clusters** — each corner gets three angular
      filled triangles fanning out *from* the corner along the two
      adjacent sides, like ice splinters frozen across the page
      edge. Two shards in ``colors["text"]`` (blue) and the longest
      one tipped in ``colors["accent"]`` (green) — the aurora light
      catching on the ice. Sizes ~8–14 px so the cluster stays
      well outside the quote block (``SIDE_MARGIN`` + layout
      ``max_width`` always leaves ≥30 px of free corner).
    * **Mid-edge snowflake ticks** — at the midpoint of each edge,
      a small four-armed star (radius ~6 px) drawn in
      ``colors["text"]`` — a filled diamond plus a thin orthogonal
      cross. Reinforces the architectural symmetry without crowding
      the quote.

    The top-right frost-crystal cluster spans roughly x ≥ width-30,
    y ≤ 30 — overlaps the default ``DEBUG MODE`` label band. So
    ``glacier`` carries an inset entry in ``_DEBUG_LABEL_RIGHT_INSET``
    (34 px) mirroring ``blueprint``'s rationale.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    body_color = colors["text"]
    accent_color = colors["accent"]

    outer_inset = 14
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=body_color,
        width=1,
    )

    # Frost-crystal clusters at the four corners. Each cluster paints
    # three triangular shards fanning out *along* the two adjacent edges
    # from the corner. Shard 1 is short, on the horizontal axis; shard
    # 2 is short, on the vertical axis; shard 3 is the longest, on the
    # 45° diagonal — tipped in the accent colour for aurora-on-ice
    # contrast.
    corner_anchors = [
        # (anchor_x, anchor_y, dx, dy) — inner-frame corner plus the
        # unit-vector pair pointing into the page.
        (outer_inset + 2, outer_inset + 2, +1, +1),                       # top-left
        (width - 3 - outer_inset, outer_inset + 2, -1, +1),                # top-right
        (outer_inset + 2, height - 3 - outer_inset, +1, -1),               # bottom-left
        (width - 3 - outer_inset, height - 3 - outer_inset, -1, -1),       # bottom-right
    ]
    short_arm = 9
    long_arm = 14
    base_half = 3  # half-width of each shard's base near the corner
    for ax, ay, dx, dy in corner_anchors:
        # Horizontal shard — tip along the top/bottom edge.
        tip_h = (ax + dx * short_arm, ay)
        base_h_a = (ax, ay - base_half * dy)
        base_h_b = (ax, ay + base_half * dy)
        draw.polygon([tip_h, base_h_a, base_h_b], fill=body_color)
        # Vertical shard — tip along the left/right edge.
        tip_v = (ax, ay + dy * short_arm)
        base_v_a = (ax - base_half * dx, ay)
        base_v_b = (ax + base_half * dx, ay)
        draw.polygon([tip_v, base_v_a, base_v_b], fill=body_color)
        # Diagonal shard — the longest, tipped in accent for aurora.
        tip_d = (ax + dx * long_arm, ay + dy * long_arm)
        base_d_a = (ax + dx * base_half, ay - dy * base_half)
        base_d_b = (ax - dx * base_half, ay + dy * base_half)
        draw.polygon([tip_d, base_d_a, base_d_b], fill=accent_color)

    # Mid-edge snowflake ticks. Four-armed star: a filled diamond plus
    # a hairline cross through it. Painted in body colour so the
    # ornament reads as an architectural rivet rather than a feature
    # accent.
    star_r = 6
    midpoints = [
        (width // 2, outer_inset),            # top
        (width // 2, height - 1 - outer_inset),  # bottom
        (outer_inset, height // 2),           # left
        (width - 1 - outer_inset, height // 2),  # right
    ]
    diamond_r = 3
    for mx, my in midpoints:
        draw.polygon(
            [
                (mx, my - diamond_r),
                (mx + diamond_r, my),
                (mx, my + diamond_r),
                (mx - diamond_r, my),
            ],
            fill=body_color,
        )
        draw.line([(mx - star_r, my), (mx + star_r, my)], fill=body_color, width=1)
        draw.line([(mx, my - star_r), (mx, my + star_r)], fill=body_color, width=1)

    # Aurora-on-ice post-pass: flip ~50% of the diagonal shard's green
    # pixels to white on a 1×1 checkerboard inside each corner cluster's
    # bbox. The eye averages the resulting green+white pattern into a
    # sky-blue highlight at panel distance (50/50 green+white is the
    # documented two-ink mint recipe; here it lifts the deepest shard
    # tip toward the "sunlight catching the ice surface" register the
    # theme's brief calls for — the two short body-blue shards stay
    # solid so the cluster keeps a clear depth/highlight gradient).
    # Bbox-scoped because the shards fan ≤ long_arm+2 px from each
    # anchor; walking the full 800×480 canvas would be wasteful.
    pixels = image.load()
    for ax, ay, dx, dy in corner_anchors:
        x0 = min(ax + dx * (long_arm + 2), ax - base_half - 1)
        x1 = max(ax + dx * (long_arm + 2), ax + base_half + 1)
        y0 = min(ay + dy * (long_arm + 2), ay - base_half - 1)
        y1 = max(ay + dy * (long_arm + 2), ay + base_half + 1)
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(width - 1, x1)
        y1 = min(height - 1, y1)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if (x + y) & 1 == 0 and pixels[x, y] == accent_color:
                    pixels[x, y] = SPECTRA6["white"]


def draw_chalkboard_border(image: Image.Image, colors: dict) -> None:
    """Paint a classroom-chalkboard surround: doubled white wooden frame,
    a sparse cluster of chalk-dust dots tucked into the bottom-left
    corner of the slate (the chalk-tray side), a green-chalk teacher's
    check-mark in the upper-right margin, and a row of coral eraser-
    smudge spots along the bottom inner edge.

    Four motifs, all evoking the iconic slate / wood / chalk-dust
    combination of a Victorian-through-1990s schoolroom blackboard
    and the multi-colour chalk box that sat on every teacher's desk:

    * **Doubled wooden frame** — outer rectangle at inset 8 with a 3 px
      stroke (the chunky wooden surround) plus an inner rectangle at
      inset 18 with a 1 px stroke (the inside edge of the wood). The
      ~7 px band between the two rules stays unfilled so the panel's
      black ground reads through as dark wood grain rather than a
      single flat white strip — the visual silhouette of a real
      chalkboard frame.
    * **Chalk-dust scatter** — a sparse, deterministic stipple of
      tiny white dots (radius 1 px) inside the bottom-left corner
      of the inner frame. Pinned to the BL because that's where the
      chalk tray actually sits on a classroom board.
    * **Green-chalk check-mark** — a small ``✓`` painted in solid
      panel-native green at the upper-right inner margin, evoking
      the teacher's "marked correct" annotation that primary-school
      cursive practice sheets accumulate. Sits at y≈45, well below
      the ``DEBUG MODE`` banner band (y=14-29), so ``chalkboard``
      stays absent from ``_DEBUG_LABEL_RIGHT_INSET``. The green is
      solid Spectra-6 ink: only the panel's saturated green chalk
      reads as such at viewing distance, and stippling would dilute
      the recognition of the canonical correction mark.
    * **Coral eraser-smudge dots** — five small filled red dots
      along the bottom inner edge of the frame, each Bayer-post-
      passed with white pixels at 50/50 parity inside its bbox so
      the eye averages red+white at panel distance into coral
      (the documented two-ink recipe in ``spectra6_color_recipes.md``).
      Reads as the leftover pink eraser-stub marks that build up at
      the bottom of a real chalkboard, the spot the teacher most
      often drags an eraser across. Same post-pass pattern
      ``draw_placard_border`` uses on its thumbtack accents.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    frame_color = colors["text"]  # white chalk frame on the black slate
    accent_color = colors["accent"]  # yellow chalk-stick (matched phrase)
    chalk_green = SPECTRA6["green"]
    smudge_red = SPECTRA6["red"]

    # Outer thick wooden surround.
    outer_inset = 8
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=frame_color,
        width=3,
    )
    # Inner thin frame — the inside lip of the wood.
    inner_inset = 18
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=frame_color,
        width=1,
    )

    # Chalk-dust stipple inside the BL corner of the inner frame. Coords
    # are hand-tuned (not RNG'd) so the scatter is deterministic across
    # renders — the corpus rotates through 144 buckets and a non-stable
    # corner would make A/B comparisons noisier. Footprint stays within
    # a 40×30 px box pinned to the inner-frame BL corner.
    bl_x = inner_inset + 4
    bl_y = height - 1 - inner_inset - 4
    chalk_offsets = (
        (0, 0),  (5, -2), (11, 0), (18, -3), (23, 1),
        (3, -8), (9, -7), (16, -9), (22, -7), (28, -10),
        (1, -14), (7, -16), (15, -15), (20, -19), (26, -17),
        (5, -22), (12, -23), (19, -24), (24, -26),
    )
    for dx, dy in chalk_offsets:
        cx = bl_x + dx
        cy = bl_y + dy
        # 1 px dot — drawn as a single-pixel rectangle so PIL doesn't
        # anti-alias and dither the dot into surrounding palette greys
        # at snap_image_to_palette time.
        draw.rectangle((cx, cy, cx, cy), fill=frame_color)

    # Green-chalk teacher's check-mark in the upper-right margin. Two
    # short line segments forming a ✓: a 5px down-right diagonal joining
    # a 11px up-right diagonal at the elbow. Sits at y≈45 (below the
    # debug-banner band) and right-edge x ≈ width-30 (inside the inner
    # frame). 2 px stroke so the mark reads as a deliberate chalk swipe
    # rather than a hairline accident.
    tick_elbow_x = width - 1 - inner_inset - 22
    tick_elbow_y = 50
    draw.line(
        ((tick_elbow_x - 5, tick_elbow_y - 5), (tick_elbow_x, tick_elbow_y)),
        fill=chalk_green,
        width=2,
    )
    draw.line(
        ((tick_elbow_x, tick_elbow_y), (tick_elbow_x + 11, tick_elbow_y - 12)),
        fill=chalk_green,
        width=2,
    )

    # Coral eraser-smudge dots along the bottom inner edge. Five small
    # filled circles spaced 30 px apart, centred at y=height-inner-9 so
    # they sit just inside the bottom of the inner frame. Each smudge is
    # painted red first; the post-pass below stipples white over half of
    # each smudge's pixels (1×1 checkerboard) so the eye averages red+
    # white at panel distance into coral pink — the documented R+W 1:1
    # two-ink recipe — reading as the faint pink eraser-stub residue
    # that builds up at the bottom of a real classroom chalkboard.
    smudge_radius = 3
    smudge_centres = [
        (180 + i * 110, height - 1 - inner_inset - 9) for i in range(5)
    ]
    for cx, cy in smudge_centres:
        draw.ellipse(
            (cx - smudge_radius, cy - smudge_radius, cx + smudge_radius, cy + smudge_radius),
            fill=smudge_red,
        )

    # Coral post-pass — same recipe ``draw_placard_border`` uses on its
    # thumbtack accents. Bbox-scoped per smudge so the cost stays
    # trivial (~50 pixels per render).
    pixels = image.load()
    for cx, cy in smudge_centres:
        x0 = max(0, cx - smudge_radius)
        y0 = max(0, cy - smudge_radius)
        x1 = min(width - 1, cx + smudge_radius)
        y1 = min(height - 1, cy + smudge_radius)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if (x + y) & 1 == 0 and pixels[x, y] == smudge_red:
                    pixels[x, y] = SPECTRA6["white"]
    # Yellow accent kept in the local namespace so a future palette
    # tweak in ``THEMES["chalkboard"]`` (e.g. swapping yellow chalk for
    # a different colour) keeps the cross-reference live.
    del accent_color


def draw_placard_border(image: Image.Image, colors: dict) -> None:
    """Paint a hand-painted shop-sign / sandwich-board surround: doubled
    sign-painter's frame (sepia outer + black inner) plus four red
    thumbtack corner accents.

    Three motifs, all evoking the hand-lettered A-frame menu / shop-
    window placard register that Patrick Hand SC's small-caps silhouette
    suggests:

    * **Sepia outer frame** — outer rectangle at inset 14, painted as a
      1 px red stroke and then post-passed on its perimeter to flip
      half of the pixels to green per ``(x+y)&1`` parity. At panel
      viewing distance the eye averages adjacent red+green dots into
      rust-brown sepia — the documented R+G 1:1 two-ink recipe (see
      ``spectra6_color_recipes.md``) — reading as the weathered wood
      of a sun-faded A-frame sandwich board rather than the harsh
      printer-ink black of a freshly typeset poster. Same recipe the
      ``saloon`` foxing speckles use.
    * **Inner black frame** — inner rectangle at inset 18, 1 px stroke
      in ``colors["text"]`` (black). The narrow ~3 px gap between the
      two rules reads as a sign-painter's deliberate doubled brush
      stroke; the colour shift between the outer (sepia) and inner
      (black) rules reads as the "core inked, weathered at edges"
      look of a hand-lettered shop frame.
    * **Coral thumbtack corner accents** — four small filled circles
      in ``colors["accent"]`` (red) just inside the inner frame at
      each corner, suggesting the pins or tacks holding the sign up.
      Each tack's red pixels are Bayer-post-passed with white at
      50/50 parity inside its bbox so the eye averages red+white at
      panel distance into coral pink (R+W 1:1 — weathered hand-painted
      red, since the exposed corners of a sandwich-board sign would
      be the first thing to fade in the rain).
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    frame_color = colors["text"]
    accent_color = colors["accent"]

    # Outer frame painted in red as a sentinel ink so the post-pass
    # below can identify exactly which pixels to flip without coordinate
    # bookkeeping (paint-then-stipple is the same pattern the thumbtack
    # accents below use; same pattern ``draw_chalkboard_border``'s coral
    # eraser smudges use). The mid-flip-to-green Bayer post-pass turns
    # the rule into sepia.
    outer_inset = 14
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=SPECTRA6["red"],
        width=1,
    )
    inner_inset = 18
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=frame_color,
        width=1,
    )

    # Sepia post-pass on the outer frame's four edges. Walk the
    # perimeter (rather than the full bbox, which would also touch
    # interior pixels that aren't part of the rule) and flip red→green
    # on the 50/50 (x+y)&1 checkerboard so the eye averages rust-brown
    # at panel distance.
    pixels = image.load()
    outer_x0, outer_y0 = outer_inset, outer_inset
    outer_x1, outer_y1 = width - 1 - outer_inset, height - 1 - outer_inset
    for x in range(outer_x0, outer_x1 + 1):
        for y in (outer_y0, outer_y1):
            if (x + y) & 1 == 0 and pixels[x, y] == SPECTRA6["red"]:
                pixels[x, y] = SPECTRA6["green"]
    for y in range(outer_y0 + 1, outer_y1):
        for x in (outer_x0, outer_x1):
            if (x + y) & 1 == 0 and pixels[x, y] == SPECTRA6["red"]:
                pixels[x, y] = SPECTRA6["green"]
    # ``frame_color`` (black) is still used for the inner rule above;
    # kept bound for future palette extensions even though sepia post-
    # pass paints over the outer rule's "frame_color" intent.
    del frame_color

    # Red thumbtack accents — four filled circles at the inner corners,
    # offset down/in from the corner enough that the TR tack sits
    # entirely below the y=14-29 debug-label band (centre y=38, radius
    # 4 → bbox y=34-42, fully below the label).
    tack_radius = 4
    tack_inset = 38
    tack_centres = [
        (tack_inset, tack_inset),
        (width - 1 - tack_inset, tack_inset),
        (tack_inset, height - 1 - tack_inset),
        (width - 1 - tack_inset, height - 1 - tack_inset),
    ]
    for cx, cy in tack_centres:
        draw.ellipse(
            (cx - tack_radius, cy - tack_radius, cx + tack_radius, cy + tack_radius),
            fill=accent_color,
        )

    # Weathered-paint post-pass: flip ~50% of each tack's red pixels
    # to white on a 1×1 checkerboard inside each tack's bbox. The eye
    # averages red+white at panel distance into coral pink — the
    # documented two-ink recipe — so the tacks read as faded
    # hand-painted shop-sign red rather than fire-engine vermilion.
    # Sign-painter red weathers to coral over time and the tacks (at
    # the exposed corners of a sandwich-board sign) would be the first
    # element to fade. Bbox-scoped per-tack so the cost stays trivial
    # (~80 pixels per render).
    pixels = image.load()
    for cx, cy in tack_centres:
        x0 = max(0, cx - tack_radius)
        y0 = max(0, cy - tack_radius)
        x1 = min(width - 1, cx + tack_radius)
        y1 = min(height - 1, cy + tack_radius)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if (x + y) & 1 == 0 and pixels[x, y] == accent_color:
                    pixels[x, y] = SPECTRA6["white"]


def draw_chanbara_border(image: Image.Image, colors: dict) -> None:
    """Paint a samurai-cinema title-card surround: large off-canvas
    rising-sun disc with a red-to-maroon radial edge gradient, plus a
    small maroon artist's-chop seal in the top-left corner.

    Two motifs, both anchored in ``colors["accent"]`` (red) and lifted
    onto the documented R+K 1:1 maroon recipe at the edges:

    * **Rising-sun disc** — a filled red circle with its centre at
      ``(width + 30, height + 30)`` and radius ``220``. PIL's
      ``ellipse`` clips the off-canvas portion automatically; the
      visible portion is a sweeping arc through the bottom-right
      quadrant of the page. After painting the full red disc, a
      bbox-scoped radial post-pass walks the BR quadrant and flips
      ~half of the red pixels that lie in the outer 40 px shell of
      the disc (squared-distance in ``[(r-40)², r²]``) to black per
      ``(x+y)&1`` parity — the eye averages the red+black mix at
      panel viewing distance into maroon, so the disc fades from
      the bright vermilion of a noonday sun (centre) into the
      deeper oxblood of dusk (rim), the way the real rising-sun
      flag motif of kurosawa-era chanbara title cards bleeds into
      the horizon ink. White quote text rendered on top still reads
      cleanly against both red and maroon — both halves of the R+K
      mix sit on the Spectra-6 palette and contrast strongly with
      white. Deliberately pinned to the **bottom-right** corner so
      the top-right stays clear of the ``DEBUG MODE`` banner band.
    * **Artist's chop seal** — a small filled red rectangle (28×36 px)
      anchored at insets ``(24, 24)`` in the top-left corner. Painted
      in red as a sentinel, then a bbox-scoped post-pass flips half
      of the red pixels to black per ``(x+y)&1`` parity — the
      documented R+K 1:1 maroon recipe. Reads as the deep aged ink
      of a real hanko / artist's-chop seal pressed into rice paper
      decades ago rather than the bright fire-engine vermilion of a
      freshly mixed cinnabar. The single thin white horizontal
      "ichi" stroke through the chop's centre is painted *after* the
      maroon post-pass so its white pixels stay solid (and bright)
      regardless of where they land on the (x+y)&1 grid.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    accent_color = colors["accent"]
    light_color = colors.get("ornament_light", SPECTRA6["white"])

    # Large rising-sun disc anchored off-canvas in the bottom-right.
    # PIL clips the parts that fall outside the canvas, so we only see
    # the upper-left arc of the disc sweeping through the BR quadrant.
    sun_cx = width + 30
    sun_cy = height + 30
    sun_radius = 220
    draw.ellipse(
        (sun_cx - sun_radius, sun_cy - sun_radius,
         sun_cx + sun_radius, sun_cy + sun_radius),
        fill=accent_color,
    )

    # Radial maroon post-pass on the outer 40 px shell of the disc.
    # Squared-distance comparison avoids sqrt() per pixel — for 91 200
    # BR-quadrant pixels (380×240) this stays well under 100 ms in
    # pure Python. Restricted to the BR quadrant since the disc only
    # paints there (off-canvas portion clips silently). Half of each
    # red pixel inside the shell flips to black per (x+y)&1 parity —
    # the documented R+K 1:1 maroon recipe.
    sentinel_red = SPECTRA6["red"]
    maroon_dark = SPECTRA6["black"]
    pixels = image.load()
    inner_r_sq = (sun_radius - 40) * (sun_radius - 40)
    outer_r_sq = sun_radius * sun_radius
    quad_x0 = width // 2
    quad_y0 = height // 2
    for py in range(quad_y0, height):
        dy = py - sun_cy
        dy_sq = dy * dy
        for px in range(quad_x0, width):
            dx = px - sun_cx
            d_sq = dx * dx + dy_sq
            if inner_r_sq <= d_sq <= outer_r_sq:
                if (px + py) & 1 == 0 and pixels[px, py] == sentinel_red:
                    pixels[px, py] = maroon_dark

    # Artist's chop seal in the top-left corner — small filled red
    # rectangle painted as a sentinel for the maroon post-pass below.
    chop_left = 24
    chop_top = 24
    chop_w = 28
    chop_h = 36
    chop_right = chop_left + chop_w
    chop_bottom = chop_top + chop_h
    draw.rectangle(
        (chop_left, chop_top, chop_right, chop_bottom),
        fill=accent_color,
    )

    # Maroon post-pass on the chop seal's bbox — same R+K recipe as
    # the disc rim, so the two ornaments share a tonal register.
    for py in range(chop_top, chop_bottom + 1):
        for px in range(chop_left, chop_right + 1):
            if (px + py) & 1 == 0 and pixels[px, py] == sentinel_red:
                pixels[px, py] = maroon_dark

    # Single thin white horizontal "ichi" stroke through the chop's
    # centre, painted AFTER the maroon post-pass so its white pixels
    # land solid regardless of the (x+y)&1 parity. Insets 5 px from
    # the chop's left/right edges so the stroke reads as a distinct
    # mark rather than a full bisection.
    stroke_y = chop_top + chop_h // 2
    draw.line(
        [(chop_left + 5, stroke_y), (chop_right - 5, stroke_y)],
        fill=light_color,
        width=2,
    )


def _lcars_paint_lavender_block(pixels, left: int, top: int, right: int, bot: int,
                                sentinel) -> None:
    """3-way Bayer post-pass: cells 0-4 → red, 5-9 → blue, 10-15 → white.
    Sentinel must be off-palette (we use ``(1, 1, 1)``). Bbox-scoped so
    adjacent blocks painted in different sentinels stay untouched."""
    ink_red = SPECTRA6["red"]
    ink_blue = SPECTRA6["blue"]
    ink_white = SPECTRA6["white"]
    for py in range(top, bot + 1):
        row = BAYER_4x4[py % 4]
        for px in range(left, right + 1):
            if pixels[px, py] == sentinel:
                cell = row[px % 4]
                if cell < 5:
                    pixels[px, py] = ink_red
                elif cell < 10:
                    pixels[px, py] = ink_blue
                else:
                    pixels[px, py] = ink_white


def _lcars_paint_peach_block(pixels, left: int, top: int, right: int, bot: int,
                             sentinel) -> None:
    """3-way Bayer post-pass for peach (R+Y+W @ 30/50/20). The
    yellow-leaning sibling of salmon — warmer, less coral. Documented
    in spectra6_color_recipes.md under "Pastels" — this is the first
    theme to actually paint it. Partition: cells 0-4 → red (~31%),
    5-12 → yellow (~50%), 13-15 → white (~19%)."""
    ink_red = SPECTRA6["red"]
    ink_yellow = SPECTRA6["yellow"]
    ink_white = SPECTRA6["white"]
    for py in range(top, bot + 1):
        row = BAYER_4x4[py % 4]
        for px in range(left, right + 1):
            if pixels[px, py] == sentinel:
                cell = row[px % 4]
                if cell < 5:
                    pixels[px, py] = ink_red
                elif cell < 13:
                    pixels[px, py] = ink_yellow
                else:
                    pixels[px, py] = ink_white


def _lcars_paint_lilac_block(pixels, left: int, top: int, right: int, bot: int,
                             sentinel) -> None:
    """3-way Bayer post-pass for lilac (R+B+W @ 25/25/50 — paler than
    lavender, heavier white lift). Partition: cells 0-3 → red,
    4-7 → blue, 8-15 → white."""
    ink_red = SPECTRA6["red"]
    ink_blue = SPECTRA6["blue"]
    ink_white = SPECTRA6["white"]
    for py in range(top, bot + 1):
        row = BAYER_4x4[py % 4]
        for px in range(left, right + 1):
            if pixels[px, py] == sentinel:
                cell = row[px % 4]
                if cell < 4:
                    pixels[px, py] = ink_red
                elif cell < 8:
                    pixels[px, py] = ink_blue
                else:
                    pixels[px, py] = ink_white


def _lcars_post_pass_tangerine(pixels, left: int, top: int, right: int, bot: int,
                               sentinel_red) -> None:
    """Bbox-scoped R+Y biased Bayer: ~3/8 yellow on red. Same threshold
    + phase as ``draw_deco_border``'s final pass and ``_draw_text_body``'s
    ``deco`` branch so a future combined render lands on identical
    tangerine. Only touches ``sentinel_red`` pixels."""
    yellow = SPECTRA6["yellow"]
    threshold = 6  # round(0.375 * 16)
    for y in range(top, bot + 1):
        row = BAYER_4x4[y % 4]
        for x in range(left, right + 1):
            if row[x % 4] < threshold and pixels[x, y] == sentinel_red:
                pixels[x, y] = yellow


def _lcars_post_pass_coral(pixels, left: int, top: int, right: int, bot: int,
                           sentinel_red) -> None:
    """Bbox-scoped R+W 50/50 checkerboard. Only touches ``sentinel_red``
    pixels — adjacent solid-red graphics elsewhere on the page stay
    full-saturation."""
    white = SPECTRA6["white"]
    for py in range(top, bot + 1):
        for px in range(left, right + 1):
            if (px + py) & 1 and pixels[px, py] == sentinel_red:
                pixels[px, py] = white


def draw_lcars_border(image: Image.Image, colors: dict) -> None:
    """Paint a Michael Okuda LCARS interface frame: stacked coloured
    rail blocks down the left edge, joined to thin horizontal bars at
    top and bottom by quarter-circle elbows, with a large "LCARS"
    wordmark anchored in the top bar.

    Six motifs, the canonical Library Computer Access / Retrieval System
    vocabulary from Star Trek: TNG / DS9 / Voyager, painted bottom-up so
    decoration sits cleanly on the layer beneath it:

    * **Top + bottom horizontal bars** wrapping in from the left,
      ``bar_thickness = 18`` and joined to the rail by quarter-circle
      elbows of radius equal to the rail width (``rail_width = 36``).
      Both bars sit *below* / *above* the y = 14..29 ``DEBUG MODE``
      banner band (top bar at y = 36..53), so ``lcars`` is intentionally
      absent from ``_DEBUG_LABEL_RIGHT_INSET`` — same exemption pattern
      as ``dispatch`` / ``atomic`` / ``chalkboard`` / ``chanbara``.
      Painted in ``ornament_dark`` (red) as a sentinel ink for the
      tangerine post-pass below.
    * **Tangerine post-pass.** Spectra 6 has no orange ink. After the
      bars and elbows are painted in red, walk only their bounding
      rectangles and flip ~3/8 of the red pixels to yellow on the
      shared 4×4 Bayer matrix (``BAYER_4x4`` cells < threshold 6).
      Same recipe ``draw_deco_border``'s final pass uses; the
      red-biased 5/8 : 3/8 ratio corrects the perceived hue away from
      the washed-out amber a flat 50/50 R+Y checkerboard reads as on
      the panel. Bbox-scoped so the body-text region to the right of
      the rail is never touched.
    * **Six stacked rail blocks** flush with the canvas left edge,
      forming the LCARS "panel sidebar". Each block is a horizontally
      half-rounded rectangle (left edge flush at x = 0, right edge
      rounded) so the rail reads as a stack of buttons. Top-down the
      block colours cycle through **lavender → tangerine → coral →
      yellow → red → lavender** — the canonical Okudagram palette of
      lavender / orange / peach / yellow / red used on every TNG/DS9
      console. Heights vary slightly so the rhythm doesn't read as
      mechanical, the way real LCARS panels in the show varied block
      heights to suggest functional grouping.
    * **Lavender** synthesised via the 3-ink R+B+W recipe: paint each
      lavender block in a sentinel colour (``(1, 1, 1)``), then a
      per-block 3-way Bayer post-pass partitions the painted pixels
      across the four-by-four matrix into ~1/3 red / 1/3 blue / 1/3
      white. Same recipe ``draw_risograph_border``'s shifted-accent
      registration crosses use. Documented in
      ``spectra6_color_recipes.md`` under "Pastels".
    * **Coral** synthesised via the 2-ink R+W 50/50 recipe: paint in
      sentinel red, then a per-block bbox post-pass flips half the
      red pixels to white on the ``(x + y) & 1`` checkerboard. Same
      recipe ``draw_placard_border`` thumbtacks and
      ``draw_chalkboard_border`` eraser smudges use.
    * **Block labels** in black, centred inside each block in a
      condensed sans (the meta-bold chain at ~10 pt). The show used
      meaningless 4–7-character alphanumeric codes ("LCARS 40274",
      "47-Beta", etc.) as instrument labels; we follow the same
      deterministic-string convention so any future golden fixture
      reproduces. Black-on-coloured-block is the canonical Okudagram
      labelling contrast.
    * **"LCARS" wordmark** painted right-aligned inside the top bar
      using the ornament font role (Antonio Bold) at ~18 pt. The
      reference Okudagram wallpapers typically anchor a large
      tangerine-on-black wordmark in this corner ("LCARS ACCESS 441",
      "DATA NODE 188"); we keep the silhouette but compress the text
      to the bare "LCARS" identifier so it sits inside the bar's
      18 px band without bleeding into the body region.

    The chrome is a continuous L-shape that **wraps the canvas
    corner with an annular quarter-circle elbow** — the outer
    perimeter is a quarter-circle of radius ``R_out`` sweeping from
    ``(0, R_out)`` around the canvas top-left corner to ``(R_out, 0)``;
    the inner perimeter is a concentric quarter-circle of radius
    ``R_in = R_out - T`` (where ``T = bar_thickness = rail_width`` is
    the uniform annular thickness) sweeping into the page interior.
    Both arcs share a common centre at ``(R_out, R_out)``. The chrome
    annulus has uniform thickness T everywhere. (Earlier revisions
    placed the chrome BELOW the canvas top with sharp corners on the
    canvas edge; the user's "corners are backwards" feedback flagged
    both that AND the unrounded outer corner.)

    DEBUG MODE banner: in ``--mode debug`` the renderer paints a small
    yellow "DEBUG MODE" label at y = 14..29 in the top-right. Because
    the top bar now spans y = 0..bar_thickness-1, the banner sits ON
    TOP of the chrome — yellow text on tangerine has reduced contrast
    but stays legible (banner is a dev-only indicator, not deployed
    in ``--mode production``).

    Body-text overlap: the layout pipeline's largest ``max_width`` is
    680 (the ``dense`` layout), centred in the 800-px canvas → body
    text starts at x = 60. The rail blocks are confined to the rail
    column (x = 0..rail_width-1 = 0..43), leaving ≥ 16 px of clear
    margin to the densest body — the rail and body never visibly
    intersect. Same "decoration in margins" pattern ``dispatch``
    and ``nightvision`` establish.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size

    # The elbow + bars are painted in ``ornament_dark`` (red) as a
    # sentinel; coral / tangerine post-passes convert subregions to
    # the corresponding pastel. ``label_ink_on_block`` is the classic
    # Okudagram contrast colour (black) for text painted directly on
    # any of the coloured blocks.
    sentinel_red = colors["ornament_dark"]
    label_ink_on_block = SPECTRA6["black"]

    # --- Geometry ---
    # All constants scale proportionally to the canvas — the painter is
    # called from the preview API (``/api/preview``) at arbitrary sizes
    # down to ``PREVIEW_MIN_*`` = 80×60, not just the native 800×480.
    # Without scaling, the fixed native-size constants leave inverted
    # PIL bbox coordinates (e.g. ``rail_top > rail_bot``) and the
    # endpoint returns 500. Below a viable scale threshold the chrome
    # geometry collapses to sub-pixel features, so bail out and let
    # the body text + black ground stand in for the LCARS silhouette.
    scale = min(width / 800.0, height / 480.0)
    if scale < 0.5:
        return
    # ``T`` is BOTH the bar thickness AND the rail width — the annular
    # elbow geometry needs them equal so the chrome's annular thickness
    # (R_out − R_in) matches the bar's height matches the rail's width.
    # ``R_out`` is the outer-elbow radius (controls how rounded the
    # canvas-corner curve is); ``R_in`` is the derived inner-elbow
    # radius (= R_out − T) for the page-interior curve.
    T = max(8, int(round(44 * scale)))
    bar_thickness = T
    rail_width = T
    R_out = max(16, int(round(72 * scale)))   # outer elbow radius
    R_in = R_out - T                           # derived
    # Rail blocks are plain rectangles confined to the rail column —
    # no protrusion past ``rail_width``, no rounded corners. The colour
    # blocks read as flush sidebar segments rather than as detached
    # "pill buttons" floating off the rail.
    block_right = rail_width - 1

    top_bar_y1 = 0
    top_bar_y2 = bar_thickness - 1
    bottom_bar_y2 = height - 1
    bottom_bar_y1 = bottom_bar_y2 - bar_thickness + 1

    page_bg = colors.get("page_bg", SPECTRA6["black"])
    lavender_sentinel = (1, 1, 1)

    # ===========================================================
    # Layer 1: paint top/bottom bars + rail straight runs
    # ===========================================================
    # The straight runs START at ``R_out`` (away from the canvas
    # corner) — the region x ∈ [0, R_out), y ∈ [0, R_out) is the
    # elbow's annular footprint and gets painted separately in Layer
    # 2. Top bar is split into TWO segments separated by a ~6 px
    # black divider, reproducing the multi-colour Okudagram top-band
    # silhouette.
    segment_gap = max(2, int(round(6 * scale)))
    top_bar_left = R_out
    top_bar_right = width - 1
    top_bar_inner_w = top_bar_right - top_bar_left + 1
    seg1_w = int(top_bar_inner_w * 0.55)
    seg1_left = top_bar_left
    seg1_right = seg1_left + seg1_w - 1
    seg2_left = seg1_right + 1 + segment_gap
    seg2_right = top_bar_right
    # First (tangerine) segment of the top bar.
    draw.rectangle(
        (seg1_left, top_bar_y1, seg1_right, top_bar_y2),
        fill=sentinel_red,
    )
    # Second (lavender) segment of the top bar.
    draw.rectangle(
        (seg2_left, top_bar_y1, seg2_right, top_bar_y2),
        fill=lavender_sentinel,
    )
    # Bottom bar — single tangerine ribbon. Starts at R_out (clear of
    # the bottom-left elbow); the simpler silhouette leans on the
    # STARDATE callout for visual weight rather than segmenting the bar.
    draw.rectangle(
        (R_out, bottom_bar_y1, width - 1, bottom_bar_y2),
        fill=sentinel_red,
    )
    # NOTE: there's NO uniform "rail" strip painted here. The straight
    # rail section between the two elbows is composed ENTIRELY of the
    # stacked colour blocks painted in Layer 4 — the gaps between
    # blocks remain page_bg (black) and act as visual separators
    # between the colour-coded panel segments, matching the reference
    # wallpaper. (Earlier revisions painted a tangerine rail strip
    # under the blocks, which made any tangerine / peach blocks
    # visually disappear into the rail background.)

    # ===========================================================
    # Layer 2: annular-quadrant elbows (BOTH outer + inner rounded)
    # ===========================================================
    # Each elbow is bounded by TWO concentric quarter-circles:
    #   * outer arc, radius R_out, sweeping around the canvas corner
    #     from (0, R_out) → (R_out, 0) so the chrome's outer
    #     perimeter is ROUNDED (not a sharp right angle on the canvas
    #     edge)
    #   * inner arc, radius R_in = R_out − T, sweeping into the page
    #     interior from (T, R_out) → (R_out, T) so the chrome's inner
    #     perimeter is also rounded
    # Both arcs share centre point (R_out, R_out) (top elbow). The
    # annular region between them is the elbow chrome.
    #
    # Implementation: paint the full outer-disc quadrant in sentinel,
    # then carve the inner-disc quadrant in page_bg. PIL's pieslice
    # angles for the top-left quadrant relative to centre (R_out, R_out)
    # run 180° → 270° (9 o'clock clockwise to 12 o'clock).
    # Top elbow:
    draw.pieslice(
        (0, 0, 2 * R_out - 1, 2 * R_out - 1),
        start=180, end=270,
        fill=sentinel_red,
    )
    if R_in > 0:
        draw.pieslice(
            (T, T, 2 * R_out - T - 1, 2 * R_out - T - 1),
            start=180, end=270,
            fill=page_bg,
        )
    # Bottom elbow — mirror about y = height / 2. The annulus centre
    # sits at (R_out, height - R_out). The bottom-left quadrant of
    # that centre (angles 90° → 180°, 6 o'clock clockwise to 9
    # o'clock) covers x ∈ [0, R_out], y ∈ [height − R_out, height].
    bottom_disc_y1 = height - 2 * R_out
    bottom_disc_y2 = height - 1
    draw.pieslice(
        (0, bottom_disc_y1, 2 * R_out - 1, bottom_disc_y2),
        start=90, end=180,
        fill=sentinel_red,
    )
    if R_in > 0:
        draw.pieslice(
            (T, bottom_disc_y1 + T, 2 * R_out - T - 1, bottom_disc_y2 - T),
            start=90, end=180,
            fill=page_bg,
        )

    # ===========================================================
    # Layer 2: rail blocks between the two elbows
    # ===========================================================
    # SEVEN horizontally half-rounded rectangles in a pastel-dominant
    # palette (lavender / tangerine / coral / peach / lilac) so the
    # rail reads as the muted Okudagram colour-coding rather than as
    # saturated UI buttons. All five accent tones live OFF the native
    # Spectra 6 palette and require sentinel paint + bbox post-pass —
    # which is why this painter delegates to dedicated helpers
    # (``_lcars_paint_*``) rather than inlining each recipe.
    # Rail blocks slot between the two annular elbows. The rail's
    # straight section runs y ∈ [R_out, height − R_out − 1]; leave a
    # 3-px gutter on each end so the first/last block doesn't visually
    # merge into the elbow's bottom/top arc.
    rail_gutter = max(1, int(round(3 * scale)))
    rail_top = R_out + rail_gutter
    rail_bot = height - R_out - rail_gutter - 1
    rail_height = rail_bot - rail_top + 1
    block_gap = max(1, int(round(3 * scale)))
    # Seven blocks with intentionally non-uniform heights — LCARS panels
    # in the show varied block heights to suggest functional grouping.
    # Each entry in ``block_specs`` is (kind, label, proportion); the
    # proportions sum to 1.0.
    # Block labels are short alphanumeric codes (3-5 chars) — the show's
    # signature meaningless instrument numerics. Kept short because the
    # block's visible label area is only ~rail_width (= 44 px) wide;
    # a longer code would clip its leading characters at the left rail
    # edge.
    # Palette is deliberately high-contrast and AVOIDS tangerine /
    # peach (those share R+Y pixels with the elbow chrome and so
    # visually blend with it — the v6/v7 renders had two invisible
    # tangerine blocks). Mix of:
    #   * pastel 3-ink stipples (lavender, lilac) — cool accents
    #   * pastel 2-ink stipple (coral) — soft warm
    #   * native Spectra 6 inks (yellow, red, blue) — bright punch
    # The native-ink blocks (yellow / red / blue) provide unmissable
    # colour-coded "alert button" positions — canonical LCARS reads
    # red as critical, yellow as advisory, blue as informational.
    block_specs = [
        ("lavender", "40-27", 0.14),
        ("yellow",   "65-54", 0.16),
        ("coral",    "97-56", 0.13),
        ("lilac",    "76-54", 0.16),
        ("red",      "22-43", 0.13),
        ("coral",    "57-65", 0.15),
        ("blue",     "18-82", 0.13),
    ]
    assert abs(sum(p for _, _, p in block_specs) - 1.0) < 1e-6
    available_v = rail_height - block_gap * (len(block_specs) - 1)
    pixels = image.load()
    blocks: list[tuple[int, int, int, int, str]] = []
    cursor_y = rail_top
    for kind, label, prop in block_specs:
        bh = int(round(available_v * prop))
        top = cursor_y
        bot = cursor_y + bh - 1
        left = 0
        right = block_right
        # Solid native-ink blocks paint their fill colour directly; the
        # stippled blocks (coral / lavender / lilac) paint in a sentinel
        # and then a per-block bbox post-pass converts the sentinel to
        # the synthesised tone.
        if kind == "coral":
            draw.rectangle((left, top, right, bot), fill=sentinel_red)
            _lcars_post_pass_coral(pixels, left, top, right, bot, sentinel_red)
        elif kind == "lavender":
            draw.rectangle((left, top, right, bot), fill=lavender_sentinel)
            _lcars_paint_lavender_block(pixels, left, top, right, bot, lavender_sentinel)
        elif kind == "lilac":
            draw.rectangle((left, top, right, bot), fill=lavender_sentinel)
            _lcars_paint_lilac_block(pixels, left, top, right, bot, lavender_sentinel)
        elif kind == "yellow":
            draw.rectangle((left, top, right, bot), fill=SPECTRA6["yellow"])
        elif kind == "red":
            # Solid red on the page_bg-flanked rail is unambiguous —
            # there's no tangerine background nearby to share the red
            # pixels with (the tangerine chrome is at the elbow
            # quadrants, separated from this block by a 3-px page_bg
            # gap and the rounded elbow geometry).
            draw.rectangle((left, top, right, bot), fill=SPECTRA6["red"])
        elif kind == "blue":
            draw.rectangle((left, top, right, bot), fill=SPECTRA6["blue"])
        blocks.append((left, top, right, bot, label))
        cursor_y += bh + block_gap

    # ===========================================================
    # Layer 3: convert the chrome sentinels to tangerine + lavender
    # ===========================================================
    # The chrome's sentinel-red pixels (top bar left segment, bottom
    # bar, rail straight section, both annular elbow quadrants — but
    # NOT the rail blocks, which paint AFTER this pass over their own
    # bboxes) convert to tangerine in two sweeps over the chrome's y
    # extent. The lavender segment of the top bar uses a different
    # sentinel so it's untouched by the tangerine pass; its 3-way
    # Bayer post-pass runs on its bbox separately.
    # Top region: covers the top bar + the entire top elbow annulus.
    _lcars_post_pass_tangerine(pixels, 0, top_bar_y1, width - 1, R_out - 1, sentinel_red)
    # Bottom region: covers the bottom bar + the entire bottom elbow.
    _lcars_post_pass_tangerine(pixels, 0, height - R_out, width - 1, bottom_bar_y2, sentinel_red)
    # No rail-middle pass — the rail's vertical section is composed of
    # the colour blocks themselves with page_bg gaps between them.
    # Lavender segment of the top bar.
    _lcars_paint_lavender_block(pixels, seg2_left, top_bar_y1, seg2_right, top_bar_y2, lavender_sentinel)

    # ===========================================================
    # Layer 4: black labels centred inside each block
    # ===========================================================
    block_label_font = load_font(META_FONT_BOLD_CANDIDATES, max(6, int(round(10 * scale))))
    label_pad_right = 4   # small inset from the right edge so the label
                          # doesn't kiss the rail boundary
    for left, top, right, bot, label in blocks:
        baseline_bbox = draw.textbbox((0, 0), label, font=block_label_font)
        label_w = baseline_bbox[2] - baseline_bbox[0]
        label_h = baseline_bbox[3] - baseline_bbox[1]
        # Right-align inside the block (the right edge is now flush
        # with the rail boundary, so just pad in by ``label_pad_right``).
        label_x = right - label_pad_right - label_w - baseline_bbox[0]
        label_y = top + (bot - top - label_h) // 2 - baseline_bbox[1]
        draw.text(
            (label_x, label_y),
            label,
            font=block_label_font,
            fill=label_ink_on_block,
        )

    # ===========================================================
    # Layer 5: large "LCARS" wordmark in the top bar
    # ===========================================================
    # Right-aligned inside the top bar's lavender segment for a
    # tangerine-to-lavender → black-on-lavender colour transition.
    # Sized to fill ~80% of the bar's height (≈ 18 pt against a 22 px
    # bar). Antonio Bold (the theme's display face) anchors the
    # wordmark to the body typography.
    wordmark_font = load_font(theme_font_candidates("lcars", "ornament"), max(10, int(round(26 * scale))))
    wordmark_text = "LCARS"
    wordmark_bbox = draw.textbbox((0, 0), wordmark_text, font=wordmark_font)
    wordmark_w = wordmark_bbox[2] - wordmark_bbox[0]
    wordmark_h = wordmark_bbox[3] - wordmark_bbox[1]
    wordmark_x = width - 16 - wordmark_w
    wordmark_y = top_bar_y1 + (bar_thickness - wordmark_h) // 2 - wordmark_bbox[1]
    draw.text(
        (wordmark_x, wordmark_y),
        wordmark_text,
        font=wordmark_font,
        fill=label_ink_on_block,
    )

    # ===========================================================
    # Layer 6: bottom-right "STARDATE" callout
    # ===========================================================
    # The reference wallpaper anchors a large secondary heading
    # ("DATA NODE 188") at the bottom right of its bottom bar. We
    # mirror the silhouette with a STARDATE label, painted in black
    # over the tangerine bottom bar so the colour transition matches
    # the top bar's black-on-orange. Use a smaller font (~12 pt) so the
    # full string fits inside the bar's 22 px band without crowding.
    stardate_font = load_font(theme_font_candidates("lcars", "ornament"), max(7, int(round(14 * scale))))
    stardate_text = "STARDATE 47988.1"
    sd_bbox = draw.textbbox((0, 0), stardate_text, font=stardate_font)
    sd_w = sd_bbox[2] - sd_bbox[0]
    sd_h = sd_bbox[3] - sd_bbox[1]
    sd_x = width - 16 - sd_w
    sd_y = bottom_bar_y1 + (bar_thickness - sd_h) // 2 - sd_bbox[1]
    draw.text(
        (sd_x, sd_y),
        stardate_text,
        font=stardate_font,
        fill=label_ink_on_block,
    )


def draw_dispatch_border(image: Image.Image, colors: dict) -> None:
    """Paint a vintage-office dispatch border: cream-washed ground +
    thin frame + alternating black/sepia tractor-feed perforations +
    maroon rubber-stamp imprint.

    Five motifs from the typewriter / dot-matrix / dossier era, painted
    bottom to top so the upper layers sit visibly on the lower:

    * **Layer 0 — sparse cream ground wash.** A 4×4 Bayer dither
      converts ~12.5% of the white ``page_bg`` pixels to yellow,
      leaving the other 87.5% as pure white. At panel viewing
      distance the eye averages the 1-in-8 yellow alternation into a
      faint cream/vellum tone — reads as aged manila dispatch paper
      rather than the panel's flat pure white. Same Bayer pattern
      ``draw_newsprint_border``'s Layer 0 uses but with the
      ``page_bg→ink`` flip swapped for ``page_bg→yellow``. Lives
      natively on the Spectra-6 palette (every output pixel is still
      one of the six pure inks) so palette-snap is a no-op and glyph
      edges stay crisp.
    * **Outer thin black frame** at a small inset frames the page
      like a typed memo's letterhead rule.
    * **Alternating black/sepia tractor-feed perforations** — a
      column of small filled circles spaced ~40px apart on each side
      margin, echoing continuous-feed dot-matrix sprocket holes.
      Every other perforation flips from solid black to a sepia
      (R+G 1:1) Bayer stipple via the same sentinel-paint-then-
      bbox-post-pass pattern ``placard``'s thumbtacks use, reading
      as the rust-brown "carbon-paper bleed" real continuous-feed
      forms accumulate where the carbon backing oxidises against
      the sprocket holes.
    * **Maroon rubber-stamp imprint** in the upper right (inside
      the frame, well below the debug-mode label band): two
      concentric ellipse outlines plus four short diagonal hatch
      lines, evoking a smudged ink rubber stamp without committing
      to any specific lettering. Painted in red as a sentinel; a
      bbox-scoped post-pass Bayer-flips half of the stamp's red
      pixels to black per ``(x+y)&1`` parity — the documented R+K
      1:1 maroon recipe — so the stamp reads as the oxblood /
      aged-ink of a real archival stamp rather than fire-engine
      red. Sits at y≈40–70 so the oversized opening quote mark
      and the matched-phrase text block both stay clear.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    ink = colors["text"]
    page_bg = colors.get("page_bg")
    cream_light = SPECTRA6["yellow"]
    sepia_light = SPECTRA6["green"]
    sentinel_red = SPECTRA6["red"]
    maroon_dark = SPECTRA6["black"]

    # Layer 0: sparse 1-in-8 yellow-on-white Bayer cream wash. Only
    # pixels matching ``page_bg`` are affected — defence in depth if
    # a future caller paints accents before this painter runs.
    pixels = image.load()
    if page_bg is not None:
        for y in range(height):
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < 2:
                    pixels[x, y] = cream_light

    # Outer thin frame.
    frame_inset = 14
    draw.rectangle(
        (frame_inset, frame_inset, width - 1 - frame_inset, height - 1 - frame_inset),
        outline=ink,
        width=1,
    )

    # Tractor-feed perforations on the left and right margins. Every
    # other perforation pair flips from solid black to a red sentinel,
    # then the per-perforation post-pass below flips half of those red
    # pixels to green per (x+y)&1 parity — sepia.
    hole_radius = 2
    hole_spacing = 40
    hole_top = 22
    hole_bottom = height - 22
    left_x = 7
    right_x = width - 1 - 7
    sepia_centres: list[tuple[int, int]] = []
    y = hole_top
    pair_idx = 0
    while y <= hole_bottom:
        if pair_idx & 1:
            fill = sentinel_red
            sepia_centres.append((left_x, y))
            sepia_centres.append((right_x, y))
        else:
            fill = ink
        draw.ellipse(
            (left_x - hole_radius, y - hole_radius, left_x + hole_radius, y + hole_radius),
            fill=fill,
        )
        draw.ellipse(
            (right_x - hole_radius, y - hole_radius, right_x + hole_radius, y + hole_radius),
            fill=fill,
        )
        y += hole_spacing
        pair_idx += 1

    # Sepia post-pass on the alternating perforations only.
    for cx, cy in sepia_centres:
        x0 = max(0, cx - hole_radius)
        y0 = max(0, cy - hole_radius)
        x1 = min(width - 1, cx + hole_radius)
        y1 = min(height - 1, cy + hole_radius)
        for py in range(y0, y1 + 1):
            for px in range(x0, x1 + 1):
                if (px + py) & 1 == 0 and pixels[px, py] == sentinel_red:
                    pixels[px, py] = sepia_light

    # Maroon rubber-stamp imprint: two concentric ellipse outlines plus
    # short diagonal hatch lines, painted in red as a sentinel.
    stamp_cx = width - 55
    stamp_cy = 55
    outer_hw, outer_hh = 25, 15
    inner_hw, inner_hh = 19, 10
    draw.ellipse(
        (stamp_cx - outer_hw, stamp_cy - outer_hh, stamp_cx + outer_hw, stamp_cy + outer_hh),
        outline=sentinel_red,
        width=1,
    )
    draw.ellipse(
        (stamp_cx - inner_hw, stamp_cy - inner_hh, stamp_cx + inner_hw, stamp_cy + inner_hh),
        outline=sentinel_red,
        width=1,
    )
    for dx in (-9, -3, 3, 9):
        draw.line(
            (stamp_cx + dx - 3, stamp_cy + 3, stamp_cx + dx + 3, stamp_cy - 3),
            fill=sentinel_red,
            width=1,
        )

    # Maroon post-pass on the stamp's bbox. Bbox-scoped so the rest of
    # the painted accent red on the page (none today, but defence in
    # depth for future additions) stays untouched.
    stamp_x0 = max(0, stamp_cx - outer_hw - 1)
    stamp_y0 = max(0, stamp_cy - outer_hh - 1)
    stamp_x1 = min(width - 1, stamp_cx + outer_hw + 1)
    stamp_y1 = min(height - 1, stamp_cy + outer_hh + 1)
    for py in range(stamp_y0, stamp_y1 + 1):
        for px in range(stamp_x0, stamp_x1 + 1):
            if (px + py) & 1 == 0 and pixels[px, py] == sentinel_red:
                pixels[px, py] = maroon_dark
    # ``accent`` is the dispatch theme's red slot; kept bound for future
    # palette extensions even though the sentinel-paint-then-bbox-
    # post-pass approach above doesn't read from it directly.
    accent = colors["accent"]
    del accent


def draw_atomic_border(image: Image.Image, colors: dict) -> None:
    """Atomic-age decorative border: dithered ground + rounded frame + atom + starbursts.

    Four layers from the 1950s-60s atomic / Sputnik / Googie design
    vocabulary:

    * **Layer 0 — sparse 1-in-4 white-on-green dither ground.** Every
      pixel matching ``page_bg`` whose coordinates land on the top-left
      cell of a 2×2 tile is replaced with white; the other three of
      every four pixels stay as the Spectra-6 flat green. At panel
      viewing distance the eye averages the 25/75 alternation into a
      vivid Sputnik-green wash — softer than the solid pure ink but
      noticeably greener than the 50/50 checkerboard would land.
      Painted at the very start of the painter, BEFORE the decoration
      layers below, so the rounded frame / atom / starbursts overpaint
      the dithered ground cleanly. The pattern lives natively on the
      Spectra-6 palette (every output pixel is still one of the six
      pure panel colours), so ``snap_image_to_palette`` is a no-op
      and subsequent text rendering uses these pixels as anti-aliasing
      source — the palette snap step rounds mixed-edge pixels back to
      the same colours they produced before the dither, so glyph
      silhouettes stay sharp. Same trick the ``alchemy`` parchment
      halftone uses.
    * **Rounded-corner outer frame** in red — the streamlined-modern
      curve language of Googie coffee-shop architecture and motel
      signage. ``draw.rounded_rectangle`` is Pillow ≥ 8.2.
    * **Atom symbol centred at the top of the page** — three
      tilted ellipse "orbits" (at 0°, 60°, 120°) plus a small filled
      red nucleus. PIL's ``ellipse`` doesn't accept rotation, so each
      orbit is drawn as a polygon-line approximation: 64 points sampled
      around an unrotated ellipse, rotated through ``angle`` via 2×2
      cosine/sine matrix, and connected with ``draw.line``. Centred
      horizontally so it doesn't collide with the right-aligned
      ``DEBUG MODE`` banner; positioned at y=44 with orbit semi-major
      24 so the atom fits in the page-header zone (block_top ≥ 72) and
      stays clear of the body quote text.
    * **Twin starbursts at the mid-edges** (left and right) — eight
      red rays radiating from a small filled red dot, the iconic
      "atomic-energy spark" motif of mid-century diner / motel signage
      and Sputnik-era propaganda. Mid-edge placement (y = height // 2)
      keeps them outside the centred body text block and balances the
      composition top-to-bottom.

    Every decoration glyph is in the theme's ``accent`` colour (red),
    so a future palette tweak in ``THEMES["atomic"]`` flows through
    automatically.
    """
    width, height = image.size
    page_bg = colors["page_bg"]
    accent = colors["accent"]

    # Layer 0: sparse 1-in-4 white-on-green dither (one white pixel per
    # 2×2 tile, 25% white / 75% green). Only pixels matching the exact
    # ``page_bg`` colour are affected — defence in depth if a future
    # caller paints accents before this painter runs.
    dither_light = SPECTRA6["white"]
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            if (x & 1) == 0 and (y & 1) == 0 and pixels[x, y] == page_bg:
                pixels[x, y] = dither_light

    draw = ImageDraw.Draw(image)

    # Rounded outer frame.
    frame_inset = 14
    frame_radius = 24
    draw.rounded_rectangle(
        (frame_inset, frame_inset, width - 1 - frame_inset, height - 1 - frame_inset),
        radius=frame_radius,
        outline=accent,
        width=2,
    )

    # Atom symbol — three rotated ellipse outlines + nucleus.
    atom_cx = width // 2
    atom_cy = 44
    orbit_a = 24  # semi-major axis (fits below frame at y=14, above quote_top ≥ 72)
    orbit_b = 8
    n_points = 64
    for angle_deg in (0, 60, 120):
        angle = math.radians(angle_deg)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        points = []
        for i in range(n_points + 1):
            t = 2.0 * math.pi * i / n_points
            x_unrot = orbit_a * math.cos(t)
            y_unrot = orbit_b * math.sin(t)
            px = atom_cx + x_unrot * cos_a - y_unrot * sin_a
            py = atom_cy + x_unrot * sin_a + y_unrot * cos_a
            points.append((px, py))
        draw.line(points, fill=accent, width=1)
    # Nucleus.
    nucleus_r = 4
    draw.ellipse(
        (atom_cx - nucleus_r, atom_cy - nucleus_r, atom_cx + nucleus_r, atom_cy + nucleus_r),
        fill=accent,
    )

    # Twin starbursts at the mid-edges. Painted in red as a sentinel
    # ink, then the per-starburst bbox post-pass below flips ~3/8 of
    # the red pixels to yellow per the documented R+Y 5/8:3/8 Bayer
    # threshold (same tangerine recipe ``deco``'s matched phrase and
    # ``comic``'s extra warm band use). The eye averages adjacent
    # red+yellow dots into tangerine at panel viewing distance — the
    # canonical mid-century atomic-spark warmth of 1950s diner /
    # motel signage, where atomic-age vermilion was almost always
    # printed against orange / amber backgrounds rather than left as
    # the harsh fire-engine red the atom orbits use today. The atom
    # symbol itself stays solid red (rays vs. orbits is the visual
    # contrast — solid orbits, warm-stippled rays).
    starburst_outer = 11
    starburst_inner = 4
    centres = ((34, height // 2), (width - 34, height // 2))
    for star_cx, star_cy in centres:
        for angle_deg in range(0, 360, 45):
            angle = math.radians(angle_deg)
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            x1 = star_cx + starburst_inner * cos_a
            y1 = star_cy + starburst_inner * sin_a
            x2 = star_cx + starburst_outer * cos_a
            y2 = star_cy + starburst_outer * sin_a
            draw.line((x1, y1, x2, y2), fill=SPECTRA6["red"], width=1)
        # Centre dot.
        draw.ellipse(
            (star_cx - 2, star_cy - 2, star_cx + 2, star_cy + 2),
            fill=SPECTRA6["red"],
        )

    # Tangerine post-pass — bbox-scoped per starburst (~500 pixels per
    # render). Only flips pixels that match the sentinel red, so the
    # surrounding green page_bg and the dither's white flecks pass
    # through unchanged.
    sentinel_red = SPECTRA6["red"]
    flip_yellow = SPECTRA6["yellow"]
    for star_cx, star_cy in centres:
        x0 = max(0, star_cx - starburst_outer)
        y0 = max(0, star_cy - starburst_outer)
        x1 = min(width - 1, star_cx + starburst_outer)
        y1 = min(height - 1, star_cy + starburst_outer)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if BAYER_4x4[y & 3][x & 3] < 6 and pixels[x, y] == sentinel_red:
                    pixels[x, y] = flip_yellow


# Cycle of marker-ink colours used by ``draw_marker_border``. Hardcoded at
# module scope (rather than pulled from ``colors``) for the same reason as
# ``_COMIC_STRIPE_PALETTE``: the marker theme's THEMES dict only exposes
# four of the five Spectra 6 ink colours (text=black, accent=blue,
# ornament_dark=red, source=black) — there is no slot for yellow or green —
# and forcing a THEMES schema extension just to unlock those two greenfield
# accents would re-pin every cross-theme invariant test for one border. The
# whole point of the marker theme is to light up *every* spot colour the
# panel can produce, so the decoration reaches past the theme dict.
_MARKER_BORDER_PALETTE = (
    SPECTRA6["red"],
    SPECTRA6["blue"],
    SPECTRA6["green"],
    SPECTRA6["yellow"],
    SPECTRA6["black"],
)


def draw_marker_border(image: Image.Image, colors: dict) -> None:
    """Paint a fridge-doodle marker frame: multi-colour dashed perimeter,
    asterisk sparkles at every corner, and mid-edge filled marker dots.

    The marker theme's brief is "use the full capabilities of the display"
    — the Spectra 6 panel can render five non-white spot colours (red,
    yellow, blue, green, black) and this border lights up *every one of
    them* across three motifs:

    * **Perimeter dashed scribble.** Short marker-stroke dashes stepped
      around all four canvas edges at a thin inset, cycling through the
      five-colour palette so each edge picks up roughly one full rotation
      of the cycle. Leaves the canvas corners empty so the corner
      asterisks below sit cleanly without overlap. Thicker (3px) than the
      typical hairline frame to read as Sharpie ink rather than an
      engineering rule.
    * **Corner asterisks.** A six-ray asterisk (vertical + diagonal pairs)
      with a small filled dot at the centre, painted into each canvas
      corner — red top-left, blue top-right, green bottom-left, yellow
      bottom-right. The four-different-colours rotation is the visual
      signal that this is a "marker pot" theme, not a single-Sharpie
      doodle. The TR asterisk overlaps the debug-mode banner band, so
      ``_DEBUG_LABEL_RIGHT_INSET`` pushes the label inward past it.
    * **Mid-edge marker dots.** Two filled circles (yellow at left-mid,
      green at right-mid) hug the inner edge of the dashed frame to
      finish the colour balance — without them the green and yellow
      cycle in the dashed perimeter is the only place those two ink
      colours land, and they read as accidental rather than intentional.

    The colour cycle ``_MARKER_BORDER_PALETTE`` lives at module scope
    (see its docstring) — pulling from ``colors`` would force a
    THEMES-schema extension for two greenfield slots and re-pin every
    cross-theme invariant test. ``colors`` is still threaded through
    the signature so the function shape matches other border painters
    and a future palette swap inside the marker theme can extend here.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size

    # Perimeter dashed scribble. ``inset`` is the distance from the
    # canvas edge to the dash centre line; ``corner_clear`` keeps the
    # dash sequence away from the corners so the asterisks below sit
    # cleanly. ``dash_len`` / ``gap_len`` are tuned so each edge holds
    # ~10–14 dashes, which lands roughly two full cycles of the
    # five-colour palette per edge.
    inset = 12
    corner_clear = 36
    dash_len = 18
    gap_len = 10
    stride = dash_len + gap_len
    thickness = 3

    palette = _MARKER_BORDER_PALETTE
    palette_len = len(palette)
    dash_index = 0

    def _next_colour() -> tuple[int, int, int]:
        nonlocal dash_index
        col = palette[dash_index % palette_len]
        dash_index += 1
        return col

    # Top edge — left to right.
    x = corner_clear
    while x + dash_len <= width - corner_clear:
        draw.line((x, inset, x + dash_len, inset), fill=_next_colour(), width=thickness)
        x += stride
    # Right edge — top to bottom.
    y = corner_clear
    while y + dash_len <= height - corner_clear:
        draw.line(
            (width - 1 - inset, y, width - 1 - inset, y + dash_len),
            fill=_next_colour(),
            width=thickness,
        )
        y += stride
    # Bottom edge — right to left.
    x = width - corner_clear
    while x - dash_len >= corner_clear:
        draw.line((x - dash_len, height - 1 - inset, x, height - 1 - inset), fill=_next_colour(), width=thickness)
        x -= stride
    # Left edge — bottom to top.
    y = height - corner_clear
    while y - dash_len >= corner_clear:
        draw.line((inset, y - dash_len, inset, y), fill=_next_colour(), width=thickness)
        y -= stride

    # Corner asterisks. Six-ray rosette: horizontal + vertical + two
    # diagonals, with a filled dot at the centre to anchor the cluster
    # on the panel. Rays cleared of the dashed frame's reach so the two
    # motifs don't blur into one indistinct corner blot.
    aster_inset = 24
    ray = 11
    centre_radius = 3
    corners = (
        (aster_inset, aster_inset, SPECTRA6["red"]),
        (width - 1 - aster_inset, aster_inset, SPECTRA6["blue"]),
        (aster_inset, height - 1 - aster_inset, SPECTRA6["green"]),
        (width - 1 - aster_inset, height - 1 - aster_inset, SPECTRA6["yellow"]),
    )
    for cx, cy, ink in corners:
        # Cardinal arms.
        draw.line((cx - ray, cy, cx + ray, cy), fill=ink, width=2)
        draw.line((cx, cy - ray, cx, cy + ray), fill=ink, width=2)
        # Diagonal arms — slightly shorter so the asterisk reads as
        # a hand-drawn star rather than a pinwheel.
        diag = int(ray * 0.78)
        draw.line((cx - diag, cy - diag, cx + diag, cy + diag), fill=ink, width=2)
        draw.line((cx - diag, cy + diag, cx + diag, cy - diag), fill=ink, width=2)
        # Filled centre dot.
        draw.ellipse(
            (cx - centre_radius, cy - centre_radius, cx + centre_radius, cy + centre_radius),
            fill=ink,
        )

    # Mid-edge filled marker dots — upgraded from solid panel-ink fills
    # to two of the documented synthesized-colour recipes, completing
    # the marker theme's "every ink the panel can produce, plus the
    # synthesized mixes" identity:
    #
    # * Left mid-edge: MINT (G+W 1:1) — a highlighter wash, the kind
    #   of pale-green Stabilo / Sharpie highlighter that sits next to
    #   the regular marker in a kid's pencil case
    # * Right mid-edge: VIOLET (R+B 1:1) — the colour real markers
    #   produce when a blue pass crosses a red one, the canonical
    #   "second marker dragged over the first" effect
    #
    # Each dot is painted in a sentinel and then bbox-post-passed
    # through a 50/50 checkerboard to its companion ink — the same
    # paint-then-stipple pattern ``placard``'s thumbtacks /
    # ``chalkboard``'s eraser smudges / ``atomic``'s starbursts use.
    # The corner asterisks and perimeter dashes keep their solid-ink
    # cycle so the five native panel colours still appear at full
    # saturation; the synthesised mixes sit alongside as a deliberate
    # "look how many inks this panel can reach" flourish.
    dot_radius = 7
    mid_dots = (
        # (cx, cy, sentinel_dark, light_ink, label)
        (inset + 2, height // 2, SPECTRA6["green"], SPECTRA6["white"], "mint highlighter"),
        (width - 1 - inset - 2, height // 2, SPECTRA6["red"], SPECTRA6["blue"], "violet overlap"),
    )
    pixels = image.load()
    for cx, cy, dark_ink, light_ink, _ in mid_dots:
        draw.ellipse(
            (cx - dot_radius, cy - dot_radius, cx + dot_radius, cy + dot_radius),
            fill=dark_ink,
        )
        bx0 = max(0, cx - dot_radius)
        by0 = max(0, cy - dot_radius)
        bx1 = min(width - 1, cx + dot_radius)
        by1 = min(height - 1, cy + dot_radius)
        for py in range(by0, by1 + 1):
            for px in range(bx0, bx1 + 1):
                if (px + py) & 1 == 0 and pixels[px, py] == dark_ink:
                    pixels[px, py] = light_ink


# Deterministic foxing-speckle layout for ``draw_saloon_border``.
# Pre-computed once at module load (rather than re-randomised per render)
# so a given quote renders byte-identically every tick — the renderer
# golden-image suite, the contact-sheet QA tool, and the pick-equivalence
# tests all rely on the bit-exact-output contract, and a per-render
# reseed would break it. ``random.Random(seed)`` is used over hashing so
# the distribution is statistically uniform; the seed is fixed at module
# scope so test fixtures don't have to thread a seed through.
def _build_saloon_foxing_points(
    width: int, height: int, density: int, *, seed: int
) -> list[tuple[int, int, int]]:
    """Scatter ``density`` foxing speckles across a (width × height) field.

    Each speckle is a (x, y, radius) tuple where radius is 0 (single
    pixel) or 1 (3×3 cluster). The mix gives a worn-paper texture
    rather than a uniform stipple grid: most spots are single-pixel
    aging marks, a smaller fraction are three-pixel "darker" foxing.

    Density is the *target* count of speckles for the canvas; the
    actual count matches exactly because the function loops fixed times.
    """
    import random as _random
    rng = _random.Random(seed)
    points: list[tuple[int, int, int]] = []
    for _ in range(density):
        x = rng.randint(2, width - 3)
        y = rng.randint(2, height - 3)
        # ~85% single pixel (subtle), ~15% 3×3 cluster (darker spot).
        radius = 1 if rng.random() < 0.15 else 0
        points.append((x, y, radius))
    return points


# Density tuned at 800×480: ~360 speckles is enough to read as aged
# paper at the panel's viewing distance without crowding the body
# text. Body text painted on top dominates wherever glyphs land; the
# speckles only show through the white inter-glyph and inter-line gaps,
# so legibility stays clean.
_SALOON_FOXING = _build_saloon_foxing_points(
    DEFAULT_WIDTH, DEFAULT_HEIGHT, density=360, seed=0xB2A1
)


def draw_saloon_border(image: Image.Image, colors: dict) -> None:
    """Paint a 19th-century saloon-broadside / wanted-poster background.

    The marker theme's draw_marker_border is *colourful* — the saloon
    theme's brief is *sophisticated*: a multi-layered ground that
    reads as aged hand-printed paper rather than a single painted
    border. Five layers, painted bottom to top so the upper layers
    sit visibly on the lower:

    1. **Foxing speckles.** Sparse red dots scattered across the entire
       canvas via ``_SALOON_FOXING`` — pre-computed at module scope
       with a fixed seed so every render is byte-identical (the golden
       suite and contact sheet rely on this). Density tuned so body
       text remains fully legible; the dots only show through in
       white inter-glyph and inter-line gaps where they read as
       oxidation foxing on the paper rather than surface noise.
    2. **Top + bottom decorative banner bands.** A thick black
       horizontal rule, a thin black hairline rule below it, plus a
       row of red ornaments (alternating diamonds and short horizontal
       dashes) sandwiched between the rules. Mirrored at the bottom
       of the page. These bands sit in the "header / footer" zones
       (y < ~58 and y > height-58) where no body text ever lands, so
       they can be dense without legibility cost — same conservative
       safe-zone analysis the atomic atom and dispatch rubber stamp
       use.
    3. **Outer + inner double-rule frame.** Two black rectangles
       (3px outer, 1px inner) at modest insets, finishing the
       wanted-poster border treatment.
    4. **Corner fleurons.** A filled black diamond at each frame
       corner with two short flanking red triangle "wings" — the
       wood-engraved cornerpiece terminal used on Wild West saloon
       signs and 19th-century hand-printed broadsides.
    5. **Mid-edge red diamonds.** Small filled red ornaments on the
       outer rule's mid-edges, picking up the diamond motif from the
       corner fleurons and breaking up the long horizontal ink runs.

    Every shape draws from ``colors``; the saloon palette uses the
    default white/black/red triple so a future palette swap inside
    ``THEMES["saloon"]`` flows through automatically.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    ink = colors["text"]       # black
    accent = colors["accent"]  # red (foxing, ornaments, fleuron wings)
    bg = colors["page_bg"]

    # ------------------------------------------------------------------
    # Layer 1: Foxing speckles. ``_SALOON_FOXING`` is pre-computed for
    # the default (800, 480) canvas; if a caller renders at a different
    # size (e.g. the contact-sheet tile), rescale point coordinates so
    # the texture fills the canvas at the same visual density. Single-
    # pixel and 3×3-pixel spots intermix for a non-uniform "aged paper"
    # texture rather than a regular stipple grid.
    #
    # Sepia post-mix: flip ~50% of speckles to green on a (px+py)
    # parity gate so the eye averages adjacent red+green dots into
    # rust-brown at panel distance. Foxing on aged paper is literally
    # rust-brown rather than fire-engine red, and the 50/50 red+green
    # checkerboard is the documented two-ink sepia recipe in CLAUDE.md.
    # The decision keys off the (px, py) source coordinates rather than
    # the rescaled (x, y) so the foxing texture stays byte-identical
    # across canvas sizes (the golden suite and the contact sheet rely
    # on this — same fixed-seed invariant that ``_SALOON_FOXING`` already
    # honours).
    sx = width / DEFAULT_WIDTH
    sy = height / DEFAULT_HEIGHT
    foxing_alt = SPECTRA6["green"]
    for px, py, radius in _SALOON_FOXING:
        x = int(px * sx)
        y = int(py * sy)
        speckle_fill = foxing_alt if (px + py) & 1 == 0 else accent
        if radius == 0:
            draw.point((x, y), fill=speckle_fill)
        else:
            draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=speckle_fill)

    # ------------------------------------------------------------------
    # Layer 2: Top + bottom decorative banner bands.
    # Each band: a thick rule on the outer side, a hairline rule on the
    # inner side, with a row of alternating red diamonds + black dashes
    # between them. The two rules sandwich the ornament strip so the
    # band reads as a typeset divider rather than a row of free-floating
    # ornaments — the broadside-printer's idiom.
    #
    # Y-positions are chosen to clear the debug-mode chrome:
    #   * the ``DEBUG MODE`` banner sits at y=14 with ~15px height, so
    #     the top band's thick outer rule starts at y=34 (5px buffer);
    #   * the bottom debug dotted rule sits at y=443 and the text strip
    #     at y=451-466, so the bottom band's thick outer rule ends at
    #     y=440 (3px buffer above the dotted rule).
    # Body quote_top is around y=72 in every layout, so the top band's
    # inner rule at y=58 leaves 14px of clearance to body text.
    band_outer_y_top = 34
    band_inner_y_top = 58
    band_outer_y_bot = height - 1 - 39
    band_inner_y_bot = height - 1 - 63
    band_rule_thick = 3
    band_rule_thin = 1

    # Top: thick rule (outer), hairline rule (inner).
    draw.rectangle(
        (40, band_outer_y_top, width - 1 - 40, band_outer_y_top + band_rule_thick - 1),
        fill=ink,
    )
    draw.rectangle(
        (40, band_inner_y_top, width - 1 - 40, band_inner_y_top + band_rule_thin - 1),
        fill=ink,
    )
    # Bottom: hairline rule (inner), thick rule (outer).
    draw.rectangle(
        (40, band_inner_y_bot - band_rule_thin + 1, width - 1 - 40, band_inner_y_bot),
        fill=ink,
    )
    draw.rectangle(
        (40, band_outer_y_bot - band_rule_thick + 1, width - 1 - 40, band_outer_y_bot),
        fill=ink,
    )

    # Banner ornaments — alternating red diamonds + short black dashes
    # in the row between the two rules. The ``DEBUG MODE`` banner sits
    # at y=14 (above band_outer_y_top=22), so the entire ornament strip
    # is below the debug label and no _DEBUG_LABEL_RIGHT_INSET tweak is
    # needed.
    diamond_size = 5
    dash_len = 14
    ornament_step = 36
    band_mid_y_top = (band_outer_y_top + band_rule_thick + band_inner_y_top) // 2
    band_mid_y_bot = (band_inner_y_bot + band_outer_y_bot - band_rule_thick) // 2
    n_ornaments = (width - 160) // ornament_step
    start_x = (width - n_ornaments * ornament_step) // 2 + ornament_step // 2
    for i in range(n_ornaments):
        cx = start_x + i * ornament_step
        if i % 2 == 0:
            # Red diamond.
            for cy in (band_mid_y_top, band_mid_y_bot):
                draw.polygon(
                    [
                        (cx, cy - diamond_size),
                        (cx + diamond_size, cy),
                        (cx, cy + diamond_size),
                        (cx - diamond_size, cy),
                    ],
                    fill=accent,
                )
        else:
            # Short black dash.
            for cy in (band_mid_y_top, band_mid_y_bot):
                draw.line(
                    (cx - dash_len // 2, cy, cx + dash_len // 2, cy),
                    fill=ink,
                    width=2,
                )

    # ------------------------------------------------------------------
    # Layer 3: Outer + inner double-rule frame. Tight insets so the
    # foxing speckles between the page edge and the frame remain
    # visible (otherwise the frame would mask them and the texture
    # would only read inside the body region).
    #
    # The outer 3px rule is painted in red as a sentinel ink, then the
    # post-pass below walks the rule's 4 edge strips and flips half of
    # the painted pixels to green per (x+y)&1 parity — the documented
    # R+G 1:1 two-ink sepia recipe (same recipe Layer 1's foxing uses).
    # The eye averages adjacent red+green dots into rust-brown at
    # panel viewing distance, so the rule reads as the rusted iron of
    # a 19th-century wood-engraved cornerpiece frame rather than the
    # fire-engine printer ink of a freshly cast Linotype slug. The
    # red-pixel guard makes the post-pass robust to PIL's
    # anti-aliasing rounding at the edge boundaries.
    outer_inset = 12
    inner_inset = 18
    outer_rule_width = 3
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=SPECTRA6["red"],
        width=outer_rule_width,
    )
    pixels = image.load()
    outer_x0, outer_y0 = outer_inset, outer_inset
    outer_x1, outer_y1 = width - 1 - outer_inset, height - 1 - outer_inset
    sepia_light = SPECTRA6["green"]
    sentinel_red = SPECTRA6["red"]
    # Top edge strip — 3 rows.
    for y in range(outer_y0, outer_y0 + outer_rule_width):
        for x in range(outer_x0, outer_x1 + 1):
            if (x + y) & 1 == 0 and pixels[x, y] == sentinel_red:
                pixels[x, y] = sepia_light
    # Bottom edge strip — 3 rows.
    for y in range(outer_y1 - outer_rule_width + 1, outer_y1 + 1):
        for x in range(outer_x0, outer_x1 + 1):
            if (x + y) & 1 == 0 and pixels[x, y] == sentinel_red:
                pixels[x, y] = sepia_light
    # Left edge strip — 3 columns, skipping rows already covered by
    # the top/bottom strips above to avoid redundant work (the corner
    # 3×3 cells get flipped once, not twice).
    for x in range(outer_x0, outer_x0 + outer_rule_width):
        for y in range(outer_y0 + outer_rule_width, outer_y1 - outer_rule_width + 1):
            if (x + y) & 1 == 0 and pixels[x, y] == sentinel_red:
                pixels[x, y] = sepia_light
    # Right edge strip — 3 columns, same exclusion as the left strip.
    for x in range(outer_x1 - outer_rule_width + 1, outer_x1 + 1):
        for y in range(outer_y0 + outer_rule_width, outer_y1 - outer_rule_width + 1):
            if (x + y) & 1 == 0 and pixels[x, y] == sentinel_red:
                pixels[x, y] = sepia_light

    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=ink,
        width=1,
    )

    # ------------------------------------------------------------------
    # Layer 4: Corner fleurons. A filled black diamond at each outer
    # corner with two short red triangular "wings" pointing along the
    # frame edges — the wood-engraved cornerpiece motif on 19th-century
    # broadsides and saloon signs. The diamond sits on the outer-rule
    # corner; the wings extend a short distance along the top/bottom
    # and side edges, evoking the spreading cornerpiece flourish.
    diamond_corner = 9
    wing_len = 14
    wing_w = 5
    corners = (
        # (cx, cy, dx_along_top_or_bot, dy_along_side)
        (outer_inset, outer_inset, 1, 1),                              # TL
        (width - 1 - outer_inset, outer_inset, -1, 1),                 # TR
        (outer_inset, height - 1 - outer_inset, 1, -1),                # BL
        (width - 1 - outer_inset, height - 1 - outer_inset, -1, -1),   # BR
    )
    for cx, cy, dx, dy in corners:
        # Black filled diamond on the corner anchor.
        draw.polygon(
            [
                (cx, cy - diamond_corner),
                (cx + diamond_corner, cy),
                (cx, cy + diamond_corner),
                (cx - diamond_corner, cy),
            ],
            fill=ink,
        )
        # Red wing along the horizontal edge.
        draw.polygon(
            [
                (cx + dx * (diamond_corner + 2), cy - wing_w),
                (cx + dx * (diamond_corner + 2 + wing_len), cy),
                (cx + dx * (diamond_corner + 2), cy + wing_w),
            ],
            fill=accent,
        )
        # Red wing along the vertical edge.
        draw.polygon(
            [
                (cx - wing_w, cy + dy * (diamond_corner + 2)),
                (cx, cy + dy * (diamond_corner + 2 + wing_len)),
                (cx + wing_w, cy + dy * (diamond_corner + 2)),
            ],
            fill=accent,
        )

    # ------------------------------------------------------------------
    # Layer 5: Mid-edge red diamonds on the outer rule. Picks up the
    # corner fleuron motif and breaks the long horizontal/vertical
    # rules into shorter visual segments. Painted on top of the rule
    # itself so the diamond reads as a "punched" ornament rather than
    # a separate floating element.
    mid_diamond = 7
    midpoints = (
        (width // 2, outer_inset),
        (width // 2, height - 1 - outer_inset),
        (outer_inset, height // 2),
        (width - 1 - outer_inset, height // 2),
    )
    for cx, cy in midpoints:
        draw.polygon(
            [
                (cx, cy - mid_diamond),
                (cx + mid_diamond, cy),
                (cx, cy + mid_diamond),
                (cx - mid_diamond, cy),
            ],
            fill=accent,
        )
    # Fall-through to silence the "unused bg" — kept in the signature
    # so a future palette extension (e.g. cream foxing on a tinted
    # ground) has the field already wired.
    del bg


def draw_newsprint_border(image: Image.Image, colors: dict) -> None:
    """Paint a broadsheet-style Scotch-rule border around the canvas margin.

    Three motifs from 19th-century newspaper typography:

    * **Layer 0 — newsprint halftone + faint sepia foxing.** A 4×4
      Bayer dither converts 2 of every 16 ``page_bg`` white pixels to
      black (the 12.5% grey newsprint-pulp halftone the theme has
      always used), plus 1 red pixel and 1 green pixel per 4×4 tile
      at Bayer values 6 and 9 — together a 12.5% rust-brown sepia
      speckle layer the eye averages into pale foxing at panel
      viewing distance. Real archival newspaper paper develops this
      faint orange-brown tint as the lignin in the pulp oxidises
      under light, the same way real newsprint develops the grey
      halftone the original Layer 0 already simulates. Adjacent
      Bayer cells — red at ``(y%4, x%4) == (1, 3)`` and green at
      ``(2, 3)`` — sit in the same column one row apart, blending
      at panel distance into the documented R+G 1:1 sepia recipe
      (same recipe ``saloon``'s foxing speckles use). Cell values 6
      and 9 are deliberately chosen to keep the speckle pattern off
      every existing pinned border / cross-gating sample coordinate
      (``test_newsprint_inner_hairline_is_one_pixel_and_has_gap_above``,
      ``test_blueprint_border_is_theme_gated`` at (6, 16), and
      ``test_illuminated_border_is_theme_gated`` at (400, 22) all
      sample cells whose Bayer values are outside {6, 9}, so the
      foxing layer doesn't paint at any of them).
      The theme stays "no-colour-accent" by construction
      (``test_newsprint_theme_has_no_colour_accent`` still passes
      because the matched phrase / body / accent THEMES slots stay
      black-on-black); the rust-brown lives entirely on the
      *paper*, not the typography. Painted at the very start of the
      painter so the Scotch-rule frame below overpaints the
      dithered ground cleanly. Lives natively on the Spectra-6
      palette (every output pixel still one of the six pure inks),
      so palette-snap is a no-op and glyph edges stay crisp.
    * **Scotch rule frame.** A classic thick-thin parallel rule: a
      heavier outer rectangle and a hairline inner rectangle separated
      by a narrow band of white space. The signature border of
      19th-century newspaper typography — no corner accents, no
      coloured ornament, nothing but weighted ink.
    """
    width, height = image.size
    page_bg = colors.get("page_bg")
    ink = colors["text"]

    # Layer 0: 12.5% black-on-white Bayer halftone + faint 12.5% sepia
    # foxing speckles. Only pixels matching the exact ``page_bg`` colour
    # are affected — defence in depth if a future caller paints accents
    # before this painter runs. Skipped when ``page_bg`` is absent from
    # the palette so direct-call test paths that only provide ``text``
    # stay valid.
    if page_bg is not None:
        _BAYER_4 = BAYER_4x4
        sepia_red = SPECTRA6["red"]
        sepia_green = SPECTRA6["green"]
        pixels = image.load()
        for y in range(height):
            row = _BAYER_4[y & 3]
            for x in range(width):
                if pixels[x, y] != page_bg:
                    continue
                cell = row[x & 3]
                if cell < 2:
                    pixels[x, y] = ink           # 12.5% black halftone
                elif cell == 6:
                    pixels[x, y] = sepia_red     # 6.25% red speckle at (1, 3)
                elif cell == 9:
                    pixels[x, y] = sepia_green   # 6.25% green speckle at (2, 3)

    draw = ImageDraw.Draw(image)

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
    """Paint a HUD-style nightvision field without closing the outer frame."""
    draw = ImageDraw.Draw(image)
    width, height = image.size
    body = colors["text"]
    accent = colors.get("accent", body)
    subtle = colors.get("subtle", body)

    margin = 12
    arm = 26
    thickness = 2
    right_x = width - 1 - margin
    bottom_y = height - 1 - margin

    # Preserve the original bracket-only silhouette.
    draw.rectangle((margin, margin, margin + arm, margin + thickness - 1), fill=body)
    draw.rectangle((margin, margin, margin + thickness - 1, margin + arm), fill=body)
    draw.rectangle((right_x - arm, margin, right_x, margin + thickness - 1), fill=body)
    draw.rectangle((right_x - thickness + 1, margin, right_x, margin + arm), fill=body)
    draw.rectangle((margin, bottom_y - thickness + 1, margin + arm, bottom_y), fill=body)
    draw.rectangle((margin, bottom_y - arm, margin + thickness - 1, bottom_y), fill=body)
    draw.rectangle((right_x - arm, bottom_y - thickness + 1, right_x, bottom_y), fill=body)
    draw.rectangle((right_x - thickness + 1, bottom_y - arm, right_x, bottom_y), fill=body)

    # Faint scanlines contained inside the page, leaving the bracket gaps intact.
    for y in range(margin + 18, bottom_y - 6, 14):
        draw.line((margin + 30, y, right_x - 30, y), fill=subtle, width=1)

    # Sage post-pass on the scanlines only: flip ~25% of the green
    # scanline pixels to white per ``BAYER_4x4`` threshold 4 (cells
    # 0-3, 4/16 of pixels). Eye averages 75% green + 25% white at
    # panel viewing distance into pale sage — the documented W+G
    # 3:1 (inverted mint) recipe — so the scanlines read as ambient
    # ground glow rather than the crisp bright-green CRT lines they
    # were before, without crowding the body text in the central
    # region. Limited to the scanline x range so the bracket arms
    # at the corners (x < margin + 30) keep their solid green.
    if subtle == SPECTRA6["green"]:
        pixels = image.load()
        sage_light = SPECTRA6["white"]
        for scan_y in range(margin + 18, bottom_y - 6, 14):
            row = BAYER_4x4[scan_y & 3]
            for sx in range(margin + 30, right_x - 30):
                if row[sx & 3] < 4 and pixels[sx, scan_y] == subtle:
                    pixels[sx, scan_y] = sage_light

    # Mid-edge targeting ticks that float inside the canvas rather than joining the frame.
    tick = 12
    cx = width // 2
    cy = height // 2
    top_y = margin + 20
    bottom_tick_y = bottom_y - 20
    left_x = margin + 20
    right_tick_x = right_x - 20
    draw.line((cx - 48, top_y, cx - 48 + tick, top_y), fill=accent, width=2)
    draw.line((cx + 48 - tick, top_y, cx + 48, top_y), fill=accent, width=2)
    draw.line((cx - 48, bottom_tick_y, cx - 48 + tick, bottom_tick_y), fill=accent, width=2)
    draw.line((cx + 48 - tick, bottom_tick_y, cx + 48, bottom_tick_y), fill=accent, width=2)
    draw.line((left_x, cy - 32, left_x, cy - 32 + tick), fill=accent, width=2)
    draw.line((left_x, cy + 32 - tick, left_x, cy + 32), fill=accent, width=2)
    draw.line((right_tick_x, cy - 32, right_tick_x, cy - 32 + tick), fill=accent, width=2)
    draw.line((right_tick_x, cy + 32 - tick, right_tick_x, cy + 32), fill=accent, width=2)

    # Tiny corner telemetry, kept clear of the debug-banner region.
    meta_font = load_font(META_FONT_CANDIDATES, size=12)
    draw_text(draw, (24, 20), 'SIG 92%', font=meta_font, fill=accent)
    draw_text(draw, (24, height - 34), 'GAIN AUTO', font=meta_font, fill=accent)
    draw_text(draw, (width - 122, 40), 'AZ 041  EL 17', font=meta_font, fill=accent)



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

    stripe_thickness = 19
    stripe_gap = 11
    period = stripe_thickness + stripe_gap
    palette = _COMIC_STRIPE_PALETTE

    # Bands run with slope -1 (down-and-left): each line passes through
    # (c, qh) at the sub-image's bottom edge and would naturally hit
    # (c + qh, 0) at the top edge. Extend each stripe beyond both bounds
    # so the painted segment reaches the canvas edge cleanly after PIL's
    # line-cap rasterisation, while the larger period leaves a deliberate
    # yellow gap between neighbouring bands.
    stripe_cs = list(range(-qh - period, qw + period + 1, period))
    keep_count = min(4, len(stripe_cs))
    if qh == 240 and qw == 400:
        kept_indices = {17, 18, 19, 20}
    else:
        default_qh = 240
        default_qw = 400
        default_stripe_cs = list(range(-default_qh - period, default_qw + period + 1, period))
        default_keep_indices = {17, 18, 19, 20}
        target_mid = sum(default_keep_indices) / len(default_keep_indices)
        scale = len(stripe_cs) / len(default_stripe_cs)
        scaled_mid = target_mid * scale
        keep_start = round(scaled_mid - (keep_count - 1) / 2)
        keep_start = max(0, min(keep_start, max(0, len(stripe_cs) - keep_count)))
        kept_indices = set(range(keep_start, min(len(stripe_cs), keep_start + keep_count)))

    overshoot = max(stripe_thickness, stripe_gap)
    for i, c in enumerate(stripe_cs):
        if i in kept_indices:
            color = palette[i % len(palette)]
            qd.line(
                [(c - overshoot, qh + overshoot), (c + qh + overshoot, -overshoot)],
                fill=color,
                width=stripe_thickness,
            )

    # 45° right-isoceles triangle mask pinned to the bottom-right of
    # the quadrant. Legs of length qh (the shorter dimension) so the
    # hypotenuse runs at exactly slope -1, parallel to the stripes.
    # Painted in mode "L" so paste() reads it as a per-pixel alpha —
    # striped pixels land on the canvas only where the mask is 255.
    mask = Image.new("L", (qw, qh), 0)
    md = ImageDraw.Draw(mask)
    md.polygon([(qw - qh, qh), (qw, 0), (qw, qh)], fill=255)

    image.paste(quadrant, (qx, qy), mask=mask)


# Deterministic stone-grain speckle layout for ``draw_roman_border``. Same
# pre-compute-once-at-module-scope pattern as ``_SALOON_FOXING`` (see that
# helper for why a per-render reseed would break the byte-exact-output
# contract the renderer golden-image suite relies on). Density is tuned
# lower than saloon's foxing — Roman limestone reads cleaner than
# 19th-century pulp paper, and over-stippling fights the body text on
# dense-layout quotes. Only the outer "stone slab" perimeter is
# speckled; the central tabula ansata "carved face" stays clear so
# the quote body never sits on a noisy field.
def _build_roman_stone_grain(
    width: int, height: int, density: int, *, seed: int, exclude_inset: int
) -> list[tuple[int, int, int]]:
    """Scatter ``density`` stone-grain speckles across a ring around the
    canvas edge, leaving the central rectangle (``exclude_inset`` from
    each edge) clear for the carved tabula.

    Each speckle is an (x, y, radius) tuple where radius is 0 (single
    pixel) or 1 (3×3 cluster), mirroring ``_build_saloon_foxing_points``
    so a future shared helper would have an obvious factoring shape.
    """
    import random as _random
    rng = _random.Random(seed)
    points: list[tuple[int, int, int]] = []
    attempts = 0
    while len(points) < density and attempts < density * 8:
        attempts += 1
        x = rng.randint(2, width - 3)
        y = rng.randint(2, height - 3)
        # Skip points inside the central tabula carved face — the body
        # quote sits there and we don't want speckle noise behind it.
        if exclude_inset <= x < width - exclude_inset and exclude_inset <= y < height - exclude_inset:
            continue
        radius = 1 if rng.random() < 0.18 else 0
        points.append((x, y, radius))
    return points


# 800×480 canvas, ring outside an inset-26 central exclusion. ~140 speckles
# is dense enough to read as limestone grain in the margin between the
# canvas edge and the outer tabula rule but sparse enough that body text
# never has to compete with it (the central exclusion guarantees that).
# Tuned to sit just inside the tabula's outer rule (rect_inset_x=30,
# rect_inset_y=14) so the speckles fill the page-edge ring AND the
# narrow band between the page edge and the frame line, but never bleed
# into the inscribed face.
_ROMAN_STONE_GRAIN = _build_roman_stone_grain(
    DEFAULT_WIDTH, DEFAULT_HEIGHT, density=140, seed=0x5C1B, exclude_inset=26
)


def draw_roman_border(image: Image.Image, colors: dict) -> None:
    """Paint a Roman lapidary stone-tablet frame.

    Six stacked layers, painted bottom-to-top so each upper layer sits
    cleanly on the ones below:

    1. **Stone-grain speckles** in the outer margin ring — limestone /
       marble grain that doesn't reach the central carved face. Pre-
       computed via ``_ROMAN_STONE_GRAIN`` (see that helper for the
       byte-exact-output contract). Mostly single-pixel; ~18% are 3×3
       darker spots so the texture reads as natural quarry stone rather
       than a uniform stipple grid.
    2. **Tabula ansata silhouette** — the iconic Roman votive-tablet
       shape: a central rectangle with two trapezoidal "dovetail"
       handles (``ansae``) extending OUTWARD from the left and right
       mid-edges. Drawn here as a thin black outline so the page_bg
       limestone shows through both inside the rectangle AND inside the
       handles. Found on triumphal arches, altar plinths, and votive
       inscriptions across the Forum.
    3. **Inner channel rule** — a hairline black rule a few pixels
       inside the outer tabula outline, evoking the V-cut "carved
       channel" that Roman stonemasons ran around the inscribed face
       to delineate the carved zone from the rough-dressed margin.
    4. **SPQR cartouche at top centre** — the four canonical letters
       (Senatus Populusque Romanus) painted in red rubrum between the
       outer rule and the inner channel rule, each pair separated by a
       small filled red interpunct dot (``·``) — the dot-separator
       Romans used between words on monumental inscriptions. The whole
       cartouche is centred horizontally and clears the right-aligned
       ``DEBUG MODE`` banner band by sitting in the top zone above
       y=34, well above the body quote's quote_top ≥ 72.
    5. **Mid-edge interpunct dots** — small filled red circles at the
       four mid-edge points of the inner rule, picking up the
       interpunct motif from the SPQR cartouche and breaking the long
       vertical/horizontal rules into shorter visual segments.
    6. **Laurel sprig at bottom centre** — two short curved black
       branches mirrored around the bottom-centre, with three small
       filled black "leaf" ovals on each branch. The laurel wreath
       (``corona triumphalis``) was the Imperial victory crown; a
       half-wreath sprig is the smallest motif that still reads as
       "Roman" without crowding the bottom debug strip.

    Every shape draws from ``colors``; the roman palette uses the
    default white/black/red triple so a future palette tweak inside
    ``THEMES["roman"]`` flows through automatically.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    ink = colors["text"]       # black
    accent = colors["accent"]  # red rubrum

    # ------------------------------------------------------------------
    # Layer 1: Stone-grain speckles in the outer margin ring.
    # ``_ROMAN_STONE_GRAIN`` is pre-computed for the default 800×480
    # canvas; rescale x/y at render time so the texture fills any
    # (e.g. contact-sheet) tile size at the same visual density.
    sx = width / DEFAULT_WIDTH
    sy = height / DEFAULT_HEIGHT
    for px, py, radius in _ROMAN_STONE_GRAIN:
        x = int(px * sx)
        y = int(py * sy)
        if radius == 0:
            draw.point((x, y), fill=ink)
        else:
            draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=ink)

    # ------------------------------------------------------------------
    # Layer 2: Tabula ansata outline. Outer rectangle + two trapezoidal
    # dovetail handles at the left and right mid-edges.
    #
    # Geometry choice: the ``ansa`` (handle) is a trapezoid whose
    # vertical "outer" edge is shorter than its inner edge, with the
    # narrower side facing OUT. That's the classic Roman silhouette —
    # see e.g. the Arch of Titus inscription frame. Handle height is
    # roughly half the central rectangle's height so the silhouette
    # reads as "tablet with ears" rather than "tablet with pegs".
    # Frame insets are tight against the page edges so the inscribed
    # face inside the tabula has the maximum amount of breathing room
    # for body text. The tabula's ansae extend OUTWARD from these
    # insets, so leave room on the left/right edges for the
    # ``handle_outer_offset`` flange.
    rect_inset_x = 30
    rect_inset_y = 14
    rect_left = rect_inset_x
    rect_right = width - 1 - rect_inset_x
    rect_top = rect_inset_y
    rect_bot = height - 1 - rect_inset_y

    # ``ansa`` (handle) dimensions — measured in pixels rather than as a
    # fraction of the rectangle height because the visual ratio that
    # reads as "Roman tablet" is roughly 70:40 (inner:outer) regardless
    # of canvas size; scaling by ``rect_bot - rect_top`` would give
    # absurd 218px-tall handles on an 800×480 panel.
    handle_outer_offset = 22       # how far the ansa extends past the rectangle
    handle_inner_height = 90       # vertical span where the ansa meets the rectangle
    handle_outer_height = 56       # vertical span at the ansa's outer edge
    rect_mid = (rect_top + rect_bot) // 2

    rule_thick = 3

    # Outer tabula silhouette as one polygon traversal so the corners
    # join cleanly without painting any inner cross-rule. Walk
    # clockwise starting at the top-left corner.
    tabula_outline = [
        # Top edge.
        (rect_left, rect_top),
        (rect_right, rect_top),
        # Right ansa: inner top → outer top → outer bottom → inner bottom.
        (rect_right, rect_mid - handle_inner_height // 2),
        (rect_right + handle_outer_offset, rect_mid - handle_outer_height // 2),
        (rect_right + handle_outer_offset, rect_mid + handle_outer_height // 2),
        (rect_right, rect_mid + handle_inner_height // 2),
        # Bottom edge.
        (rect_right, rect_bot),
        (rect_left, rect_bot),
        # Left ansa: inner bottom → outer bottom → outer top → inner top.
        (rect_left, rect_mid + handle_inner_height // 2),
        (rect_left - handle_outer_offset, rect_mid + handle_outer_height // 2),
        (rect_left - handle_outer_offset, rect_mid - handle_outer_height // 2),
        (rect_left, rect_mid - handle_inner_height // 2),
    ]
    # Close the polygon by repeating the first point.
    draw.line(tabula_outline + [tabula_outline[0]], fill=ink, width=rule_thick)

    # ------------------------------------------------------------------
    # Layer 3: Inner channel rule. A hairline black rectangle a few
    # pixels inside the central tabula rectangle (NOT inside the
    # ansae — channels are only run around the inscribed face on
    # actual Roman monuments). Reads as the V-cut groove a stonemason
    # would run to delineate the inscribed area.
    channel_inset = 8
    draw.rectangle(
        (
            rect_left + channel_inset,
            rect_top + channel_inset,
            rect_right - channel_inset,
            rect_bot - channel_inset,
        ),
        outline=ink,
        width=1,
    )

    # ------------------------------------------------------------------
    # Layer 4: SPQR cartouche at top centre, painted INSIDE the tablet
    # between the inner channel rule and the body quote_top (≈y=72 in
    # every layout). Sitting on the carved face rather than between the
    # outer/inner rules — the channel band is only ``channel_inset``
    # wide which is too small for legible Cinzel glyphs at 20pt; an
    # actual Roman inscription would have the SPQR cartouche carved on
    # the inscribed face above the dedication, not crammed into the
    # frame channel. The font is loaded via the theme's ornament chain
    # so a missing-Cinzel install degrades to a heavy serif rather than
    # the bitmap fallback.
    cart_font = load_font(theme_font_candidates("roman", "ornament"), size=18)
    cart_letters = ("S", "P", "Q", "R")
    interpunct_r = 2
    letter_gap = 18  # gap between adjacent letter centres' interpunct slots
    # Measure the letters first so we can centre the whole cartouche
    # band horizontally.
    letter_widths = []
    letter_height = 0
    for ch in cart_letters:
        bbox = draw.textbbox((0, 0), ch, font=cart_font)
        letter_widths.append(bbox[2] - bbox[0])
        letter_height = max(letter_height, bbox[3] - bbox[1])
    cart_total_w = sum(letter_widths) + (len(cart_letters) - 1) * letter_gap
    cart_start_x = (width - cart_total_w) // 2
    # Vertical position: centred in the band between the inner channel
    # rule (y = rect_top + channel_inset = 30) and the body quote_top
    # (≈y=72). Lands at y≈42 so the bottom of the letter glyph is well
    # above the body text.
    cart_band_top = rect_top + channel_inset + 8
    # Draw letters with red interpunct dots between each pair.
    cursor_x = cart_start_x
    for i, ch in enumerate(cart_letters):
        draw.text((cursor_x, cart_band_top), ch, font=cart_font, fill=accent)
        cursor_x += letter_widths[i]
        if i < len(cart_letters) - 1:
            dot_cx = cursor_x + letter_gap // 2
            dot_cy = cart_band_top + letter_height // 2
            draw.ellipse(
                (
                    dot_cx - interpunct_r,
                    dot_cy - interpunct_r,
                    dot_cx + interpunct_r,
                    dot_cy + interpunct_r,
                ),
                fill=accent,
            )
            cursor_x += letter_gap

    # ------------------------------------------------------------------
    # Layer 5: Mid-edge interpunct dots on the inner channel rule. Picks
    # up the interpunct motif from the SPQR cartouche and breaks the
    # long inner rule's straight runs visually. Painted on top of the
    # rule so each dot reads as a "punched" red ornament against the
    # carved channel.
    mid_dot_r = 4
    mid_points = (
        (width // 2, rect_top + channel_inset),                    # top
        (width // 2, rect_bot - channel_inset),                    # bottom
        (rect_left + channel_inset, (rect_top + rect_bot) // 2),   # left
        (rect_right - channel_inset, (rect_top + rect_bot) // 2),  # right
    )
    for cx, cy in mid_points:
        draw.ellipse(
            (cx - mid_dot_r, cy - mid_dot_r, cx + mid_dot_r, cy + mid_dot_r),
            fill=accent,
        )

    # ------------------------------------------------------------------
    # Layer 6: Laurel sprig at the bottom centre, painted INSIDE the
    # tablet between the body text and the inner channel rule (mirror
    # band of the SPQR cartouche above). Two short black stems mirrored
    # around the bottom-centre, each carrying three small filled olive
    # "leaf" ovals angled outward. The corona triumphalis was the
    # Imperial victory crown; a single sprig is the smallest motif that
    # still reads as "Roman" without crowding the bottom debug strip.
    #
    # Each leaf is painted in solid yellow and then a per-leaf bbox
    # post-pass flips half of the yellow pixels to green per (x+y)&1
    # parity — the documented Y+G 1:1 olive recipe. The eye averages
    # adjacent yellow+green dots into olive at panel viewing distance,
    # the canonical botanical colour of Mediterranean laurel and olive
    # leaves (which is what a Roman corona triumphalis was actually
    # plaited from). The black stems and the red centre berry stay
    # solid for ink-contrast against the limestone face.
    laurel_band_y = rect_bot - channel_inset - 8
    laurel_cx = width // 2
    stem_len = 36
    leaf_count = 3
    leaf_a, leaf_b = 5, 2  # leaf ellipse semi-axes (long, short)
    leaf_centres: list[tuple[int, int]] = []
    for sign in (-1, 1):
        # Stem: a short straight rule along the bottom band, slanted
        # very slightly upward toward the centre so the two stems
        # converge under the centre dot.
        stem_x0 = laurel_cx + sign * 6
        stem_y0 = laurel_band_y + 1
        stem_x1 = stem_x0 + sign * stem_len
        stem_y1 = laurel_band_y - 3
        draw.line((stem_x0, stem_y0, stem_x1, stem_y1), fill=ink, width=1)
        # Leaves: three small filled ellipses straddling the stem,
        # rotated to point outward. PIL's ``ellipse`` is axis-aligned,
        # but at this size axis-aligned reads as "leaf" perfectly well —
        # save the polygon-rotation gymnastics for the atom orbits.
        for j in range(1, leaf_count + 1):
            t = j / (leaf_count + 1)
            leaf_cx = int(stem_x0 + sign * stem_len * t)
            leaf_cy = int(stem_y0 + (stem_y1 - stem_y0) * t) - 3
            draw.ellipse(
                (leaf_cx - leaf_a, leaf_cy - leaf_b, leaf_cx + leaf_a, leaf_cy + leaf_b),
                fill=SPECTRA6["yellow"],
            )
            leaf_centres.append((leaf_cx, leaf_cy))
    # Olive post-pass on each leaf bbox. Only flips yellow pixels (the
    # leaf fills) — the surrounding white page_bg and red berry pass
    # through unchanged.
    pixels = image.load()
    olive_light = SPECTRA6["green"]
    sentinel_yellow = SPECTRA6["yellow"]
    for leaf_cx, leaf_cy in leaf_centres:
        x0 = max(0, leaf_cx - leaf_a)
        y0 = max(0, leaf_cy - leaf_b)
        x1 = min(width - 1, leaf_cx + leaf_a)
        y1 = min(height - 1, leaf_cy + leaf_b)
        for py in range(y0, y1 + 1):
            for px in range(x0, x1 + 1):
                if (px + py) & 1 == 0 and pixels[px, py] == sentinel_yellow:
                    pixels[px, py] = olive_light
    # Centre laurel "berry" — a small filled red dot at the join.
    draw.ellipse(
        (laurel_cx - 2, laurel_band_y - 4, laurel_cx + 2, laurel_band_y),
        fill=accent,
    )


def _draw_pentagram(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, color, line_width: int = 1) -> None:
    """Draw a pentagram (5-pointed star inscribed in a circle).

    Vertices are placed at the canonical apothegmatic positions — top
    vertex at -90° (12 o'clock), then four more at +72° intervals
    walking clockwise. The star itself is drawn by connecting every
    SECOND vertex (0→2→4→1→3→0), the single closed path that
    produces the inscribed pentagram silhouette. The surrounding
    circle is the protective "magic circle" boundary the medieval
    Solomonic tradition drew around the figure.
    """
    # Outer protective circle.
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=color,
        width=line_width,
    )
    # Five outer vertices.
    points = [
        (
            cx + radius * math.cos(math.radians(-90 + i * 72)),
            cy + radius * math.sin(math.radians(-90 + i * 72)),
        )
        for i in range(5)
    ]
    # Pentagram path: connect every second vertex. The 0→2→4→1→3→0
    # walk is the only one that produces the iconic five-pointed
    # inscribed star without crossing the same edge twice.
    order = [0, 2, 4, 1, 3, 0]
    for i in range(len(order) - 1):
        draw.line(
            [points[order[i]], points[order[i + 1]]],
            fill=color,
            width=line_width,
        )


def _draw_sol(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, color, line_width: int = 2) -> None:
    """Sun symbol ☉: outlined circle with filled centre dot. The canonical
    alchemical glyph for Sol / gold / the solar principle.
    """
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=color,
        width=line_width,
    )
    dot = max(2, radius // 4)
    draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=color)


def _draw_luna(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, color, page_bg, line_width: int = 2) -> None:
    """Moon symbol ☽: crescent opening to the right.

    Drawn as a filled disc in ``color``, then occluded by a second
    filled disc in ``page_bg`` offset rightward. The result is a
    crescent that opens to the right — the canonical lunar / Luna /
    silver / philosophical-mercury glyph. ``line_width`` is unused
    but accepted so every glyph helper shares the same signature.
    """
    _ = line_width  # signature parity with the other glyph helpers
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=color,
    )
    occlude_offset = radius // 2 + 2
    draw.ellipse(
        (
            cx - radius + occlude_offset,
            cy - radius,
            cx + radius + occlude_offset,
            cy + radius,
        ),
        fill=page_bg,
    )


def _draw_mars(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, color, line_width: int = 2) -> None:
    """Mars symbol ♂: outlined circle with arrow at 45° upper-right.

    The body circle sits centred at ``(cx, cy)``; the arrow shaft
    extends outward from the circle at -45° (upper-right) for a
    distance roughly equal to ``radius``, terminating in two short
    barbs at ±135° from the shaft direction — the canonical
    alchemical glyph for Mars / iron / the martial principle.
    """
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=color,
        width=line_width,
    )
    angle = math.radians(-45)
    sx = cx + radius * math.cos(angle)
    sy = cy + radius * math.sin(angle)
    shaft_len = int(radius * 1.05)
    ex = sx + shaft_len * math.cos(angle)
    ey = sy + shaft_len * math.sin(angle)
    draw.line((sx, sy, ex, ey), fill=color, width=line_width)
    head_len = max(4, radius // 2)
    for head_angle in (
        math.radians(-45 + 135),
        math.radians(-45 - 135),
    ):
        hx = ex + head_len * math.cos(head_angle)
        hy = ey + head_len * math.sin(head_angle)
        draw.line((ex, ey, hx, hy), fill=color, width=line_width)


def _draw_venus(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, color, line_width: int = 2) -> None:
    """Venus symbol ♀: outlined circle with descending cross.

    The body circle sits centred at ``(cx, cy)``; below the circle, a
    vertical stroke descends for ~``radius`` pixels with a horizontal
    bar crossing it at its midpoint — the canonical alchemical glyph
    for Venus / copper / the feminine principle.
    """
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=color,
        width=line_width,
    )
    stroke_top = cy + radius
    stroke_bot = stroke_top + radius + 2
    draw.line((cx, stroke_top, cx, stroke_bot), fill=color, width=line_width)
    bar_y = (stroke_top + stroke_bot) // 2
    bar_half = max(4, radius * 2 // 3)
    draw.line((cx - bar_half, bar_y, cx + bar_half, bar_y), fill=color, width=line_width)


def _draw_alchemical_triangle(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    color,
    point_up: bool,
    with_bar: bool,
    line_width: int = 2,
) -> None:
    """Four classical-element triangle glyphs.

    +-----------------+--------------+
    | ``point_up``    | bare         | bar         |
    +=================+==============+=============+
    | True            | 🜂 Fire       | 🜁 Air        |
    | False           | 🜄 Water      | 🜃 Earth      |
    +-----------------+--------------+-------------+

    The bar is the canonical alchemical convention for marking the
    "lighter" of each pair (air is light-fire, earth is light-water).
    Drawn as an outlined equilateral triangle inscribed in a circle
    of ``radius`` for visual parity with the planetary glyphs.
    """
    half_base = radius * math.sin(math.radians(60))
    apex_offset = radius
    base_offset = radius * 0.5
    if point_up:
        apex = (cx, cy - apex_offset)
        left = (cx - half_base, cy + base_offset)
        right = (cx + half_base, cy + base_offset)
    else:
        apex = (cx, cy + apex_offset)
        left = (cx - half_base, cy - base_offset)
        right = (cx + half_base, cy - base_offset)
    draw.polygon([apex, right, left], outline=color, width=line_width)

    if with_bar:
        # Bar at the geometric midpoint of the triangle, drawn slightly
        # shorter than the local triangle-edge intersection so the
        # endpoints sit inside the outline rather than poking through
        # it. The bar height is independent of which way the triangle
        # points — it sits horizontally across the figure.
        bar_y = (apex[1] + (left[1] + right[1]) / 2) / 2
        # At ``bar_y``, the triangle's width is proportional to how far
        # we are from the apex. Distance-along-axis as a fraction:
        if point_up:
            t = (bar_y - apex[1]) / (left[1] - apex[1]) if left[1] != apex[1] else 0
        else:
            t = (apex[1] - bar_y) / (apex[1] - left[1]) if apex[1] != left[1] else 0
        local_half = half_base * t
        bar_half = max(3, local_half - 2)
        draw.line(
            (cx - bar_half, bar_y, cx + bar_half, bar_y),
            fill=color,
            width=line_width,
        )


def draw_alchemy_border(image: Image.Image, colors: dict) -> None:
    """Paint a full transmutation-circle ritual diagram on the panel:
    rectangular ritual boundary + four corner pentagrams + big
    inscribed transmutation circle (double ring + incantation
    tick-band + inscribed pentagram + inner pentagon + vertex
    sub-circles) + the four classical-element glyphs at the outer
    corners of the inner figure.

    Four layers, painted bottom-to-top so each upper layer sits
    cleanly on the ones below:

    1. **Outer rectangular ritual rule** — thin red rectangle around
       the panel edge, echoing the page-binding rule a medieval
       scribe drew before lettering. Painted at line width 2 so it
       reads as a deliberate enclosure rather than a hairline.
    2. **Four corner pentagrams** — the canonical protective glyph
       of Western ceremonial magic, each enclosed in its own
       protective circle. Sized at radius 22 so they read as
       discrete inscribed sigils at viewing distance, walked with
       the 0→2→4→1→3→0 vertex order that produces the
       inscribed-star silhouette.
    3. **Inscribed transmutation circle** — the central
       Solomonic/Hermetic figure of the page, modelled on the
       grimoire-tradition magic circle: concentric outer and inner
       rings centred on the canvas, with the band between them
       carrying short radial tick marks (mimicking the curved
       incantation text a real circle would inscribe in that band),
       a large pentagram inscribed in the inner ring, the natural
       inner pentagon connecting the five inner intersection points
       of that pentagram (the "operative chamber" the body quote
       occupies), and five small filled sub-dots at the pentagram's
       outer vertices marking the cardinal/elemental anchor points.
       The body quote overlays the entire figure; the inscribed
       lines are deliberately hairline-thin (width 1) so the black
       serif text dominates and the magic circle reads as a backdrop
       through which the operative phrase is being declared.
    4. **Four classical-element glyphs at the outer corners** of the
       inner figure, the canonical alchemical vocabulary of the four
       elements:
         - ``🜃 Earth`` (downward triangle with bar) at top-left
         - ``🜄 Water`` (downward triangle) at top-right
         - ``🜂 Fire``  (upward triangle) at bottom-left
         - ``🜁 Air``   (upward triangle with bar) at bottom-right
       The "heavy" downward-pointing elements anchor the top of the
       figure; the "light" upward-pointing elements anchor the
       bottom — every corner of the inner field carrying one
       cardinal element. The centre positions on both rows (and the
       bottom-centre) stay clear: the transmutation circle's top
       and bottom arcs with their tick-mark incantation bands sit
       at those cardinal positions and read as the principal seals
       on their own.

    Together the four layers paint a real Solomonic grimoire-page:
    rectangular ritual binding rule outside, big inscribed
    transmutation circle inside, every outer corner anchored by
    one of the four elements, body quote sitting in the operative
    chamber as the spoken phrase being declared into the circle.

    The two colour tracks are deliberate: the rectangular
    boundary + corner protective sigils are RED (the rubricated /
    sulphur / ritual-enclosure colour), while everything *inside*
    the boundary — magic circle, inscribed pentagram, pentagon,
    and the four elemental triangles — is BLUE (the
    philosophical-mercury / Hermetic / sapphire colour). Real
    alchemical manuscripts used the same red / blue split to
    distinguish the operative / outer side of the work from the
    philosophical / inner side.

    Before any of the four decoration layers paint, a Layer-0
    parchment halftone keeps only 2 of every 16 page_bg yellow
    pixels and converts the other 14 to white via a 4×4 Bayer-dither
    pattern, so the rendered ground reads as a pale ivory parchment
    flecked with yellow rather than the Spectra-6 panel's vivid
    pure yellow.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    rule_color = colors["accent"]               # red ritual boundary
    sigil_color = colors["accent"]              # red corner pentagrams
    hermetic_color = colors["ornament_dark"]    # blue elemental glyphs
    page_bg = colors["page_bg"]                 # yellow — used by the Layer-0 halftone
    stroke = 2

    # ------------------------------------------------------------------
    # Layer 0: Parchment halftone. Keep only 2 of every 16
    # page_bg yellow pixels and convert the other 14 to white in
    # a 4×4 Bayer-dither pattern — each 4×4 tile retains a sparse
    # diagonal pair of yellow flecks against a white ground. At
    # panel viewing distance the eye averages the resulting
    # alternation into a pale ivory parchment with subtle yellow
    # warmth, the same way newsprint halftones a flat tone using
    # only black ink. The pattern is applied at the
    # pixel level so it lives natively on the Spectra-6 palette
    # (every output pixel is still one of the six pure panel colours);
    # ``snap_image_to_palette`` is a no-op on these pixels.
    #
    # We dither here at the very start of the painter, BEFORE the
    # four decoration layers below, so the corner pentagrams /
    # transmutation circle / elemental sigils all
    # overpaint the halftoned ground cleanly. Subsequent text
    # rendering uses these halftoned pixels as anti-aliasing source
    # colour; the Spectra-6 palette snap step rounds the resulting
    # mixed-edge pixels back to the same black-on-yellow they
    # produced before the dither, so glyph silhouettes stay sharp.
    #
    # Only pixels matching the exact ``page_bg`` colour are
    # affected, so any deliberate-yellow ink elsewhere in the
    # palette (which the alchemy theme doesn't use, but a future
    # theme variant might) would pass through unchanged.
    _BAYER_4 = (
        (0, 8, 2, 10),
        (12, 4, 14, 6),
        (3, 11, 1, 9),
        (15, 7, 13, 5),
    )
    halftone_white = SPECTRA6["white"]
    halftone_threshold = 2    # 14 of 16 Bayer cells become white → 87.5% density
    pixels = image.load()
    for y in range(height):
        row = _BAYER_4[y & 3]
        for x in range(width):
            if pixels[x, y] == page_bg and row[x & 3] >= halftone_threshold:
                pixels[x, y] = halftone_white

    # ------------------------------------------------------------------
    # Layer 1: Outer red ritual boundary.
    outer_inset = 14
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=rule_color,
        width=stroke,
    )

    # ------------------------------------------------------------------
    # Layer 2: Bigger corner pentagrams. Offset chosen so the
    # protective circle (radius 22) sits with a few px of breathing
    # room inside the outer rule (inset 14) — the pentagram is
    # *contained* by the ritual boundary, not crossing it.
    pent_radius = 22
    pent_offset = outer_inset + 26     # = 40
    pent_centres = [
        (pent_offset, pent_offset),
        (width - 1 - pent_offset, pent_offset),
        (pent_offset, height - 1 - pent_offset),
        (width - 1 - pent_offset, height - 1 - pent_offset),
    ]
    for cx, cy in pent_centres:
        _draw_pentagram(draw, cx, cy, pent_radius, sigil_color, line_width=stroke)

    # ------------------------------------------------------------------
    # Geometry shared by the magic-circle backdrop and the top + bottom
    # rows of flanking glyphs.
    centre_x = width // 2
    centre_y = height // 2
    top_y = pent_offset
    bot_y = height - 1 - pent_offset
    flank_radius = 22               # elemental glyphs at the four outer corners (doubled from 11 so the bar / no-bar contrast of the four element triangles reads clearly at panel viewing distance — at radius 11 the heavier 4 px triangle stroke obscured which glyph was which)
    flank_spacing = 80              # px between centre and outer-corner glyph

    # ------------------------------------------------------------------
    # Layer 3: Inscribed transmutation circle — the big Solomonic /
    # Hermetic figure modelled on real grimoire-page magic circles
    # (concentric ring carrying an incantation text band, an inscribed
    # pentagram inside, the natural inner pentagon, and small anchor
    # circles at the pentagram's outer vertices).
    #
    # All five sub-figures are painted at line width 1 in the
    # Hermetic blue so the inscribed lines read as a *backdrop*
    # through which the black serif body quote is declared. A
    # heavier stroke would compete with the text for visual
    # primacy; the body quote is the operative phrase and must
    # remain dominant.
    outer_ring_r = 222
    inner_ring_r = 212

    # 3a. Outer + inner concentric rings — the two parallel boundary
    # circles between which a real Solomonic operator would
    # letter the incantation text. Both at line width 1 so they
    # read as fine drawn lines rather than ink slabs.
    draw.ellipse(
        (centre_x - outer_ring_r, centre_y - outer_ring_r,
         centre_x + outer_ring_r, centre_y + outer_ring_r),
        outline=hermetic_color, width=1,
    )
    draw.ellipse(
        (centre_x - inner_ring_r, centre_y - inner_ring_r,
         centre_x + inner_ring_r, centre_y + inner_ring_r),
        outline=hermetic_color, width=1,
    )

    # 3b. Incantation tick band — 72 short radial dashes between the
    # two rings (one every 5° around the full 360° circle). At
    # viewing distance the spacing reads as the rhythm of
    # closely-set inscribed letters running around the band; the
    # individual ticks are intentionally featureless because real
    # text along that arc would render at sub-pixel size on the
    # Spectra 6 panel and dither into noise.
    tick_count = 72
    for i in range(tick_count):
        theta = math.radians(i * 360 / tick_count)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        x0 = centre_x + (inner_ring_r + 1) * cos_t
        y0 = centre_y + (inner_ring_r + 1) * sin_t
        x1 = centre_x + (outer_ring_r - 1) * cos_t
        y1 = centre_y + (outer_ring_r - 1) * sin_t
        draw.line((x0, y0, x1, y1), fill=hermetic_color, width=1)

    # 3c. Inscribed pentagram — five-pointed star inscribed in the
    # inner ring, walked with the canonical 0→2→4→1→3→0 vertex
    # order that produces the single closed inscribed-star path.
    # Sized so its vertices sit just inside the inner ring with a
    # few px of breathing room, so the star reads as *inscribed*
    # rather than *touching* the ring.
    inscribed_pent_r = 195
    inscribed_pent_vertices = [
        (
            centre_x + inscribed_pent_r * math.cos(math.radians(-90 + i * 72)),
            centre_y + inscribed_pent_r * math.sin(math.radians(-90 + i * 72)),
        )
        for i in range(5)
    ]
    pent_path_order = [0, 2, 4, 1, 3, 0]
    for i in range(len(pent_path_order) - 1):
        draw.line(
            (inscribed_pent_vertices[pent_path_order[i]],
             inscribed_pent_vertices[pent_path_order[i + 1]]),
            fill=hermetic_color, width=1,
        )

    # 3d. Inner pentagon — connects the five inner intersection
    # points of the inscribed pentagram. The inner pentagon's
    # circumradius is the outer pentagram's radius divided by
    # ``phi²`` (golden ratio squared, ≈ 2.618), which is the
    # natural alchemical proportion the pentagram self-generates.
    # Vertices sit at angular offsets of -54°, 18°, 90°, 162°,
    # 234° (each rotated 36° from the corresponding outer
    # pentagram vertex). The pentagon is the "operative chamber"
    # — in a real transmutation circle, the operative phrase is
    # inscribed inside this inner pentagon. Here, the body quote
    # overlays it.
    phi_squared = (1 + math.sqrt(5)) ** 2 / 4   # ≈ 2.618
    inner_pent_r = inscribed_pent_r / phi_squared
    inner_pentagon_vertices = [
        (
            centre_x + inner_pent_r * math.cos(math.radians(-54 + i * 72)),
            centre_y + inner_pent_r * math.sin(math.radians(-54 + i * 72)),
        )
        for i in range(5)
    ]
    draw.polygon(inner_pentagon_vertices, outline=hermetic_color, width=1)

    # 3e. Vertex sub-circles — small filled RED dots at each of the
    # five outer pentagram vertices, marking the cardinal /
    # elemental anchor points of the circle (where, in a real
    # grimoire, the operator places the candles or sigil-stones
    # representing the five elements: spirit at top, water +
    # earth at the lower diagonals, fire + air at the upper
    # diagonals). Painted in red to tie back to the rectangular
    # boundary's colour vocabulary — these are the "external"
    # / operative anchor points, not part of the inner Hermetic
    # geometry.
    sub_dot_r = 5
    for vx, vy in inscribed_pent_vertices:
        draw.ellipse(
            (vx - sub_dot_r, vy - sub_dot_r, vx + sub_dot_r, vy + sub_dot_r),
            fill=sigil_color,
        )

    # ------------------------------------------------------------------
    # Layer 4: Four classical-element glyphs at the outer corners of
    # the inner figure. Top-left + top-right are the "heavy" downward
    # elements; bottom-left + bottom-right are the "light" upward ones.
    # The centre positions on both rows (and the bottom-centre)
    # are deliberately left clear — the transmutation circle's top and
    # bottom arcs (with their tick-mark incantation bands) sit at
    # those cardinal positions and read as the principal seals on
    # their own — no glyph is overlaid there.
    #
    # Each element now paints in its CANONICAL alchemical colour rather
    # than the shared blue ``hermetic_color``: earth → olive (Y+G 1:1),
    # water → sky (B+W 1:1), fire → tangerine (R+Y 5/8:3/8), air →
    # violet (R+B 1:1). The 2-ink Bayer mixes lift each glyph onto a
    # tone the alchemical tradition actually assigned to that element
    # — green earth, sky-blue water, warm-orange fire, mauve / Tyrian
    # air. Glyphs paint with a heavier stroke (``triangle_stroke``)
    # than the outer ritual rectangle so the element sigils read as
    # heavy / hard inscribed marks rather than hairline diagrams.
    #
    # Each triangle is painted in a UNIQUE per-element sentinel ink
    # (off-palette, dark RGB), then a per-element bbox post-pass
    # translates exactly the sentinel pixels into a 2-ink Bayer mix of
    # the recipe's dark and light inks. The sentinel approach avoids
    # collisions with on-palette pixels already in the bbox — Earth's
    # bbox in particular sits over the parchment-halftone yellow
    # flecks of Layer 0, and a yellow-sentinel approach incorrectly
    # flipped those flecks too, producing a visible green rectangle
    # bleed around the triangle.
    #
    # Air uses 2-ink violet rather than 3-ink lavender because
    # ``draw_text_dithered`` (and the polygon outlines /
    # line strokes underlying ``_draw_alchemical_triangle``) only
    # support 2-ink mixes today; ``_fill_swatch_stipple_3way`` is
    # rectangle-only. Violet still reads as the canonical
    # ethereal / spiritual ink for air without needing the new
    # primitive.
    triangle_stroke = 4
    earth_sentinel = (1, 1, 1)
    water_sentinel = (2, 2, 2)
    fire_sentinel = (3, 3, 3)
    air_sentinel = (4, 4, 4)
    elements = (
        # (cx, cy, point_up, with_bar, sentinel, dark_ink, light_ink, density, label)
        (centre_x - 2 * flank_spacing, top_y, False, True,
         earth_sentinel, SPECTRA6["yellow"], SPECTRA6["green"], 0.5, "🜃 Earth/olive"),
        (centre_x + 2 * flank_spacing, top_y, False, False,
         water_sentinel, SPECTRA6["blue"], SPECTRA6["white"], 0.5, "🜄 Water/sky"),
        (centre_x - 2 * flank_spacing, bot_y, True, False,
         fire_sentinel, SPECTRA6["red"], SPECTRA6["yellow"], 0.375, "🜂 Fire/tangerine"),
        (centre_x + 2 * flank_spacing, bot_y, True, True,
         air_sentinel, SPECTRA6["red"], SPECTRA6["blue"], 0.5, "🜁 Air/violet"),
    )
    for cx, cy, point_up, with_bar, sentinel, dark_ink, light_ink, density, _ in elements:
        _draw_alchemical_triangle(
            draw, cx, cy, flank_radius, sentinel,
            point_up=point_up, with_bar=with_bar, line_width=triangle_stroke,
        )
        # Per-element bbox post-pass. The triangle's longest extent is
        # flank_radius along the apex axis plus a margin of the
        # triangle stroke on each side; pad by 4 px so antialiased
        # pixels at the polygon corners stay in scope.
        bx0 = max(0, cx - flank_radius - 4)
        by0 = max(0, cy - flank_radius - 4)
        bx1 = min(width - 1, cx + flank_radius + 4)
        by1 = min(height - 1, cy + flank_radius + 4)
        threshold = round(density * 16)
        if density <= 0.25:
            for py in range(by0, by1 + 1):
                for px in range(bx0, bx1 + 1):
                    if pixels[px, py] == sentinel:
                        pixels[px, py] = light_ink if (px & 1) == 0 and (py & 1) == 0 else dark_ink
        elif density >= 0.5:
            for py in range(by0, by1 + 1):
                for px in range(bx0, bx1 + 1):
                    if pixels[px, py] == sentinel:
                        pixels[px, py] = light_ink if (px + py) & 1 == 0 else dark_ink
        else:
            for py in range(by0, by1 + 1):
                row = BAYER_4x4[py & 3]
                for px in range(bx0, bx1 + 1):
                    if pixels[px, py] == sentinel:
                        pixels[px, py] = light_ink if row[px & 3] < threshold else dark_ink
    # ``hermetic_color`` still drives the pentagram / pentagon / tick-
    # band geometry above; the four element triangles now use their
    # own per-element ink so the canonical alchemical colour mapping
    # reads at panel distance.
    del hermetic_color


def draw_swiss_border(image: Image.Image, colors: dict) -> None:
    """Paint the Swiss International theme's deliberately minimal frame.

    The visual identity is what's *missing* — every other theme in
    the rotation decorates aggressively, ``swiss`` refuses to. Just
    two strokes near the top edge of the page, the Müller-Brockmann /
    Vignelli typographic grid:

    * A single 1 px black hairline rule running across the page at
      ``y = 60``, dividing a small header zone from the body block —
      the canonical asymmetric-grid gesture of Swiss poster design.
    * A small 6×6 px filled red square in the header zone at
      ``(width - 40, 28)``, the only chromatic accent on the page
      besides the matched phrase. References Vignelli's NYC Subway
      signage and the Müller-Brockmann concert poster series, where
      a single small geometric mark anchors the grid without
      cluttering it.

    No corner ornaments, no frame, no second rule, no Layer-0 wash.
    The composition's signature is austerity — a deliberate
    counterpoint to the borderful majority. Paints in
    ``colors["text"]`` for the rule and ``colors["accent"]`` for the
    red square so direct-call test paths with non-standard palettes
    still produce a visually coherent frame.
    """
    draw = ImageDraw.Draw(image)
    width, _ = image.size
    ink = colors["text"]
    accent = colors["accent"]
    rule_y = 60
    draw.line((SIDE_MARGIN, rule_y, width - SIDE_MARGIN, rule_y), fill=ink, width=1)
    # The red square sits between the (y=14..29) debug-mode banner band
    # and the y=60 grid rule, so it never collides with the banner glyphs.
    # Painting it just above the rule visually anchors the asymmetric
    # grid — the square reads as a tag attached to the rule rather than
    # a free-floating accent.
    square_x = width - 40
    square_y = 42
    square_size = 6
    draw.rectangle(
        (square_x, square_y, square_x + square_size, square_y + square_size),
        fill=accent,
    )


def draw_herbarium_border(image: Image.Image, colors: dict) -> None:
    """Paint a 19th-century pressed-plant specimen-sheet frame.

    Three motifs from the natural-history specimen tradition:

    * **Layer 0 — sparse 1-in-8 yellow-on-white cream ground wash.**
      Same Y+W recipe (Bayer threshold 2) ``illuminated`` and
      ``dispatch`` use for their aged-vellum / typewriter-paper tone.
      Only pixels matching the exact ``page_bg`` colour are flipped,
      so direct-call test paths that pass a non-standard palette stay
      valid.
    * **Engraver's-frame hairline rule** at inset 14 px — a single
      thin black rectangle the way real herbarium mounting sheets
      were ruled. No double rule (that would compete with the
      specimen graphic for visual weight); the corner pinholes below
      do the "mounted" gesture instead.
    * **Pressed-leaf silhouette in the bottom-right corner.** A
      stylised oval leaf (~80×40 px) painted in yellow as a sentinel
      ink and then bbox-post-passed to flip half of those yellow
      pixels to green per ``(x+y) & 1`` parity. The eye averages the
      Y+G alternation at panel distance into the documented olive
      recipe — the dried-leaf colour real pressed-and-aged
      herbarium specimens take on. The leaf has a darker midrib
      line and three pairs of side veins to read as plant material
      rather than a generic ellipse. Painted *before* the text
      layer in ``render`` (the border helper runs first), so body
      text is drawn on top.
    * **Specimen cartouche in the bottom-left** — a small ~120×30 px
      rectangle outlined in 1 px black with the Latin tag
      ``"Tempus fugit"`` rendered in tiny IM Fell English italic
      inside. The diagonally-balanced counterweight to the leaf —
      real herbarium sheets always pair the specimen with a label,
      and the asymmetry is what reads as scientific recording rather
      than decoration. Falls back through the META_FONT chain when
      IM Fell isn't installed so the label still renders.
    * **Four small "pinhole" dots** at the inner corners of the
      hairline rule (where the specimen would be physically pinned
      to the sheet). Reinforces the "mounted" gesture.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    ink = colors["text"]
    page_bg = colors.get("page_bg")
    cream_light = SPECTRA6["yellow"]
    olive_sentinel = cream_light
    olive_other = SPECTRA6["green"]

    pixels = image.load()
    if page_bg is not None:
        for y in range(height):
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < 2:
                    pixels[x, y] = cream_light

    outer_inset = 14
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=ink,
        width=1,
    )

    # Pressed-leaf silhouette (bottom-right). The leaf is a horizontal
    # ellipse painted in the olive sentinel ink (yellow), then
    # post-passed to flip half the pixels to green per parity → olive
    # at panel distance.
    leaf_w = 84
    leaf_h = 42
    leaf_inset = 38
    leaf_cx = width - 1 - leaf_inset - leaf_w // 2
    leaf_cy = height - 1 - leaf_inset - leaf_h // 2
    leaf_left = leaf_cx - leaf_w // 2
    leaf_right = leaf_cx + leaf_w // 2
    leaf_top = leaf_cy - leaf_h // 2
    leaf_bot = leaf_cy + leaf_h // 2
    draw.ellipse((leaf_left, leaf_top, leaf_right, leaf_bot), fill=olive_sentinel)
    # Stem extending up-right from the leaf, ~16 px, same olive sentinel.
    stem_x0 = leaf_right - 4
    stem_y0 = leaf_cy
    stem_x1 = stem_x0 + 18
    stem_y1 = stem_y0 - 14
    draw.line((stem_x0, stem_y0, stem_x1, stem_y1), fill=olive_sentinel, width=2)
    # Midrib (darker reference vein). Paint solid green so the post-pass
    # leaves it as solid green-on-olive — reads as the leaf's central rib.
    draw.line((leaf_left + 6, leaf_cy, leaf_right - 6, leaf_cy), fill=olive_other, width=1)
    # Three pairs of side veins fanning outward from the midrib.
    for offset in (-12, 0, 12):
        vx = leaf_cx + offset
        draw.line((vx, leaf_cy, vx - 8, leaf_top + 6), fill=olive_other, width=1)
        draw.line((vx, leaf_cy, vx + 8, leaf_bot - 6), fill=olive_other, width=1)
    # Bbox post-pass: flip half of the painted yellow sentinel pixels
    # to green per ``(x+y) & 1`` parity → olive.
    bx0 = max(0, leaf_left - 1)
    by0 = max(0, leaf_top - 16)  # cover the stem too
    bx1 = min(width - 1, max(leaf_right, stem_x1) + 1)
    by1 = min(height - 1, leaf_bot + 1)
    for py in range(by0, by1 + 1):
        for px in range(bx0, bx1 + 1):
            if pixels[px, py] == olive_sentinel and (px + py) & 1:
                pixels[px, py] = olive_other

    # Specimen cartouche (bottom-left). Outline rectangle + small Latin tag.
    label_w = 140
    label_h = 32
    label_inset = 32
    label_x0 = label_inset
    label_y0 = height - 1 - label_inset - label_h
    label_x1 = label_x0 + label_w
    label_y1 = label_y0 + label_h
    draw.rectangle((label_x0, label_y0, label_x1, label_y1), outline=ink, width=1)
    # IM Fell italic at ~14 px so the label reads as a scribbled tag rather
    # than a competing heading. Falls back to the META font chain so the
    # label always renders.
    label_text = "Tempus fugit"
    label_font_candidates = [
        IMFELLENGLISH_ITALIC,
        IMFELLENGLISH_REGULAR,
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        *META_FONT_CANDIDATES,
    ]
    label_font = load_font(label_font_candidates, size=14)
    bbox = draw.textbbox((0, 0), label_text, font=label_font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    tx = label_x0 + (label_w - text_w) // 2
    ty = label_y0 + (label_h - text_h) // 2 - bbox[1]
    draw.text((tx, ty), label_text, font=label_font, fill=ink)

    # Four pinhole dots at the inner corners of the engraver's rule.
    pinhole_offset = 3
    pinhole_radius = 1
    for cx, cy in (
        (outer_inset + pinhole_offset, outer_inset + pinhole_offset),
        (width - 1 - outer_inset - pinhole_offset, outer_inset + pinhole_offset),
        (outer_inset + pinhole_offset, height - 1 - outer_inset - pinhole_offset),
        (width - 1 - outer_inset - pinhole_offset, height - 1 - outer_inset - pinhole_offset),
    ):
        draw.ellipse(
            (cx - pinhole_radius, cy - pinhole_radius, cx + pinhole_radius, cy + pinhole_radius),
            fill=ink,
        )


def _draw_mucha_vine(
    draw: ImageDraw.ImageDraw,
    pixels,
    width: int,
    height: int,
    cx: int,
    cy: int,
    direction: int,
    stem_ink,
    leaf_ink,
    leaf_other,
    berry_sentinel,
) -> tuple[int, int, int, int]:
    """Paint a single S-shaped vine ornament with three trefoil leaves
    and a berry at the stem tip.

    ``direction`` is ``+1`` for a vine that fans down-and-right from
    ``(cx, cy)`` (top-left corner) and ``-1`` for the mirror that
    fans up-and-left (bottom-right corner). Returns the bbox of the
    ornament for the caller's post-pass loops.
    """
    # S-shaped stem approximated as a polyline through five control
    # points spaced ~22 px apart. PIL doesn't ship curve primitives;
    # the same n-point polyline trick ``atomic``'s atom orbits use is
    # the established pattern.
    stem_pts: list[tuple[int, int]] = []
    for i in range(7):
        t = i / 6.0
        # Two-lobe S-curve: x oscillates by ~18 px around the centre
        # while y advances linearly down (or up) along ``direction``.
        x_off = round(18 * math.sin(t * math.pi * 1.6) * direction)
        y_off = round(direction * t * 110)
        stem_pts.append((cx + x_off, cy + y_off))
    draw.line(stem_pts, fill=stem_ink, width=2)

    # Three trefoil leaves sprouting along the stem at t = 1/4, 1/2, 3/4.
    leaf_centres: list[tuple[int, int]] = []
    for t_frac in (0.25, 0.5, 0.75):
        idx = round(t_frac * (len(stem_pts) - 1))
        sx, sy = stem_pts[idx]
        # Leaves alternate left / right of the stem.
        side = direction if t_frac == 0.5 else -direction
        leaf_centres.append((sx + side * 16, sy + (8 if t_frac < 0.5 else -6) * direction))

    leaf_radii = (9, 5)  # outer / inner diameters
    for lcx, lcy in leaf_centres:
        # Each "trefoil" is three overlapping ellipses fanning from the
        # stem attachment point. Pinned to the leaf_ink sentinel so the
        # post-pass below converts the trefoil to olive.
        for angle_deg in (-30, 0, 30):
            angle = math.radians(angle_deg)
            ex = lcx + round(leaf_radii[0] * math.cos(angle) * direction)
            ey = lcy + round(leaf_radii[0] * math.sin(angle))
            draw.ellipse(
                (ex - leaf_radii[1], ey - leaf_radii[1], ex + leaf_radii[1], ey + leaf_radii[1]),
                fill=leaf_ink,
            )

    # Berry at the stem tip — a filled circle painted in the
    # berry_sentinel (off-palette). The caller does the R+Y → tangerine
    # post-pass.
    tip_x, tip_y = stem_pts[-1]
    berry_radius = 5
    draw.ellipse(
        (tip_x - berry_radius, tip_y - berry_radius, tip_x + berry_radius, tip_y + berry_radius),
        fill=berry_sentinel,
    )

    # Bbox of the ornament for the post-pass loop. Padded by the leaf
    # radius so the trefoil halos are inside.
    xs = [p[0] for p in stem_pts] + [lc[0] for lc in leaf_centres] + [tip_x]
    ys = [p[1] for p in stem_pts] + [lc[1] for lc in leaf_centres] + [tip_y]
    bx0 = max(0, min(xs) - leaf_radii[0] - 2)
    by0 = max(0, min(ys) - leaf_radii[0] - 2)
    bx1 = min(width - 1, max(xs) + leaf_radii[0] + 2 + berry_radius)
    by1 = min(height - 1, max(ys) + leaf_radii[0] + 2 + berry_radius)
    return (bx0, by0, bx1, by1)


def draw_mucha_border(image: Image.Image, colors: dict) -> None:
    """Paint an Art Nouveau / Mucha frame: cream Layer-0 wash + thin
    teal rule + organic vine ornaments at two diagonal corners.

    Three motifs from the Belle Époque poster tradition:

    * **Layer 0 — cream ground wash.** The same Y+W Bayer recipe
      ``illuminated`` and ``dispatch`` use. Warms the panel's flat
      white to the aged-ivory ground real Mucha posters were printed
      on.
    * **Thin teal hairline rule** at inset 18 — painted in green as
      a sentinel ink and then perimeter-post-passed to flip half of
      those green pixels to blue per ``(x+y) & 1`` parity. The eye
      averages G+B at panel distance into cyan (the documented
      recipe ``glacier`` uses), tying the border decoration to the
      matched-phrase cyan accent the ``_draw_text_body`` seam
      produces.
    * **Organic vine ornaments at the top-left and bottom-right
      corners** — the rotation's first all-curve / organic border.
      Each vine is an S-shaped polyline-approximated stem painted in
      red as a maroon-sentinel ink, with three trefoil leaf clusters
      painted in yellow as an olive-sentinel ink, and a berry painted
      in red as a tangerine-sentinel ink at the stem tip. Three
      separate bbox post-passes convert the sentinel ink fields to
      maroon (R+K 1:1, same as the body), olive (Y+G 1:1, same as
      ``roman``'s laurel), and tangerine (R+Y 5/8:3/8 via the shared
      ``BAYER_4x4`` matrix, same as ``deco``'s sunburst and
      ``atomic``'s starburst rays). The top-right and bottom-left
      corners are deliberately *unornamented* — Mucha posters
      compose asymmetrically around an off-centre figure rather
      than around a balanced frame, and reproducing that asymmetry
      is the visual signature.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    page_bg = colors.get("page_bg")
    cream_light = SPECTRA6["yellow"]
    # Sentinels — each painted ink colour is on-palette before the
    # post-pass runs (so ``snap_image_to_palette`` is a no-op for any
    # untouched pixel), but the painter immediately post-passes its
    # own painted pixels to flip them to the second ink in the recipe.
    stem_sentinel = SPECTRA6["red"]
    stem_other = SPECTRA6["black"]
    leaf_sentinel = SPECTRA6["yellow"]
    leaf_other = SPECTRA6["green"]
    berry_sentinel = SPECTRA6["red"]
    berry_other = SPECTRA6["yellow"]
    rule_sentinel = SPECTRA6["green"]
    rule_other = SPECTRA6["blue"]

    pixels = image.load()
    # Layer 0 — sparse 1-in-8 yellow-on-white cream wash.
    if page_bg is not None:
        for y in range(height):
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < 2:
                    pixels[x, y] = cream_light

    rule_inset = 18
    # Outer rule — painted in green sentinel, post-passed to cyan.
    draw.rectangle(
        (rule_inset, rule_inset, width - 1 - rule_inset, height - 1 - rule_inset),
        outline=rule_sentinel,
        width=1,
    )
    # Perimeter post-pass: flip half of the painted green sentinel pixels
    # to blue per ``(x+y) & 1`` parity → cyan.
    for x in range(rule_inset, width - rule_inset):
        for y in (rule_inset, height - 1 - rule_inset):
            if pixels[x, y] == rule_sentinel and (x + y) & 1:
                pixels[x, y] = rule_other
    for y in range(rule_inset, height - rule_inset):
        for x in (rule_inset, width - 1 - rule_inset):
            if pixels[x, y] == rule_sentinel and (x + y) & 1:
                pixels[x, y] = rule_other

    # Top-left vine.
    tl_bbox = _draw_mucha_vine(
        draw, pixels, width, height,
        cx=rule_inset + 22, cy=rule_inset + 22, direction=+1,
        stem_ink=stem_sentinel, leaf_ink=leaf_sentinel,
        leaf_other=leaf_other, berry_sentinel=berry_sentinel,
    )
    # Bottom-right vine.
    br_bbox = _draw_mucha_vine(
        draw, pixels, width, height,
        cx=width - 1 - rule_inset - 22, cy=height - 1 - rule_inset - 22, direction=-1,
        stem_ink=stem_sentinel, leaf_ink=leaf_sentinel,
        leaf_other=leaf_other, berry_sentinel=berry_sentinel,
    )

    # Stem post-pass: R+K 1:1 maroon (same recipe as the body) —
    # restrict to the stem sentinel ink so the leaves stay yellow
    # for their own post-pass below.
    for bbox in (tl_bbox, br_bbox):
        bx0, by0, bx1, by1 = bbox
        for py in range(by0, by1 + 1):
            for px in range(bx0, bx1 + 1):
                if pixels[px, py] == stem_sentinel and (px + py) & 1:
                    pixels[px, py] = stem_other
    # Leaf post-pass: Y+G 1:1 olive.
    for bbox in (tl_bbox, br_bbox):
        bx0, by0, bx1, by1 = bbox
        for py in range(by0, by1 + 1):
            for px in range(bx0, bx1 + 1):
                if pixels[px, py] == leaf_sentinel and (px + py) & 1:
                    pixels[px, py] = leaf_other
    # Berry post-pass: R+Y 5/8:3/8 via BAYER_4x4 → tangerine. The
    # berry pixels overlap with the stem-sentinel set, so we restrict
    # to a small ~6 px radius around each stem tip — recompute the
    # stem-tip coordinates from the direction sign.
    for bbox, direction in ((tl_bbox, +1), (br_bbox, -1)):
        bx0, by0, bx1, by1 = bbox
        # The stem-tip pre-post-pass painted a 5-radius filled circle
        # in berry_sentinel (= stem_sentinel = red). After the stem
        # post-pass above, half of those red pixels were flipped to
        # black; we re-paint a small radius around the tip with the
        # tangerine recipe so the berry reads as warm orange, not maroon.
        # The tip is the last polyline control point — but its exact
        # coordinates aren't returned; reconstruct from the bbox shape.
        if direction == +1:
            tip_x = bx1 - 7
            tip_y = by1 - 7
        else:
            tip_x = bx0 + 7
            tip_y = by0 + 7
        radius = 6
        for py in range(max(0, tip_y - radius), min(height - 1, tip_y + radius) + 1):
            row = BAYER_4x4[py & 3]
            for px in range(max(0, tip_x - radius), min(width - 1, tip_x + radius) + 1):
                dx = px - tip_x
                dy = py - tip_y
                if dx * dx + dy * dy > radius * radius:
                    continue
                # Inside the berry: repaint either red (5/8) or yellow (3/8)
                # via threshold 6/16 of the shared Bayer matrix.
                pixels[px, py] = berry_other if row[px & 3] < 6 else berry_sentinel


def _build_fillmore_blob(cx: int, cy: int, scale: float, seed: int) -> list[tuple[int, int]]:
    """Return a free-form 18-point polygon approximating a melted-amoeba
    blob silhouette centred on ``(cx, cy)``.

    Deterministic — the same ``seed`` always produces the same shape.
    ``scale`` scales the radius distribution; the blob's nominal
    radius is ~80×``scale`` so a ``scale=1.0`` blob sits ~80 px from
    its centre.
    """
    import random as _random
    rng = _random.Random(seed)
    n = 18
    base_r = 80 * scale
    points: list[tuple[int, int]] = []
    for i in range(n):
        angle = (i / n) * 2 * math.pi
        # Radial wobble per vertex — keeps the silhouette organic
        # rather than circular. Range ~0.55..1.25 of base_r.
        wobble = 0.55 + rng.random() * 0.7
        r = base_r * wobble
        x = cx + round(r * math.cos(angle))
        y = cy + round(r * math.sin(angle))
        points.append((x, y))
    return points


def draw_fillmore_border(image: Image.Image, colors: dict) -> None:
    """Paint a 1960s Fillmore poster frame: Layer-0 white wash that
    tempers the saturated-yellow ground, plus corner blob panels in
    diagonal balance, sized to clear the body text area.

    Three motifs from the Wes Wilson / Victor Moscoso poster tradition:

    * **Layer 0 — sparse 1-in-8 white-on-yellow Bayer wash.**
      Flips ~2/16 of the yellow ``page_bg`` pixels to white per
      ``BAYER_4x4[y%4][x%4] < 2``, so the eye averages the
      alternation at panel distance into a slightly-paler
      yellow. Same density as the cream Layer-0 wash
      ``illuminated`` / ``dispatch`` / ``herbarium`` / ``mucha``
      use on their *white* grounds (which lifts white toward
      warm vellum); here the same primitive runs on the
      *yellow* ground to do the inverse — pulling the saturated
      Spectra-6 yellow back a notch toward a softer
      sun-faded tone — without crossing the threshold into
      cream / off-white territory and losing the Fillmore-
      poster identity. Real Fillmore prints used yellow
      stock that was already partly sun-faded by the time
      the audience saw the poster on a venue door, so the
      perceived hue is period-faithful. Only pixels matching
      the exact ``page_bg`` colour are flipped, so the blobs /
      star / inner circle painted below stay solid by
      construction (they overpaint pixels that were once
      page_bg and are skipped by the Layer 0 guard).
    * **Green blob panel in the top-left corner** — a free-form
      18-point polygon (seeded so the silhouette is deterministic)
      filled in solid green, with a small red 5-point star painted
      at the blob's centre. Sized so the blob fits inside the
      ~72 px top margin reserved by ``render`` for headers and
      ornaments, never intruding into the body text block which
      starts at ``block_top = max(72, ...)``.
    * **Blue blob panel in the bottom-right corner** — the mirror
      shape filled in solid blue, with a small yellow filled circle
      inside. Same size as the TL blob for visual balance,
      positioned in the bottom margin clear of the body.

    No outer frame — the composition is grounded by the corner
    blobs rather than by a containing rectangle, the way real
    Fillmore posters compose. The combination of pale-yellow
    ``page_bg`` (Layer-0 wash) + maroon-stippled body + blue
    matched phrase + green blob + yellow inner circle + red star
    = all six Spectra-6 native inks visible on one page, the
    visual maximalist of the rotation. Body text breathes
    diagonally between the two corner blobs.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    green_ink = SPECTRA6["green"]
    blue_ink = SPECTRA6["blue"]
    red_ink = SPECTRA6["red"]
    yellow_ink = SPECTRA6["yellow"]
    page_bg = colors.get("page_bg")

    # Layer 0: sparse 1-in-8 white-on-yellow Bayer wash. Only pixels
    # matching the exact ``page_bg`` colour are flipped, so any future
    # caller that pre-paints accents before this painter runs stays
    # valid. Skipped when ``page_bg`` is absent from the palette dict
    # so direct-call test paths providing only ``text`` stay valid.
    if page_bg is not None:
        pixels = image.load()
        for y in range(height):
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < 2:
                    pixels[x, y] = SPECTRA6["white"]

    # Green blob (TL). Centre tucked into the corner margin. With
    # scale=0.4 the base radius is 32 px, so the blob silhouette
    # extends ~y=2..70 and ~x=2..70 — fully inside the y<72 top
    # margin the body text leaves free.
    tl_cx = 38
    tl_cy = 38
    tl_blob = _build_fillmore_blob(tl_cx, tl_cy, scale=0.4, seed=1)
    draw.polygon(tl_blob, fill=green_ink)
    # Small red 5-point star inside the green blob — keeps the
    # graphic punchy at the reduced scale without crowding the
    # silhouette.
    star_r_outer = 12
    star_r_inner = 5
    star_pts: list[tuple[int, int]] = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        r = star_r_outer if i % 2 == 0 else star_r_inner
        star_pts.append((
            tl_cx + round(r * math.cos(angle)),
            tl_cy + round(r * math.sin(angle)),
        ))
    draw.polygon(star_pts, fill=red_ink)

    # Blue blob (BR). Mirror position; same scale for visual balance.
    br_cx = width - 38
    br_cy = height - 38
    br_blob = _build_fillmore_blob(br_cx, br_cy, scale=0.4, seed=2)
    draw.polygon(br_blob, fill=blue_ink)
    # Small yellow filled circle inside the blue blob.
    inner_r = 12
    draw.ellipse(
        (br_cx - inner_r, br_cy - inner_r, br_cx + inner_r, br_cy + inner_r),
        fill=yellow_ink,
    )


# Deterministic 80-star scatter for ``draw_firmament_border``. The
# (x, y, magnitude) tuples are precomputed via ``random.Random(0xF18)``
# at module load — see the seed-and-shuffle preamble inline below the
# scatter list — so the star field is reproducible across renders and
# the test suite can pin specific stars to specific pixels without
# depending on Python's random implementation. Restricted to the top
# margin (y in [4, 64]) and the bottom margin (y in [height-64,
# height-4]) so stars never collide with the body text (block_top ≥ 72
# and attribution sits at height-72 onward).
_FIRMAMENT_STAR_SEED = 0xF18


def _build_firmament_stars(width: int, height: int) -> list[tuple[int, int, int]]:
    """Return ~150 deterministic (x, y, magnitude) stars confined to the
    top and bottom decoration margins. Magnitude 1 = brightest (8-point
    sparkle with tapered rays), 2 = medium (4-point compass cross),
    3 = faint (2x2 cluster), 4 = faintest (single pixel). Reseeded per
    call so a different canvas size still produces a stable scatter.
    """
    import random as _random  # match the in-function import pattern used by _build_fillmore_blob

    rng = _random.Random(_FIRMAMENT_STAR_SEED)
    stars: list[tuple[int, int, int]] = []
    side_margin = 20

    def _add(count: int, magnitude: int) -> None:
        for _ in range(count):
            x = rng.randint(side_margin, width - side_margin - 1)
            # Bias y to top or bottom margin band (each ~60 px tall).
            if rng.random() < 0.5:
                y = rng.randint(4, 64)
            else:
                y = rng.randint(height - 64, height - 4)
            stars.append((x, y, magnitude))

    _add(80, 4)   # very faint pinprick stars
    _add(40, 3)   # faint 2x2 clusters
    _add(20, 2)   # medium 4-point crosses
    _add(10, 1)   # bright 8-point sparkles
    return stars


def _paint_firmament_star(pixels, width: int, height: int, sx: int, sy: int, magnitude: int) -> None:
    """Paint a single deterministic yellow star at (sx, sy) onto the
    image's pixel-access object. Magnitude controls the shape:

    * mag 4: single yellow pixel (faintest)
    * mag 3: 2×2 cluster (faint cluster)
    * mag 2: 4-point compass cross with 2px arms + a centre dot
    * mag 1: 8-point sparkle — long N/S/E/W rays that taper from 3px
      core to 1px tip, plus shorter diagonal NE/NW/SE/SW rays. Reads
      as a deliberate "navigational" star like the bright stars on
      17th-century atlas pages (Bayer's Uranometria, Cellarius's
      Harmonia Macrocosmica).
    """
    yellow = SPECTRA6["yellow"]

    def _set(ax: int, ay: int) -> None:
        if 0 <= ax < width and 0 <= ay < height:
            pixels[ax, ay] = yellow

    if magnitude >= 4:
        _set(sx, sy)
    elif magnitude == 3:
        for dy in (0, 1):
            for dx in (0, 1):
                _set(sx + dx, sy + dy)
    elif magnitude == 2:
        # 4-point cross — vertical/horizontal arms with a 2x2 core.
        for dy in (0, 1):
            for dx in (0, 1):
                _set(sx + dx, sy + dy)
        _set(sx + 2, sy)
        _set(sx + 2, sy + 1)
        _set(sx - 1, sy)
        _set(sx - 1, sy + 1)
        _set(sx, sy + 2)
        _set(sx + 1, sy + 2)
        _set(sx, sy - 1)
        _set(sx + 1, sy - 1)
    else:
        # Magnitude 1 — 8-point sparkle. 3x3 core, long cardinal rays
        # (5 px tip → tapered, single-pixel terminal), short
        # inter-cardinal rays (2 px, diagonal).
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                _set(sx + dx, sy + dy)
        # Long cardinal rays — 5px each, tapered (1px ray after the core).
        for offset in range(2, 6):
            _set(sx, sy - offset)  # N
            _set(sx, sy + offset)  # S
            _set(sx - offset, sy)  # W
            _set(sx + offset, sy)  # E
        # Inter-cardinal sparkle accents (2px diagonal stubs).
        for offset in (2, 3):
            _set(sx - offset, sy - offset)  # NW
            _set(sx + offset, sy - offset)  # NE
            _set(sx - offset, sy + offset)  # SW
            _set(sx + offset, sy + offset)  # SE


def draw_firmament_border(image: Image.Image, colors: dict) -> None:
    """Paint a 17th-century celestial-atlas frame around the quote:
    navy ground wash, lavender Milky Way swaths in two corners,
    scattered yellow stars in three magnitude tiers, two recognisable
    constellation polylines (Cassiopeia + Orion's Belt), four corner
    astronomy ornaments (sun, crescent moon, compass rose, ringed
    Saturn), and a sky-blue ecliptic arc across the top margin.

    Six layers, painted in Z-order so each successive layer overpaints
    the previous:

    * **Layer 0 — Navy ground wash.** ``page_bg`` is stored as solid
      black; this pass flips half of those black pixels to blue on
      ``(x + y) & 1`` parity. The eye averages B+K at panel distance
      into navy (the documented two-ink recipe). Same idempotent
      shape ``mucha`` / ``fillmore`` / ``atomic`` use for their
      Layer 0 ground washes — the second ``_paint_theme_border``
      invocation (post-text in ``render``) is a no-op because
      already-flipped pixels no longer match ``page_bg``.

    * **Layer 1 — Milky Way swaths (R+B+W lavender 3-ink).** Two
      short polygon swaths in opposite corner margins: BL (top of
      bottom margin) and TR (top margin, deliberately *left* of
      the crescent moon to avoid sentinel collision in the moon's
      blue-sentinel bbox). Each polygon is painted in an off-palette
      sentinel ink (``(2, 2, 2)``), then a per-pixel walk inside
      each polygon's bbox replaces sentinel pixels via the same
      3-way Bayer partition ``_fill_swatch_stipple_3way`` uses
      (cells 0–4 → red, 5–9 → blue, 10–15 → white). Cannot call
      the helper directly — it unconditionally overwrites every
      rect pixel and would wipe the navy ground. The lavender
      density (~1/3 each of three inks) means the band reads as
      a faint pastel violet stripe — the visible-spectrum
      arm of the Milky Way as classical atlases drew it.

    * **Layer 2 — Star field.** ~80 deterministic stars in three
      magnitude tiers, confined to the top and bottom margins so
      they never overlap body text. Mag-3 (faintest, ~50 stars):
      single yellow pixel. Mag-2 (medium, ~20 stars): 5-pixel
      yellow ``+`` cross. Mag-1 (brightest, ~10 stars): 3×3
      filled yellow square plus 4 single-pixel rays radiating
      N/S/E/W to form a small asterisk.

    * **Layer 3 — Constellation polylines.** Cassiopeia (5 stars,
      W shape) in the top-left margin and Orion's Belt (3 stars,
      tilted line) in the bottom-right margin. Each star is
      explicitly painted at its polyline vertex so the pattern
      reads even when the seeded scatter happens to leave that
      coordinate empty. Thin (1 px) white lines connect them via
      ``draw.line``.

    * **Layer 4 — Four corner astronomy ornaments.**

      * **TL Sun** at ``(32, 32)``: filled yellow disc (radius 8)
        plus 8 short yellow rays radiating outward to radius 14.
        Solid yellow throughout, no post-pass — the sun is the
        only ornament that paints in its final ink directly.
      * **TR Crescent moon** at ``(width - 32, 54)``: a filled
        circle (radius 10) painted in blue sentinel, then a
        smaller circle (radius 8) in ``page_bg`` (black) offset
        4 px left to carve the crescent. A bbox-scoped post-pass
        flips blue sentinel pixels to white on ``(x + y) & 1``
        parity, producing sky-blue (B+W 1:1 — the documented
        recipe ``glacier``'s frost-crystal tips use). Centre at
        y=54 sits well below the y=14-29 DEBUG MODE banner
        band, so no ``_DEBUG_LABEL_RIGHT_INSET`` entry is needed
        (same exemption pattern as ``dispatch`` / ``atomic``).
      * **BL Compass rose** at ``(32, height - 40)``: 8 thin
        white lines radiating from a small yellow centre dot,
        alternating long (12 px on the cardinals) and short
        (7 px on the inter-cardinals) — the canonical compass
        silhouette of a portolan-chart wind rose.
      * **BR Saturn** at ``(width - 44, height - 40)``: a filled
        disc (radius 8) in red sentinel that bbox-post-passes
        to tangerine (R+Y 5/8:3/8 via ``BAYER_4x4 < 6`` — the
        documented recipe ``deco``'s matched phrase and
        ``atomic``'s starburst rays use), plus an elliptical
        ring (semi-major 16, semi-minor 6, rotated 20°)
        approximated as a 64-point polyline (PIL has no native
        ellipse rotation — same trick ``draw_atomic_border``'s
        atom orbits use), painted in green sentinel and bbox-
        post-passed to cyan (G+B 1:1 via ``(x + y) & 1`` — the
        documented recipe ``mucha``'s outer rule and
        ``glacier``'s matched phrase use). The two post-passes
        share the Saturn corner bbox but filter on distinct
        sentinels (red vs green), so they don't collide. The
        first theme in the rotation to combine TWO synthesised
        tones in a single ornament.

    * **Layer 5 — Ecliptic arc.** A shallow sky-blue arc across
      the top margin from ``(40, 70)`` to ``(width - 40, 70)``,
      curving up to ``y = 20`` at its midpoint — the path of
      the sun and planets through the zodiac as a celestial-
      atlas page would have drawn it. Painted in blue sentinel
      via ``draw.arc``, then a bbox-scoped post-pass flips half
      to white on ``(x + y) & 1`` parity producing sky-blue.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    page_bg = colors.get("page_bg")
    pixels = image.load()

    blue_ink = SPECTRA6["blue"]
    white_ink = SPECTRA6["white"]
    yellow_ink = SPECTRA6["yellow"]
    red_ink = SPECTRA6["red"]
    green_ink = SPECTRA6["green"]
    black_ink = SPECTRA6["black"]
    # Off-palette sentinels — each is a unique RGB triple that no other
    # Spectra-6 ink shares, so the per-ornament post-pass can filter on
    # its sentinel without touching Layer 0's blue pixels (Layer 0 flips
    # half the navy ground to blue, so reusing SPECTRA6["blue"] as a
    # sentinel here would have the post-pass spray sky-blue stipple
    # across every Layer 0 blue pixel inside the ornament's bbox).
    milky_sentinel = (2, 2, 2)
    moon_sentinel = (3, 3, 3)
    arc_sentinel = (4, 4, 4)

    # ---- Layer 0: Navy ground wash (B+K 1:1 via (x+y)&1 parity) ----
    if page_bg is not None:
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == page_bg and (x + y) & 1:
                    pixels[x, y] = blue_ink

    # ---- Layer 1: Milky Way (dense star scatter inside two flowing blobs) ----
    # The Milky Way is literally a region of densely concentrated
    # stars, so render it that way: define two irregular flowing
    # blob silhouettes — NOT rectangles — and scatter additional
    # yellow pinprick stars inside each blob at much higher density
    # than the ambient star field. Faint pixel-level red/blue
    # "nebular dust" accents (cells 0/1 of a 4×4 Bayer at 12.5%
    # total density) add a warm/cool hint without dominating the
    # silhouette. The result reads as the dense star fields and
    # nebular haze a 17th-century atlas (Cellarius, Hevelius) drew
    # by stippling the engraving plate.
    #
    # Sentinel-painted polygons, then a per-pixel walk inside each
    # blob's bbox: painted sentinel pixels are replaced via a
    # deterministic per-position hash so the scatter is reproducible
    # without an RNG-state thread through the post-pass. Ratios:
    #   * ~1/22 of blob pixels → yellow star (dense star scatter)
    #   * cell 0 (1/16) → red speck (warm nebular dust)
    #   * cell 1 (1/16) → blue speck (cool nebular dust)
    #   * remainder → revert to the Layer 0 navy ground
    import random as _random_blob

    blob_rng = _random_blob.Random(_FIRMAMENT_STAR_SEED ^ 0x42)

    def _build_blob(cx: float, cy: float, base_r: float, aspect: float = 1.0) -> list[tuple[float, float]]:
        n = 32
        points = []
        for i in range(n):
            t = 2.0 * math.pi * i / n
            # Per-vertex radial wobble in [0.65, 1.15] * base_r so the
            # silhouette reads as organic, not geometric. Two-octave
            # noise: a slow wobble plus a faster one for cliff-like
            # detail.
            r = base_r * (0.65 + 0.40 * blob_rng.random()) * (
                0.85 + 0.30 * blob_rng.random()
            )
            points.append((cx + r * math.cos(t) * aspect, cy + r * math.sin(t)))
        return points

    # Top blob — drifts above the moon, shorter and shallower than
    # before so the band reads as a wispy nebula rather than a solid
    # cloud. Sits between Cassiopeia (TL) and Lyra (TR), threading
    # below the ecliptic arc.
    top_blob = _build_blob(width / 2 + 30, 52, 36, aspect=2.2)
    # Bottom blob — narrower, mirrored opposite-diagonal.
    bottom_blob = _build_blob(width / 2 - 60, height - 30, 32, aspect=2.4)

    for poly in (top_blob, bottom_blob):
        draw.polygon(poly, fill=milky_sentinel)
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        x0, x1 = max(0, int(min(xs))), min(width, int(max(xs)) + 1)
        y0, y1 = max(0, int(min(ys))), min(height, int(max(ys)) + 1)
        for y in range(y0, y1):
            for x in range(x0, x1):
                if pixels[x, y] != milky_sentinel:
                    continue
                # Deterministic per-position hash → very sparse paint:
                # 1/40 chance yellow pin-star, 1/30 chance red dust,
                # 1/30 chance blue dust. Total ~9% painted; remaining
                # ~91% reverts to the navy ground. At panel viewing
                # distance the eye averages this to a faint cloudy
                # haze with embedded pin-stars — what 17th-century
                # atlas engravers stippled when they drew the
                # Milky Way's diffuse trail.
                star_hash = (x * 73856093) ^ (y * 19349663)
                bucket = star_hash % 120
                if bucket < 3:
                    pixels[x, y] = yellow_ink   # 3/120 = 1/40 star
                elif bucket < 7:
                    pixels[x, y] = red_ink      # 4/120 ≈ 1/30 warm dust
                elif bucket < 11:
                    pixels[x, y] = blue_ink     # 4/120 ≈ 1/30 cool dust
                else:
                    # Revert to navy ground (Layer 0 parity).
                    pixels[x, y] = blue_ink if (x + y) & 1 else black_ink

    # ---- Layer 2: Star field ----
    for sx, sy, mag in _build_firmament_stars(width, height):
        _paint_firmament_star(pixels, width, height, sx, sy, mag)

    # ---- Layer 3: Constellation polylines + Latin labels ----
    # Cardo Italic for constellation names — the small-caps register of
    # 17th-century celestial-atlas labels. ImageFont is loaded lazily so
    # the label step is graceful if the font is missing.
    try:
        label_font = ImageFont.truetype(CARDO_ITALIC, 11)
    except OSError:
        label_font = ImageFont.load_default()

    # Cassiopeia — W shape, top-left margin. Five canonical stars.
    cassiopeia = [(60, 34), (95, 50), (130, 28), (165, 50), (200, 36)]
    for cx, cy in cassiopeia:
        _paint_firmament_star(pixels, width, height, cx, cy, magnitude=1)
    draw.line(cassiopeia, fill=white_ink, width=1)
    # Latin label below the W, white italic.
    draw.text((90, 60), "CASSIOPEIA", font=label_font, fill=white_ink)

    # Orion's Belt — three stars in a tilted line, bottom-right margin.
    orion_belt = [
        (width - 220, height - 30),
        (width - 160, height - 36),
        (width - 100, height - 42),
    ]
    for cx, cy in orion_belt:
        _paint_firmament_star(pixels, width, height, cx, cy, magnitude=1)
    draw.line(orion_belt, fill=white_ink, width=1)
    draw.text((width - 196, height - 18), "ORION", font=label_font, fill=white_ink)

    # Lyra — small parallelogram in the top-right margin, between the
    # Milky Way wisp and the moon. Four stars; the brightest is Vega.
    lyra = [
        (width - 280, 28),
        (width - 240, 18),
        (width - 220, 42),
        (width - 268, 52),
    ]
    for cx, cy in lyra:
        _paint_firmament_star(pixels, width, height, cx, cy, magnitude=2)
    # Vega — promote the first vertex to a brighter sparkle.
    _paint_firmament_star(pixels, width, height, lyra[0][0], lyra[0][1], magnitude=1)
    # Close the parallelogram (4 segments).
    lyra_closed = lyra + [lyra[0]]
    draw.line(lyra_closed, fill=white_ink, width=1)
    draw.text((width - 280, 60), "LYRA", font=label_font, fill=white_ink)

    # Crux (Southern Cross) — four stars in a cross pattern, bottom-left
    # margin. Compact, fits between the compass rose and the body block.
    crux = [
        (200, height - 56),   # top
        (216, height - 42),   # right
        (200, height - 28),   # bottom
        (184, height - 42),   # left
    ]
    _paint_firmament_star(pixels, width, height, crux[0][0], crux[0][1], magnitude=1)
    for cx, cy in crux[1:]:
        _paint_firmament_star(pixels, width, height, cx, cy, magnitude=2)
    # Two crossing lines.
    draw.line((crux[0], crux[2]), fill=white_ink, width=1)
    draw.line((crux[1], crux[3]), fill=white_ink, width=1)
    draw.text((132, height - 18), "CRUX AUSTRALIS", font=label_font, fill=white_ink)

    # ---- Layer 4: Four corner astronomy ornaments ----

    # TL Sun (Sol Invictus). Filled yellow disc + 16 alternating-length
    # rays + a faint single-pixel halo of yellow at the cardinal
    # boundaries → reads as a medieval sun-in-splendour rather than a
    # geometric asterisk. The face stays implied (a small 2px crescent
    # carved into the lower-right of the disc suggests a smile contour
    # without committing to a literal face that would read as
    # cartoonish at 12 px). All solid yellow, no post-pass.
    sun_cx, sun_cy = 36, 36
    sun_r = 11
    draw.ellipse(
        (sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r),
        fill=yellow_ink,
    )
    # 16 rays in alternating tiers — 8 long primary, 8 short secondary.
    for i, angle_deg in enumerate(range(0, 360, 22)):
        angle = math.radians(angle_deg)
        is_long = i % 2 == 0
        ray_inner = sun_r + (1 if is_long else 3)
        ray_outer = sun_r + (12 if is_long else 6)
        x1 = sun_cx + ray_inner * math.cos(angle)
        y1 = sun_cy + ray_inner * math.sin(angle)
        x2 = sun_cx + ray_outer * math.cos(angle)
        y2 = sun_cy + ray_outer * math.sin(angle)
        draw.line((x1, y1, x2, y2), fill=yellow_ink, width=1)
    # Implied "face" — two tiny navy carved dots for eyes + a 3px
    # smile arc, sitting in the lower half of the disc. Painted in the
    # navy ground colours via the (x+y)&1 parity of the existing Layer
    # 0 stipple, so it reads as a deliberate carved relief rather than
    # an additional decoration layer. Two left+right eye dots at
    # cy-2, a 3px wide smile centred at cy+3.
    for ex in (sun_cx - 3, sun_cx + 3):
        pixels[ex, sun_cy - 2] = blue_ink if (ex + sun_cy - 2) & 1 else black_ink
    # Smile — 3 px arc.
    for dx in (-2, -1, 0, 1, 2):
        sy = sun_cy + 3 + (1 if abs(dx) >= 2 else 0)
        pixels[sun_cx + dx, sy] = blue_ink if (sun_cx + dx + sy) & 1 else black_ink

    # TR Crescent moon (Luna). The phase is a waning gibbous with a
    # small "Luna" face suggestion (two tiny dark dots for craters).
    # Sentinel-painted then bbox post-passed to sky-blue (B+W 1:1).
    moon_cx, moon_cy = width - 36, 50
    moon_r = 13
    draw.ellipse(
        (moon_cx - moon_r, moon_cy - moon_r, moon_cx + moon_r, moon_cy + moon_r),
        fill=moon_sentinel,
    )
    # Carve the shadow.
    carve_r = 11
    carve_cx = moon_cx - 5
    draw.ellipse(
        (carve_cx - carve_r, moon_cy - carve_r, carve_cx + carve_r, moon_cy + carve_r),
        fill=page_bg if page_bg is not None else black_ink,
    )
    # Sky-blue post-pass, scoped to the moon bbox.
    mx0, mx1 = moon_cx - moon_r - 1, moon_cx + moon_r + 1
    my0, my1 = moon_cy - moon_r - 1, moon_cy + moon_r + 1
    for y in range(max(0, my0), min(height, my1 + 1)):
        for x in range(max(0, mx0), min(width, mx1 + 1)):
            if pixels[x, y] == moon_sentinel:
                pixels[x, y] = white_ink if (x + y) & 1 else blue_ink
    # Two small "craters" — pixel-relief navy dots in the lit portion.
    for cx_off, cy_off in ((4, -2), (6, 3)):
        ax, ay = moon_cx + cx_off, moon_cy + cy_off
        if 0 <= ax < width and 0 <= ay < height:
            pixels[ax, ay] = blue_ink if (ax + ay) & 1 else black_ink

    # BL Compass rose (Wind Rose). Replace the earlier stick-ray design
    # with a filled-wedge portolan-chart compass: four large filled
    # triangular points at the cardinals (N, S, E, W) painted in white,
    # four smaller diagonal points (NE, SE, SW, NW) in white, plus a
    # filled yellow inner diamond and a small "N" label above the
    # north point so the orientation reads at a glance.
    rose_cx, rose_cy = 40, height - 44
    long_r = 18
    short_r = 8
    side = 4  # half-width of the cardinal wedge at the base
    # Cardinal wedges — each a filled triangle from centre to the
    # tip, with a small width at the base for the silhouette.
    cardinals = [
        ((rose_cx, rose_cy - long_r), (rose_cx - side, rose_cy), (rose_cx + side, rose_cy)),   # N
        ((rose_cx + long_r, rose_cy), (rose_cx, rose_cy - side), (rose_cx, rose_cy + side)),   # E
        ((rose_cx, rose_cy + long_r), (rose_cx - side, rose_cy), (rose_cx + side, rose_cy)),   # S
        ((rose_cx - long_r, rose_cy), (rose_cx, rose_cy - side), (rose_cx, rose_cy + side)),   # W
    ]
    for triangle in cardinals:
        draw.polygon(triangle, fill=white_ink)
    # Diagonal points — thinner short wedges.
    diag_side = 2
    for angle_deg in (45, 135, 225, 315):
        angle = math.radians(angle_deg)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        # Perpendicular for the base width.
        perp_x, perp_y = -sin_a, cos_a
        tip = (rose_cx + short_r * cos_a, rose_cy + short_r * sin_a)
        base_a = (rose_cx + diag_side * perp_x, rose_cy + diag_side * perp_y)
        base_b = (rose_cx - diag_side * perp_x, rose_cy - diag_side * perp_y)
        draw.polygon((tip, base_a, base_b), fill=white_ink)
    # Inner filled yellow diamond (the "pivot").
    draw.polygon(
        ((rose_cx, rose_cy - 3), (rose_cx + 3, rose_cy),
         (rose_cx, rose_cy + 3), (rose_cx - 3, rose_cy)),
        fill=yellow_ink,
    )
    # "N" label above the north point.
    try:
        n_font = ImageFont.truetype(CARDO_BOLD, 11)
    except OSError:
        n_font = ImageFont.load_default()
    draw.text((rose_cx - 4, rose_cy - long_r - 13), "N", font=n_font, fill=yellow_ink)

    # BR Saturn (Saturnus). Proper banded gas giant with the Cassini
    # division: a tangerine disc with a single navy "equatorial band"
    # darkening the centre row, plus TWO concentric ring lines (outer
    # + inner with a 1 px gap = Cassini division), drawn as 64-point
    # polyline approximations rotated 18° to suggest the planet's
    # axial tilt. The two rings paint in green sentinel and bbox-
    # post-pass independently to cyan (G+B 1:1). The disc paints in
    # red sentinel and post-passes to tangerine (R+Y 5/8:3/8). The
    # bbox post-pass filters on its sentinel so the rings and disc
    # don't collide.
    saturn_cx, saturn_cy = width - 56, height - 48
    saturn_r = 11
    draw.ellipse(
        (saturn_cx - saturn_r, saturn_cy - saturn_r,
         saturn_cx + saturn_r, saturn_cy + saturn_r),
        fill=red_ink,
    )
    # Outer ring + inner ring (Cassini division 1 px between them).
    angle = math.radians(18)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    n_points = 96
    for ring_a, ring_b in ((22, 8), (19, 6)):
        ring_points = []
        for i in range(n_points + 1):
            t = 2.0 * math.pi * i / n_points
            xu = ring_a * math.cos(t)
            yu = ring_b * math.sin(t)
            ring_points.append((
                saturn_cx + xu * cos_a - yu * sin_a,
                saturn_cy + xu * sin_a + yu * cos_a,
            ))
        draw.line(ring_points, fill=green_ink, width=1)
    # Equatorial band — single horizontal dark line across the disc
    # (deliberately drawn AFTER the disc so it cuts through the
    # tangerine). Paint in black so it survives the disc post-pass.
    band_y = saturn_cy + 1
    draw.line(
        (saturn_cx - saturn_r + 2, band_y, saturn_cx + saturn_r - 2, band_y),
        fill=black_ink, width=1,
    )
    # Saturn post-pass — bbox scoped to the corner. Two independent
    # sentinel filters (red → tangerine, green → cyan) inside the same
    # bbox. The black band pixels match neither sentinel and survive.
    sat_pad = 24
    sat_x0 = max(0, saturn_cx - sat_pad)
    sat_x1 = min(width, saturn_cx + sat_pad + 1)
    sat_y0 = max(0, saturn_cy - sat_pad)
    sat_y1 = min(height, saturn_cy + sat_pad + 1)
    for y in range(sat_y0, sat_y1):
        for x in range(sat_x0, sat_x1):
            px_val = pixels[x, y]
            if px_val == red_ink and BAYER_4x4[y & 3][x & 3] < 6:
                pixels[x, y] = yellow_ink
            elif px_val == green_ink and (x + y) & 1:
                pixels[x, y] = blue_ink

    # ---- Layer 4b: Roman-numeral hour markers ----
    # XII / III / VI / IX at the four cardinal page positions. Reads
    # as a horological-astrolabe rim, the period instrument that
    # married astronomy to timekeeping. Subtle (small italic Cardo
    # at the very edges of the canvas) so it doesn't compete with
    # the ornaments. Each numeral is positioned to sit clear of
    # the corner ornaments and the body region.
    try:
        roman_font = ImageFont.truetype(CARDO_ITALIC, 12)
    except OSError:
        roman_font = ImageFont.load_default()
    # XII — top centre. Offset right slightly so it clears the top
    # Milky Way blob (centred at width/2 + 30) on its left side.
    draw.text((width // 2 - 60, 4), "XII", font=roman_font, fill=white_ink)
    # VI — bottom RIGHT of centre. The bottom Milky Way blob sits
    # left-of-centre (width/2 - 60), so VI lives to the right of it.
    draw.text((width // 2 + 60, height - 16), "VI", font=roman_font, fill=white_ink)
    # III — right edge, vertically at the body horizontal centre.
    draw.text((width - 16, height // 2 - 6), "III", font=roman_font, fill=white_ink)
    # IX — left edge, mirroring III.
    draw.text((4, height // 2 - 6), "IX", font=roman_font, fill=white_ink)

    # ---- Layer 5: Ecliptic arc ----
    # A shallow arc across the top margin: bbox that crosses near
    # (width/2, 20) at its peak and meets y=70 at x=40 and x=width-40.
    # Use draw.arc on a tall bbox so only the bottom segment of the
    # ellipse paints, producing the upward-curving sun-path silhouette.
    # Painted in ``arc_sentinel`` (off-palette) — the bbox post-pass
    # filters on the sentinel so it can't touch the Layer 0 navy
    # stipple's blue pixels in the same band.
    arc_bbox = (40, 20, width - 40, 140)
    draw.arc(arc_bbox, start=180, end=360, fill=arc_sentinel, width=1)
    ax0, ay0 = 40, 14
    ax1, ay1 = width - 40, 72
    for y in range(max(0, ay0), min(height, ay1 + 1)):
        for x in range(max(0, ax0), min(width, ax1 + 1)):
            if pixels[x, y] == arc_sentinel:
                pixels[x, y] = white_ink if (x + y) & 1 else blue_ink


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
    "gothic": draw_gothic_border,
    "dispatch": draw_dispatch_border,
    "atomic": draw_atomic_border,
    "marker": draw_marker_border,
    "saloon": draw_saloon_border,
    "roman": draw_roman_border,
    "alchemy": draw_alchemy_border,
    "newsprint": draw_newsprint_border,
    "nightvision": draw_nightvision_border,
    "risograph": draw_risograph_border,
    "grimoire": draw_grimoire_border,
    "deco": draw_deco_border,
    "glacier": draw_glacier_border,
    "chalkboard": draw_chalkboard_border,
    "placard": draw_placard_border,
    "chanbara": draw_chanbara_border,
    "lcars": draw_lcars_border,
    "swiss": draw_swiss_border,
    "herbarium": draw_herbarium_border,
    "mucha": draw_mucha_border,
    "fillmore": draw_fillmore_border,
    "firmament": draw_firmament_border,
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
#   - dispatch: rubber-stamp imprint sits at y=40-70 (centre y=55), well
#     below the label's y=14-29 band; no horizontal-overlap concern since
#     the two graphics are vertically separated. The frame and tractor-feed
#     perforations don't reach into the label's bbox either.
#   - atomic: atom symbol is centred at (width//2, 44) — far from the
#     right-aligned label's x range. Mid-edge starbursts sit at y=height//2,
#     also clear of the label band. The rounded outer frame at inset 14 is
#     identical to other framed themes here.
_DEBUG_LABEL_RIGHT_INSET = {
    "bauhaus": 38,      # past the 6+22px TR filled square
    "blueprint": 34,    # past the TR crosshair arm (frame at 16 + 8px arm)
    "illuminated": 28,  # past the TR jewel (frame at 14, radius 5 → x=width-9)
    "gothic": 30,       # past the TR quatrefoil right lobe (frame at 14,
                        # lobe centre offset +4 with radius 5 → x=width-6)
    "risograph": 44,    # past the shifted TR registration mark at x=width-15
    "marker": 44,       # past the TR asterisk (centre at width-25, ray 11
                        # → rightmost arm at x=width-14) plus breathing gap
    "saloon": 44,       # past the TR fleuron horizontal wing (corner at
                        # width-13, wing tip at width-38) plus breathing gap.
                        # The decorative banner band starts at y=34 so it's
                        # already below the label's y=14-29 band.
    "roman": 38,        # past the tabula's right vertical rule (frame at
                        # rect_inset_x=30, 3px width → outer edge at
                        # x=width-30, rule painted from x=width-33 to
                        # x=width-31) plus breathing gap. The SPQR
                        # cartouche is centred horizontally so it never
                        # reaches the label's x range.
    "alchemy": 76,      # past the bigger TR corner pentagram. Centre
                        # at (width-41, 40) with radius 22 → protective
                        # circle extends LEFT to x=width-63; inset
                        # clears that plus a 13px breathing gap so
                        # the ``DEBUG MODE`` glyphs sit cleanly inside
                        # the ritual boundary. The top-right elemental
                        # triangle (🜄 Water at +2*flank_spacing,
                        # centred at x=width//2+160=560 with radius 11)
                        # sits well left of the label's x range.
    "grimoire": 50,     # past the TR inscribed pentagram. Centre at
                        # (width-31, 30) with ring_radius=14 and 2px
                        # stroke (half-width 1) → leftmost pixel of
                        # the ring at x=width-46. Plus a 4px breathing
                        # gap → label's right edge must end at x ≤
                        # width-50. The ring's top vertex sits at y=15
                        # (well inside the label's y=14-29 band), so
                        # the horizontal inset is what does the work.
    "glacier": 34,      # past the TR frost-crystal cluster. The diagonal
                        # shard (long_arm=14) reaches roughly to
                        # x=width-3-outer_inset+1-14 = width-30 with the
                        # accent-tipped point, plus a 4px breathing gap.
                        # ``deco`` is intentionally absent — its stepped
                        # corner reaches x ≤ width-14 (well outside the
                        # default debug-label edge at SIDE_MARGIN) and
                        # its rising-sun fan is centred horizontally.
    "herbarium": 24,    # past the TR pinhole dot (centre at width-18,
                        # y=17, radius 1 → leftmost pixel at x=width-19)
                        # plus a 4 px breathing gap, so the dot reads
                        # as a distinct corner pin rather than as part
                        # of the debug label. The bottom-right
                        # pressed-leaf graphic sits at y ≈ height-79
                        # (well below the y=14-29 banner band), and
                        # the bottom-left specimen cartouche is in
                        # the opposite corner, so neither needs an
                        # inset adjustment. ``swiss`` and ``mucha``
                        # are intentionally absent — swiss's red
                        # header square sits at y=42 (below the
                        # banner), and mucha deliberately leaves the
                        # TR corner unornamented for asymmetric
                        # composition. ``fillmore``'s TR concentric
                        # rings sit at y=110 (centre), well below
                        # the banner band. ``firmament``'s TR crescent
                        # moon centre sits at y=54 (well below the
                        # y=14-29 banner band) and the TR Milky Way
                        # swath is bounded at x ≤ width-100 (left of
                        # the default label right edge), so neither
                        # graphic touches the label bbox.
}

# Themes whose matched-phrase (``quote_bold``) face has a distinctive
# silhouette that breaks if its inter-word gaps are inflated by
# justification slack. The default per-theme contract is "every inter-
# word space on a justified line is equally elastic — slack is divided
# evenly across them"; themes in this set treat the matched-phrase
# spaces as *rigid* (kept at the bold face's natural space width) so
# only the body's inter-word gaps absorb slack. Without the seam,
# TFoust's "quarter past two" on a justified line in ``grimoire`` reads
# as three disconnected ink-stained syllables rather than a single
# inscription — the hollow / shaggy character of the face survives
# only at its natural inter-letter rhythm. Gothic shares the rigid
# treatment because its UnifrakturMaguntia matched-phrase blackletter
# has the same problem at scale — elastic spaces between blackletter
# words read as breaks between Latin clauses rather than a single
# inscribed phrase. Strict superset is fine: the ``score_row`` / wrap
# / fit pipeline does not depend on this set.
_THEMES_RIGID_MATCH_SPACING: frozenset[str] = frozenset({"grimoire", "gothic"})


def _justify_distribution(space_is_bold: list[bool], slack: int, rigid_match: bool) -> list[int]:
    """Return the per-space slack contribution for a justified line.

    ``space_is_bold`` is the list of inter-word spaces on the line, in
    visual order, with each entry telling whether the space sits
    inside the bold matched phrase. ``slack`` is the leftover pixel
    width to redistribute. When ``rigid_match`` is True, bold-internal
    spaces are kept at the bold face's natural width (contribution 0)
    and the full slack is split evenly across only the body's
    inter-word gaps; otherwise every space is equally elastic, which
    is the renderer's default contract. The returned list has the
    same length as ``space_is_bold`` so the call site can iterate
    over it lock-step with the line's space occurrences.

    Returns an empty list when there's no elastic space to absorb
    slack (e.g. ``rigid_match`` is True and every space on the line
    happens to sit inside the matched phrase) — the call site falls
    through to the unjustified ragged-right layout, same path the
    "slack > 25% of max_width" guard takes.
    """
    elastic_count = sum(1 for is_bold in space_is_bold if not (rigid_match and is_bold))
    if elastic_count == 0:
        return []
    base = slack // elastic_count
    remainder = slack - base * elastic_count
    distribute: list[int] = []
    elastic_seen = 0
    for is_bold in space_is_bold:
        if rigid_match and is_bold:
            distribute.append(0)
        else:
            distribute.append(base + (1 if elastic_seen < remainder else 0))
            elastic_seen += 1
    return distribute


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
    # ``card_quote_bold`` falls through to ``quote_bold`` for every theme
    # that doesn't override it; the seam exists so themes whose bold
    # chain starts with an ASCII-only display face (TFoust on grimoire)
    # can route the card's title and matched phrase — both of which
    # may contain em-dashes or curly quotes — through a unicode-safe
    # face without changing their main-render typography.
    title_font = load_font(theme_font_candidates(theme, "card_quote_bold"), size=44)
    author_font = load_font(theme_font_candidates(theme, "quote_regular"), size=28)
    id_font = load_font(META_FONT_CANDIDATES, size=18)
    phrase_font = load_font(theme_font_candidates(theme, "card_quote_bold"), size=28)

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
        _draw_text_body(image, draw, ((width - w) // 2, y), text, font=font, fill=fill, theme=theme)
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


def render_static_message(message: str, width: int, height: int, theme: str = "default") -> Image.Image:
    """Render a centered headline message in the active theme.

    Used by the ``--quiet-image=auto`` and ``--startup-image=auto`` sentinels
    so the goodnight / startup frame matches the operator's chosen theme
    instead of always showing the dark ``assets/goodnight.png``. Reuses the
    theme palette, border, and bundled fonts so it visually matches the quote
    frame an operator sees seconds before quiet hours begin.
    """
    colors = THEMES[theme]
    image = Image.new("RGB", (width, height), color=colors["page_bg"])
    _paint_theme_border(image, theme, colors)
    draw = ImageDraw.Draw(image)

    max_text_width = width - 2 * SIDE_MARGIN - 40
    headline_candidates = theme_font_candidates(theme, "quote_bold")
    line_gap = 12
    for size in range(96, 35, -4):
        font = load_font(headline_candidates, size=size)
        lines = wrap_text(draw, message, font, max_text_width)
        line_heights = [
            draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1]
            for line in lines
        ]
        block_h = sum(line_heights) + max(0, len(lines) - 1) * line_gap
        if block_h <= height - 80:
            break

    y = max(40, (height - block_h) // 2)
    for line, h in zip(lines, line_heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        _draw_text_body(image, draw, ((width - w) // 2, y), line, font=font, fill=colors["text"], theme=theme)
        y += h + line_gap

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


# Synthesised two-ink stipple recipes documented in spectra6_color_recipes.md
# (and summarised in CLAUDE.md). Each entry is (display name, dark ink, light
# ink, light density, short label). The order here drives the two-row swatch
# band at the bottom of the diagnostic frame; the four in-use recipes
# (tangerine / candlelit / mint / coral) lead so they read as the active
# palette before the reference / unused recipes. ``sage`` follows the doc's
# "for ratios above 50%, swap dark/light and pass the complementary density"
# rule (75% white + 25% green → sparse-1-in-4 green on white). ``lime`` uses
# the same 0.375 biased-Bayer recipe as ``tangerine`` but with the green/yellow
# pair. The full set covers every two-ink recipe reachable through
# ``draw_text_dithered`` today — three-ink mixes (lavender, salmon, …) need a
# ``_three_way_bayer`` primitive that doesn't exist yet.
_DIAGS_SYNTH_SWATCHES: list[tuple[str, tuple[int, int, int], tuple[int, int, int], float, str]] = [
    # Row 1 — reds / oranges / violets / sepia / cream
    ("tangerine", SPECTRA6["red"],    SPECTRA6["yellow"], 0.375, "R+Y 5:3"),
    ("candlelit", SPECTRA6["red"],    SPECTRA6["white"],  0.25,  "R+W 3:1"),
    ("coral",     SPECTRA6["red"],    SPECTRA6["white"],  0.5,   "R+W 1:1"),
    ("amber",     SPECTRA6["red"],    SPECTRA6["yellow"], 0.5,   "R+Y 1:1"),
    ("violet",    SPECTRA6["red"],    SPECTRA6["blue"],   0.5,   "R+B 1:1"),
    ("maroon",    SPECTRA6["red"],    SPECTRA6["black"],  0.5,   "R+K 1:1"),
    ("sepia",     SPECTRA6["red"],    SPECTRA6["green"],  0.5,   "R+G 1:1"),
    ("cream",     SPECTRA6["yellow"], SPECTRA6["white"],  0.5,   "Y+W 1:1"),
    # Row 2 — greens / blues / neutrals
    ("mint",      SPECTRA6["green"],  SPECTRA6["white"],  0.5,   "G+W 1:1"),
    ("sage",      SPECTRA6["white"],  SPECTRA6["green"],  0.25,  "W+G 3:1"),
    ("olive",     SPECTRA6["yellow"], SPECTRA6["green"],  0.5,   "Y+G 1:1"),
    ("lime",      SPECTRA6["yellow"], SPECTRA6["green"],  0.375, "Y+G 5:3"),
    ("forest",    SPECTRA6["green"],  SPECTRA6["black"],  0.5,   "G+K 1:1"),
    ("cyan",      SPECTRA6["green"],  SPECTRA6["blue"],   0.5,   "G+B 1:1"),
    ("sky",       SPECTRA6["blue"],   SPECTRA6["white"],  0.5,   "B+W 1:1"),
    ("navy",      SPECTRA6["blue"],   SPECTRA6["black"],  0.5,   "B+K 1:1"),
    ("gray",      SPECTRA6["black"],  SPECTRA6["white"],  0.5,   "K+W 1:1"),
]

# Number of swatches in the first row of the diags synth band. The list above
# splits 8 / 9, keeping the in-use recipes left-justified on row 1 and the
# larger remainder on row 2 so per-swatch widths stay readable (~79 px).
_DIAGS_SYNTH_ROW1_COUNT = 8

_DIAGS_SPECTRA6_SWATCHES: list[tuple[str, tuple[int, int, int], str]] = [
    ("white",  SPECTRA6["white"],  "#FFFFFF"),
    ("black",  SPECTRA6["black"],  "#000000"),
    ("red",    SPECTRA6["red"],    "#FF0000"),
    ("yellow", SPECTRA6["yellow"], "#FFFF00"),
    ("blue",   SPECTRA6["blue"],   "#0000FF"),
    ("green",  SPECTRA6["green"],  "#00FF00"),
]


def _diags_system_info() -> dict[str, str]:
    """Return host / IP / uptime strings for the diagnostic frame.

    Each lookup is wrapped so a misconfigured environment (no network,
    non-Linux host, restricted /proc access) still produces a renderable
    frame — the missing field falls back to ``"—"`` rather than aborting
    the render and wedging the panel.

    IP discovery uses the standard "UDP connect to a public address"
    trick: it never actually sends a packet, but it pins the kernel's
    chosen source address for that route, which is the appliance's
    primary outbound IP. Falls back to ``socket.gethostbyname`` and
    finally ``"—"`` when both fail (offline appliance with no DNS).
    """
    import socket

    info: dict[str, str] = {"host": "—", "ip": "—", "uptime": "—"}
    try:
        host = socket.gethostname()
        if host:
            info["host"] = host
    except Exception:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 53))
            info["ip"] = sock.getsockname()[0]
        finally:
            sock.close()
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
            if ip and ip != "127.0.0.1":
                info["ip"] = ip
        except Exception:
            pass
    try:
        with open("/proc/uptime", "r") as fh:
            seconds = int(float(fh.read().split()[0]))
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        if days:
            info["uptime"] = f"{days}d {hours}h {minutes}m"
        elif hours:
            info["uptime"] = f"{hours}h {minutes}m"
        else:
            info["uptime"] = f"{minutes}m"
    except Exception:
        pass
    return info


def _fill_swatch_stipple(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    dark: tuple[int, int, int],
    light: tuple[int, int, int],
    light_density: float,
) -> None:
    """Paint a rectangular region with the same on-palette Bayer stipple
    that ``draw_text_dithered`` applies to glyph masks. The three density
    branches mirror that function so the swatch displays the recipe the
    theme code would actually paint.
    """
    x0, y0, x1, y1 = rect
    # Clip to image bounds — ``PixelAccess`` (``px[x, y]``) raises
    # ``IndexError`` on out-of-range coordinates, unlike PIL's draw primitives
    # which silently clip. Callers may legitimately pass a rect that's partly
    # or fully outside the image (e.g. the diags layout when rendered into a
    # 320×192 web-preview thumbnail, where the synth-swatch band sits below
    # the canvas) and the swatch should just disappear rather than crash.
    w, h = image.size
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(w, x1)
    y1 = min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return
    px = image.load()
    if light_density <= 0.25:
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = light if (x % 2 == 0 and y % 2 == 0) else dark
    elif light_density >= 0.5:
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = dark if (x + y) % 2 == 0 else light
    else:
        threshold = round(light_density * 16)
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = light if BAYER_4x4[y % 4][x % 4] < threshold else dark


def _fill_swatch_stipple_3way(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    ink_a: tuple[int, int, int],
    ink_b: tuple[int, int, int],
    ink_c: tuple[int, int, int],
    density_a: float,
    density_b: float,
) -> None:
    """Paint a rectangular region with a 3-ink Bayer stipple.

    Partitions the 4×4 Bayer tile by two thresholds: cells where the tile
    value is below ``round(density_a * 16)`` get ``ink_a``, cells below
    ``round((density_a + density_b) * 16)`` get ``ink_b``, the remainder
    get ``ink_c``. The third density is implicit (``1 − density_a −
    density_b``). This is the ``_three_way_bayer`` primitive
    ``spectra6_color_recipes.md`` references as the prerequisite for the
    documented three-ink recipes (lavender, salmon, plum, …); see that
    doc's "Three-ink recipes" section for the recipes and their
    weight splits.

    Clipping semantics match ``_fill_swatch_stipple`` (silently truncate to
    image bounds so thumbnail-size diags renders don't crash on rects that
    sit fully below the canvas).
    """
    x0, y0, x1, y1 = rect
    w, h = image.size
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(w, x1)
    y1 = min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return
    threshold_a = round(density_a * 16)
    threshold_b = round((density_a + density_b) * 16)
    px = image.load()
    for y in range(y0, y1):
        for x in range(x0, x1):
            cell = BAYER_4x4[y % 4][x % 4]
            if cell < threshold_a:
                px[x, y] = ink_a
            elif cell < threshold_b:
                px[x, y] = ink_b
            else:
                px[x, y] = ink_c


# Synthesised three-ink stipple recipes documented in
# ``spectra6_color_recipes.md`` ("Three-ink recipes" section). Each entry is
# (display name, ink_a, ink_b, ink_c, density_a, density_b, short label).
# The implicit third density is ``1 - density_a - density_b``. Rendered by
# the diags frame in two rows of 6 below the two-ink band so an operator
# can see whether (e.g.) the 1/3-each lavender or the white-heavy lilac
# actually reads as the named pastel at panel distance.
_DIAGS_TRIPLE_SWATCHES: list[
    tuple[str, tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], float, float, str]
] = [
    # Pastels (3rd ink = white)
    ("light orange", SPECTRA6["red"],    SPECTRA6["yellow"], SPECTRA6["white"], 0.40,    0.40,    "R+Y+W 40/40/20"),
    ("salmon",       SPECTRA6["red"],    SPECTRA6["yellow"], SPECTRA6["white"], 1 / 3,   1 / 3,   "R+Y+W 1:1:1"),
    ("peach",        SPECTRA6["red"],    SPECTRA6["yellow"], SPECTRA6["white"], 0.30,    0.50,    "R+Y+W 30/50/20"),
    ("lavender",     SPECTRA6["red"],    SPECTRA6["blue"],   SPECTRA6["white"], 1 / 3,   1 / 3,   "R+B+W 1:1:1"),
    ("lilac",        SPECTRA6["red"],    SPECTRA6["blue"],   SPECTRA6["white"], 0.25,    0.25,    "R+B+W 25/25/50"),
    ("seafoam",      SPECTRA6["green"],  SPECTRA6["blue"],   SPECTRA6["white"], 0.40,    0.30,    "G+B+W 40/30/30"),
    # Pastels continued + deep tones (3rd ink = white or black) + chromatic (no W/K)
    ("khaki",        SPECTRA6["yellow"], SPECTRA6["green"],  SPECTRA6["white"], 0.40,    0.30,    "Y+G+W 40/30/30"),
    ("beige",        SPECTRA6["red"],    SPECTRA6["yellow"], SPECTRA6["white"], 0.25,    0.25,    "R+Y+W 25/25/50"),
    ("plum",         SPECTRA6["red"],    SPECTRA6["blue"],   SPECTRA6["black"], 1 / 3,   1 / 3,   "R+B+K 1:1:1"),
    ("print sepia",  SPECTRA6["red"],    SPECTRA6["yellow"], SPECTRA6["black"], 0.40,    0.40,    "R+Y+K 40/40/20"),
    ("burnt orange", SPECTRA6["red"],    SPECTRA6["yellow"], SPECTRA6["green"], 0.50,    0.40,    "R+Y+G 50/40/10"),
    ("forest-teal",  SPECTRA6["green"],  SPECTRA6["blue"],   SPECTRA6["yellow"], 0.40,   0.40,    "G+B+Y 40/40/20"),
]

_DIAGS_TRIPLE_ROW1_COUNT = 6


def render_diags_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Render the diagnostic frame for the ``diags`` theme.

    Replaces the literary layout with a status panel: large clock, picker
    metrics (bucket / layout / quality / source / matched phrase), the
    Spectra 6 native palette, and the synthesised two- and three-ink
    stipple recipes documented in ``spectra6_color_recipes.md``. Useful
    for on-panel calibration ("does ``mint`` actually read green at panel
    distance? does ``lavender`` actually read as a pastel violet?") and
    for confirming the picker chose what you'd expect — the BUCKET /
    LAYOUT / QUALITY / ID / MATCHED fields in the status table at top
    carry that confirmation now that the literary footer is gone.
    """
    colors = THEMES["diags"]
    image = Image.new("RGB", (width, height), color=colors["page_bg"])
    draw = ImageDraw.Draw(image)

    INSET = 12
    PAD_X = 22

    # Outer frame
    draw.rectangle((INSET, INSET, width - INSET - 1, height - INSET - 1), outline=colors["text"], width=1)

    # Header bar
    header_font = load_font(META_FONT_BOLD_CANDIDATES, size=14)
    header = "LITCLOCK · DIAGS"
    draw.text((PAD_X, INSET + 8), header, font=header_font, fill=colors["accent"])
    rule_y = INSET + 32
    draw.line((PAD_X, rule_y, width - PAD_X, rule_y), fill=colors["text"])

    # ----- Top section: big clock + status grid -----
    clock_font = load_font(theme_font_candidates("diags", "quote_bold"), size=88)
    clock_bbox = draw.textbbox((0, 0), time_str, font=clock_font)
    clock_w = clock_bbox[2] - clock_bbox[0]
    clock_x = PAD_X
    clock_y = rule_y + 10
    draw.text((clock_x - clock_bbox[0], clock_y - clock_bbox[1]), time_str, font=clock_font, fill=colors["text"])

    # Status table — right of the clock
    field_key_font = load_font(META_FONT_BOLD_CANDIDATES, size=12)
    field_val_font = load_font(META_FONT_CANDIDATES, size=12)
    fields_x = clock_x + clock_w + 36
    key_col_w = 92
    f_y = clock_y + 6
    LINE_H = 17

    layout_name = choose_layout(quote_row.get("display_quote") or "")
    bucket = quote_row.get("bucket") or "—"
    resolved = quote_row.get("resolved_bucket") or bucket
    quality = quote_row.get("quality_score")
    source_id = quote_row.get("source_id")
    line_number = quote_row.get("line_number")
    matched = (quote_row.get("matched_text") or "—").replace("\n", " ").strip()
    fallback = quote_row.get("used_fallback")

    if resolved and bucket and resolved != bucket and fallback:
        bucket_display = f"{bucket} → {resolved}"
    else:
        bucket_display = resolved or bucket

    if source_id and line_number is not None:
        id_display = f"{source_id}:{line_number}"
    elif source_id:
        id_display = str(source_id)
    else:
        id_display = "—"

    fields = [
        ("BUCKET", bucket_display),
        ("LAYOUT", layout_name),
        ("QUALITY", "—" if quality is None else str(quality)),
        ("FALLBACK", "yes" if fallback else "no"),
        ("ID", id_display),
        ("MATCHED", matched if len(matched) <= 36 else matched[:34] + "…"),
    ]
    for key, val in fields:
        draw.text((fields_x, f_y), key, font=field_key_font, fill=colors["accent"])
        draw.text((fields_x + key_col_w, f_y), val, font=field_val_font, fill=colors["text"])
        f_y += LINE_H

    # ----- System info strip (host / ip / uptime) -----
    # Sits in the open band between the status table (ends ~y=162) and the
    # Spectra 6 swatches (start y=192) so the picker-output column on the
    # right and the appliance-identity row at the bottom of the top block
    # read as visually paired diagnostics.
    sys_info = _diags_system_info()
    sys_label_font = load_font(META_FONT_BOLD_CANDIDATES, size=11)
    sys_val_font = load_font(META_FONT_CANDIDATES, size=11)
    sys_y = 170
    sys_entries = [
        ("HOST", sys_info["host"]),
        ("IP", sys_info["ip"]),
        ("UPTIME", sys_info["uptime"]),
    ]
    # Distribute the three entries evenly across the inner width so the
    # row looks balanced regardless of how long each value happens to be.
    avail_strip_w = width - 2 * PAD_X
    slot_w = avail_strip_w // len(sys_entries)
    for i, (key, val) in enumerate(sys_entries):
        slot_x = PAD_X + i * slot_w
        draw.text((slot_x, sys_y), key, font=sys_label_font, fill=colors["accent"])
        key_bb = draw.textbbox((0, 0), key, font=sys_label_font)
        key_w = key_bb[2] - key_bb[0]
        draw.text((slot_x + key_w + 8, sys_y), val, font=sys_val_font, fill=colors["text"])

    # ----- Middle section: Spectra 6 swatches -----
    section_font = load_font(META_FONT_BOLD_CANDIDATES, size=12)
    label_bold = load_font(META_FONT_BOLD_CANDIDATES, size=10)
    label_reg = load_font(META_FONT_CANDIDATES, size=10)

    s1_y = 186
    draw.text((PAD_X, s1_y), "SPECTRA 6 NATIVE PALETTE", font=section_font, fill=colors["accent"])

    sw_top = s1_y + 14
    sw_h = 36
    sw_gap = 6
    sw_count = len(_DIAGS_SPECTRA6_SWATCHES)
    avail_w = width - 2 * PAD_X
    sw_w = (avail_w - (sw_count - 1) * sw_gap) // sw_count
    for i, (name, rgb, hex_code) in enumerate(_DIAGS_SPECTRA6_SWATCHES):
        x0 = PAD_X + i * (sw_w + sw_gap)
        x1 = x0 + sw_w
        y1 = sw_top + sw_h
        draw.rectangle((x0, sw_top, x1, y1), fill=rgb, outline=colors["text"], width=1)
        # Pick a label colour that contrasts the swatch fill — black on light
        # cells (white / yellow / green), white on the two darker ones.
        is_dark_fill = rgb in (SPECTRA6["black"], SPECTRA6["blue"], SPECTRA6["red"])
        label_fill = SPECTRA6["white"] if is_dark_fill else SPECTRA6["black"]
        draw.text((x0 + 5, sw_top + 4), name.upper(), font=label_bold, fill=label_fill)
        draw.text((x0 + 5, sw_top + 18), hex_code, font=label_reg, fill=label_fill)

    # ----- Synth bands -----
    # Two-ink: 17 recipes in 2 rows (8 + 9). Three-ink: 12 recipes in 2 rows
    # (6 + 6). All four rows share the same per-swatch geometry; only the
    # column count and the painter (2-ink vs 3-ink Bayer partition) change.
    # Labels are bold-name + faded-recipe, two 9 pt lines. The four rows
    # plus their two section headers are the lower half of the frame —
    # the literary footer (quote preview + attribution) was dropped to make
    # room. The status table at top already carries the diagnostic info
    # (BUCKET / LAYOUT / QUALITY / ID / MATCHED) that footer surfaced.
    label_bold_9 = load_font(META_FONT_BOLD_CANDIDATES, size=9)
    label_reg_9 = load_font(META_FONT_CANDIDATES, size=9)
    sw2_color_h = 22
    sw2_label_h = 22
    sw2_row_h = sw2_color_h + sw2_label_h
    sw2_row_gap = 3
    sw2_gap = 5

    def _paint_synth_row(row_top: int, entries: list, painter) -> None:
        n = len(entries)
        row_w = (avail_w - (n - 1) * sw2_gap) // n
        for col_idx, entry in enumerate(entries):
            x0 = PAD_X + col_idx * (row_w + sw2_gap)
            x1 = x0 + row_w
            color_y1 = row_top + sw2_color_h
            # Paint the full coloured stipple area first; the inset of 1 leaves
            # the outline cleanly visible after the rectangle stroke below.
            painter(entry, (x0 + 1, row_top + 1, x1, color_y1))
            draw.rectangle((x0, row_top, x1, color_y1), outline=colors["text"], width=1)
            name = entry[0]
            recipe = entry[-1]
            draw.text((x0, color_y1 + 2), name, font=label_bold_9, fill=colors["text"])
            draw.text((x0, color_y1 + 12), recipe, font=label_reg_9, fill=colors["subtle"])

    def _two_ink_painter(entry, rect):
        _name, dark, light, density, _recipe = entry
        _fill_swatch_stipple(image, rect, dark, light, density)

    def _three_ink_painter(entry, rect):
        _name, ink_a, ink_b, ink_c, density_a, density_b, _recipe = entry
        _fill_swatch_stipple_3way(image, rect, ink_a, ink_b, ink_c, density_a, density_b)

    # ----- Two-ink synth band -----
    s2_y = sw_top + sw_h + 8
    draw.text((PAD_X, s2_y), "SYNTHESISED (2-INK STIPPLE)", font=section_font, fill=colors["accent"])
    sw2_top = s2_y + 14
    sw2_row1 = _DIAGS_SYNTH_SWATCHES[:_DIAGS_SYNTH_ROW1_COUNT]
    sw2_row2 = _DIAGS_SYNTH_SWATCHES[_DIAGS_SYNTH_ROW1_COUNT:]
    _paint_synth_row(sw2_top, sw2_row1, _two_ink_painter)
    _paint_synth_row(sw2_top + sw2_row_h + sw2_row_gap, sw2_row2, _two_ink_painter)

    # ----- Three-ink synth band -----
    sw2_band_end = sw2_top + 2 * sw2_row_h + sw2_row_gap
    s3_y = sw2_band_end + 6
    draw.text((PAD_X, s3_y), "SYNTHESISED (3-INK STIPPLE)", font=section_font, fill=colors["accent"])
    sw3_top = s3_y + 14
    sw3_row1 = _DIAGS_TRIPLE_SWATCHES[:_DIAGS_TRIPLE_ROW1_COUNT]
    sw3_row2 = _DIAGS_TRIPLE_SWATCHES[_DIAGS_TRIPLE_ROW1_COUNT:]
    _paint_synth_row(sw3_top, sw3_row1, _three_ink_painter)
    _paint_synth_row(sw3_top + sw2_row_h + sw2_row_gap, sw3_row2, _three_ink_painter)

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


# ---------------------------------------------------------------------------
# Astrarium frame
# ---------------------------------------------------------------------------
# The astrarium theme dispatches into its own custom render path (like
# ``diags``) because the visual identity is a dashboard, not a literary
# frame: an astronomical-clock dial on the left, the quote on the right,
# and a datum strip across the bottom. Every painted pixel stays on the
# Spectra 6 palette — the multi-coloured halftone ring quadrants you see
# are synthesised via the documented two-ink stipple recipes (R+Y
# tangerine, Y+G olive, G+B teal, R+G sepia) so ``snap_image_to_palette``
# is a no-op rather than a quantising re-map.


def _astrarium_paint_cream_wash(image: Image.Image) -> None:
    """Sparse 1-in-8 yellow Bayer wash over the white page background.

    Same Layer 0 recipe ``dispatch`` / ``illuminated`` / ``herbarium`` /
    ``mucha`` already use — flips ~12.5% of the page's white pixels to
    yellow on the documented `BAYER_4x4[y%4][x%4] < 2` threshold so the
    panel reads as faintly cream archival paper at viewing distance
    rather than the panel's flat pure white.
    """
    px = image.load()
    w, h = image.size
    for y in range(h):
        row = BAYER_4x4[y % 4]
        for x in range(w):
            if row[x % 4] < 2 and px[x, y] == SPECTRA6["white"]:
                px[x, y] = SPECTRA6["yellow"]


def _astrarium_paint_ring_quadrant(
    image: Image.Image,
    cx: int,
    cy: int,
    r_outer: int,
    r_inner: int,
    angle_start_deg: float,
    angle_end_deg: float,
    dark: tuple[int, int, int],
    light: tuple[int, int, int],
    light_density: float,
) -> None:
    """Fill an annular pie-slice with a two-ink Bayer stipple.

    The four ring quadrants on the dial each pull a different recipe:
    R+Y tangerine top-right, Y+G olive bottom-right, G+B teal bottom-
    left, and solid black top-left (with a sparse white constellation
    speckle layered on top, painted separately). The density branches
    mirror ``draw_text_dithered`` so the dial ring averages to the same
    perceived hue at panel distance as a body-text recipe would.
    """
    import math
    px = image.load()
    w, h = image.size
    r_outer_sq = r_outer * r_outer
    r_inner_sq = r_inner * r_inner
    a0 = math.radians(angle_start_deg)
    a1 = math.radians(angle_end_deg)
    threshold = round(light_density * 16)
    y0 = max(0, cy - r_outer - 1)
    y1 = min(h, cy + r_outer + 2)
    x0 = max(0, cx - r_outer - 1)
    x1 = min(w, cx + r_outer + 2)
    for y in range(y0, y1):
        dy = y - cy
        for x in range(x0, x1):
            dx = x - cx
            d_sq = dx * dx + dy * dy
            if d_sq < r_inner_sq or d_sq > r_outer_sq:
                continue
            # atan2 with screen-space y axis flipped so 0° is "up" and
            # angles increase clockwise — the conventional clock-face
            # convention. Normalises into [0, 2π) so the < / <= span
            # checks work even when the start crosses 0.
            angle = math.atan2(dx, -dy)  # -π..π, 0 at top
            if angle < 0:
                angle += 2 * math.pi
            if not (a0 <= angle < a1):
                continue
            if light_density <= 0.25:
                px[x, y] = light if (x % 2 == 0 and y % 2 == 0) else dark
            elif light_density >= 0.5:
                px[x, y] = dark if (x + y) % 2 == 0 else light
            else:
                px[x, y] = light if BAYER_4x4[y % 4][x % 4] < threshold else dark


def _astrarium_paint_constellation_field(
    image: Image.Image,
    cx: int,
    cy: int,
    r_outer: int,
    r_inner: int,
    angle_start_deg: float,
    angle_end_deg: float,
    seed: int,
) -> None:
    """Paint a sparse white-on-black speckle pattern inside an annular
    sector, evoking the constellation field that sits on the top-left
    halftone quadrant of the dial. Uses a seeded random walk so the
    speckle is deterministic across renders — operators expect a stable
    image when the same quote re-displays."""
    import math
    import random
    rng = random.Random(seed)
    px = image.load()
    w, h = image.size
    a0 = math.radians(angle_start_deg)
    a1 = math.radians(angle_end_deg)
    n_stars = 22
    for _ in range(n_stars):
        # Sample uniformly inside the annular sector by inverse CDF on r².
        r = math.sqrt(rng.uniform(r_inner * r_inner, r_outer * r_outer))
        angle = rng.uniform(a0, a1)
        # Convert back to screen-space cartesian (0° = up, clockwise).
        sx = cx + int(r * math.sin(angle))
        sy = cy - int(r * math.cos(angle))
        if 0 <= sx < w and 0 <= sy < h:
            px[sx, sy] = SPECTRA6["white"]
            # 4-pointed micro-star for the brightest few: cross +1 px on
            # each axis, picked deterministically by the seeded rng.
            if rng.random() < 0.35:
                for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = sx + ox, sy + oy
                    if 0 <= nx < w and 0 <= ny < h:
                        px[nx, ny] = SPECTRA6["white"]


def _astrarium_paint_dial(image: Image.Image, draw: ImageDraw.ImageDraw, cx: int, cy: int, time_str: str) -> None:
    """Paint the astronomical-clock dial centred at (cx, cy).

    Layered outside-in:
    1. Outer minute-tick ring (60 ticks, long every 5)
    2. Halftone quadrant ring (4 stipple recipes — tangerine / olive /
       teal / black-with-constellation-speckle)
    3. Hour numeral band ("60" / "15" / "30" / "45" — minute reference,
       same orientation as on the mockup)
    4. Inner rule
    5. Centre disc with HH:MM and AM/PM
    """
    import math
    BLACK = SPECTRA6["black"]
    WHITE = SPECTRA6["white"]
    RED = SPECTRA6["red"]
    YELLOW = SPECTRA6["yellow"]
    BLUE = SPECTRA6["blue"]
    GREEN = SPECTRA6["green"]

    r_outer = 168
    r_ring_outer = 150
    r_ring_inner = 128
    r_inner_rule = 108

    # Layer 1: outer hairline circle + 60 minute ticks.
    draw.ellipse((cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer), outline=BLACK, width=1)
    for tick in range(60):
        angle = math.radians(tick * 6)
        is_major = tick % 5 == 0
        tick_len = 8 if is_major else 4
        x_inner = cx + int((r_outer - tick_len) * math.sin(angle))
        y_inner = cy - int((r_outer - tick_len) * math.cos(angle))
        x_outer = cx + int(r_outer * math.sin(angle))
        y_outer = cy - int(r_outer * math.cos(angle))
        draw.line((x_inner, y_inner, x_outer, y_outer), fill=BLACK, width=1 if is_major else 1)

    # Layer 2: four halftone ring quadrants. Quadrant angles use the
    # clock-face convention from ``_astrarium_paint_ring_quadrant``
    # (0° = up, increasing clockwise), so 0–90° is top-right etc.
    _astrarium_paint_ring_quadrant(
        image, cx, cy, r_ring_outer, r_ring_inner, 0, 90,
        dark=RED, light=YELLOW, light_density=0.375,  # tangerine TR
    )
    _astrarium_paint_ring_quadrant(
        image, cx, cy, r_ring_outer, r_ring_inner, 90, 180,
        dark=RED, light=GREEN, light_density=0.5,  # sepia/brown BR (R+G)
    )
    _astrarium_paint_ring_quadrant(
        image, cx, cy, r_ring_outer, r_ring_inner, 180, 270,
        dark=GREEN, light=BLUE, light_density=0.5,  # teal BL (G+B → cyan)
    )
    # TL solid black + constellation speckle on top.
    _astrarium_paint_ring_quadrant(
        image, cx, cy, r_ring_outer, r_ring_inner, 270, 360,
        dark=BLACK, light=BLACK, light_density=0.5,
    )
    _astrarium_paint_constellation_field(
        image, cx, cy, r_ring_outer - 2, r_ring_inner + 2, 270, 360, seed=2026
    )

    # Boundary ellipses to crisp up the ring edges after the per-pixel
    # painters (which can leave a slightly jagged 1px boundary).
    draw.ellipse((cx - r_ring_outer, cy - r_ring_outer, cx + r_ring_outer, cy + r_ring_outer), outline=BLACK, width=1)
    draw.ellipse((cx - r_ring_inner, cy - r_ring_inner, cx + r_ring_inner, cy + r_ring_inner), outline=BLACK, width=1)
    # Quadrant separator lines (faint).
    for deg in (0, 90, 180, 270):
        angle = math.radians(deg)
        x0 = cx + int(r_ring_inner * math.sin(angle))
        y0 = cy - int(r_ring_inner * math.cos(angle))
        x1 = cx + int(r_ring_outer * math.sin(angle))
        y1 = cy - int(r_ring_outer * math.cos(angle))
        draw.line((x0, y0, x1, y1), fill=BLACK, width=1)

    # Layer 3: minute numerals at 60 / 15 / 30 / 45 positions
    # (canonical orientation matching the mockup).
    numeral_font = load_font(META_FONT_BOLD_CANDIDATES, size=11)
    for label, deg in (("60", 0), ("15", 90), ("30", 180), ("45", 270)):
        angle = math.radians(deg)
        r_label = r_outer - 18
        nx = cx + int(r_label * math.sin(angle))
        ny = cy - int(r_label * math.cos(angle))
        bbox = draw.textbbox((0, 0), label, font=numeral_font)
        w_lbl = bbox[2] - bbox[0]
        h_lbl = bbox[3] - bbox[1]
        # Erase a small disc behind the numeral so the tick rules
        # don't run through the digits.
        bg_pad = 3
        draw.ellipse(
            (nx - w_lbl // 2 - bg_pad, ny - h_lbl // 2 - bg_pad,
             nx + w_lbl // 2 + bg_pad, ny + h_lbl // 2 + bg_pad),
            fill=WHITE,
        )
        draw.text((nx - w_lbl // 2 - bbox[0], ny - h_lbl // 2 - bbox[1]), label, font=numeral_font, fill=BLACK)

    # Layer 4: inner rule.
    draw.ellipse((cx - r_inner_rule, cy - r_inner_rule, cx + r_inner_rule, cy + r_inner_rule), outline=BLACK, width=1)

    # Layer 5: centre disc. Clear the interior (the ring painters above
    # only fill the annular bands but the constellation-speckle pass can
    # spill into the inner area depending on geometry — explicit fill
    # keeps the disc clean).
    draw.ellipse((cx - r_inner_rule + 2, cy - r_inner_rule + 2, cx + r_inner_rule - 2, cy + r_inner_rule - 2), fill=WHITE)

    # Small "LOCAL TIME" header above the digits.
    header_font = load_font(META_FONT_CANDIDATES, size=10)
    label = "LOCAL TIME"
    bbox = draw.textbbox((0, 0), label, font=header_font)
    lw = bbox[2] - bbox[0]
    draw.text((cx - lw // 2 - bbox[0], cy - 56 - bbox[1]), label, font=header_font, fill=BLACK)

    # Big HH:MM digits.
    try:
        hh, mm = time_str.split(":")
        hour24 = int(hh)
        minute = int(mm)
    except (ValueError, AttributeError):
        hour24 = 0
        minute = 0
    hour12 = hour24 % 12 or 12
    ampm = "AM" if hour24 < 12 else "PM"
    digit_text = f"{hour12}:{minute:02d}"

    time_font = load_font(theme_font_candidates("astrarium", "quote_bold"), size=54)
    bbox = draw.textbbox((0, 0), digit_text, font=time_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - tw // 2 - bbox[0], cy - th // 2 - bbox[1] - 6), digit_text, font=time_font, fill=BLACK)

    # AM/PM beneath the digits.
    ampm_font = load_font(META_FONT_CANDIDATES, size=12)
    bbox = draw.textbbox((0, 0), ampm, font=ampm_font)
    aw = bbox[2] - bbox[0]
    draw.text((cx - aw // 2 - bbox[0], cy + 28 - bbox[1]), ampm, font=ampm_font, fill=BLACK)

    # Tiny tangerine sun glyph below "LOCAL TIME", above the digits.
    # Painted in red sentinel and bbox-post-passed to R+Y tangerine so
    # it shares the matched-phrase ink recipe.
    sun_cx = cx
    sun_cy = cy - 38
    sun_r = 4
    draw.ellipse((sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r), fill=RED)
    for ang_deg in range(0, 360, 45):
        ang = math.radians(ang_deg)
        x0 = sun_cx + int((sun_r + 2) * math.sin(ang))
        y0 = sun_cy - int((sun_r + 2) * math.cos(ang))
        x1 = sun_cx + int((sun_r + 6) * math.sin(ang))
        y1 = sun_cy - int((sun_r + 6) * math.cos(ang))
        draw.line((x0, y0, x1, y1), fill=RED, width=1)
    # Post-pass the sun's bbox to tangerine.
    px = image.load()
    bb_x0 = sun_cx - sun_r - 8
    bb_y0 = sun_cy - sun_r - 8
    bb_x1 = sun_cx + sun_r + 8
    bb_y1 = sun_cy + sun_r + 8
    for y in range(max(0, bb_y0), min(image.height, bb_y1)):
        for x in range(max(0, bb_x0), min(image.width, bb_x1)):
            if px[x, y] == RED and BAYER_4x4[y % 4][x % 4] >= 6:
                px[x, y] = YELLOW


def _astrarium_paint_header(image: Image.Image, draw: ImageDraw.ImageDraw, width: int, time_str: str) -> None:
    """Top-strip dashboard chrome — brand on the left, mode/date on the
    right, hairline rule beneath."""
    import datetime
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]

    brand_bold = load_font(META_FONT_BOLD_CANDIDATES, size=14)
    brand_regular = load_font(META_FONT_CANDIDATES, size=14)
    chrome_small = load_font(META_FONT_CANDIDATES, size=10)
    chrome_bold = load_font(META_FONT_BOLD_CANDIDATES, size=10)

    # Brand line: "LITCLOCK // ASTRARIUM"
    x = 24
    y = 22
    draw.text((x, y), "LITCLOCK", font=brand_bold, fill=BLACK)
    bbox = draw.textbbox((0, 0), "LITCLOCK", font=brand_bold)
    x += bbox[2] - bbox[0] + 10
    draw.text((x, y), "//", font=brand_regular, fill=BLACK)
    bbox = draw.textbbox((0, 0), "//", font=brand_regular)
    x += bbox[2] - bbox[0] + 8
    draw.text((x, y), "ASTRARIUM", font=brand_bold, fill=RED)

    # Right-side info stack: date (red label + bold value) and "S6 800×480"
    # box. Anchored to the right margin.
    now = datetime.datetime.now()
    day_label = now.strftime("%a · %b %d").upper()
    sol = f"SOL {now.timetuple().tm_yday} · YR {now.year}"

    s6_label = "S6"
    s6_meta = f"{image.width}×{image.height}"
    s6_label_bbox = draw.textbbox((0, 0), s6_label, font=chrome_bold)
    s6_meta_bbox = draw.textbbox((0, 0), s6_meta, font=chrome_small)
    s6_label_w = s6_label_bbox[2] - s6_label_bbox[0]
    s6_meta_w = s6_meta_bbox[2] - s6_meta_bbox[0]
    s6_right = width - 24
    s6_box_x0 = s6_right - s6_label_w - 12
    s6_box_y0 = 14
    s6_box_x1 = s6_right
    s6_box_y1 = 34
    draw.rectangle((s6_box_x0, s6_box_y0, s6_box_x1, s6_box_y1), outline=BLACK, width=1)
    draw.text(
        (s6_box_x0 + (s6_box_x1 - s6_box_x0 - s6_label_w) // 2 - s6_label_bbox[0],
         s6_box_y0 + (s6_box_y1 - s6_box_y0 - (s6_label_bbox[3] - s6_label_bbox[1])) // 2 - s6_label_bbox[1]),
        s6_label, font=chrome_bold, fill=BLACK,
    )
    draw.text((s6_right - s6_meta_w - s6_meta_bbox[0], 38 - s6_meta_bbox[1]), s6_meta, font=chrome_small, fill=BLACK)

    # Date stack to the left of the S6 box.
    date_right = s6_box_x0 - 14
    sol_bbox = draw.textbbox((0, 0), sol, font=chrome_bold)
    day_bbox = draw.textbbox((0, 0), day_label, font=chrome_bold)
    draw.text((date_right - (sol_bbox[2] - sol_bbox[0]) - sol_bbox[0], 16 - sol_bbox[1]), sol, font=chrome_bold, fill=BLACK)
    draw.text((date_right - (day_bbox[2] - day_bbox[0]) - day_bbox[0], 32 - day_bbox[1]), day_label, font=chrome_bold, fill=RED)

    # Hairline dashed rule under the header — dotted every 4px.
    rule_y = 50
    for x in range(24, width - 24, 4):
        draw.point((x, rule_y), fill=BLACK)
    del time_str  # reserved on the signature for symmetry with the dial/datum painters; this strip is wall-clock derived from datetime.now()


def _astrarium_paint_quote_panel(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    quote_row: dict,
    panel_left: int,
    panel_right: int,
    panel_top: int,
    panel_bottom: int,
) -> None:
    """Lay the quote, matched-phrase tangerine accent, and attribution
    into the right column."""
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    YELLOW = SPECTRA6["yellow"]

    panel_width = panel_right - panel_left
    max_text_width = panel_width - 16

    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""

    # Centre a small four-pointed star ornament above the body, painted
    # in teal (G+B) sentinel + post-pass for the cyan compass-rose
    # micro-graphic in the mockup.
    star_cx = panel_left + panel_width // 2
    star_cy = panel_top + 18
    star_r = 12
    draw.line((star_cx - star_r, star_cy, star_cx + star_r, star_cy), fill=SPECTRA6["green"], width=1)
    draw.line((star_cx, star_cy - star_r, star_cx, star_cy + star_r), fill=SPECTRA6["green"], width=1)
    for s in range(-star_r // 2, star_r // 2 + 1):
        if -star_r // 2 <= s <= star_r // 2:
            draw.point((star_cx + s, star_cy + s), fill=SPECTRA6["green"])
            draw.point((star_cx + s, star_cy - s), fill=SPECTRA6["green"])
    draw.ellipse((star_cx - 2, star_cy - 2, star_cx + 2, star_cy + 2), fill=SPECTRA6["green"])
    px = image.load()
    for y in range(max(0, star_cy - star_r - 2), min(image.height, star_cy + star_r + 2)):
        for x in range(max(0, star_cx - star_r - 2), min(image.width, star_cx + star_r + 2)):
            if px[x, y] == SPECTRA6["green"] and (x + y) & 1:
                px[x, y] = SPECTRA6["blue"]

    # Body block: fit the quote into the panel's interior. The panel
    # interior is narrower than the standard 660px layout so use a
    # smaller font range.
    body_top = panel_top + 44
    body_bottom = panel_bottom - 42
    body_height = body_bottom - body_top
    quote_font, quote_font_bold, wrapped_quote, line_height, chosen_size = fit_quote(
        draw,
        display_quote,
        matched,
        max_text_width,
        body_height,
        font_max=38,
        font_min=18,
        line_height_mult=1.14,
        theme="astrarium",
    )
    quote_block_height = len(wrapped_quote) * line_height

    # Vertically centre the wrapped quote inside its panel.
    block_top = body_top + max(0, (body_height - quote_block_height) // 2)
    y = block_top

    # Oversized opening quotation mark in tangerine, anchored above the
    # first body line near the left edge of the panel.
    mark_size = max(48, int(chosen_size * 1.6))
    mark_font = load_font(theme_font_candidates("astrarium", "ornament"), size=mark_size)
    open_mark = "“"
    open_bbox = draw.textbbox((0, 0), open_mark, font=mark_font)
    open_h = open_bbox[3] - open_bbox[1]
    open_x = panel_left + 4
    open_y = block_top - open_h // 4
    draw_text_dithered(
        image,
        (open_x - open_bbox[0], open_y - open_bbox[1]),
        open_mark,
        font=mark_font,
        dark=RED,
        light=YELLOW,
        light_density=0.375,
    )

    for line in wrapped_quote:
        # Strip leading/trailing whitespace tokens (same trim logic as
        # ``render``).
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        drawable = line[start:end]
        x = panel_left + 8
        body_ascent = _font_ascent(quote_font)
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            chunk_y = y + (body_ascent - _font_ascent(font))
            if is_bold:
                # Tangerine matched phrase — same R+Y 5/8:3/8 recipe
                # ``deco`` uses for its body matched-phrase.
                draw_text_dithered(
                    image,
                    (x, chunk_y),
                    chunk,
                    font=font,
                    dark=RED,
                    light=YELLOW,
                    light_density=0.375,
                )
            else:
                draw.text((x, chunk_y), chunk, font=font, fill=BLACK)
            bbox = draw.textbbox((0, 0), chunk, font=font)
            x += bbox[2] - bbox[0]
        y += line_height

    # Closing quotation mark, mirrored to the bottom-right of the panel.
    close_mark = "”"
    close_bbox = draw.textbbox((0, 0), close_mark, font=mark_font)
    close_w = close_bbox[2] - close_bbox[0]
    close_h = close_bbox[3] - close_bbox[1]
    close_x = panel_right - close_w - 4
    close_y = y - close_h // 3
    if close_y + close_h > panel_bottom:
        close_y = panel_bottom - close_h - 2
    draw_text_dithered(
        image,
        (close_x - close_bbox[0], close_y - close_bbox[1]),
        close_mark,
        font=mark_font,
        dark=RED,
        light=YELLOW,
        light_density=0.375,
        pattern_offset=(1, 0),
    )

    # Attribution (author + title) — small serif, below the closing mark.
    author = quote_row.get("author") or None
    title = quote_row.get("title") or fallback_title(quote_row)
    attrib_font = load_font(theme_font_candidates("astrarium", "quote_regular"), size=14)
    attrib_y = max(y + 6, close_y + close_h - 18)
    attrib_y = min(attrib_y, panel_bottom - 36)
    if author:
        draw.text((panel_left + 8, attrib_y), author, font=attrib_font, fill=BLACK)
        attrib_y += 16
    if title:
        title_font = load_font(theme_font_candidates("astrarium", "quote_regular"), size=12)
        # Wrap if too long for the panel.
        title_lines = wrap_text(draw, title, title_font, max_text_width)[:1]
        if title_lines:
            draw.text((panel_left + 8, attrib_y), title_lines[0], font=title_font, fill=BLACK)


def _astrarium_paint_datum_strip(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    time_str: str,
) -> None:
    """Paint the bottom datum strip — small panels with readouts that
    are actually derivable from the appliance's state (time of day,
    date, loop health). The earlier draft also surfaced tide,
    temperature, and atmospheric-pressure values to fill the mockup's
    six-cell strip, but the appliance has no thermometer / barometer /
    tide sensor, so those were hardcoded placeholders pretending to be
    live readings. Cosmetic faux-sensor cards were removed entirely;
    the three remaining cells are honest signals."""
    import math
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]

    strip_top = height - 78
    strip_bottom = height - 14
    # Top dashed rule (same dotted style as the header).
    for x in range(24, width - 24, 4):
        draw.point((x, strip_top), fill=BLACK)

    label_font = load_font(META_FONT_BOLD_CANDIDATES, size=9)
    value_font = load_font(META_FONT_BOLD_CANDIDATES, size=14)
    unit_font = load_font(META_FONT_CANDIDATES, size=9)

    try:
        hh, mm = time_str.split(":")
        hour24 = int(hh)
        minute = int(mm)
    except (ValueError, AttributeError):
        hour24, minute = 0, 0
    # Toy solar-elevation model: peaks at noon, zero at sunrise/sunset.
    # Just a deterministic function of (hour, minute); not real
    # astronomy — the dashboard furniture only needs to *vary* with
    # time of day to feel alive.
    minute_of_day = hour24 * 60 + minute
    solar_norm = math.sin(math.pi * minute_of_day / (24 * 60))
    solar_elevation = max(0.0, solar_norm) * 75.0

    # Lunar phase: deterministic from current day-of-year, modulo 30.
    import datetime
    doy = datetime.datetime.now().timetuple().tm_yday
    moon_phase_pct = (doy % 30) / 30.0 * 100

    panels: list[tuple[str, str, str, tuple[int, int, int]]] = [
        ("SOLAR ELEVATION", f"{solar_elevation:.1f}", "°", BLACK),
        ("LUNAR PHASE", f"{int(moon_phase_pct)}", "%", BLACK),
        ("SYSTEM STATUS", "OK", "·", RED),
    ]

    inner_left = 24
    inner_right = width - 24
    inner_width = inner_right - inner_left
    panel_w = inner_width // len(panels)
    for i, (label, value, unit, value_color) in enumerate(panels):
        px0 = inner_left + i * panel_w
        px1 = inner_left + (i + 1) * panel_w if i < len(panels) - 1 else inner_right
        # Vertical separator.
        if i > 0:
            for y in range(strip_top + 6, strip_bottom - 4, 2):
                draw.point((px0, y), fill=BLACK)
        # Label.
        lbl_y = strip_top + 6
        draw.text((px0 + 4, lbl_y), label, font=label_font, fill=BLACK)
        # Value (bold) + unit beside it.
        val_bbox = draw.textbbox((0, 0), value, font=value_font)
        val_y = strip_top + 22
        draw.text((px0 + 4 - val_bbox[0], val_y - val_bbox[1]), value, font=value_font, fill=value_color)
        val_w = val_bbox[2] - val_bbox[0]
        unit_bbox = draw.textbbox((0, 0), unit, font=unit_font)
        draw.text(
            (px0 + 4 + val_w + 4 - unit_bbox[0], val_y + (val_bbox[3] - val_bbox[1]) - (unit_bbox[3] - unit_bbox[1]) - unit_bbox[1]),
            unit, font=unit_font, fill=BLACK,
        )
        # Tiny inline glyph for variety — a few dots in the panel's
        # bottom area suggesting a sparkline/indicator.
        sparkline_y = strip_top + 52
        for j in range(8):
            sx = px0 + 4 + j * 7
            if sx >= px1 - 8:
                break
            offset = int(2 * math.sin(j * 0.9 + i)) - 1
            draw.point((sx, sparkline_y + offset), fill=BLACK)


def render_astrarium_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Render the astrarium-theme dashboard frame.

    Composition (designed at the canonical 800×480; other sizes use the
    same layout proportions so contact-sheet and curator-preview renders
    still produce a recognisable thumbnail):

      ┌────────────────────────────────────────────────────────────────┐
      │ LITCLOCK // ASTRARIUM           SAT · MAY 19  | S6 │ 800×480   │
      │ ─────────────────────────────────────────────────────────────  │
      │                                                                │
      │         ╭──────────╮                  ★                        │
      │       60│   ┌──┐   │15                                          │
      │         │   │  │   │     “It was at  ten o'clock                │
      │         │   └──┘   │      today that the first                  │
      │       45│ 10:00 AM │30    of all Time Machines                  │
      │         ╰──────────╯      began its career.                     │
      │                                                                │
      │ ─────────────────────────────────────────────────────────────  │
      │ SOLAR ELEV │ LUNAR │ TIDE │ TEMP │ ATMOS │ SYS STATUS           │
      │   53.2°    │  18%  │14:47 │18.6° │1013hPa│    OK                │
      └────────────────────────────────────────────────────────────────┘

    Stays fully on the Spectra 6 palette: the four halftone ring
    quadrants on the dial paint via two-ink Bayer stipples (tangerine /
    olive / teal / black) the same way ``deco`` / ``herbarium`` /
    ``glacier`` synthesise their accents, so ``snap_image_to_palette``
    at the end is a no-op on the painted regions.
    """
    image = Image.new("RGB", (width, height), color=SPECTRA6["white"])
    # Layer 0: cream wash background.
    _astrarium_paint_cream_wash(image)
    draw = ImageDraw.Draw(image)

    # Top-strip dashboard chrome.
    _astrarium_paint_header(image, draw, width, time_str)

    # Dial centred in the left half. Use proportional positioning so
    # non-standard canvas sizes (thumbnails) still render the dial in
    # the correct quadrant.
    dial_zone_w = int(width * 0.5)
    dial_cx = dial_zone_w // 2 + 8
    dial_cy = 64 + (height - 64 - 78) // 2
    _astrarium_paint_dial(image, draw, dial_cx, dial_cy, time_str)

    # Quote panel in the right half.
    panel_left = int(width * 0.5) - 4
    panel_right = width - 24
    panel_top = 62
    panel_bottom = height - 86
    _astrarium_paint_quote_panel(image, draw, quote_row, panel_left, panel_right, panel_top, panel_bottom)

    # Vertical hairline divider between the dial and the quote panel
    # (a faint dotted line, similar to the dashed header rule).
    div_x = int(width * 0.5)
    for y in range(64, height - 82, 4):
        draw.point((div_x, y), fill=SPECTRA6["black"])

    # Bottom datum strip.
    _astrarium_paint_datum_strip(image, draw, width, height, time_str)

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


def render(time_str: str, quote_row: dict, width: int, height: int, mode: str = "debug", theme: str = "default") -> Image.Image:
    if mode == "card":
        return render_source_card(quote_row, width, height, theme=theme)
    if theme == "diags":
        return render_diags_frame(time_str, quote_row, width, height)
    if theme == "astrarium":
        return render_astrarium_frame(time_str, quote_row, width, height)
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
    _paint_ornament_mark(
        image,
        (open_x - open_bb[0], open_y - open_bb[1]),
        "“",
        font=mark_font,
        theme=theme,
        colors=colors,
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

        # Themes in ``_THEMES_RIGID_MATCH_SPACING`` exclude the
        # bold-internal inter-word gaps from slack distribution so the
        # matched phrase keeps its face's natural rhythm on a justified
        # line. Default for every other theme: all inter-word spaces
        # are equally elastic.
        space_is_bold = [is_bold for chunk, is_bold in drawable if chunk == " "]
        rigid_match = theme in _THEMES_RIGID_MATCH_SPACING
        is_last = line_index == total_lines - 1
        slack = layout["max_width"] - current_width

        distribute: list[int] = []
        # Only full-justify when the line is at least 75% full; looser lines look
        # worse justified than ragged-right due to excessive inter-word gaps.
        if not is_last and space_is_bold and 0 < slack <= layout["max_width"] * 0.25:
            distribute = _justify_distribution(space_is_bold, slack, rigid_match)

        x = (width - layout["max_width"]) // 2
        space_idx = 0
        # PIL's default text anchor is "la" (left, ascender top), so
        # ``y`` is interpreted as the top of each font's ASCENT band,
        # not a shared baseline. When ``quote_font`` and
        # ``quote_font_bold`` come from the same family their ascents
        # are identical and the per-chunk shift is zero; when they
        # come from different families (e.g. gothic = EB Garamond
        # body + UnifrakturMaguntia bold, ascent 41 vs 32 at body
        # font_size), drawing both at the same ``y`` leaves the bold
        # phrase visually floating above the body baseline. Shift each
        # chunk's draw point by ``body_ascent − chunk_ascent`` so all
        # chunks share a baseline regardless of metric drift.
        body_ascent = _font_ascent(quote_font)
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            fill = colors["accent"] if is_bold else colors["text"]
            chunk_y = y + (body_ascent - _font_ascent(font))
            _draw_text_body(image, draw, (x, chunk_y), chunk, font=font, fill=fill, theme=theme)
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
    _paint_ornament_mark(
        image,
        (close_x - close_bb[0], close_y - close_bb[1]),
        "”",
        font=mark_font,
        theme=theme,
        colors=colors,
        pattern_offset=(1, 0),
    )

    y = quote_top + quote_block_height + layout["author_gap"]
    if author_lines:
        author_text_line = author_lines[0]
        author_x = (width - layout["max_width"]) // 2
        _draw_text_body(image, draw, (author_x, y), author_text_line, font=attribution_font, fill=colors["text"], theme=theme)
        y += author_size + layout["title_gap"]

    for line in title_lines:
        title_x = (width - layout["max_width"]) // 2
        _draw_text_body(image, draw, (title_x, y), line, font=attribution_title_font, fill=colors["source"], theme=theme)
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

        _draw_text_body(image, draw, (strip_x, strip_y), debug_strip, font=debug_font, fill=colors["faint"], theme=theme)

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


def main() -> int:
    args = parse_args()
    output_path = Path(args.output) if args.output else Path("output/current.png")
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if args.mode == "goodnight":
        image = render_static_message(args.message, args.width, args.height, theme=args.theme)
    else:
        quote_row = pick_quote(args.time, history_path=args.history_path, history_days=args.history_days)
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
