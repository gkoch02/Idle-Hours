"""Where the bundled fonts live: the package directory and every font file and fallback chain.

Pure data at the bottom of the render_quote layers (docs/render_quote_split.md). The font
candidate chains sit here, below theme_tables, because THEME_FONTS is built from them.
"""

from __future__ import annotations

from pathlib import Path

# The idle_hours/ package directory (fonts/, assets/), one level above this
# file now that render_quote is a package (issue #335).
BASE_DIR = Path(__file__).resolve().parent.parent

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
# ``ornament``) resolves through a fallback chain; entries are a path string or
# a ``(path, variation_name)`` tuple for variable fonts (``load_font`` calls
# ``set_variation_by_name``). Pin an instance on every variable entry — several
# fonts default to Thin, Light or Black. ``default`` / ``dark`` keep the
# Playfair chain so their goldens don't drift. Each chain ends at the Playfair
# / DejaVu defaults so a missing-fonts install still renders rather than
# bitmap-fallbacking. Notes on the early themes:
#
# * ``newsprint`` → Old Standard TT (Didone-flavoured broadsheet serif).
# * ``nightvision`` → Space Mono (retro-terminal mono legible on eInk);
#   DejaVu Sans Mono as fallback.
# * ``bauhaus`` → Jost (geometric sans, distinct from Archivo's grotesque).
# * ``comic`` → Bangers (all-caps comic hand). One weight only, so the
#   matched phrase falls through to DejaVu Sans Bold for weight contrast.
OLDSTANDARD_REGULAR = str(BASE_DIR / "fonts/old-standard-tt/OldStandard-Regular.ttf")
OLDSTANDARD_BOLD = str(BASE_DIR / "fonts/old-standard-tt/OldStandard-Bold.ttf")
SPACEMONO_REGULAR = str(BASE_DIR / "fonts/space-mono/SpaceMono-Regular.ttf")
SPACEMONO_BOLD = str(BASE_DIR / "fonts/space-mono/SpaceMono-Bold.ttf")
ALFA_SLAB_ONE = str(BASE_DIR / "fonts/alfa-slab-one/AlfaSlabOne-Regular.ttf")
ARCHIVO_BOLD = str(BASE_DIR / "fonts/archivo/Archivo-Bold.ttf")
# Archivo Narrow (witcher labels + WILD HUNT mark) — variable on weight, the nearest open face
# to Bell Gothic Bold.
ARCHIVONARROW_VARIABLE = str(BASE_DIR / "fonts/archivo-narrow/ArchivoNarrow[wght].ttf")
EBGARAMOND_REGULAR = str(BASE_DIR / "fonts/eb-garamond/EBGaramond-Regular.ttf")
EBGARAMOND_BOLD = str(BASE_DIR / "fonts/eb-garamond/EBGaramond-Bold.ttf")
UNIFRAKTUR_BOOK = str(BASE_DIR / "fonts/unifraktur/UnifrakturMaguntia-Book.ttf")
JOST_VARIABLE = str(BASE_DIR / "fonts/jost/Jost-Variable.ttf")
BANGERS_REGULAR = str(BASE_DIR / "fonts/bangers/Bangers-Regular.ttf")
SPECIALELITE_REGULAR = str(BASE_DIR / "fonts/special-elite/SpecialElite-Regular.ttf")
ATOMICAGE_REGULAR = str(BASE_DIR / "fonts/atomic-age/AtomicAge-Regular.ttf")
PERMANENTMARKER_REGULAR = str(BASE_DIR / "fonts/permanent-marker/PermanentMarker-Regular.ttf")
RYE_REGULAR = str(BASE_DIR / "fonts/rye/Rye-Regular.ttf")
CINZELDECORATIVE_REGULAR = str(BASE_DIR / "fonts/cinzel-decorative/CinzelDecorative-Regular.ttf")
CINZELDECORATIVE_BOLD = str(BASE_DIR / "fonts/cinzel-decorative/CinzelDecorative-Bold.ttf")
CINZELDECORATIVE_BLACK = str(BASE_DIR / "fonts/cinzel-decorative/CinzelDecorative-Black.ttf")
# IM Fell English — Igino Marini's revival of John Fell's 17th-century Oxford
# types (OFL). The metal-type inking irregularities read as an antique page.
# Its 352-glyph cmap covers curly quotes / em-dash / extended Latin, so it is
# safe in body and ornament slots. Body face for ``alchemy``.
IMFELLENGLISH_REGULAR = str(BASE_DIR / "fonts/im-fell-english/IMFellEnglish-Regular.ttf")
IMFELLENGLISH_ITALIC = str(BASE_DIR / "fonts/im-fell-english/IMFellEnglish-Italic.ttf")
# IM Fell Double Pica (expedition body + matched phrase) — the Fell types at Double Pica size,
# the face Clair Obscur: Expedition 33 sets its UI text in. Roman and italic only; no bold exists.
IMFELLDOUBLEPICA_REGULAR = str(BASE_DIR / "fonts/im-fell-double-pica/IMFELLDoublePica-Regular.ttf")
IMFELLDOUBLEPICA_ITALIC = str(BASE_DIR / "fonts/im-fell-double-pica/IMFELLDoublePica-Italic.ttf")
# Bebas Neue (expedition numerals + label chrome) — condensed display caps, the face the same
# game sets its UI numbers in. One static Regular.
BEBASNEUE_REGULAR = str(BASE_DIR / "fonts/bebas-neue/BebasNeue-Regular.ttf")
# MedievalSharp (OFL). Calligraphic display face with sharply pointed
# strokes; matched-phrase + ornament face for ``alchemy``.
MEDIEVALSHARP_REGULAR = str(BASE_DIR / "fonts/medieval-sharp/MedievalSharp-Regular.ttf")
# Uncial Antiqua — Astigmatic (OFL). Single-weight ecclesiastical uncial;
# ``vitrail``'s rose-window numeral and quote marks. Single weight, so the
# matched phrase differs by its violet-glass colour alone. Falls back through
# MedievalSharp → UnifrakturMaguntia to stay on a medieval silhouette.
UNCIALANTIQUA_REGULAR = str(BASE_DIR / "fonts/uncial-antiqua/UncialAntiqua-Regular.ttf")
# Righteous — Astigmatic (OFL). 1930s geometric art-deco display sans.
# Single weight, so ``deco``'s matched phrase differs by colour alone. Falls
# back through heavy sans before the Playfair chain to stay a display face.
RIGHTEOUS_REGULAR = str(BASE_DIR / "fonts/righteous/Righteous-Regular.ttf")
# Playwrite GB J Guides — TypeTogether (OFL). British school joined cursive
# with the dotted-outline guide letters. Single weight (a bold would defeat
# the practice-letter look), so ``chalkboard``'s matched phrase differs by
# its yellow alone. Falls back through DejaVu Sans Italic so a missing
# install stays slanted.
PLAYWRITE_GB_J_GUIDES_REGULAR = str(BASE_DIR / "fonts/playwrite-gb-j-guides/PlaywriteGBJGuides-Regular.ttf")
# Patrick Hand SC — Patrick Wagesreiter (OFL). Hand-printed small caps (the
# SC variant sets lowercase as small capitals): shop-sign register for
# ``placard``. Single weight; matched phrase differs by colour. Falls back
# through heavy sans before the Playfair chain.
PATRICK_HAND_SC_REGULAR = str(BASE_DIR / "fonts/patrick-hand-sc/PatrickHandSC-Regular.ttf")
# Shojumaru — Astigmatic (OFL). Brush-painted display face (samurai cinema
# posters) for ``chanbara``. Single weight; matched phrase differs by colour.
# Falls back through heavy sans before the Playfair chain.
SHOJUMARU_REGULAR = str(BASE_DIR / "fonts/shojumaru/Shojumaru-Regular.ttf")
# Antonio — Vernon Adams (OFL). The usual free LCARS substitute: a tall
# condensed sans echoing Helvetica Compressed. Variable Weight axis
# (100..700, default Regular); ``THEME_FONTS["lcars"]`` pins Regular / Bold.
# The condensed proportions are what read as console UI. Falls back through
# heavy sans before the Playfair chain.
ANTONIO_VARIABLE = str(BASE_DIR / "fonts/antonio/Antonio-Variable.ttf")
# Lumen (Font Studio, OFL) — a 5x7 LED dot-matrix face on a strict grid, one
# dot every tenth of an em. Variable Weight (dot size, 100..900) and
# Roundness axes. ``gantry`` reads it as dot bitmaps, not as outlines.
LUMEN_VARIABLE = str(BASE_DIR / "fonts/lumen/Lumen-Variable.ttf")
# Oswald (Vernon Adams / Kalapi Gajjar / Cyreal, OFL) — the free stand-in for
# the heavy condensed grotesque of *Control*'s title cards; variable Weight
# axis with ExtraLight..Bold named instances. Used by ``control``.
OSWALD_VARIABLE = str(BASE_DIR / "fonts/oswald/Oswald-Variable.ttf")
# IBM Plex Mono (IBM, OFL) — static Medium / SemiBold / Bold, converted from
# IBM's WOFF. The S.A.M. terminal face of ``observation``.
PLEXMONO_MEDIUM = str(BASE_DIR / "fonts/ibm-plex-mono/IBMPlexMono-Medium.ttf")
PLEXMONO_SEMIBOLD = str(BASE_DIR / "fonts/ibm-plex-mono/IBMPlexMono-SemiBold.ttf")
PLEXMONO_BOLD = str(BASE_DIR / "fonts/ibm-plex-mono/IBMPlexMono-Bold.ttf")
# Libre Franklin (OFL) — Franklin Gothic revival, the grotesque of gallery
# wall text. Variable Weight axis (Thin..Black) plus a separate italic file.
# The wall-text face of ``furies``.
LIBREFRANKLIN_VARIABLE = str(BASE_DIR / "fonts/libre-franklin/LibreFranklin-Variable.ttf")
LIBREFRANKLIN_ITALIC_VARIABLE = str(BASE_DIR / "fonts/libre-franklin/LibreFranklin-Italic-Variable.ttf")
# Titillium Web (OFL) — a cold, legible technical humanist sans (observatory
# printout rather than game HUD). Static Regular / SemiBold / Bold / Italic.
# Used by ``trisolaris``.
TITILLIUM_REGULAR = str(BASE_DIR / "fonts/titillium-web/TitilliumWeb-Regular.ttf")
TITILLIUM_SEMIBOLD = str(BASE_DIR / "fonts/titillium-web/TitilliumWeb-SemiBold.ttf")
TITILLIUM_BOLD = str(BASE_DIR / "fonts/titillium-web/TitilliumWeb-Bold.ttf")
TITILLIUM_ITALIC = str(BASE_DIR / "fonts/titillium-web/TitilliumWeb-Italic.ttf")
# Spectral (Production Type, OFL) — a sharp book serif whose stems hold as
# bone-white on black; Medium body, SemiBold matched phrase, Medium Italic
# byline. The text face of ``biomech``.
SPECTRAL_MEDIUM = str(BASE_DIR / "fonts/spectral/Spectral-Medium.ttf")
SPECTRAL_SEMIBOLD = str(BASE_DIR / "fonts/spectral/Spectral-SemiBold.ttf")
SPECTRAL_MEDIUM_ITALIC = str(BASE_DIR / "fonts/spectral/Spectral-MediumItalic.ttf")
# Grenze Gotisch (OFL) — blackletter/roman hybrid with thorned terminals;
# variable Weight axis, instances pinned. ``biomech``'s plate label and all of
# ``bosch``'s banderole: textura capitals over a roman's open lowercase, so it
# holds as running text at 16 px where UnifrakturMaguntia shreds.
GRENZE_GOTISCH_VARIABLE = str(BASE_DIR / "fonts/grenze-gotisch/GrenzeGotisch-Variable.ttf")
BARLOWCOND_REGULAR = str(BASE_DIR / "fonts/barlow-condensed/BarlowCondensed-Regular.ttf")
BARLOWCOND_MEDIUM = str(BASE_DIR / "fonts/barlow-condensed/BarlowCondensed-Medium.ttf")
BARLOWCOND_SEMIBOLD = str(BASE_DIR / "fonts/barlow-condensed/BarlowCondensed-SemiBold.ttf")
BARLOWCOND_BOLD = str(BASE_DIR / "fonts/barlow-condensed/BarlowCondensed-Bold.ttf")
# Barlow (expanse) — DIN-descended grotesque at text width, the nearest open
# face to the modified DIN Pro of the Rocinante's screens: Regular body,
# SemiBold matched phrase, Bold sender; Barlow Condensed takes the labels.
BARLOW_REGULAR = str(BASE_DIR / "fonts/barlow/Barlow-Regular.ttf")
BARLOW_MEDIUM = str(BASE_DIR / "fonts/barlow/Barlow-Medium.ttf")
BARLOW_SEMIBOLD = str(BASE_DIR / "fonts/barlow/Barlow-SemiBold.ttf")
BARLOW_BOLD = str(BASE_DIR / "fonts/barlow/Barlow-Bold.ttf")
# Michroma (saros status chrome; atropos HUD chrome) — a wide geometric display sans, one static
# weight, the nearest open face to Kellion (Returnal) and Korataki (Saros).
# Exo 2 (saros body fallback) is variable with a Thin default, so every candidate pins an instance.
MICHROMA_REGULAR = str(BASE_DIR / "fonts/michroma/Michroma-Regular.ttf")
EXO2_VARIABLE = str(BASE_DIR / "fonts/exo-2/Exo2[wght].ttf")
EXO2_ITALIC_VARIABLE = str(BASE_DIR / "fonts/exo-2/Exo2-Italic[wght].ttf")
# Saira (atropos + saros body) — squared technical grotesque, the nearest open face to Returnal's
# Erbaum and Saros's Tamba Sans. Variable on weight and width with a Thin default: pin an instance.
SAIRA_VARIABLE = str(BASE_DIR / "fonts/saira/Saira[wdth,wght].ttf")
SAIRA_ITALIC_VARIABLE = str(BASE_DIR / "fonts/saira/Saira-Italic[wdth,wght].ttf")
# Orbitron (saros wordmark) — a squared geometric display sans, the nearest open face to Arame,
# Saros's main display face. Variable on weight, default Regular.
ORBITRON_VARIABLE = str(BASE_DIR / "fonts/orbitron/Orbitron[wght].ttf")
# Jura (OFL) — humanist technical sans with calligraphic stroke endings,
# static Medium / SemiBold / Bold. The Culture pair's body face: futurist but
# urbane rather than martial.
JURA_MEDIUM = str(BASE_DIR / "fonts/jura/Jura-Medium.ttf")
JURA_SEMIBOLD = str(BASE_DIR / "fonts/jura/Jura-SemiBold.ttf")
JURA_BOLD = str(BASE_DIR / "fonts/jura/Jura-Bold.ttf")
# Share Tech Mono (Carrois Type Design, OFL) — a narrow squared technical mono,
# the signal-header and caption face of the Culture pair.
SHARETECHMONO_REGULAR = str(BASE_DIR / "fonts/share-tech-mono/ShareTechMono-Regular.ttf")
# Inter — Rasmus Andersson (OFL). Grotesque UI sans, the open Helvetica
# stand-in, used by ``betweenus`` / ``betweenus_dark`` and ``lumon``. Variable,
# default Regular, but every candidate pins its instance so a bold is
# unambiguous.
INTER_VARIABLE = str(BASE_DIR / "fonts/inter/Inter-Variable.ttf")
# Montserrat (OFL) — the ``lumon`` digits and body: the open face closest to
# the Gotham-like sans of the MDR terminal's number grid (round, even digits
# that sit square in a grid). Variable on weight, default Regular; every
# candidate still pins a name.
MONTSERRAT_VARIABLE = str(BASE_DIR / "fonts/montserrat/Montserrat[wght].ttf")
# Fraunces — Undercase Type (OFL). Variable soft old-style serif, the face of
# the Between Us web app; used by ``betweenus`` / ``betweenus_dark``. Named
# instances sit at opsz 9 (the sturdy text cut). The DEFAULT axis instance is
# Black (wght 900), so every candidate pins an instance by name.
FRAUNCES_VARIABLE = str(BASE_DIR / "fonts/fraunces/Fraunces-Variable.ttf")
FRAUNCES_ITALIC_VARIABLE = str(BASE_DIR / "fonts/fraunces/Fraunces-Italic-Variable.ttf")
# Cormorant Garamond — Christian Thalmann (OFL). High-contrast Garamond
# revival with a poster-register contrast (``nocturne``'s body). Variable,
# named instances Light..Bold (default Regular).
CORMORANT_VARIABLE = str(BASE_DIR / "fonts/cormorant-garamond/CormorantGaramond-Variable.ttf")
# Yuji Boku (OFL). Sumi-brush Japanese face for ``kanagawa``, from the same
# brush-and-ink tradition as its seigaiha pattern. Single weight; matched
# phrase differs by colour. Distinct from chanbara's all-caps Shojumaru.
YUJI_BOKU_REGULAR = str(BASE_DIR / "fonts/yuji-boku/YujiBoku-Regular.ttf")
# Bungee Shade — David Jonathan Ross (OFL). 3D-blocked display face evoking
# 1960s Fillmore poster lettering. Single weight, so ``fillmore``'s matched
# phrase differs by its blue alone. Falls back through Bangers / Atomic Age
# and heavy sans before the Playfair chain.
BUNGEE_SHADE_REGULAR = str(BASE_DIR / "fonts/bungee-shade/BungeeShade-Regular.ttf")
# Cardo — David J. Perry (OFL). Humanist Renaissance serif for classical
# scholarship; ``firmament``'s body face. Regular / Bold / Italic. Falls back
# through EB Garamond → DejaVu Serif → Liberation Serif → Playfair.
CARDO_REGULAR = str(BASE_DIR / "fonts/cardo/Cardo-Regular.ttf")
CARDO_BOLD = str(BASE_DIR / "fonts/cardo/Cardo-Bold.ttf")
CARDO_ITALIC = str(BASE_DIR / "fonts/cardo/Cardo-Italic.ttf")
# Press Start 2P (OFL). Pixel face on a fixed 8×8 grid after the 1980s Namco
# arcade type, no descenders (PIL reports ascent=size, descent=0). The only
# face of ``questline`` — body, matched phrase and chrome alike. Single
# weight; the matched phrase differs by its yellow. Falls back through sans
# faces (no other pixel face is bundled to fall to).
PRESSSTART2P_REGULAR = str(BASE_DIR / "fonts/press-start-2p/PressStart2P-Regular.ttf")
# Pixelify Sans (OFL). A proportional 16-bit pixel sans with descenders and a
# real weight axis; ``chrono``'s step up from questline's 8-bit face. The
# matched phrase pins the Bold instance, so chrono gets weight contrast on
# top of the yellow. Falls back through sans faces before Playfair.
PIXELIFYSANS_VARIABLE = str(BASE_DIR / "fonts/pixelify-sans/PixelifySans-Variable.ttf")
OXANIUM_VARIABLE = str(BASE_DIR / "fonts/oxanium/Oxanium-Variable.ttf")
# Libre Caslon Text (OFL). Screen-legible Caslon revival — the English book
# face of Anna Atkins's era (1843). ``anna_atkins`` body and matched phrase;
# the margin labels stay in Pinyon Script. Variable, Regular / Bold pinned.
# Falls back through serif faces before the Playfair chain.
LIBRECASLON_VARIABLE = str(BASE_DIR / "fonts/libre-caslon-text/LibreCaslonText-Variable.ttf")
# Silkscreen — Jason Kottke (OFL). Crisp fixed-grid pixel face (5 px cap
# height at size 8) whose grid maps one mask pixel to one cross-stitch, the
# ``sampler`` face. Ships static Regular + Bold, so the matched phrase gets a
# true second weight. The frame stitches from these masks directly; the
# THEME_FONTS fallbacks are a safety net only (non-grid glyphs read wrong as
# stitches, so ship the TTFs).
SILKSCREEN_REGULAR = str(BASE_DIR / "fonts/silkscreen/Silkscreen-Regular.ttf")
SILKSCREEN_BOLD = str(BASE_DIR / "fonts/silkscreen/Silkscreen-Bold.ttf")
# Dancing Script (OFL). Fluid pen-script with a weight axis (400..700); the
# ``letter`` body face. Copperplate (Pinyon) hairlines shatter at body sizes
# after ``snap_image_to_palette``, so Dancing Script carries the text and
# Pinyon only the ornament, a legible body beside a period ornament. Its Bold instance
# gives the matched phrase a real weight step. Falls back through slanted
# sans (DejaVu / Liberation Italic) before the Playfair chain.
DANCINGSCRIPT_VARIABLE = str(BASE_DIR / "fonts/dancing-script/DancingScript-Variable.ttf")
# Pinyon Script (OFL). Formal copperplate, single weight; ONLY in ``letter``'s
# ornament slot, where legibility doesn't matter. Kept off the body chains
# on purpose — at 18-24 px the hairlines break up after palette snap. Falls
# back through Dancing Script Bold before the shared ornament chain.
PINYONSCRIPT_REGULAR = str(BASE_DIR / "fonts/pinyon-script/PinyonScript-Regular.ttf")

