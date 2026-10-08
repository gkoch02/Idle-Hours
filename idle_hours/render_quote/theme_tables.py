"""Per-theme data: colours, cycle order, font roles and the small per-theme flags.

Transitional (issue #335): the registry stage derives these from each theme module's spec.
"""

from __future__ import annotations

from ._paths import (
    _HAND_SCRIPT_BOLD,
    _HAND_SCRIPT_REGULAR,
    ALEGREYA_BOLD,
    ALEGREYA_ITALIC,
    ALEGREYA_REGULAR,
    ALFA_SLAB_ONE,
    ALMENDRA_BOLD,
    ALMENDRA_DISPLAY,
    ALMENDRA_REGULAR,
    ANTONIO_VARIABLE,
    ARCHIVO_BOLD,
    ARCHIVO_REGULAR,
    ARCHIVONARROW_VARIABLE,
    ATOMICAGE_REGULAR,
    BANGERS_REGULAR,
    BARLOW_BOLD,
    BARLOW_MEDIUM,
    BARLOW_REGULAR,
    BARLOW_SEMIBOLD,
    BARLOWCOND_BOLD,
    BARLOWCOND_MEDIUM,
    BARLOWCOND_REGULAR,
    BARLOWCOND_SEMIBOLD,
    BEBASNEUE_REGULAR,
    BERKSHIRE_SWASH_REGULAR,
    BITTER_VARIABLE,
    BUNGEE_SHADE_REGULAR,
    CAESARDRESSING_REGULAR,
    CARDO_BOLD,
    CARDO_ITALIC,
    CARDO_REGULAR,
    CINZELDECORATIVE_BLACK,
    CINZELDECORATIVE_BOLD,
    CINZELDECORATIVE_REGULAR,
    CORMORANT_VARIABLE,
    DANCINGSCRIPT_VARIABLE,
    EAGLELAKE_REGULAR,
    EBGARAMOND_BOLD,
    EBGARAMOND_REGULAR,
    EXO2_ITALIC_VARIABLE,
    EXO2_VARIABLE,
    FONDAMENTO_ITALIC,
    FONDAMENTO_REGULAR,
    FRAUNCES_ITALIC_VARIABLE,
    FRAUNCES_VARIABLE,
    GRENZE_GOTISCH_VARIABLE,
    ICELAND_REGULAR,
    IMFELLDOUBLEPICA_ITALIC,
    IMFELLDOUBLEPICA_REGULAR,
    IMFELLENGLISH_ITALIC,
    IMFELLENGLISH_REGULAR,
    INTER_VARIABLE,
    JOST_VARIABLE,
    JURA_BOLD,
    JURA_MEDIUM,
    JURA_SEMIBOLD,
    LATO_BOLD,
    LATO_ITALIC,
    LATO_REGULAR,
    LIBREBASKERVILLE_ITALIC_VARIABLE,
    LIBREBASKERVILLE_VARIABLE,
    LIBRECASLON_VARIABLE,
    LIBREFRANKLIN_ITALIC_VARIABLE,
    LIBREFRANKLIN_VARIABLE,
    LUMEN_VARIABLE,
    MEDIEVALSHARP_REGULAR,
    META_FONT_BOLD_CANDIDATES,
    META_FONT_CANDIDATES,
    MICHROMA_REGULAR,
    MONTSERRAT_VARIABLE,
    OLDSTANDARD_BOLD,
    OLDSTANDARD_REGULAR,
    ORNAMENT_FONT_CANDIDATES,
    OSWALD_VARIABLE,
    OXANIUM_VARIABLE,
    PATRICK_HAND_SC_REGULAR,
    PERMANENTMARKER_REGULAR,
    PINYONSCRIPT_REGULAR,
    PIXELIFYSANS_VARIABLE,
    PLAYWRITE_GB_J_GUIDES_REGULAR,
    PLEXMONO_BOLD,
    PLEXMONO_MEDIUM,
    PRESSSTART2P_REGULAR,
    QUICKSAND_BOLD,
    QUICKSAND_REGULAR,
    QUOTE_FONT_BOLD_CANDIDATES,
    QUOTE_FONT_REGULAR_CANDIDATES,
    QUOTE_FONT_SEMIBOLD_CANDIDATES,
    RIGHTEOUS_REGULAR,
    RUBIK_VARIABLE,
    RYE_REGULAR,
    SAIRA_ITALIC_VARIABLE,
    SAIRA_VARIABLE,
    SHOJUMARU_REGULAR,
    SILKSCREEN_BOLD,
    SILKSCREEN_REGULAR,
    SPACEMONO_BOLD,
    SPACEMONO_REGULAR,
    SPECIALELITE_REGULAR,
    SPECTRAL_MEDIUM,
    SPECTRAL_SEMIBOLD,
    TITILLIUM_BOLD,
    TITILLIUM_ITALIC,
    TITILLIUM_REGULAR,
    TITILLIUM_SEMIBOLD,
    UNCIALANTIQUA_REGULAR,
    UNIFRAKTUR_BOOK,
    YUJI_BOKU_REGULAR,
)
from .palette import SPECTRA6

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
    "kanagawa",
    "marquee",
    "tarot",
    "vinyl",
    "vitrail",
    "cartograph",
    "questline",
    "chrono",
    "outrun",
    "circuit",
    "letter",
    "grimdark",
    "sampler",
    "anna_atkins",
    "lieder",
    "izakaya",
    "abyssal",
    "pride",
    "pulp",
    "synoptic",
    "vhs",
    "bakelite",
    "cardcatalog",
    "metro",
    "intaglio",
    "nocturne",
    "plaque",
    "daguerreotype",
    "autochrome",
    "photo",
    "betweenus",
    "betweenus_dark",
    "carcosa",
    "control",
    "observation",
    "trisolaris",
    "biomech",
    "codex",
    "culture",
    "orbital",
    "furies",
    "bosch",
    "semiotic",
    "atropos",
    "saros",
    "expedition",
    "witcher",
    "hades",
    "expanse",
    "beksinski",
    "goya",
    "hal",
    "lumon",
    "dsky",
    "oblivion",
    "yorha",
    "hitchhiker",
    "escritoire",
    "lasvegas",
    "bladerunner",
    "traumateam",
    "redacted",
    "gantry",
    "platform",
    "splitflap",
    "diags",
)
# Themes registered in THEMES but excluded from every rotation (button B, web
# dropdown, auto, random); reachable only via explicit `--theme NAME`.
# RANDOM_EXCLUDED_THEMES filters only --theme random. Use this for themes worth
# keeping as opt-in but not ready for unattended rotation.
CYCLE_EXCLUDED_THEMES: frozenset[str] = frozenset({"vinyl"})
# Who reads a custom-frame theme's palette. A theme with its own
# ``render_<theme>_frame`` paints its own inks, but still needs a THEMES entry,
# because three paths draw from the palette alone and never call the frame:
#
# * ``render_source_card`` — the button-C overlay (``render`` checks
#   ``mode == "card"`` before dispatching to any frame);
# * ``render_static_message`` — ``--mode goodnight --message TEXT`` only;
# * ``contact_sheet`` — the sheet's gutters, captions and placeholder tiles.
#
# The quiet-hours sleep frame is NOT one of them: ``render_sleep_frame`` goes
# through ``render`` like any quote, so it uses the theme's own frame. New
# entries should point at this note rather than restate it. (``diags`` also
# reads its own entry, for its status labels.)
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
    # Between Us, light: the app's warm-paper card UI (see the section comment
    # above ``draw_betweenus_border``). White ground carrying a cream gradient
    # wash, black Fraunces body, the matched phrase in *italic* solid red —
    # the panel's red is the app's ``love`` terracotta unmixed, and a solid
    # ink keeps the italic's thin strokes whole. Both ornament slots take the
    # page ground: the app has no quotation-mark ornaments and the marks are
    # skipped outright in ``_paint_ornament_mark``.
    "betweenus": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["white"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Between Us, dark: the app's dark set is not an inversion of the light
    # one — the same warm paper on a near-black ground, accents lightened so
    # they stay readable. Black ground with a sparse red + white wash, white
    # Fraunces body, and a yellow *sentinel* accent that ``_draw_text_body``
    # reroutes to the R+Y 1:1 amber — the apricot the app's dark ``want``
    # becomes on the panel. The sentinel only surfaces literally in the
    # debug banner, where yellow-on-black is legible (the ``anna_atkins`` /
    # ``firmament`` pattern). Ornaments skipped, as for the light variant.
    "betweenus_dark": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["black"],
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
    # yellow accent for the matched phrase. Pure green reads dim and muddy on
    # black at viewing distance, so ``_draw_text_body`` stipples green body
    # glyphs 50/50 with white (``draw_text_dithered``) to lift them to a
    # brighter mint. The quote marks dither green/white for the same tone.
    # The corner brackets and scanlines in ``draw_nightvision_border`` stay
    # solid green: their HUD silhouette would break under stippling.
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
    # Cyanotype blueprint. Blue paper, white ink for body, frame and grid,
    # with the registration crosshairs and matched phrase in red — the
    # drafter's red-pencil callout. ``draw_blueprint_border``'s Layer 0 paints
    # a 50/50 white/blue checkerboard so the ground reads as a paler cyanotype
    # wash. Inverted polarity plus Archivo keep it distinct from ``scholar``.
    "blueprint": {
        "page_bg": SPECTRA6["blue"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["red"],
        # Both ornament keys white: the quote marks render solid white rather
        # than dithered (same trick as ``gothic`` / ``illuminated``).
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
    # Cathedral chronicle. Black ground, white body, red rubric for the
    # matched phrase and the oversized blackletter quote marks.
    # UnifrakturMaguntia fills both the ornament and quote-bold slots; body
    # stays in EB Garamond so dense layouts still read. Opposite polarity to
    # ``illuminated``.
    "gothic": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["red"],
        # Both ornament keys red: the marks dither between ornament_dark and
        # ornament_light (``draw_faux_gray_text``), and on a black ground a
        # white half would show and wash the rubric pinkish-grey. Pinning
        # both to red collapses the dither to solid red.
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
    # Risograph / zine two-colour print. Red body, blue "overprint" on the
    # matched phrase, and no black ink anywhere — that constraint defines the
    # theme and is pinned as a test invariant. ornament_dark is blue so the
    # quote marks carry the second-colour texture. Rubik gives the zine
    # register.
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
    # Golden-age comic panel. Yellow ground, black body for speech-bubble
    # legibility, red matched phrase like a sound-effect callout. Bangers is
    # an all-caps comic hand; the body shouting slightly is the point.
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
    # ink, red matched phrase — the bichrome ribbon. Special Elite's uneven
    # inking does most of the work; ``draw_dispatch_border`` adds the frame,
    # tractor-feed perforations and red rubber stamp. Same palette as
    # ``default``, different silhouette.
    "dispatch": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        # Half-density quote marks (black/white dither) mimic worn-ribbon
        # inking; a solid mark would erase that texture.
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Mid-century atomic age. The only theme with flat green as its ground,
    # softened by ``draw_atomic_border``'s Layer 0 (one white pixel per 2×2
    # tile — a 50/50 checkerboard reads minty pastel; 1-in-4 stays vivid).
    # Black body in Atomic Age, red matched phrase and graphics: a
    # rounded-corner Googie frame, an atom symbol at the top, and starbursts
    # at the mid-edges.
    "atomic": {
        "page_bg": SPECTRA6["green"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        # Both ornament keys red so the quote marks render solid against the
        # dithered ground instead of half-density (same trick as `gothic`).
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["red"],
        "source": SPECTRA6["black"],
    },
    # Printed circuit board. ``draw_circuit_border``'s Layer 0 flips half the
    # green ground to black on the (x+y) checkerboard so the soldermask reads
    # as FR-4 bottle-green (G+K 1:1) — the opposite of ``atomic``, which
    # lightens the same green. White silkscreen body, gold (yellow) traces,
    # pads and accent; Space Mono. Both ornament keys yellow so the quote
    # marks read as solid copper rather than dithering pale.
    "circuit": {
        "page_bg": SPECTRA6["green"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["yellow"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # Permanent-marker fridge doodle. White paper, black Sharpie body in
    # Permanent Marker, blue matched phrase (a second marker), red quote
    # marks. ``draw_marker_border`` paints in all four spot inks plus black —
    # the one theme that uses every colour the panel has.
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
    # Wild West saloon / "WANTED" broadside. Default palette shape (white,
    # black, red) with the Rye slab face and a layered ground from
    # ``draw_saloon_border``: red foxing speckles, a double-rule frame, banner
    # bands, corner fleurons and mid-edge diamonds.
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
    # Roman lapidary inscription. White stone ground, black body, red accent
    # (the red lead carvers painted into the grooves) for the matched phrase
    # and the SPQR cartouche. Cinzel Decorative is modelled on Trajan's
    # Column. ``draw_roman_border`` adds limestone speckles, a tabula ansata
    # with dovetail handles, the interpunct SPQR cartouche, mid-edge
    # interpuncts and a laurel sprig.
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
    # Parchment alchemical manuscript: yellow ground, black body, red
    # rubricated matched phrase, blue Hermetic ornaments (quote marks and
    # the magic-circle sigils) — the blue mercury / red sulphur split of the
    # Mutus Liber and Splendor Solis. IM Fell English body, MedievalSharp for
    # the matched phrase and quote marks.
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
    # Faustian spellbook. Black leather ground, white IM Fell English body,
    # Eagle Lake matched phrase; the red accent is a sentinel that
    # ``_draw_text_body`` paints as B+W sky blue, matching the quote marks.
    # Same palette shape as ``gothic`` but different iconography: inscribed
    # pentagrams and the planetary sigils on the mid-edges (Sun ☉ top, Moon ☽
    # bottom, Mars ♂ left, Venus ♀ right). ``alchemy`` is the daytime
    # parchment counterpart.
    "grimoire": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["red"],
        # Quote marks render as a 50/50 blue/white checkerboard
        # (``draw_faux_gray_text``) — the "sky" mix: a cool moon-silver
        # counterpoint to the warm red iconography.
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # Art-deco poster: white ground, black body, Righteous display sans and a
    # tangerine accent synthesised from red and yellow: 5/8 red : 3/8 yellow on
    # ``BAYER_4x4`` (threshold 6/16). Don't use 50/50 — yellow's higher
    # luminance makes it read washed-out amber. The dither is applied in two
    # places that must share the tone: ``_draw_text_body`` stipples fills
    # equal to ``accent``, and ``draw_deco_border``'s final pass flips its red
    # pixels on the same threshold. Border: stepped-corner L-shapes plus a
    # rising-sun motif on the top edge.
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
    # Icy / aurora: white ground, blue Iceland body, green accent.
    # ``draw_glacier_border`` adds frost-crystal shards in the corners and
    # star ticks at the mid-edges. ``_draw_text_body`` reroutes the green
    # accent to a 5/8:3/8 G+B teal (Bayer threshold 6/16); a 50/50 cyan reads
    # too close to the blue body.
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
    # Classroom chalkboard: black slate, white chalk body in Playwrite GB
    # Joined Guides (British school joined cursive), yellow chalk accent.
    # Same palette as ``dark``; the font and ``draw_chalkboard_border``'s
    # wooden frame differentiate it.
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
    # Hand-painted shop placard: white ground, black Patrick Hand SC body
    # (hand-lettered small caps), red matched phrase. ``draw_placard_border``
    # adds a doubled sign-painter's frame and red thumbtack corners.
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
    # Samurai cinema title card: black ground, white Shojumaru brush body, red
    # matched phrase. ``draw_chanbara_border`` adds an off-canvas rising-sun
    # disc bottom-right and a red chop seal top-left.
    "chanbara": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["red"],
        # Both ornament keys red so the quote marks render solid against
        # black rather than half-dithering into the ground.
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["red"],
        "source": SPECTRA6["white"],
    },
    # LCARS (Star Trek TNG-era interface). Black canvas, a tangerine "elbow"
    # sidebar top-left and bottom-left, stacked yellow / coral / red pills
    # with white callouts, condensed Antonio body. Tangerine uses the `deco`
    # recipe (red sentinel + bbox post-pass flipping ~3/8 to yellow on
    # BAYER_4x4 at threshold 6); the coral pill uses red + white per
    # `(x+y)&1`. The yellow accent renders solid — no body reroute.
    "lcars": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],
        # ``ornament_dark`` is the red sentinel the elbow is painted in before
        # the post-pass turns it tangerine; ``ornament_light`` is the second
        # ink of that recipe and the topmost pill's colour.
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # Swiss International style: the least ornamented frame — its border
    # painter draws only a hairline rule near the top and a small red square.
    # Inter body, Inter Bold + red for the matched phrase.
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
    # Herbarium specimen sheet. Cream Y+W Layer 0, black IM Fell English
    # body, matched phrase rerouted in ``_draw_text_body`` to forest green
    # (G+K 1:1) — an olive (Y+G) accent would sink into the cream ground.
    # The border adds an olive pressed leaf bottom-right and a "Tempus fugit"
    # cartouche bottom-left: the theme's colour story is the green axis.
    "herbarium": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        # Green sentinel, rerouted by ``_draw_text_body`` to G+K forest green.
        # The leaf uses a separate Y+G olive so text and decoration land on
        # related but distinct greens.
        "accent": SPECTRA6["green"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Art Nouveau poster (Mucha). Cream Layer 0 on white; the body is maroon
    # (R+K 1:1) via a ``_draw_text_body`` reroute — the first theme with a
    # synthesised body colour — and the matched phrase cyan (G+B 1:1).
    # Border: Bézier S-vines top-left and bottom-right with olive trefoil
    # leaves and a tangerine berry at each tip.
    "mucha": {
        # Body is the red sentinel; ``_draw_text_body`` stipples it R+K to
        # maroon. THEMES values must be native inks
        # (``test_theme_colors_stay_within_spectra6_palette``).
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["red"],
        "subtle": SPECTRA6["red"],
        "faint": SPECTRA6["red"],
        # Green sentinel, rerouted G+B to cyan for the matched phrase.
        "accent": SPECTRA6["green"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["red"],
    },
    # 1960s Fillmore concert poster. Yellow ground, red-sentinel body that
    # ``_draw_text_body`` stipples R+K to maroon (as ``mucha``) to tame the
    # red-on-yellow clash, saturated blue matched phrase, green and blue
    # corner blob panels. ``draw_fillmore_border``'s 1-in-8 white-on-yellow
    # Layer 0 makes the yellow read sun-faded. All six inks appear. Body in
    # Bungee Shade, a 3D-blocked display face.
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
    # 17th-century celestial atlas (*Uranometria*, *Harmonia Macrocosmica*).
    # White Cardo body on a navy ground, yellow stars in three magnitudes,
    # Cassiopeia and Orion's Belt, and four corner ornaments (sun, crescent,
    # compass rose, Saturn). ``page_bg`` is black; ``draw_firmament_border``
    # synthesises navy (B+K 1:1) in Layer 0 by flipping ``(x+y) & 1`` pixels
    # to blue. The yellow accent is a sentinel ``_draw_text_body`` reroutes to
    # Y+W cream. The Milky Way's R+B+W lavender is painted as a sentinel and
    # post-passed within its bbox, because ``_fill_swatch_stipple_3way``
    # overwrites every rect pixel and would wipe the navy.
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
    # Astrarium — astronomical-clock dashboard, a custom two-column layout
    # (dial left, quote right, datum strip below) dispatched from ``render``.
    # The dial's quadrants are tangerine (R+Y) / olive (Y+G) / teal (G+B) /
    # black; the matched phrase uses the same R+Y 5/8:3/8 tangerine as the
    # dial. The palette stays white/black/red for the palette-only paths
    # (see the note above ``THEMES``).
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
    # Kanagawa — Japanese seascape built on the seigaiha (青海波) wave
    # pattern rather than a literal Great Wave (polygon fills on six inks
    # can't carry the print's brushwork; the silhouette read as rolling
    # hills). Overlapping indigo fish-scale half-disks with three white arcs
    # fill the bottom ~34% of the canvas; the deepest row gets a B+K navy
    # post-pass.
    #
    # Above it: a vertically graduated sky-blue Bayer wash, five ink-stroke
    # birds at fixed anchors, a faint stippled horizon, and a red hanko seal
    # with a white 川 bottom-right whose base is post-passed to R+K maroon.
    #
    # The body sits in a cream rounded paper panel knocked out of the
    # seigaiha (the blueprint clear-rect pattern) with a 1 px frame and a 2 px
    # drop shadow. The cream is a sparse off-grid yellow scatter (~6%) rather
    # than a Bayer pattern, which lattices visibly against the indigo.
    #
    # Yuji Boku sumi-brush body; solid red matched phrase tied to the hanko.
    "kanagawa": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        # Solid red matched phrase, tied tonally to the hanko's red base.
        # (A B+K navy stipple was tried and read as vivid blue.)
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Cinema marquee. Custom frame (``render_marquee_frame``): a 1930s
    # movie-palace facade — black ground, yellow bulb border, the book title
    # as the Bungee Shade feature title, the quote below in white Cormorant
    # Italic with a red matched phrase, and WRITTEN BY credit chrome in
    # yellow. No HH:MM is drawn. Palette serves the palette-only paths (see
    # the note above ``THEMES``).
    "marquee": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["yellow"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["yellow"],
    },
    # Major-arcana tarot card. Custom frame (``render_tarot_frame``): a
    # centred card with a cream Y+W wash, doubled red+black border, the
    # Roman-numeral hour above the trump's plate and the trump's own name at
    # the foot, and the quote in EB Garamond with the matched phrase in
    # Tyrian purple (R+B 1:1). Mirror-symmetric chrome.
    "tarot": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["blue"],
        "source": SPECTRA6["black"],
    },
    # Spoken-word LP (Caedmon / Spoken Arts register). Custom frame
    # (``render_vinyl_frame``): turntable, grooves, tonearm, label and sleeve,
    # with the quote as the "reading passage" on the jacket back. The chrome
    # text (SPOKEN WORD, READING, READ ALOUD, the catalog bar) frames it as an
    # audiobook so it fits the literary corpus.
    "vinyl": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["black"],
    },
    # Gothic stained-glass lancet window. Custom frame
    # (``render_vitrail_frame``): black lead came dividing jewel-toned panes
    # in every solid ink and documented stipple recipe, a rose-window
    # medallion with the Roman-numeral hour, and the quote in a clear
    # white-glass cartouche. Matched phrase in R+B violet. The frame hardcodes
    # its inks; this palette is for the palette-only paths (see the note
    # above ``THEMES``).
    "vitrail": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["red"],
        "source": SPECTRA6["black"],
    },
    # Antique cartographer's chart. Cream Y+W Layer 0 plus a sparse R+G
    # sepia foxing scatter (the ``newsprint`` / ``tarot`` aged-paper recipe).
    # ``draw_cartograph_border`` paints two corner coastlines in R+G sepia, a
    # 32 px R+Y compass rose bottom-left, a sea-serpent in the right margin,
    # three italic Latin place labels, and knocks the body back to a cream
    # cartouche via ``clear_rect`` (doubled red+black rule, registration
    # corners). Body in IM Fell English Italic; the matched phrase is IM Fell
    # Regular in red, so roman/italic plus colour do the differentiation.
    "cartograph": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        # Solid red — the vermilion of cartographers' call-out labels. The
        # italic/roman split carries half the differentiation.
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Pixel RPG dialogue. Custom frame (``render_questline_frame``): a
    # dithered pixel sky, a sprite, and a bordered dialogue box with the
    # quote as NPC speech (matched phrase yellow), the author as nameplate
    # and the title as footer. The frame hardcodes its inks; ``fit_quote``
    # takes the theme name only to pick fonts. Palette serves the
    # palette-only paths (see the note above ``THEMES``).
    "questline": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["white"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # 16-bit SNES JRPG (FF VI / Chrono Trigger). Custom frame
    # (``render_chrono_frame``): gradient twilight sky, stars, moon,
    # mountains, the translucent-blue gradient dialogue window with a bevel,
    # a portrait sub-window, and the quote as dialogue (matched phrase in
    # yellow Pixelify Sans Bold). Palette serves the palette-only paths (see
    # the note above ``THEMES``).
    "chrono": {
        "page_bg": SPECTRA6["blue"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["white"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # Synthwave / Outrun. Custom frame (``render_outrun_frame``): a Bayer
    # gradient sky from navy to a magenta horizon, a banded half-sun, and a
    # cyan/magenta neon perspective grid. White Oxanium quote in the upper
    # sky, matched phrase in red-biased magenta (R+B 5/8:3/8; a G+B teal read
    # dim on the cool sky), Antonio credit line. Palette serves the
    # palette-only paths (see the note above ``THEMES``).
    "outrun": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["white"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # Grimdark / Imperial Gothic. Black void, bone-white body, red accent
    # rerouted to R+Y 5:3 forge-amber on the matched phrase.
    # ``draw_grimdark_border`` adds a doubled gold + blood trim, an Aquila in
    # the top margin, a skull in the bottom margin, rivets and studs. Both
    # ornament slots gold so the blackletter quote marks paint solid gilt (a
    # white half would wash it grey on black — cf. ``gothic``).
    "grimdark": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["yellow"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # The King in Yellow (Chambers, 1895). Black ground, pallid white body,
    # the King's yellow for the matched phrase — solid, never stippled: the
    # one thing this theme must not do is soften the yellow. Same inks as
    # ``dark``; ``draw_carcosa_border`` (tattered curtains, the Yellow Sign,
    # twin suns over Lake Hali) and Almendra separate them. Both ornament
    # slots yellow so the quote marks paint solid.
    "carcosa": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["yellow"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["yellow"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # Codex Seraphinianus — Luigi Serafini's imaginary encyclopedia (1981). A
    # custom frame (``render_codex_frame``): cream page, a chimerical plant
    # plate in full-palette colour, columns of procedurally generated asemic
    # script, the quote as the page's one deciphered passage, and the time as
    # a base-21 page number in invented numerals. These slots are read only by
    # the palette-only paths (see the note above ``THEMES``).
    "codex": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["blue"],
        "source": SPECTRA6["blue"],
    },
    # Remedy's *Control* — the Astral Plane. A custom frame
    # (``render_control_frame``): white void, floating isometric stone blocks
    # in K+W stipple, the Board's inverted black pyramid, a concrete plinth
    # carrying a black wayfinding sign. Black Jost Bold prose; the matched
    # phrase is Hiss red with a coral bloom stippled into the white around it.
    # Palette serves the palette-only paths (see the note above ``THEMES``).
    "control": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Francis Bacon, *Three Studies for Figures at the Base of a Crucifixion*
    # (1944). A custom frame (``render_furies_frame``): the triptych under glass
    # in gilt frames on a black gallery wall — three smeared grey figures on a
    # flat cadmium orange — and the quote as white wall text beneath, the
    # matched phrase in the painting's orange with a red smear dragged off it.
    # Palette serves the palette-only paths (see the note above ``THEMES``).
    "furies": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # Hieronymus Bosch, *The Garden of Earthly Delights* (c. 1490-1510) — a
    # custom frame (``render_bosch_frame``): the triptych open, Paradise /
    # Garden / Hell, the quote lettered on a phylactery banderole across the
    # centre panel, and the whole altarpiece crazed with craquelure. Black
    # Grenze Gotisch, rubricated red matched phrase. Palette serves the
    # palette-only paths (see the note above ``THEMES``).
    "bosch": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["red"],
        "source": SPECTRA6["black"],
    },
    # Ron Cobb's Semiotic Standard (the Nostromo signage in *Alien*, 1979) —
    # a custom frame (``render_semiotic_frame``): a black bulkhead between
    # yellow/black hazard stripes, the hour's pictogram as a featured sign
    # with two companions, and the quote on a white crew-notice placard in
    # Barlow Condensed with the matched phrase in red. These literary-layout
    # slots serve only the palette-only paths (see the note above ``THEMES``).
    "semiotic": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["red"],
        "source": SPECTRA6["black"],
    },
    # Housemarque's *Returnal* (2021) — night in the Overgrown Ruins of
    # Atropos. A custom frame (``render_atropos_frame``): teal fog dithered to
    # the cold inks over a black plain, rain, Sentient statues, the Helios
    # wreck, ember-lit tendrils, bullet-hell orbs, a xenoglyph slab, the
    # translation in Saira and the HUD in Michroma, the matched phrase in the
    # HUD's tangerine. Palette serves the palette-only paths (see the note
    # above ``THEMES``).
    "atropos": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # Sandfall Interactive's *Clair Obscur: Expedition 33* (2025) — the
    # Monolith from the Lumière promenade. A custom frame
    # (``render_expedition_frame``): a dusk dithered against the calibrated
    # inks, the Paintress seated beside the slab with the hour painted on it,
    # a gust of petals, a gas lamp and balustrade, the journal in IM Fell
    # Double Pica with the matched phrase in the number's paint. Palette
    # serves the palette-only paths (see the note above ``THEMES``).
    "expedition": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["yellow"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["yellow"],
    },
    # CD Projekt Red's *The Witcher 3: Wild Hunt* (2015) — a bestiary page
    # under the meditation dial. A custom frame (``render_witcher_frame``):
    # cream parchment in a dark binding, the entry in Barlow Condensed with
    # the matched phrase in the interface's tangerine, the hour as the sun
    # or moon on the dial and the title's claw slashes at its hub. These
    # Palette serves the palette-only paths (see the note above ``THEMES``).
    "witcher": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["yellow"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["black"],
    },
    # Supergiant Games' *Hades II* (2025) — a boon at the Crossroads under
    # the moon. A custom frame (``render_hades_frame``): a dithered night
    # over the witches' camp, the moon's phase as the hour, Hecate's green
    # witchfire, and the quote as a boon card — black and gold, the author
    # as the god's name in Caesar Dressing, white Spectral text with the
    # matched phrase in gold. Palette serves the palette-only paths (see the
    # note above ``THEMES``).
    "hades": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["yellow"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # *The Expanse* (2015–2022) — the Rocinante's console. A custom frame
    # (``render_expanse_frame``): dark glass panels with their corners cut,
    # a tactical plot whose tracked contact sits at the hour's bearing, and
    # the quote as an incoming tightbeam — white Barlow with the matched
    # phrase and the sender in the MCRN's orange, cyan gauges across the
    # foot. Palette serves the palette-only paths (see the note above
    # ``THEMES``).
    "expanse": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["yellow"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # Zdzisław Beksiński's fantastic period — a procession across a dead
    # plain toward a cathedral of bone under a dust-coloured haze. A custom
    # frame (``render_beksinski_frame``): the haze and the plain dithered
    # to umber, ochre and bone, the hour as the number of figures in the
    # file, black Old Standard text in the haze with the matched phrase in
    # red. Palette serves the palette-only paths (see the note above
    # ``THEMES``).
    "beksinski": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["red"],
        "faint": SPECTRA6["yellow"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["black"],
    },
    # Goya's *Pinturas negras* (1819-1823) — the murals of the Quinta del
    # Sordo, and *El Perro* above all. A custom frame (``render_goya_frame``):
    # the ochre void painted in continuous tone and dithered to black, red,
    # yellow and white, the dark slope at the foot with the dog's head
    # looking up at the matched phrase, a craquelure over the whole plaster,
    # the quote in black Libre Baskerville with the matched phrase in Saturn's
    # red, and the author and title on a Prado gallery label. Palette serves
    # the palette-only paths (see the note above ``THEMES``).
    "goya": {
        "page_bg": SPECTRA6["yellow"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # *2001: A Space Odyssey* (1968) — the Discovery One's monitors and HAL
    # 9000. A custom frame (``render_hal_frame``): a solid blue main monitor
    # with the hour's subsystem mnemonic in Michroma across its header, the
    # quote in white Jost with the matched phrase Bold in yellow, the twelve
    # mnemonic tiles along the foot in the film's flat colours with the
    # hour's tile white, and HAL's red lens in its white bezel at the right.
    # Palette serves the palette-only paths (see the note above ``THEMES``).
    # *Cyberpunk* — a Trauma Team International dispatch screen. A custom
    # frame (``render_traumateam_frame``): black screen, the drawn wordmark
    # and mark in white, a red dispatch band with the hour's unit, white
    # Oxanium body with the matched phrase Bold on a red block, and a vitals
    # trace along the foot. Palette serves the palette-only paths (see the
    # note above ``THEMES``).
    "traumateam": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # *Control* — a declassified Federal Bureau of Control document. A custom
    # frame (``render_redacted_frame``): the Bureau's letterhead, a red
    # DECLASSIFIED stamp, the quote typed in Special Elite with the matched
    # phrase in red and seeded black bars over other words. Palette serves the
    # palette-only paths (see the note above ``THEMES``).
    "redacted": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # An overhead highway message sign at night. A custom frame
    # (``render_gantry_frame``): amber LEDs, the matched phrase lit white,
    # the source on a green guide sign. Palette serves the palette-only paths
    # (see the note above ``THEMES``).
    "gantry": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["yellow"],
        "subtle": SPECTRA6["yellow"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["white"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # A railway departure board at night. A custom frame
    # (``render_platform_frame``): amber Round Medium dots, the matched phrase
    # in Round Bold. Palette serves the palette-only paths (see the note above
    # ``THEMES``).
    "platform": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["yellow"],
        "subtle": SPECTRA6["yellow"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["yellow"],
    },
    # A split-flap message board on a wall. A custom frame
    # (``render_splitflap_frame``): white capitals on charcoal flap tiles,
    # the matched phrase on yellow tiles. Palette serves the palette-only
    # paths (see the note above ``THEMES``).
    "splitflap": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    "hal": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # *Severance* (2022–) — the Macrodata Refinement terminal. A custom frame
    # (``render_lumon_frame``): a vignetted blue CRT dithered to blue and
    # black in a black bezel, the file's name and completion in the header
    # (the completion is the hour over twelve), four rows of white digits
    # with the hour's scary cluster boxed, the quote in white Montserrat with
    # the matched phrase Bold in yellow inside the refiner's hover box, and
    # the five bins along the foot. Palette serves the palette-only paths
    # (see the note above ``THEMES``).
    "lumon": {
        "page_bg": SPECTRA6["blue"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # The Apollo DSKY — a custom frame (``render_dsky_frame``): black panel,
    # the quote typed in Special Elite with a yellow phrase, Jost legends,
    # the display's segments white in a green bloom. Palette serves the
    # palette-only paths.
    "dsky": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["green"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["green"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # *Oblivion* (2013) — a custom frame (``render_oblivion_frame``): white
    # desk, black hairlines, Exo 2 Light quote with the phrase in red.
    # Palette serves the palette-only paths.
    "oblivion": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # *NieR: Automata* — a custom frame (``render_yorha_frame``): cream
    # dot-grid ground, black EB Garamond, the phrase knocked out white of a
    # black box. Palette serves the palette-only paths.
    "yorha": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["yellow"],
        "accent": SPECTRA6["black"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # The 1981 BBC Guide — a custom frame (``render_hitchhiker_frame``): black
    # screen, white Michroma entry with the phrase in yellow, flat-colour
    # planets. Palette serves the palette-only paths.
    "hitchhiker": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["green"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # A handwritten letter on a writing desk, seen at an angle: cream paper
    # on dark mahogany, black ink with the matched phrase in blue, brass out
    # of focus beyond the sheet. A custom frame (``render_escritoire_frame``);
    # palette serves the palette-only paths (see the note above ``THEMES``).
    "escritoire": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["yellow"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["black"],
    },
    # *Blade Runner 2049* (2017) — a custom frame (``render_lasvegas_frame``):
    # the orange haze of the dead Las Vegas, a colossal statue, K, and an
    # LAPD archive pane with white Barlow prose and the phrase in yellow.
    # Palette serves the palette-only paths (see the note above ``THEMES``).
    "lasvegas": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # *Blade Runner 2049* (2017), the systems — a custom frame
    # (``render_bladerunner_frame``): black glass, white hairlines and
    # Barlow Condensed, the phrase and the hour's prompt in yellow, the
    # X-ray in blue and white. Palette serves the palette-only paths.
    "bladerunner": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # Housemarque's *Saros* (2026) — the eclipse over Carcosa. A custom frame
    # (``render_saros_frame``): a black sun in a dithered corona whose phase
    # is the hour, a silhouetted colony rim-lit beneath it,
    # white Saira prose with the matched phrase as an ember. Palette serves
    # the palette-only paths (see the note above ``THEMES``).
    "saros": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["yellow"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # *Observation* (No Code, 2019) — the station AI's camera feed. A custom
    # frame (``render_observation_frame``): black space, a banded Saturn with
    # its polar hexagon and lit rings, a glowing hexagonal anomaly under a
    # tracking reticle, and the quote as an audio-log transcript in a S.A.M.
    # HUD panel. White prose, yellow matched phrase with a tangerine halo.
    # Palette serves the palette-only paths (see the note above ``THEMES``).
    "observation": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["yellow"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # Liu Cixin's *The Three-Body Problem* — the Trisolaran sky. A custom
    # frame (``render_trisolaris_frame``): black space, three suns and a
    # planet whose positions come from an actual gravitational integration
    # driven by the clock, the Red Coast Base dish on a ridge at the foot.
    # White prose; the matched phrase is sunlight — a yellow core in a
    # tangerine bloom. Palette serves the palette-only paths (see the note
    # above ``THEMES``).
    "trisolaris": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["yellow"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["white"],
    },
    # H. R. Giger and Zdzisław Beksiński — a biomechanical portal onto a
    # burning dusk. A custom frame (``render_biomech_frame``): an airbrushed
    # K+W wall of vertebrae, ribbed hoses and skulls, lit as a procedural
    # height field, framing a pointed arch through which a Beksiński ruin
    # stands against a blood-red sky. Bone-white prose; the matched phrase is
    # an ember — yellow core, red bloom. Palette serves the palette-only
    # paths (see the note above ``THEMES``).
    "biomech": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["red"],
        "source": SPECTRA6["white"],
    },
    # Iain M. Banks's Culture — a Mind's signal intercepted in deep space, beside
    # the Orbital it concerns. A custom frame (``render_culture_frame``): black
    # space, the signal's header and body in white, the matched phrase yellow in
    # a green drone-aura bloom, a tilted Orbital whose current plate marks the
    # time of day, and the phrase again in Marain-idiom glyphs. Palette
    # serves the palette-only paths (see the note above ``THEMES``).
    "culture": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["blue"],
        "source": SPECTRA6["white"],
    },
    # The Culture's Arch — the far side of an Orbital seen from one of its
    # plates. A custom frame (``render_orbital_frame``) whose sky, sun and
    # quote card all follow the hour, and whose Arch is lit plate by plate by
    # each plate's own local time. Palette serves the palette-only paths (see
    # the note above ``THEMES``): day inks — white card, dark type, blue
    # phrase.
    "orbital": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Wax-sealed letter. Cream ground from ``draw_letter_border``'s Layer 0
    # (the shared Y+W cream recipe), black Dancing Script body, sealing-wax
    # red matched phrase echoing the maroon seal stamped bottom-right. The
    # oversized opening mark is Pinyon Script on the faux-gray path
    # (black/white 50/50), so it reads as a pale pen stroke rather than a
    # blot. Fold creases and seal separate it from ``default``; see
    # THEME_FONTS for the font pairing.
    "letter": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Anna Atkins 1843 botanical cyanotype. Prussian-blue ground carrying a
    # Floyd–Steinberg-dithered cyanotype plate (``dither_image_to_palette``;
    # see ``draw_anna_atkins_border``), white algae/fern silhouettes and
    # copperplate Latin labels. White Libre Caslon drawn straight over the
    # plate with a per-glyph black halo from ``_draw_text_body``. ``accent``
    # is a yellow sentinel that ``_draw_text_body`` reroutes to a B+W 50/50
    # sky-blue stipple; it shows literally only in the debug banner (the
    # ``firmament`` pattern). Ornament keys blue/white give the quote marks
    # the same sky-blue.
    "anna_atkins": {
        "page_bg": SPECTRA6["blue"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # Engraved art-song manuscript. A custom-render frame, so these colours
    # serve only the palette-only paths (see the note above ``THEMES``); the frame
    # itself hardcodes its three-tier ink hierarchy (black plate / maroon
    # editorial / red voice — see the lieder section comment).
    "lieder": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Neon alley at night. A custom-render frame, so these colours serve only
    # the palette-only paths (see the note above ``THEMES``); the frame itself paints
    # its tube cores and blooms directly (see the izakaya section comment).
    "izakaya": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # Deep sea. A custom-render frame, so these colours serve only
    # the palette-only paths (see the note above ``THEMES``); the frame paints its own
    # depth gradient and blooms (see the abyssal section comment).
    "abyssal": {
        "page_bg": SPECTRA6["blue"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["green"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # The Progress Pride flag, flying. Custom frame (``render_pride_frame``):
    # the flag is full-bleed and the quote sits in a white cartouche. Palette
    # serves the palette-only paths (see the note above ``THEMES``); stripe
    # inks come from ``_PRIDE_STRIPE_INKS``. ``accent`` is blue because the
    # frame's matched phrase is the R+B violet stipple and blue is the half
    # that still reads on the white card.
    "pride": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["blue"],
        "source": SPECTRA6["black"],
    },
    # 1940s lurid paperback front. Custom frame (``render_pulp_frame``) that
    # owns the whole canvas. Palette serves the palette-only paths (see the
    # note above ``THEMES``).
    "pulp": {
        "page_bg": SPECTRA6["yellow"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["red"],
        "source": SPECTRA6["black"],
    },
    # Bakelite console — an amber-phosphor CRT in a butterscotch slab (see the
    # ``render_bakelite_frame`` section comment). Custom frame; palette serves
    # the palette-only paths (see the note above ``THEMES``). ``text`` is the
    # yellow phosphor core, ``accent`` the red halo, ``page_bg`` the black
    # glass.
    "bakelite": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["yellow"],
        "subtle": SPECTRA6["yellow"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["red"],
    },
    # Banknote / security engraving. Custom frame (``render_intaglio_frame``);
    # palette serves the palette-only paths (see the note above ``THEMES``).
    # The face is a real note's three plates: black intaglio, green tint
    # lathework, red numbering press, on white paper.
    "intaglio": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["green"],
        "accent": SPECTRA6["green"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["green"],
        "source": SPECTRA6["black"],
    },
    # Whistler nocturne — blue-and-gold night river. Custom frame
    # (``render_nocturne_frame``); palette serves the palette-only paths (see
    # the note above ``THEMES``). The canvas is flow-field blue brushwork
    # over black with synthesised-gold light.
    "nocturne": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["blue"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["blue"],
    },
    # Patinated bronze memorial plaque. Custom frame (``render_plaque_frame``);
    # palette serves the palette-only paths (see the note above ``THEMES``).
    # The tablet is dark verdigris with relief-lit burnished-brass lettering
    # (forest-teal with gold was too low-contrast to read).
    "plaque": {
        "page_bg": SPECTRA6["green"],
        "text": SPECTRA6["yellow"],
        "subtle": SPECTRA6["yellow"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["yellow"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["yellow"],
    },
    # Cased 1850s daguerreotype, lying open. Custom frame
    # (``render_daguerreotype_frame``); palette serves the palette-only paths
    # (see the note above ``THEMES``): the lid's red velvet pad with the quote
    # gold-stamped on it, the matched phrase in white.
    "daguerreotype": {
        "page_bg": SPECTRA6["red"],
        "text": SPECTRA6["yellow"],
        "subtle": SPECTRA6["yellow"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["white"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["yellow"],
    },
    # Autochrome Lumière colour plate as a lantern slide. Custom frame
    # (``render_autochrome_frame``); palette serves the palette-only paths
    # (see the note above ``THEMES``): the black paper mask, the caption
    # lettered on it in white with the matched phrase in yellow.
    "autochrome": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # The operator's own photograph. Custom frame (``render_photo_frame``);
    # palette serves the palette-only paths (see the note above ``THEMES``).
    # The picture is whatever ``IDLE_HOURS_PHOTO_PATH`` names, dithered
    # against all six inks, with the quote on a cream card over its quietest
    # region.
    "photo": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Library catalogue card. Custom frame (``render_cardcatalog_frame``) —
    # the stamp column needs a right margin the literary layout doesn't
    # leave. Palette serves the palette-only paths (see the note above
    # ``THEMES``); the card is manila (cream + sepia foxing) with violet ink.
    "cardcatalog": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["blue"],
        "ornament_dark": SPECTRA6["red"],
        "ornament_light": SPECTRA6["blue"],
        "source": SPECTRA6["black"],
    },
    # Worn VHS tape under a camcorder OSD. Custom frame (``render_vhs_frame``)
    # that owns the canvas; palette serves the palette-only paths (see the
    # note above ``THEMES``). Red and blue are the two chroma records that
    # drift apart in ``draw_text_chroma_shift``; the body is white.
    "vhs": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
    # Meteorological surface analysis. A literary-layout theme (NOT a custom
    # frame): ``draw_synoptic_border`` paints the chart under the shared
    # layout and knocks the body out to a boxed legend via ``clear_rect``.
    # Blue and red are the cold- and warm-front inks; the matched phrase is
    # warm-front red.
    "synoptic": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["red"],
        # Both ornament slots take the page ground on purpose: the shared
        # layout paints the quote marks OUTSIDE the body rect, where a big
        # glyph on the chart reads as debris. Effectively not drawn.
        "ornament_dark": SPECTRA6["white"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    # Metropolitan transit diagram. A custom-render frame
    # (``render_metro_frame``): the full-palette route network owns the canvas
    # and the quote sits in a central interchange card. The matched phrase is
    # the red express route through the otherwise-black text block.
    "metro": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["blue"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["blue"],
        "ornament_light": SPECTRA6["yellow"],
        "source": SPECTRA6["black"],
    },
    # Diagnostic / status panel. Custom layout dispatched from ``render``:
    # clock, bucket / layout / quality / source fields, and a swatch grid of
    # the inks and synthesised two-ink tones. White/black/red keeps the
    # palette-only paths (see the note above ``THEMES``) readable; the frame
    # also reads it for its status labels.
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
    # Counted cross-stitch sampler. Custom frame (``render_sampler_frame``):
    # every glyph is stitched as "X" marks from a Silkscreen mask onto cream
    # Aida cloth (a Y+W stipple wash synthesised at render time), inside a
    # full-palette floral border with house / heart / bird motifs. Black
    # floss body, red floss matched phrase; no HH:MM. Palette serves the
    # palette-only paths (see the note above ``THEMES``).
    "sampler": {
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
        # Inter (grotesque). Every candidate pins its instance so the
        # matched-phrase bold is unambiguous; falls back through sans faces
        # before the Playfair chain so the theme stays sans.
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
    # Between Us — Fraunces. The matched phrase is the *italic* cut, not a
    # bold ("say *what you want.*" is the app's own gesture). Light keeps it
    # at Italic 400 because it paints solid; dark steps to SemiBold Italic so
    # the amber stipple has stroke mass. Italic fallbacks keep a missing
    # install slanted.
    "betweenus": {
        "quote_regular": [
            (FRAUNCES_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (FRAUNCES_ITALIC_VARIABLE, "Italic"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Italic.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (FRAUNCES_VARIABLE, "SemiBold"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "betweenus_dark": {
        "quote_regular": [
            (FRAUNCES_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (FRAUNCES_ITALIC_VARIABLE, "SemiBold Italic"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-BoldItalic.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-BoldItalic.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (FRAUNCES_VARIABLE, "SemiBold"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Jost's near-monoline strokes are what let this theme bloom:
    # ``paint_neon_mask`` reads a blurred glyph mask as halo density, so a
    # high-contrast face haloes unevenly (stems flare, hairlines vanish) and
    # stops reading as a lit tube. Space Mono Bold carries the stencilled
    # legend — the same chrome split ``metro`` uses.
    "bakelite": {
        "quote_regular": [
            (JOST_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (JOST_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            SPACEMONO_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Intaglio's legend is Old Standard TT, the Didone nearest engraved
    # currency. Cinzel Decorative (ornament slot) carries the masthead and
    # denominations; the frame loads Pinyon Script (promise line) and Space
    # Mono (serial, microprint) directly, the bakelite pattern.
    "intaglio": {
        "quote_regular": [
            OLDSTANDARD_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            OLDSTANDARD_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            CINZELDECORATIVE_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Nocturne blooms its body text, and a high-contrast face haloes unevenly
    # (see ``bakelite``). Cormorant Garamond is the right register, so the
    # body pins **Medium**: enough stem weight to survive the halo where
    # Regular's hairlines would shred.
    "nocturne": {
        "quote_regular": [
            (CORMORANT_VARIABLE, "Medium"),
            EBGARAMOND_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (CORMORANT_VARIABLE, "Bold"),
            EBGARAMOND_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (CORMORANT_VARIABLE, "SemiBold"),
            EBGARAMOND_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Plaque: Cinzel Decorative, the Trajan capitalis of cast bronze
    # tablets. The chain steps one weight heavier — Bold body, Black matched
    # phrase — because a relief face needs stroke mass: Regular's 2 px
    # hairlines leave nothing for the gold once the rim light claims the
    # edges. Fallbacks stay heavy serifs for the same reason.
    "plaque": {
        "quote_regular": [
            CINZELDECORATIVE_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "quote_bold": [
            CINZELDECORATIVE_BLACK,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            CINZELDECORATIVE_BLACK,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Daguerreotype's caption slip is Libre Caslon Text, shared with
    # ``anna_atkins`` on purpose (the photographic themes share a face).
    # Space Mono is loaded directly by the frame for the plate label.
    "daguerreotype": {
        "quote_regular": [
            (LIBRECASLON_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (LIBRECASLON_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (LIBRECASLON_VARIABLE, "SemiBold"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Autochrome: Libre Caslon Text, like the other photographic themes. The
    # sans mount chrome loads directly from the meta chain.
    "autochrome": {
        "quote_regular": [
            (LIBRECASLON_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (LIBRECASLON_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (LIBRECASLON_VARIABLE, "SemiBold"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Photo: Libre Caslon, the photographic themes' caption face — a neutral
    # book serif suits a caption over an unknown picture.
    "photo": {
        "quote_regular": [
            (LIBRECASLON_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (LIBRECASLON_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (LIBRECASLON_VARIABLE, "SemiBold"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Metro: Jost, whose open counters survive route-map legend sizes; the
    # true Bold gives the matched phrase an interchange label's weight.
    "metro": {
        "quote_regular": [
            (JOST_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (JOST_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            SPACEMONO_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "scholar": {
        # Bitter slab serif. The variable font defaults to Thin (axis
        # minimum 100), so every candidate pins an instance — without it the
        # panel shows near-invisible ghost strokes.
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
        # IM Fell English (shared with ``alchemy`` / ``grimoire``). The
        # matched phrase is IM Fell *Italic* rather than a heavier weight —
        # italic is the convention for Latin names on a specimen sheet — and
        # the forest-green accent (``_draw_text_body``) carries the rest. The
        # Regular fallback keeps a missing italic off the bitmap fallback.
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
    # Circuit shares nightvision's Space Mono chain — the silkscreen register
    # of a PCB legend — with the same DejaVu Sans Mono fallback.
    "circuit": {
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
        # Archivo grotesque; falls back through common Linux/Pi sans installs
        # before the Playfair chain.
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
        # EB Garamond body with a UnifrakturMaguntia ornament (quote marks
        # only): a blackletter body would shred at dense-layout sizes on the
        # panel.
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
        # UnifrakturMaguntia covers the matched-phrase bold as well as the
        # ornament, so short phrases sit in the body like a red blackletter
        # heading; the body stays EB Garamond for legibility. EB Garamond Bold
        # is the second rank for a missing-Unifraktur install.
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
        # Jost variable, default 400; every candidate pins its instance so
        # the bold phrase stays distinguishable. Same sans fallbacks as
        # ``blueprint``.
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
        # Rubik's default instance is Light (300), NOT Regular, so a missing
        # set_variation_by_name renders the body too thin. Pin Regular / Bold
        # on every candidate.
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
        # Bangers ships only Regular, so the matched phrase differs by colour;
        # a sans Bold behind it keeps the phrase heavier on a fallback install.
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
        # Special Elite ships one weight and its uneven inking is the point,
        # so the matched phrase differs by colour alone — a bichrome ribbon
        # shifting black to red. Falls back through Space Mono / DejaVu Sans
        # Mono so a missing install stays typewriter-adjacent.
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
        # Atomic Age (OFL) — chunky 1950s display face. Regular only, so the
        # matched phrase differs by colour. Falls back through heavy sans
        # before the Playfair chain.
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
        # Permanent Marker (Apache 2.0) — single-weight marker hand; the
        # matched phrase differs by its blue. Falls back through heavy sans
        # before the Playfair chain.
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
        # Cinzel Decorative (OFL) — Trajan's Column capitalis revival. The
        # matched phrase steps up one weight (Regular → Bold) rather than
        # switching face, which would break the inscription; Black carries the
        # SPQR cartouche and quote marks. Falls back through heavy serifs.
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
        # Rye (OFL) — wood-engraved Western display slab. Regular only, so the
        # matched phrase differs by its red, as on a two-colour broadside.
        # Falls back through heavy serifs.
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
        # Body — IM Fell English, the 17th-century Oxford types of the era
        # England printed real alchemical treatises (OFL).
        #
        # Matched phrase + ornament — MedievalSharp (OFL), a ritual scribe's
        # hand. Regular only, so the matched phrase differs by its red
        # rubrication alone.
        #
        # Fallbacks: EB Garamond / system serifs for a missing IM Fell, and
        # UnifrakturMaguntia (the next-nearest ritual hand) for a missing
        # MedievalSharp.
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
        # IM Fell English body, shared with ``alchemy``; the two differ by
        # ground and matched-phrase face. EB Garamond Regular is the second
        # rank. Eagle Lake carries the matched phrase — the spiked "phantom
        # scrawl" that defines the theme — with EB Garamond Bold behind it
        # only as a missing-file fallback (Eagle Lake has the curly quotes and
        # em-dash). The ornament stays IM Fell so the quote marks match the
        # body's vintage-press character.
        "quote_regular": [
            IMFELLENGLISH_REGULAR,
            EBGARAMOND_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            EAGLELAKE_REGULAR,
            EBGARAMOND_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            IMFELLENGLISH_REGULAR,
            EBGARAMOND_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "deco": {
        # Righteous (OFL) — 1930s art-deco display sans, Regular only; the
        # matched phrase differs by its accent. Heavy-sans fallbacks.
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
        # Patrick Hand SC (OFL) — hand-printed small caps, single weight; the
        # matched phrase differs by its red. Heavy-sans fallbacks.
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
        # Shojumaru (OFL) — brush display face, single weight; the matched
        # phrase differs by its red. Heavy-sans fallbacks before Playfair.
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
        # Playwrite GB J Guides (OFL) — joined cursive with dotted guide
        # letters, single weight; the matched phrase differs by its yellow.
        # Italic fallbacks keep a missing install slanted.
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
        # Iceland (OFL) — single-weight techno display face. The matched
        # phrase reuses Regular, and ``_draw_text_body`` adds a
        # ``stroke_width=1`` faux bold over the teal G+B stipple: the teal
        # alone sits too close in hue to the blue body. Heavy-sans fallbacks.
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
        # Cormorant Garamond — high-contrast humanist serif in the Art Nouveau
        # poster register. Variable, Regular / Bold pinned. Berkshire Swash
        # takes the ornament slot (the ``illuminated`` body + period-ornament
        # pairing); a missing Swash falls through to Cormorant Bold.
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
        # Bungee Shade, single weight; the matched phrase differs by its blue.
        # Falls back through Bangers and Atomic Age before heavy sans.
        # The whole body is set in Bungee Shade on purpose: under the maroon
        # stipple it is borderline illegible, and that is the Fillmore
        # register — the posters made you work for the band's name. (A Rubik
        # Black body was tried and reverted as too polite.)
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
        # Cardo (OFL) — humanist Renaissance serif. Italic fills the ornament
        # role for the opening quote mark. Falls back through EB Garamond →
        # DejaVu Serif → Liberation Serif → Playfair.
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
        # Antonio (OFL) — the free LCARS substitute. Default axis instance is
        # Regular, but Regular / Bold are pinned by name so an upstream
        # default change can't shift the weight. Heavy-sans fallbacks.
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
        # The stardate callouts, the elbow wordmark and the oversized quote
        # marks all use the same condensed Antonio so the console stays
        # consistent.
        "ornament": [
            (ANTONIO_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Astrarium — EB Garamond body. Cormorant's hairlines drop below 1 px at
    # the 18-38 pt fit range and vanish into the washed ground; EB Garamond's
    # moderate contrast survives the pixel grid. (Playfair would erase the
    # difference from default; Cardo belongs to firmament.) Bold carries the
    # matched phrase and the quote marks. The dashboard's sans chrome loads
    # directly from ``META_FONT_BOLD_CANDIDATES`` in
    # ``render_astrarium_frame``.
    "astrarium": {
        "quote_regular": [
            EBGARAMOND_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            EBGARAMOND_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            EBGARAMOND_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "kanagawa": {
        # Yuji Boku for body and matched phrase, single weight; the matched
        # phrase differs by its red.
        #
        # Fallbacks favour humanist serifs (Cormorant Garamond → EB Garamond
        # → Playfair) over sans: a grotesque would clash with the brush
        # register.
        "quote_regular": [
            YUJI_BOKU_REGULAR,
            (CORMORANT_VARIABLE, "Regular"),
            EBGARAMOND_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            YUJI_BOKU_REGULAR,
            (CORMORANT_VARIABLE, "Bold"),
            EBGARAMOND_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            YUJI_BOKU_REGULAR,
            (CORMORANT_VARIABLE, "Bold"),
            EBGARAMOND_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Marquee — Cardo Italic for the body (the "feature copy" register),
    # Cardo Bold for the matched phrase so weight differs independently of
    # the red. Bungee Shade (ornament slot) carries the feature title — the
    # book title as 3D relief letters on the canopy.
    "marquee": {
        "quote_regular": [
            CARDO_ITALIC,
            CARDO_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            CARDO_BOLD,
            CARDO_ITALIC,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            BUNGEE_SHADE_REGULAR,
            CARDO_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Tarot — EB Garamond body (17th-century treatise type), Cinzel
    # Decorative Bold for the matched phrase, Cinzel Decorative Black for the
    # Roman-numeral hour so it reads as carved relief at chrome scale.
    "tarot": {
        "quote_regular": [
            EBGARAMOND_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            CINZELDECORATIVE_BOLD,
            EBGARAMOND_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            CINZELDECORATIVE_BLACK,
            CINZELDECORATIVE_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Vinyl — Cormorant Garamond Regular / Bold: high-contrast forms that
    # read at both label scale (12 pt) and sleeve scale (~32 pt). The
    # ornament reuses Bold for the 33⅓ rpm badge.
    "vinyl": {
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
    # Vitrail — the ornament slot prefers Uncial Antiqua for the rose-window
    # numeral, falling back through MedievalSharp → UnifrakturMaguntia so a
    # missing install stays medieval. The matched phrase differs by its R+B
    # violet accent.
    "vitrail": {
        # Body, cartouche attribution and matched phrase use Liberation Serif,
        # an even-weight serif that stays crisp at the 15-30 px cartouche
        # sizes, falling back through the default Playfair chains.
        "quote_regular": [
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            *QUOTE_FONT_REGULAR_CANDIDATES,
        ],
        "quote_bold": [
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            UNCIALANTIQUA_REGULAR,
            MEDIEVALSHARP_REGULAR,
            UNIFRAKTUR_BOOK,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Cartograph — IM Fell English Italic body with an upright Roman matched
    # phrase: the period mapmakers' convention of italic legends and upright
    # place names. The ornament reuses Regular so the quote marks match the
    # matched phrase. DejaVu Serif Italic fallback keeps it slanted.
    "cartograph": {
        "quote_regular": [
            IMFELLENGLISH_ITALIC,
            IMFELLENGLISH_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            IMFELLENGLISH_REGULAR,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            IMFELLENGLISH_REGULAR,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Press Start 2P everywhere — body, matched phrase and chrome. Single
    # weight, so the matched phrase differs by its yellow. Falls back through
    # sans faces (no other pixel face is bundled).
    "questline": {
        "quote_regular": [
            PRESSSTART2P_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            PRESSSTART2P_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            PRESSSTART2P_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Pixelify Sans — proportional 16-bit pixel sans; the matched phrase pins
    # Bold for weight contrast on top of the yellow. Sans fallbacks.
    "chrono": {
        "quote_regular": [
            (PIXELIFYSANS_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (PIXELIFYSANS_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (PIXELIFYSANS_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Oxanium (OFL) — squared techno sans in the 1980s retro-future register.
    # Chosen over Orbitron because Orbitron is so wide that a dense quote
    # shrinks unreadably; Oxanium's narrower proportions hold long lines.
    # Variable; the matched phrase pins Bold for a weight step on top of the
    # magenta accent. Sans fallbacks before the Playfair chain.
    "outrun": {
        "quote_regular": [
            (OXANIUM_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (OXANIUM_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (OXANIUM_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "carcosa": {
        # Almendra for the body and matched phrase (a real Bold step under the
        # yellow), Almendra Display for the quote marks. Each chain falls back
        # through the bundled IM Fell English — the nearest period book face —
        # before the system serifs and the Playfair chain.
        "quote_regular": [
            ALMENDRA_REGULAR,
            IMFELLENGLISH_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            ALMENDRA_BOLD,
            IMFELLENGLISH_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            ALMENDRA_DISPLAY,
            ALMENDRA_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "codex": {
        # Fondamento — a calligraphic pen hand for Serafini's handwritten
        # encyclopedia. Regular body, Italic matched phrase (no bold cut
        # exists; the italic plus the red carries the step). Falls back
        # through the bundled IM Fell English, the nearest period book hand,
        # before the system serifs.
        "quote_regular": [
            FONDAMENTO_REGULAR,
            IMFELLENGLISH_REGULAR,
            *QUOTE_FONT_REGULAR_CANDIDATES,
        ],
        "quote_bold": [
            FONDAMENTO_ITALIC,
            IMFELLENGLISH_ITALIC,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            FONDAMENTO_ITALIC,
            FONDAMENTO_REGULAR,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "control": {
        # Jost Bold — the game's title cards and logo are ITC Avant Garde
        # Gothic Bold, and Jost is the bundle's geometric in that line. Bold
        # for the body as well as the phrase: a title card is heavy, and the
        # phrase steps out by its Hiss red and bloom, not weight. Oswald
        # stays as the fallback so a stripped install lands on a heavy sans.
        "quote_regular": [
            (JOST_VARIABLE, "Bold"),
            (OSWALD_VARIABLE, "Bold"),
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "quote_bold": [
            (JOST_VARIABLE, "Bold"),
            (OSWALD_VARIABLE, "Bold"),
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            ARCHIVO_BOLD,
            (OSWALD_VARIABLE, "Bold"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "trisolaris": {
        # Titillium Web — a cold, technical humanist sans. Regular for the
        # body over the black sky; SemiBold for the matched phrase, which
        # already carries a bloom, so a full Bold would clog its counters
        # once the halo closes in around them.
        "quote_regular": [
            TITILLIUM_REGULAR,
            *META_FONT_CANDIDATES,
            *QUOTE_FONT_REGULAR_CANDIDATES,
        ],
        "quote_bold": [
            TITILLIUM_SEMIBOLD,
            TITILLIUM_BOLD,
            *META_FONT_BOLD_CANDIDATES,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            TITILLIUM_ITALIC,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "furies": {
        # Libre Franklin — Franklin Gothic, the grotesque of mid-century
        # museum wall text. Medium for the body (white strokes on black want
        # the extra stem to survive the palette snap), ExtraBold for the
        # matched phrase so the orange stipple and its dragged smear have
        # stroke mass to live in. Italic for the attribution / ornament.
        "quote_regular": [
            (LIBREFRANKLIN_VARIABLE, "Medium"),
            (INTER_VARIABLE, "Medium"),
            *QUOTE_FONT_REGULAR_CANDIDATES,
        ],
        "quote_bold": [
            (LIBREFRANKLIN_VARIABLE, "ExtraBold"),
            (INTER_VARIABLE, "Bold"),
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (LIBREFRANKLIN_ITALIC_VARIABLE, "Medium Italic"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "bosch": {
        # Grenze Gotisch — textura capitals over a legible lowercase, the
        # nearest open face to the gothic book hand Bosch lettered his
        # phylacteries in. Medium for the body (a scroll's ink must survive
        # the palette snap on cream), Bold for the rubricated phrase — a real
        # weight step under the red. IM Fell English, the nearest bundled
        # period book face, is the fallback before the system serifs.
        "quote_regular": [
            (GRENZE_GOTISCH_VARIABLE, "Medium"),
            IMFELLENGLISH_REGULAR,
            *QUOTE_FONT_REGULAR_CANDIDATES,
        ],
        "quote_bold": [
            (GRENZE_GOTISCH_VARIABLE, "Bold"),
            IMFELLENGLISH_REGULAR,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (GRENZE_GOTISCH_VARIABLE, "Black"),
            UNIFRAKTUR_BOOK,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "semiotic": {
        # Barlow Condensed — a DIN-descended condensed grotesque, the register
        # of industrial wayfinding and of the stencilled legends on Cobb's
        # Nostromo signage. Medium body (black on the white placard), Bold for
        # the red matched phrase, SemiBold for chrome. Oswald, the bundle's
        # other condensed grotesque, is the fallback before the system sans.
        "quote_regular": [BARLOWCOND_MEDIUM, (OSWALD_VARIABLE, "Regular"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [BARLOWCOND_BOLD, (OSWALD_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [BARLOWCOND_SEMIBOLD, (OSWALD_VARIABLE, "Medium"), *ORNAMENT_FONT_CANDIDATES],
    },
    "atropos": {
        # Returnal's running text is Erbaum and its titles Kellion; neither is
        # open. Saira (nearest to Erbaum) carries the body (Regular) and the
        # matched phrase (SemiBold, told apart mainly by its tangerine bloom);
        # Michroma (nearest to Kellion) is the HUD chrome and the fallback.
        "quote_regular": [(SAIRA_VARIABLE, "Regular"), MICHROMA_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(SAIRA_VARIABLE, "SemiBold"), MICHROMA_REGULAR, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [MICHROMA_REGULAR, (OXANIUM_VARIABLE, "Medium"), *ORNAMENT_FONT_CANDIDATES],
    },
    "expedition": {
        # IM Fell Double Pica — the face Clair Obscur: Expedition 33 sets its
        # UI text in. The roman carries the white body on the dusk; the face
        # has no bold, so the matched phrase takes the italic and is painted
        # in the number's recipe. IM Fell English, the bundle's sibling Fell,
        # is the fallback before the system serifs. The ornament slot is
        # Cinzel Decorative, the poster lettering, for the wordmark.
        "quote_regular": [IMFELLDOUBLEPICA_REGULAR, IMFELLENGLISH_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [IMFELLDOUBLEPICA_ITALIC, IMFELLENGLISH_ITALIC, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [CINZELDECORATIVE_BOLD, CINZELDECORATIVE_REGULAR, *ORNAMENT_FONT_CANDIDATES],
    },
    "witcher": {
        # The Game Font Library lists PF DIN Text Condensed for the game's
        # interface and Bell Gothic Bold for the WILD HUNT logotype; neither
        # is open. Barlow Condensed is the bundle's DIN-descended condensed
        # grotesque: Medium for the entry's black body on cream, Bold for the
        # matched phrase, which carries the interface's tangerine. Archivo
        # Narrow, the nearest open face to Bell Gothic, takes the ornament
        # slot and every label.
        "quote_regular": [BARLOWCOND_MEDIUM, (ARCHIVONARROW_VARIABLE, "Medium"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [BARLOWCOND_BOLD, (ARCHIVONARROW_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(ARCHIVONARROW_VARIABLE, "Bold"), ARCHIVO_BOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "hades": {
        # Spectral — the serif *Hades II* sets its codex and boon text in
        # (Game Font Library): Medium for the white body on the card's
        # midnight, SemiBold for the matched phrase, which is the card's
        # gold-lit key word. Alegreya, the bundle's other literary serif, is
        # the fallback. The ornament slot is Caesar Dressing, the game's
        # title-card face, for the god's name and the wordmark.
        "quote_regular": [SPECTRAL_MEDIUM, ALEGREYA_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [SPECTRAL_SEMIBOLD, ALEGREYA_BOLD, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [CAESARDRESSING_REGULAR, CINZELDECORATIVE_BOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "expanse": {
        # Barlow — the open DIN, for a console the show sets in a modified
        # DIN Pro: Regular for the white transmission on black glass,
        # SemiBold for the matched phrase, which is told apart by its
        # orange. Barlow Condensed is the fallback and the labels' face.
        "quote_regular": [BARLOW_REGULAR, BARLOWCOND_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [BARLOW_SEMIBOLD, BARLOWCOND_SEMIBOLD, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [BARLOW_BOLD, BARLOWCOND_BOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "beksinski": {
        # Old Standard TT — the Didone of Central and Eastern European book
        # printing through the twentieth century, the letter a Polish novel
        # of Beksiński's time was set in: Regular for the black body in the
        # haze, Bold for the matched phrase in red. Shared with ``newsprint``
        # and ``intaglio``.
        "quote_regular": [OLDSTANDARD_REGULAR, *QUOTE_FONT_SEMIBOLD_CANDIDATES],
        "quote_bold": [OLDSTANDARD_BOLD, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [OLDSTANDARD_BOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "goya": {
        # Libre Baskerville — a sturdy transitional roman in the register of
        # Madrid's Imprenta Real in the Black Paintings' own decade (see the
        # constant). Regular for the black body written into the ochre void,
        # Bold for the matched phrase, which carries the red; the italic
        # takes the gallery label's title line. Libre Caslon, the bundle's
        # other low-contrast old-style, is the fallback.
        "quote_regular": [(LIBREBASKERVILLE_VARIABLE, "Regular"), (LIBRECASLON_VARIABLE, "Regular"),
                          *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(LIBREBASKERVILLE_VARIABLE, "Bold"), (LIBRECASLON_VARIABLE, "Bold"),
                       *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(LIBREBASKERVILLE_ITALIC_VARIABLE, "Italic"), (LIBREBASKERVILLE_VARIABLE, "Bold"),
                     *ORNAMENT_FONT_CANDIDATES],
    },
    "hal": {
        # Jost — the bundle's Futura, the face of the film's signage and
        # the register of its 1968 modernism — Regular for the white body on
        # the blue monitor, Bold for the matched phrase, which carries the
        # yellow. The chrome (mnemonics, nameplate, tile labels) is Michroma,
        # the open Microgramma / Eurostile the monitors' squared capitals
        # were set in; it takes the ornament slot.
        "quote_regular": [(JOST_VARIABLE, "Regular"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(JOST_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [MICHROMA_REGULAR, (JOST_VARIABLE, "Bold"), *ORNAMENT_FONT_CANDIDATES],
    },
    "lumon": {
        # Montserrat — the open Gotham, the face the MDR terminal's number
        # grid is set in the register of: Regular for the white body, Bold
        # for the matched phrase in yellow inside the hover box, Medium and
        # Bold for the digits. The file name, the completion and the byline
        # are Inter (the open neo-grotesque standing in for the show's Forma
        # DJR); the wordmark is Michroma (for Manifold Extended CF, itself
        # drawn after Microgramma).
        "quote_regular": [(MONTSERRAT_VARIABLE, "Regular"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(MONTSERRAT_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(INTER_VARIABLE, "Medium"), MICHROMA_REGULAR, *ORNAMENT_FONT_CANDIDATES],
    },
    "dsky": {
        # Special Elite — the quote is typed on a flight-plan card, and the
        # flight plans were cut on a typewriter; one weight, so the matched
        # phrase is told apart by its red ink. Jost Medium (NASA silkscreened
        # its panels in Futura Demi) for every legend on the unit.
        "quote_regular": [SPECIALELITE_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [SPECIALELITE_REGULAR, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(JOST_VARIABLE, "Medium"), *ORNAMENT_FONT_CANDIDATES],
    },
    "oblivion": {
        # Exo 2 — the film's screens are set in Blender (Nik Thoenen,
        # Gestalten; commercial), an angular geometric sans with squared
        # bowls, and Exo 2 is the bundle's open face in that family. Light
        # for the body (solid black on the white ink survives a Light stem
        # where a stipple would not), Medium for the matched phrase in red,
        # Regular for the chrome.
        "quote_regular": [(EXO2_VARIABLE, "Light"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(EXO2_VARIABLE, "Medium"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(EXO2_VARIABLE, "Regular"), *ORNAMENT_FONT_CANDIDATES],
    },
    "yorha": {
        # EB Garamond — Automata's interface is set in a refined classical
        # serif (unidentified; custom or unreleased), and EB Garamond is the
        # closest open face to it. Regular body; Bold for the matched
        # phrase, knocked out white of its black box.
        "quote_regular": [EBGARAMOND_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [EBGARAMOND_BOLD, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [EBGARAMOND_BOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "hitchhiker": {
        # Michroma — the square-shouldered monoline of the series' hand-
        # lettered computer screens. One static weight, so the matched
        # phrase is told apart by its yellow, not its weight.
        "quote_regular": [MICHROMA_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [MICHROMA_REGULAR, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [MICHROMA_REGULAR, *ORNAMENT_FONT_CANDIDATES],
    },
    "escritoire": {
        # The ``letter`` theme's hand: Dancing Script pinned Regular for the
        # body and Bold for the matched phrase and the signature. Pinyon's
        # copperplate is closer to a real letter but hairline, and shreds
        # once the warp has shrunk it.
        "quote_regular": _HAND_SCRIPT_REGULAR,
        "quote_bold": _HAND_SCRIPT_BOLD,
        "ornament": [(DANCINGSCRIPT_VARIABLE, "Bold"), *ORNAMENT_FONT_CANDIDATES],
    },
    "lasvegas": {
        # Barlow — the film's interfaces (Territory Studio) are set in plain,
        # low-contrast grotesques, and Barlow's slightly squared curves sit
        # between that and a highway sign. Medium for the white body on the
        # black pane (a Regular stem thins once the panel's white bleeds into
        # the black), Bold for the matched phrase in yellow, Barlow
        # Condensed for the tracked chrome.
        "quote_regular": [BARLOW_MEDIUM, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [BARLOW_BOLD, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [BARLOWCOND_MEDIUM, *ORNAMENT_FONT_CANDIDATES],
    },
    "bladerunner": {
        # Barlow Condensed — the film's interfaces (Territory Studio) set
        # their text in narrow, low-contrast grotesques in tracked capitals
        # and a plain mixed case. Medium for the white body on black, Bold
        # for the matched phrase in yellow, SemiBold for the chrome.
        "quote_regular": [BARLOWCOND_MEDIUM, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [BARLOWCOND_BOLD, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [BARLOWCOND_SEMIBOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "gantry": {
        # Lumen, a 5x7 LED matrix. The frame reads it as dot bitmaps on the
        # sign's own lattice (``_gantry_glyph``), so the instance only has to
        # put a dot clearly over each grid centre: Bold. The matched phrase is
        # emboldened the matrix way, by doubling columns, not by a heavier
        # instance. The guide sign sets Barlow Condensed inline.
        "quote_regular": [(LUMEN_VARIABLE, "Bold"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(LUMEN_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [BARLOWCOND_SEMIBOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "platform": {
        # Lumen's Round instances, Medium for the body and Bold for the
        # matched phrase: on this board weight is dot size. The frame places
        # the dots from the face's grid and draws them at the diameters
        # measured from these two instances (``_PLATFORM_MEDIUM_DOT`` /
        # ``_PLATFORM_BOLD_DOT``); these chains serve the palette-only paths.
        "quote_regular": [(LUMEN_VARIABLE, "Medium"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(LUMEN_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(LUMEN_VARIABLE, "Bold"), *ORNAMENT_FONT_CANDIDATES],
    },
    "splitflap": {
        # Bebas Neue, as ``fillmore`` and others: an all-caps condensed
        # grotesque, the register of the flaps on a split-flap board, which
        # carry capitals only. One weight, so the matched phrase differs by
        # its yellow tile, not by a heavier face.
        "quote_regular": [BEBASNEUE_REGULAR, *QUOTE_FONT_SEMIBOLD_CANDIDATES],
        "quote_bold": [BEBASNEUE_REGULAR, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [BEBASNEUE_REGULAR, *ORNAMENT_FONT_CANDIDATES],
    },
    "redacted": {
        # Special Elite, as ``dispatch``: the Bureau's documents are typed.
        # One weight, so the matched phrase differs by colour alone. The
        # letterhead and form labels set their own Archivo Bold.
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
        "ornament": [ARCHIVO_BOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "traumateam": {
        # Oxanium — a squared techno sans in the register of the game's
        # interface faces. Regular for the white body, Bold for the matched
        # phrase on its red block, SemiBold for the band and the chrome.
        "quote_regular": [(OXANIUM_VARIABLE, "Regular"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(OXANIUM_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(OXANIUM_VARIABLE, "SemiBold"), *ORNAMENT_FONT_CANDIDATES],
    },
    "saros": {
        # Saros's text face Tamba Sans, display Arame and chrome Korataki are
        # all commercial. Saira is the nearest open face to Tamba Sans:
        # Regular body, SemiBold rather than Bold for the matched phrase (its
        # bloom would close a Bold's counters, as in trisolaris), Italic
        # byline. Default instance is Thin, so every candidate pins one. Exo 2
        # is the fallback.
        "quote_regular": [(SAIRA_VARIABLE, "Regular"), (EXO2_VARIABLE, "Regular"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(SAIRA_VARIABLE, "SemiBold"), (EXO2_VARIABLE, "SemiBold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(SAIRA_ITALIC_VARIABLE, "Italic"), (EXO2_ITALIC_VARIABLE, "Italic"), *ORNAMENT_FONT_CANDIDATES],
    },
    "observation": {
        # IBM Plex Mono — the station's own terminal face: an engineered
        # grotesque-derived mono with the 1970s-IBM-console register the game's
        # analogue retro-future interiors are built from. Medium for the body
        # (white strokes on black need the extra stem to survive the palette
        # snap), Bold for the phrase under its tangerine halo. Space Mono is
        # the next fallback so a stripped install stays monospaced.
        "quote_regular": [
            PLEXMONO_MEDIUM,
            SPACEMONO_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            *QUOTE_FONT_REGULAR_CANDIDATES,
        ],
        "quote_bold": [
            PLEXMONO_BOLD,
            SPACEMONO_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            PLEXMONO_BOLD,
            SPACEMONO_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "biomech": {
        # Spectral — a cold, sharp book serif with sturdy stems: bone-white on
        # black needs Medium to survive the palette snap, and the matched
        # phrase steps to SemiBold under its ember bloom. Grenze Gotisch's
        # thorned blackletter carries the ornament slot (the plate label and
        # the fall-through quote marks). Falls back through the system serifs.
        "quote_regular": [
            SPECTRAL_MEDIUM,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            *QUOTE_FONT_REGULAR_CANDIDATES,
        ],
        "quote_bold": [
            SPECTRAL_SEMIBOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (GRENZE_GOTISCH_VARIABLE, "SemiBold"),
            UNIFRAKTUR_BOOK,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "culture": {
        # Jura — humanist technical sans. Medium for the body because white
        # strokes on black need the extra stem to survive the palette snap,
        # Bold for the matched phrase under its aura. Share Tech Mono carries the
        # signal header and captions (loaded directly by the frame).
        "quote_regular": [
            JURA_MEDIUM,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            *QUOTE_FONT_REGULAR_CANDIDATES,
        ],
        "quote_bold": [
            JURA_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            JURA_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "orbital": {
        # Jura again — the two Culture themes are one universe seen from two
        # places. SemiBold rather than Medium for the body: this card is white
        # by day, and dark type on a light ground wants the heavier stem to
        # hold its hairline terminals through the snap. Bold for the phrase.
        "quote_regular": [
            JURA_SEMIBOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            *QUOTE_FONT_REGULAR_CANDIDATES,
        ],
        "quote_bold": [
            JURA_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            JURA_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "grimdark": {
        # Imperial Gothic = Roman + blackletter. Cinzel Decorative body (the
        # stone-cut inscription register) with UnifrakturMaguntia quote marks
        # — a pairing neither ``roman`` nor ``gothic`` uses. The matched phrase
        # steps one Cinzel weight up (Regular → Bold) and is told apart by the
        # forge-amber reroute in ``_draw_text_body``; switching face mid-line
        # would break the inscription. Heavy-serif fallbacks before Playfair.
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
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            UNIFRAKTUR_BOOK,
            CINZELDECORATIVE_BLACK,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Wax-sealed letter. Dancing Script carries the body and matched phrase
    # (Bold instance for a real weight step); Pinyon Script only the quote
    # marks, because its hairlines shatter at body sizes after palette snap
    # (see the DANCINGSCRIPT_VARIABLE / PINYONSCRIPT_REGULAR comments). Body
    # falls back through slanted sans; the ornament falls back to Dancing
    # Script Bold so the marks stay a pen hand.
    "letter": {
        "quote_regular": _HAND_SCRIPT_REGULAR,
        "quote_bold": _HAND_SCRIPT_BOLD,
        "ornament": [
            PINYONSCRIPT_REGULAR,
            (DANCINGSCRIPT_VARIABLE, "Bold"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "anna_atkins": {
        # Libre Caslon Text, the letterpress register of an 1843 English
        # natural-history book. Regular body, Bold matched phrase, plus the
        # sky-blue stipple reroute in ``_draw_text_body``.
        "quote_regular": [
            (LIBRECASLON_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (LIBRECASLON_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        # Quote marks in Pinyon Script copperplate, rendered as the same
        # sky-blue stipple via the blue/white ornament slots.
        "ornament": [
            PINYONSCRIPT_REGULAR,
            (LIBRECASLON_VARIABLE, "Bold"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "lieder": {
        # Alegreya: roman for the sung lyric, Bold for the matched phrase,
        # Italic for every editorial mark (tempo, expression, composer, plate
        # line) — an engraved score's roman/italic split. Falls back through
        # EB Garamond and the system serifs.
        "quote_regular": [
            ALEGREYA_REGULAR,
            EBGARAMOND_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            ALEGREYA_BOLD,
            EBGARAMOND_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        # The italic fills the ornament slot because this theme's "ornament" is
        # the editorial apparatus, not an oversized quote mark.
        "ornament": [
            ALEGREYA_ITALIC,
            IMFELLENGLISH_ITALIC,
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "izakaya": {
        # Quicksand: the nearest open type to a bent glass tube. Regular body,
        # Bold matched phrase. The ornament slot is Yuji Boku, for the shop
        # signs and the lantern's hour numeral. Falls back through system sans
        # — a high-contrast serif would read as anything but neon.
        "quote_regular": [
            QUICKSAND_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            QUICKSAND_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            YUJI_BOKU_REGULAR,
            QUICKSAND_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "abyssal": {
        # Lato: humanist sans that holds as white text over a dark gradient.
        # Regular body, Bold matched phrase under the mint bloom; the italic
        # (ornament slot) sets the attribution, the one unlit text.
        "quote_regular": [
            LATO_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            LATO_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            LATO_ITALIC,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
            LATO_REGULAR,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # pride reuses ``bauhaus``'s Jost: geometric sans is the register of the
    # 1970s poster and protest printing the flag came out of (a period serif
    # would read as a book jacket). Regular body, Bold matched phrase under
    # the violet accent.
    "pride": {
        "quote_regular": [
            (JOST_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (JOST_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (JOST_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # pulp uses Alfa Slab One, a heavy mid-century advertising slab. The
    # misregistration effect needs a FAT face: on a hairline serif the
    # off-register red fringe eats the letterform instead of haloing it.
    # Space Mono carries the small serial chrome, where a slab at 14 px clogs.
    "pulp": {
        "quote_regular": [
            (ALFA_SLAB_ONE, None),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "quote_bold": [
            (ALFA_SLAB_ONE, None),
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (ALFA_SLAB_ONE, None),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # synoptic uses Space Mono rather than Archivo: ``blueprint`` owns Archivo
    # and is the nearest neighbour in register, so a mono widens the gap and
    # reads as instrument printout.
    "synoptic": {
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
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # cardcatalog reuses ``dispatch``'s Special Elite — real catalogue cards
    # were typed — and the objects differ enough that sharing is fine (#210).
    # Space Mono carries the call number and stamps, which came off a metal
    # type wheel rather than a typewriter.
    "cardcatalog": {
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
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # vhs uses Antonio for the body: a camcorder character generator draws in
    # a tall narrow cell, and the condensed stems are what let the ±2 px
    # chroma ghosts clear the stem and read (on a wide face they vanish into
    # it). The matched phrase gets a real Bold step. The OSD chrome is loaded
    # inline in ``_vhs_paint_osd`` from Pixelify Sans.
    "vhs": {
        "quote_regular": [
            (ANTONIO_VARIABLE, "Regular"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            (ANTONIO_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            (ANTONIO_VARIABLE, "Bold"),
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # sampler stitches text from a Silkscreen pixel-font mask — Regular for the
    # body floss, Bold for the matched-phrase / ornament floss. The fallbacks
    # are a safety net only (non-grid glyphs read wrong as stitches).
    "sampler": {
        "quote_regular": [
            SILKSCREEN_REGULAR,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            SILKSCREEN_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            SILKSCREEN_BOLD,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # System sans for the diagnostic status panel: a grotesque reads better at
    # small label sizes than Playfair, and it keeps the palette-only paths
    # (source card, ``--message`` headline) visibly distinct from default.
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


# Themes whose layout draws no oversized quote marks at all. Distinct from
# setting both ornament slots to ``page_bg`` (which still paints, invisibly on
# a flat ground but visibly on a washed one).
_THEMES_WITHOUT_ORNAMENT_MARKS: frozenset[str] = frozenset({"betweenus", "betweenus_dark"})

# Themes whose matched-phrase face has a silhouette that breaks if its
# inter-word gaps are inflated by justification: these keep the
# matched-phrase spaces *rigid* (the bold face's natural width) and only the
# body's gaps absorb slack. Stretched, Eagle Lake's ``grimoire`` phrase reads
# as disconnected syllables and ``gothic``'s blackletter as separate clauses.
_THEMES_RIGID_MATCH_SPACING: frozenset[str] = frozenset({"grimoire", "gothic"})

# Themes whose body text is set ragged-right instead of justified. A
# typewriter, a terminal and a hand never justified a line: a monospace
# face stretched across elastic spaces reads as a column-alignment bug,
# matched phrase, quote marks and attribution are unaffected -- only the
# slack distribution on non-last body lines.
_THEMES_RAGGED_RIGHT: frozenset[str] = frozenset({
    "nightvision",   # Space Mono terminal readout
    "circuit",       # Space Mono silkscreen
    "dispatch",      # Special Elite typewriter
    "marker",        # Permanent Marker hand lettering
    "chalkboard",    # Playwrite cursive on slate
    "placard",       # Patrick Hand SC hand-printed sign
    "kanagawa",      # Yuji Boku sumi brush
})


# Per-theme synthesised "faux bold" for the matched phrase: Pillow's
# ``stroke_width=N`` thickens each glyph by ~N px per side, for faces that
# ship a single weight. ``glacier``: Iceland ships only Regular, and its teal
# accent is too close in hue to the blue body to carry the difference alone.
#
# The value must be threaded through measurement (``wrap_styled_text`` /
# ``render``'s width loops) and drawing (``_draw_text_body``) in lock-step, or
# lines overrun ``max_width`` / gaps don't match the painted silhouette.
_BOLD_STROKE_BY_THEME: dict[str, int] = {"glacier": 1}
