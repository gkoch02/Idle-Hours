"""Per-theme data: colours, cycle order, font roles and the small per-theme flags."""

from __future__ import annotations

# The roster itself lives in the Pillow-free ``theme_names`` (issue #393);
# re-exported here so ``render_quote.THEME_ORDER`` reads are unchanged.
from idle_hours.theme_names import CYCLE_EXCLUDED_THEMES as CYCLE_EXCLUDED_THEMES
from idle_hours.theme_names import THEME_ORDER as THEME_ORDER

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
    EBGARAMOND_BOLD,
    EBGARAMOND_REGULAR,
    EXO2_ITALIC_VARIABLE,
    EXO2_VARIABLE,
    FONDAMENTO_ITALIC,
    FONDAMENTO_REGULAR,
    FRAUNCES_ITALIC_VARIABLE,
    FRAUNCES_VARIABLE,
    GRENZE_GOTISCH_VARIABLE,
    IDLE_HOURS_FRAKTUR_BOOK,
    IMFELLDOUBLEPICA_ITALIC,
    IMFELLDOUBLEPICA_REGULAR,
    IMFELLENGLISH_ITALIC,
    IMFELLENGLISH_REGULAR,
    IMFELLENGLISHSC_REGULAR,
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
    # Between Us, light: italic matched phrase in solid red, which keeps the
    # italic's thin strokes whole. Ornament slots take the page ground; the
    # marks are skipped outright in ``_paint_ornament_mark``.
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
    # Between Us, dark: ``accent`` is a yellow sentinel ``_draw_text_body``
    # reroutes to the R+Y 1:1 amber (literal only in the debug banner).
    # Ornaments skipped, as for the light variant.
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
    # Pure typography: no colour accent; the matched phrase differs by bold
    # weight alone, like an old broadsheet. The paper tone lives in the border.
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
    # Green on black. Pure green reads dim on black at distance, so
    # ``_draw_text_body`` stipples the body (and quote marks) 50/50 with white.
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
    # Cathedral chronicle: black ground, white body, red rubric.
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
    # Bauhaus poster: blue matched phrase, red quote marks; the border adds
    # the yellow, so all three primaries appear at once.
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
    # Golden-age comic: yellow ground, black body for speech-bubble
    # legibility, red matched phrase like a sound-effect callout.
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
    # Typewritten dossier: black ink, red matched phrase — the bichrome
    # ribbon. Same palette as ``default``.
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
    # Atomic age: flat green ground, softened by the border's 1-in-4 white
    # dither (a 50/50 checkerboard reads minty pastel; 1-in-4 stays vivid).
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
    # Printed circuit board: green ground darkened to G+K soldermask by the
    # painter, white silkscreen body, gold (yellow) copper accent. Both
    # ornament keys yellow so the marks read as solid copper, not pale dither.
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
    # Fridge doodle: black Sharpie body, blue matched phrase (a second
    # marker), red quote marks; the border adds the other inks.
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
    # "WANTED" broadside: the default palette shape; face and border differ.
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
    # Roman inscription: red accent as rubrum, the red lead carvers painted
    # into the grooves.
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
    # Alchemical manuscript: red rubricated matched phrase, blue Hermetic
    # ornaments — the blue mercury / red sulphur split of the Mutus Liber.
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
    # Red accent stippled to tangerine (5/8 R : 3/8 Y on ``BAYER_4x4``,
    # threshold 6) in two places that must share the tone: ``_draw_text_body``
    # and ``draw_deco_border``'s final pass. 50/50 reads washed-out amber.
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
    # Chalkboard: same palette as ``dark``; the face and the border differ.
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
    # Hand-painted shop placard: black body, red matched phrase.
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
    # Samurai cinema title card: white on black, red matched phrase.
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
    # LCARS console: the yellow accent renders solid (no body reroute); the
    # chrome's tangerine is synthesised from the ornament slots below.
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
    # Fillmore poster: ``text`` is a red sentinel ``_draw_text_body``
    # stipples R+K to maroon, taming the red-on-yellow clash.
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
    # Celestial atlas: white body on a navy ground the border synthesises
    # from the black ``page_bg``; the yellow accent is a sentinel.
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
    # Astrarium: custom frame; the palette serves the palette-only paths
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
    # Kanagawa seascape: black brush body on the cream paper card.
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
    # Cinema marquee: custom frame; the palette serves the palette-only
    # paths (see the note above ``THEMES``).
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
    # Tarot: custom frame; red + blue rubricated chrome, the matched phrase
    # in Tyrian purple (R+B 1:1).
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
    # Stained-glass window: custom frame that hardcodes its inks; this
    # palette is for the palette-only paths (see the note above ``THEMES``).
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
    # Antique chart: black italic body, upright red matched phrase, so
    # roman/italic plus colour do the differentiation.
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
    # Pixel RPG: custom frame that hardcodes its inks (``fit_quote`` takes
    # the theme name only for fonts); see the note above ``THEMES``.
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
    # 16-bit JRPG: custom frame; the palette serves the palette-only paths
    # (see the note above ``THEMES``).
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
    # Synthwave: custom frame; the matched phrase is red-biased magenta
    # (R+B 5/8:3/8). The palette serves the palette-only paths.
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
    # The King in Yellow: ``dark``'s inks, the King's yellow solid, never
    # stippled; both ornament slots yellow so the quote marks paint solid.
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
    # Codex Seraphinianus, a custom frame (``render_codex_frame``).
    # Palette serves the palette-only paths (see the note above ``THEMES``).
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
    # Remedy's *Control*, a custom frame (``render_control_frame``).
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
    # Bacon's *Three Studies*, a custom frame (``render_furies_frame``).
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
    # Bosch's *Garden of Earthly Delights*, a custom frame
    # (``render_bosch_frame``).
    # Palette serves the palette-only paths (see the note above ``THEMES``).
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
    # Cobb's Semiotic Standard, a custom frame (``render_semiotic_frame``).
    # Palette serves the palette-only paths (see the note above ``THEMES``).
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
    # *Returnal*'s Atropos, a custom frame (``render_atropos_frame``).
    # Palette serves the palette-only paths (see the note above ``THEMES``).
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
    # *Clair Obscur: Expedition 33*, a custom frame
    # (``render_expedition_frame``).
    # Palette serves the palette-only paths (see the note above ``THEMES``).
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
    # *The Witcher 3* bestiary page, a custom frame: cream parchment, black
    # ink, red for the tangerine phrase. Palette serves the palette-only paths.
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
    # *Hades II* boon card, a custom frame: black and gold, white text with a
    # gold phrase. Palette serves the palette-only paths.
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
    # *The Expanse* console, a custom frame: white on black glass, blue
    # hairlines. Palette serves the palette-only paths.
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
    # Beksiński's cathedral of bone, a custom frame: black text in a pale
    # haze, red phrase. Palette serves the palette-only paths.
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
    # Goya's *El Perro*, a custom frame: black text on the ochre void, the
    # phrase in Saturn's red. Palette serves the palette-only paths.
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
    # Trauma Team dispatch screen, a custom frame: white on black, red only
    # as a ground. Palette serves the palette-only paths.
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
    # A declassified Bureau document, a custom frame: black type on white, red
    # phrase. Palette serves the palette-only paths.
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
    # A highway LED sign at night, a custom frame: amber (yellow) on black, the
    # phrase lit white. Palette serves the palette-only paths.
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
    # A railway departure board, a custom frame: amber (yellow) dots on black.
    # Palette serves the palette-only paths.
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
    # A split-flap board, a custom frame: white capitals on black tiles, the
    # phrase on yellow. Palette serves the palette-only paths.
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
    # A red-ruled 17th-century Oxford page, a custom frame: Fell black on
    # white, the phrase rubricated. Palette serves the palette-only paths.
    "imprimatur": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["red"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["red"],
        "source": SPECTRA6["black"],
    },
    # *2001*'s Discovery monitors, a custom frame: white on the blue monitor,
    # yellow phrase. Palette serves the palette-only paths.
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
    # *Severance*'s MDR terminal, a custom frame: white on the blue CRT,
    # yellow phrase. Palette serves the palette-only paths.
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
    # The Apollo DSKY, a custom frame (its card is typed black with a red
    # phrase). This dark palette serves only the palette-only paths.
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
    # *Oblivion*'s light table, a custom frame: black on white glass, red
    # phrase. Palette serves the palette-only paths.
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
    # *NieR: Automata*'s menu, a custom frame: black on cream, the phrase
    # knocked out of a black box. Palette serves the palette-only paths.
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
    # The 1981 BBC Guide, a custom frame: white on black, yellow phrase.
    # Palette serves the palette-only paths.
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
    # A letter on a writing desk, a custom frame: black ink on cream, the
    # phrase in fountain-pen blue. Palette serves the palette-only paths.
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
    # *Blade Runner 2049*'s Las Vegas, a custom frame: white on the black
    # archive pane, yellow phrase. Palette serves the palette-only paths.
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
    # *Blade Runner 2049*'s LAPD screens, a custom frame: white on black
    # glass, yellow phrase. Palette serves the palette-only paths.
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
    # Housemarque's *Saros*, a custom frame (``render_saros_frame``).
    # Palette serves the palette-only paths (see the note above ``THEMES``).
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
    # *Observation*, a custom frame (``render_observation_frame``).
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
    # *The Three-Body Problem*, a custom frame (``render_trisolaris_frame``).
    # Palette serves the palette-only paths (see the note above ``THEMES``).
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
    # Giger and Beksiński, a custom frame (``render_biomech_frame``).
    # Palette serves the palette-only paths (see the note above ``THEMES``).
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
    # The Culture's Mind signal, a custom frame (``render_culture_frame``).
    # Palette serves the palette-only paths (see the note above ``THEMES``).
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
    # The Culture's Arch, a custom frame (``render_orbital_frame``).
    # Palette serves the palette-only paths (see the note above ``THEMES``):
    # day inks, white card, dark type, blue phrase.
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
    # Wax-sealed letter: cream from the painter's Layer 0, black body, red
    # sealing-wax matched phrase. Ornament keys black/white: the 50/50 faux-gray
    # quote marks read as a pale pen stroke rather than a blot.
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
    # Cyanotype. ``accent`` is a yellow sentinel ``_draw_text_body`` reroutes
    # to a B+W sky-blue stipple (literal only in the debug banner); ornament
    # keys blue/white give the quote marks the same sky-blue.
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
    # serve only the palette-only paths (see the note above ``THEMES``); the
    # frame hardcodes its own inks (roman black / italic black / red voice).
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
    # the palette-only paths (see the note above ``THEMES``); the frame paints
    # its tube cores and blooms directly.
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
    # Deep sea. A custom-render frame, so these colours serve only the
    # palette-only paths (see the note above ``THEMES``); the frame paints its
    # own depth gradient and blooms.
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
    # Progress Pride flag. Custom frame; palette serves the palette-only paths
    # (see the note above ``THEMES``). ``accent`` is blue: the frame's violet is
    # R+B, and blue is the half that still reads on the white card.
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
    # Bakelite console. Custom frame; palette serves the palette-only paths
    # (see the note above ``THEMES``). ``text`` is the yellow phosphor core,
    # ``accent`` the red halo, ``page_bg`` the black glass.
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
    # Whistler nocturne. Custom frame; palette serves the palette-only paths
    # (see the note above ``THEMES``).
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
    # Bronze plaque. Custom frame; palette serves the palette-only paths (see
    # the note above ``THEMES``): verdigris ground, brass lettering.
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
    # Cased daguerreotype. Custom frame; palette serves the palette-only paths
    # (see the note above ``THEMES``): gold stamping on red velvet, white phrase.
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
    # Autochrome lantern slide. Custom frame; palette serves the palette-only
    # paths (see the note above ``THEMES``): white caption on the black mask,
    # matched phrase in yellow.
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
    # The operator's own photograph. Custom frame; palette serves the
    # palette-only paths (see the note above ``THEMES``): the cream caption card.
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
    # Library catalogue card. Custom frame; palette serves the palette-only
    # paths (see the note above ``THEMES``). The frame's ink is R+B violet.
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
    # Worn VHS tape. Custom frame; palette serves the palette-only paths (see
    # the note above ``THEMES``). Red and blue are the two chroma records.
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
    # Surface analysis (a border painter, not a frame). Blue and red are the
    # cold- and warm-front inks; the matched phrase is warm-front red.
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
    # Transit diagram. Custom frame; the matched phrase is the red express
    # route through the otherwise-black text block.
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
    # Diagnostic status panel, a custom frame. White/black/red keeps the
    # palette-only paths readable; the frame also reads it for its labels.
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
    # Counted cross-stitch sampler. Custom frame; palette serves the
    # palette-only paths (see the note above ``THEMES``). Black floss body,
    # red floss matched phrase.
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
    # Fraunces, every candidate pinned (the default instance is Black). The
    # matched phrase is the italic cut: Italic 400 in light, SemiBold Italic in
    # dark so the amber stipple has stroke mass.
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
    # Jost: near-monoline strokes bloom evenly, where a high-contrast face
    # haloes unevenly. Space Mono Bold carries the stencilled legend.
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
    # Cormorant Garamond, body pinned to **Medium**, not Regular: the body
    # blooms, and Regular's hairlines shred in the halo.
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
    # Cinzel Decorative one weight heavier (Bold body, Black phrase): a relief
    # face needs stroke mass. Fallbacks stay heavy serifs for the same reason.
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
    # Libre Caslon Text, shared on purpose by the photographic themes.
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
    # Libre Caslon Text, like the other photographic themes. The sans mount
    # chrome loads directly from the meta chain.
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
    # Libre Caslon: a neutral book serif suits a caption over an unknown picture.
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
    # Jost: open counters survive route-map legend sizes.
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
    # Space Mono, nightvision's chain: the silkscreen register of a PCB legend.
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
    "gothic": {
        # Blackletter for the matched phrase and quote marks; EB Garamond
        # body for legibility, and its Bold behind a missing Unifraktur.
        # Idle Hours Fraktur is Unifraktur with an open k, so "o'clock"
        # doesn't read as "o'clocf".
        "quote_regular": [
            EBGARAMOND_REGULAR,
            *QUOTE_FONT_SEMIBOLD_CANDIDATES,
        ],
        "quote_bold": [
            IDLE_HOURS_FRAKTUR_BOOK,
            EBGARAMOND_BOLD,
            *QUOTE_FONT_BOLD_CANDIDATES,
        ],
        "ornament": [
            IDLE_HOURS_FRAKTUR_BOOK,
            EBGARAMOND_BOLD,
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    "bauhaus": {
        # Jost variable, default 400; every candidate pins its instance so
        # the bold phrase stays distinguishable.
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
        # Single weight: the matched phrase differs by colour alone. Mono
        # fallbacks keep a missing install typewriter-adjacent.
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
        # Regular only, so the matched phrase differs by colour.
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
        # Single weight; the matched phrase differs by its blue.
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
        # The matched phrase steps up a weight rather than switching face,
        # which would break the inscription; Black carries the marks.
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
        # Regular only: the matched phrase differs by its red, as on a
        # two-colour broadside.
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
        # IM Fell English body; MedievalSharp (Regular only) for the matched
        # phrase and marks, with UnifrakturMaguntia, the next-nearest ritual
        # hand, behind it.
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
    "deco": {
        # Regular only; the matched phrase differs by its accent.
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
        # Single weight; the matched phrase differs by its red.
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
        # Single weight; the matched phrase differs by its red.
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
        # Single weight; the matched phrase differs by its yellow. Italic
        # fallbacks keep a missing install slanted.
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
    "fillmore": {
        # Bungee Shade for the whole body on purpose: borderline illegible
        # under the maroon stipple, which is the Fillmore register.
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
        # Cardo; the Italic fills the ornament role for the opening mark.
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
        # The default axis instance is Regular, but Regular / Bold are pinned
        # by name so an upstream default change can't shift the weight.
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
        # Wordmark, callouts and quote marks share the condensed Antonio.
        "ornament": [
            (ANTONIO_VARIABLE, "Bold"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            *ORNAMENT_FONT_CANDIDATES,
        ],
    },
    # Astrarium — EB Garamond, not Cormorant: Cormorant's hairlines drop below
    # 1 px at the 18-38 pt fit range and vanish into the washed ground.
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
        # Single weight; the matched phrase differs by its red. Serif
        # fallbacks: a grotesque would clash with the brush register.
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
    # Marquee — Cardo Italic body, Cardo Bold matched phrase; Bungee Shade in
    # the ornament slot carries the feature title.
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
    # Tarot — EB Garamond body; Cinzel Decorative Bold matched phrase and
    # Black Roman-numeral hour.
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
    # Vitrail — Uncial Antiqua for the rose-window numeral only, with medieval
    # fallbacks; it shatters at byline sizes.
    "vitrail": {
        # Liberation Serif stays crisp at the 15-30 px cartouche sizes.
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
    # Cartograph — italic body, upright matched phrase and quote marks (the
    # mapmakers' italic legends and upright place names).
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
    # Press Start 2P everywhere; single weight, so the matched phrase
    # differs by its yellow.
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
    # Oxanium, not Orbitron: Orbitron is so wide that a dense quote shrinks
    # unreadably. Variable; the matched phrase pins Bold.
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
        # Almendra body / Bold phrase, Almendra Display quote marks; IM Fell
        # English before the system serifs.
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
        # Fondamento has no bold: the Italic carries the matched phrase.
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
        # Jost pinned Bold for the body as well as the phrase; Archivo for the sign.
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
        # SemiBold, not Bold, for the phrase: its bloom would clog a Bold's counters.
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
        # Libre Franklin, instances pinned: Medium body, ExtraBold phrase,
        # Medium Italic attribution.
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
        # Grenze Gotisch, instances pinned: Medium body, Bold phrase, Black ornament.
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
        # Barlow Condensed: Medium body, Bold phrase, SemiBold chrome.
        "quote_regular": [BARLOWCOND_MEDIUM, (OSWALD_VARIABLE, "Regular"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [BARLOWCOND_BOLD, (OSWALD_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [BARLOWCOND_SEMIBOLD, (OSWALD_VARIABLE, "Medium"), *ORNAMENT_FONT_CANDIDATES],
    },
    "atropos": {
        # Saira's default instance is Thin, so every candidate pins one.
        "quote_regular": [(SAIRA_VARIABLE, "Regular"), MICHROMA_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(SAIRA_VARIABLE, "SemiBold"), MICHROMA_REGULAR, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [MICHROMA_REGULAR, (OXANIUM_VARIABLE, "Medium"), *ORNAMENT_FONT_CANDIDATES],
    },
    "expedition": {
        # IM Fell Double Pica has no bold: the italic carries the matched phrase.
        # Cinzel Decorative is the wordmark.
        "quote_regular": [IMFELLDOUBLEPICA_REGULAR, IMFELLENGLISH_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [IMFELLDOUBLEPICA_ITALIC, IMFELLENGLISH_ITALIC, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [CINZELDECORATIVE_BOLD, CINZELDECORATIVE_REGULAR, *ORNAMENT_FONT_CANDIDATES],
    },
    "witcher": {
        # Barlow Condensed for PF DIN Text Condensed; Archivo Narrow (for Bell
        # Gothic) takes the ornament slot. Archivo Narrow is variable: pin it.
        "quote_regular": [BARLOWCOND_MEDIUM, (ARCHIVONARROW_VARIABLE, "Medium"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [BARLOWCOND_BOLD, (ARCHIVONARROW_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(ARCHIVONARROW_VARIABLE, "Bold"), ARCHIVO_BOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "hades": {
        # The game's own Spectral (Medium body, SemiBold phrase); Caesar
        # Dressing, its title-card face, in the ornament slot.
        "quote_regular": [SPECTRAL_MEDIUM, ALEGREYA_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [SPECTRAL_SEMIBOLD, ALEGREYA_BOLD, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [CAESARDRESSING_REGULAR, CINZELDECORATIVE_BOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "expanse": {
        # Barlow for the show's modified DIN Pro: Regular body, SemiBold
        # phrase (told apart by its orange); Barlow Condensed falls back.
        "quote_regular": [BARLOW_REGULAR, BARLOWCOND_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [BARLOW_SEMIBOLD, BARLOWCOND_SEMIBOLD, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [BARLOW_BOLD, BARLOWCOND_BOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "beksinski": {
        # Old Standard TT, the period's Didone (shared with ``newsprint``):
        # Regular body, Bold phrase.
        "quote_regular": [OLDSTANDARD_REGULAR, *QUOTE_FONT_SEMIBOLD_CANDIDATES],
        "quote_bold": [OLDSTANDARD_BOLD, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [OLDSTANDARD_BOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "goya": {
        # Libre Baskerville (see the constant): Regular body, Bold phrase, the
        # italic for the label's title line; Libre Caslon falls back.
        "quote_regular": [(LIBREBASKERVILLE_VARIABLE, "Regular"), (LIBRECASLON_VARIABLE, "Regular"),
                          *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(LIBREBASKERVILLE_VARIABLE, "Bold"), (LIBRECASLON_VARIABLE, "Bold"),
                       *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(LIBREBASKERVILLE_ITALIC_VARIABLE, "Italic"), (LIBREBASKERVILLE_VARIABLE, "Bold"),
                     *ORNAMENT_FONT_CANDIDATES],
    },
    "hal": {
        # Jost (the film's Futura): Regular body, Bold phrase. Michroma (its
        # Microgramma) takes the ornament slot for the chrome.
        "quote_regular": [(JOST_VARIABLE, "Regular"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(JOST_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [MICHROMA_REGULAR, (JOST_VARIABLE, "Bold"), *ORNAMENT_FONT_CANDIDATES],
    },
    "lumon": {
        # Montserrat (for the grid's Gotham): Regular body, Bold phrase. Inter
        # (for Forma DJR) takes the ornament slot; Michroma is the wordmark.
        "quote_regular": [(MONTSERRAT_VARIABLE, "Regular"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(MONTSERRAT_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(INTER_VARIABLE, "Medium"), MICHROMA_REGULAR, *ORNAMENT_FONT_CANDIDATES],
    },
    "dsky": {
        # Special Elite, one weight: the phrase differs by its red ink. Jost
        # Medium (for Futura Demi) is every legend on the unit.
        "quote_regular": [SPECIALELITE_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [SPECIALELITE_REGULAR, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(JOST_VARIABLE, "Medium"), *ORNAMENT_FONT_CANDIDATES],
    },
    "oblivion": {
        # Exo 2 (for the film's Blender), default instance Thin, so pin one:
        # Light body (solid black on white holds it), Medium phrase.
        "quote_regular": [(EXO2_VARIABLE, "Light"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(EXO2_VARIABLE, "Medium"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(EXO2_VARIABLE, "Regular"), *ORNAMENT_FONT_CANDIDATES],
    },
    "yorha": {
        # EB Garamond, the nearest open face to the game's unidentified serif:
        # Regular body, Bold phrase.
        "quote_regular": [EBGARAMOND_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [EBGARAMOND_BOLD, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [EBGARAMOND_BOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "hitchhiker": {
        # Michroma, one static weight: the phrase differs by its yellow.
        "quote_regular": [MICHROMA_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [MICHROMA_REGULAR, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [MICHROMA_REGULAR, *ORNAMENT_FONT_CANDIDATES],
    },
    "escritoire": {
        # ``letter``'s Dancing Script, pinned Regular body and Bold phrase;
        # Pinyon's hairlines shred once the warp shrinks them.
        "quote_regular": _HAND_SCRIPT_REGULAR,
        "quote_bold": _HAND_SCRIPT_BOLD,
        "ornament": [(DANCINGSCRIPT_VARIABLE, "Bold"), *ORNAMENT_FONT_CANDIDATES],
    },
    "lasvegas": {
        # Barlow: Medium body (a Regular stem thins as white bleeds into the
        # black), Bold phrase; Barlow Condensed for the chrome.
        "quote_regular": [BARLOW_MEDIUM, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [BARLOW_BOLD, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [BARLOWCOND_MEDIUM, *ORNAMENT_FONT_CANDIDATES],
    },
    "bladerunner": {
        # Barlow Condensed: Medium body, Bold phrase, SemiBold chrome.
        "quote_regular": [BARLOWCOND_MEDIUM, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [BARLOWCOND_BOLD, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [BARLOWCOND_SEMIBOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "gantry": {
        # Lumen, read as dot bitmaps (``_gantry_glyph``), pinned Bold so a dot
        # sits over every grid centre; the phrase is bolded by doubling columns.
        "quote_regular": [(LUMEN_VARIABLE, "Bold"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(LUMEN_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [BARLOWCOND_SEMIBOLD, *ORNAMENT_FONT_CANDIDATES],
    },
    "platform": {
        # Lumen Round Medium body, Bold phrase. The frame draws its own dots
        # (``_PLATFORM_*_DOT``); these chains serve the palette-only paths.
        "quote_regular": [(LUMEN_VARIABLE, "Medium"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(LUMEN_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(LUMEN_VARIABLE, "Bold"), *ORNAMENT_FONT_CANDIDATES],
    },
    "splitflap": {
        # Bebas Neue, one weight: the phrase differs by its yellow tile.
        "quote_regular": [BEBASNEUE_REGULAR, *QUOTE_FONT_SEMIBOLD_CANDIDATES],
        "quote_bold": [BEBASNEUE_REGULAR, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [BEBASNEUE_REGULAR, *ORNAMENT_FONT_CANDIDATES],
    },
    "imprimatur": {
        # Fell roman body; the SC cut (one weight) for the phrase, so it
        # differs by letterform as well as by its red.
        "quote_regular": [IMFELLENGLISH_REGULAR, *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [IMFELLENGLISHSC_REGULAR, IMFELLENGLISH_REGULAR, *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [IMFELLENGLISHSC_REGULAR, *ORNAMENT_FONT_CANDIDATES],
    },
    "redacted": {
        # Special Elite, one weight: the phrase differs by colour alone.
        # The letterhead and form labels set their own Archivo Bold.
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
        # Oxanium: Regular body, Bold phrase, SemiBold chrome.
        "quote_regular": [(OXANIUM_VARIABLE, "Regular"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(OXANIUM_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(OXANIUM_VARIABLE, "SemiBold"), *ORNAMENT_FONT_CANDIDATES],
    },
    "saros": {
        # Saira's default instance is Thin, so every candidate pins one; SemiBold,
        # not Bold, for the bloomed phrase.
        "quote_regular": [(SAIRA_VARIABLE, "Regular"), (EXO2_VARIABLE, "Regular"), *QUOTE_FONT_REGULAR_CANDIDATES],
        "quote_bold": [(SAIRA_VARIABLE, "SemiBold"), (EXO2_VARIABLE, "SemiBold"), *QUOTE_FONT_BOLD_CANDIDATES],
        "ornament": [(SAIRA_ITALIC_VARIABLE, "Italic"), (EXO2_ITALIC_VARIABLE, "Italic"), *ORNAMENT_FONT_CANDIDATES],
    },
    "observation": {
        # IBM Plex Mono: Medium body (white on black), Bold phrase; Space Mono
        # next so a stripped install stays monospaced.
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
        # Spectral Medium body, SemiBold phrase; Grenze Gotisch (pinned) ornament.
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
        # Jura Medium body (white on black), Bold phrase; Share Tech Mono chrome
        # is loaded by the frame.
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
        # Jura SemiBold body (dark type on the day card), Bold phrase.
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
    # Dancing Script (Bold instance pinned for the matched phrase); Pinyon
    # Script only for the marks, whose hairlines shatter at body sizes. The
    # ornament falls back to Dancing Script Bold so the marks stay a pen hand.
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
        # Libre Caslon Text, the letterpress register of Atkins's era.
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
        # Alegreya: roman lyric, Bold matched phrase, Italic editorial marks.
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
        # Quicksand, the nearest open type to a bent glass tube; Yuji Boku in
        # the ornament slot for the signs and the lantern numeral.
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
        # Lato: holds as white text over a dark gradient. The italic (ornament
        # slot) sets the attribution, the one unlit text.
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
    # Jost, ``bauhaus``'s chain: the geometric sans of 1970s protest printing.
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
    # Alfa Slab One: the misregistration needs a FAT face (on a hairline
    # serif the red fringe eats the letterform).
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
    # Space Mono: a mono reads as instrument printout.
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
    # Special Elite, ``dispatch``'s typewriter: real catalogue cards were
    # typed. Space Mono (type-wheel call number and stamps) is the fallback.
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
    # Antonio: condensed stems let the ±2 px chroma ghosts clear the stem.
    # The OSD chrome loads Pixelify Sans inline in ``_vhs_paint_osd``.
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
    # Silkscreen: the pixel grid is the stitch chart. Fallbacks are a safety
    # net only (non-grid glyphs read wrong as stitches).
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
    # System sans: reads better than Playfair at label sizes, and keeps the
    # palette-only paths visibly distinct from ``default``.
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
# body's gaps absorb slack. Stretched, ``gothic``'s blackletter phrase reads
# as separate clauses.
_THEMES_RIGID_MATCH_SPACING: frozenset[str] = frozenset({"gothic"})

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
# ship a single weight. No live theme sets one.
#
# The value must be threaded through measurement (``wrap_styled_text`` /
# ``render``'s width loops) and drawing (``_draw_text_body``, which needs a
# branch passing ``stroke_width=_bold_stroke_for_theme(theme)``) in lock-step,
# or lines overrun ``max_width`` / gaps don't match the painted silhouette.
_BOLD_STROKE_BY_THEME: dict[str, int] = {}