# Alegreya (OFL) — humanist serif for long-form literary setting with a
# calligraphic italic. `lieder`: roman for the lyrics, bold for the matched
# phrase, italic for tempo / expression / composer chrome — an engraved
# score's roman-vs-italic division.
ALEGREYA_REGULAR = str(BASE_DIR / "fonts/alegreya/Alegreya-Regular.ttf")
ALEGREYA_BOLD = str(BASE_DIR / "fonts/alegreya/Alegreya-Bold.ttf")
ALEGREYA_ITALIC = str(BASE_DIR / "fonts/alegreya/Alegreya-Italic.ttf")
# Noto Music (OFL) — a *symbol* face: Unicode Musical Symbols (U+1D100..) plus
# U+2669.. notes. `lieder` takes its G clef and noteheads from it, since a
# polygon clef spiral turns to mush. Engraved on the metric where a five-line
# staff is one em tall.
NOTOMUSIC_REGULAR = str(BASE_DIR / "fonts/noto-music/NotoMusic-Regular.ttf")

# Quicksand (OFL) — rounded monoline geometric sans, the nearest open type to
# a bent glass tube; `izakaya`'s neon lettering. Deliberately plain: the glow
# is the effect, so the letterform must be a uniform-width tube.
QUICKSAND_REGULAR = str(BASE_DIR / "fonts/quicksand/Quicksand-Regular.ttf")
QUICKSAND_BOLD = str(BASE_DIR / "fonts/quicksand/Quicksand-Bold.ttf")

# Lato (OFL) — humanist sans with open counters, sturdy enough for white text
# on `abyssal`'s dark gradient at panel distance.
LATO_REGULAR = str(BASE_DIR / "fonts/lato/Lato-Regular.ttf")
LATO_BOLD = str(BASE_DIR / "fonts/lato/Lato-Bold.ttf")
LATO_ITALIC = str(BASE_DIR / "fonts/lato/Lato-Italic.ttf")
# Caesar Dressing (hades title card + the author as the boon's name) — Open
# Window's brushed Greek-inscription display face, the one *Hades II* sets
# its title cards and god names in. One static Regular, capitals only.
CAESARDRESSING_REGULAR = str(BASE_DIR / "fonts/caesar-dressing/CaesarDressing-Regular.ttf")
# Spectral SC (hades foot) — the small-caps cut of Production Type's Spectral,
# the serif *Hades II* sets its codex and boon descriptions in.
SPECTRALSC_MEDIUM = str(BASE_DIR / "fonts/spectral-sc/SpectralSC-Medium.ttf")
# Hammersmith One (hades chrome) — Sorkin Type's open Johnston, the nearest
# open face to P22 Underground, the game's main interface face.
HAMMERSMITHONE_REGULAR = str(BASE_DIR / "fonts/hammersmith-one/HammersmithOne-Regular.ttf")
# Libre Baskerville (OFL) — the ``goya`` face, in the register of Madrid's
# Imprenta Real romans of the Black Paintings' decade. Benton's ATF
# Baskerville redrawn for screen: taller x-height, wider counters and less
# contrast, which is what holds on a dithered ochre ground (a Didone's
# hairlines shred in the stipple). Two variable files, default Regular /
# Italic; every candidate still pins one.
LIBREBASKERVILLE_VARIABLE = str(BASE_DIR / "fonts/libre-baskerville/LibreBaskerville-Variable.ttf")
LIBREBASKERVILLE_ITALIC_VARIABLE = str(BASE_DIR / "fonts/libre-baskerville/LibreBaskerville-Italic-Variable.ttf")

# Almendra + Almendra Display (OFL) — a calligraphic book face in the
# fin-de-siècle Decadent register of *The King in Yellow*. The Display cut's
# hollowed strokes carry only the quote marks. `carcosa` only.
ALMENDRA_REGULAR = str(BASE_DIR / "fonts/almendra/Almendra-Regular.ttf")
ALMENDRA_BOLD = str(BASE_DIR / "fonts/almendra/Almendra-Bold.ttf")
ALMENDRA_DISPLAY = str(BASE_DIR / "fonts/almendra/AlmendraDisplay-Regular.ttf")
# Fondamento (OFL) — chancery book hand. The Codex Seraphinianus is
# handwritten, so `codex`'s deciphered passage is set in a pen hand; the
# Italic carries the matched phrase (roman/italic plus colour, as
# `cartograph` — no bold exists). `codex` only.
FONDAMENTO_REGULAR = str(BASE_DIR / "fonts/fondamento/Fondamento-Regular.ttf")
FONDAMENTO_ITALIC = str(BASE_DIR / "fonts/fondamento/Fondamento-Italic.ttf")

# The pen hand ``letter`` and ``escritoire`` share: Dancing Script pinned by
# instance, then slanted sans stand-ins so a host without it still gets a
# hand-ish italic rather than an upright face. One list, so the two themes
# cannot drift apart.
_HAND_SCRIPT_REGULAR = [
    (DANCINGSCRIPT_VARIABLE, "Regular"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Italic.ttf",
    *QUOTE_FONT_SEMIBOLD_CANDIDATES,
]
_HAND_SCRIPT_BOLD = [
    (DANCINGSCRIPT_VARIABLE, "Bold"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-BoldItalic.ttf",
    *QUOTE_FONT_BOLD_CANDIDATES,
]
