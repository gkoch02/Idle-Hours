"""Font loading and caching, and the per-theme glyph fallbacks for characters a face lacks.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import ImageFont

from .theme_tables import THEME_FONTS

_FONT_FALLBACK_WARNED = False


def theme_font_candidates(theme: str, role: str) -> list:
    """Return the candidate chain for ``role`` under ``theme``.

    Unknown themes fall back to the ``default`` entry so a forgotten
    ``THEME_FONTS`` registration still renders rather than raising.

    ``card_<base>`` roles (e.g. ``card_quote_bold``, used by
    ``render_source_card``) fall back: theme's ``card_<base>`` → theme's
    ``<base>`` → default's ``<base>``. The seam is for a theme whose
    ``quote_bold`` starts with a display face lacking characters the card
    emits (U+2014 from ``normalize_dashes``, U+201C / U+201D around the
    phrase): PIL's font fallback is file-level, not glyph-level, so such a
    face draws ``.notdef`` boxes. No theme overrides it today; the layering
    stays because the next ASCII-only display face will need it.
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


_FONT_CACHE: dict[tuple, ImageFont.ImageFont] = {}


def _normalize_candidates(candidates) -> tuple:
    """Normalize the load_font candidates list into a hashable cache key.

    Plain string entries become ``(path, None)``; tuple entries pass through.
    """
    return tuple((c, None) if not isinstance(c, tuple) else tuple(c) for c in candidates)


def load_font(candidates: list, size: int):
    """Load the first reachable TrueType font in ``candidates``, memoized.

    Each entry is a path string or a ``(path, variation_name)`` tuple; for
    the tuple form ``set_variation_by_name`` selects the named instance. This
    is load-bearing for variable fonts whose default instance is Thin (e.g.
    Bitter). A variation name the file doesn't expose silently falls back to
    the default instance; the next candidate is tried only if the file is
    missing or unreadable.

    Cached per process on ``(normalised_candidates, size)`` — ``fit_quote``
    calls this many times per render with the same chain at different sizes.

    Contract: callers must NOT mutate the returned font (e.g. call
    ``set_variation_by_name`` on it). Variation pinning lives in the
    candidate tuple so it is part of the cache key; a mutation would corrupt
    other cache consumers.
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
    # Deliberately NOT caching the bitmap fallback: a transient miss would
    # pin the process to degraded rendering for its lifetime (contact_sheet
    # renders 144 frames in one process). Re-scanning is cheap; the
    # warn-once comes from _FONT_FALLBACK_WARNED, not from caching.
    return ImageFont.load_default()


def normalize_dashes(text: str) -> str:
    if not text or "--" not in text:
        return text or ""
    return re.sub(r"(?<!-)--(?!-)", "\u2014", text)


# ---------------------------------------------------------------------------
# Missing-glyph fallback
# ---------------------------------------------------------------------------
#
# PIL's font fallback is file-level, not glyph-level: a face with no glyph for
# a character draws its ``.notdef`` box (tofu). Several bundled display faces
# lack common marks (Iceland has no ``…``; ~20 faces have no ``′``), so
# ``render`` rewrites such characters to ASCII stand-ins — *only* those the
# theme's body / matched-phrase faces actually lack, so a theme whose fonts
# carry the glyph stays byte-identical.

# A codepoint no font maps: the last Unicode noncharacter. Rendering it yields
# the face's ``.notdef`` glyph, whatever that looks like (a box, a hollow
# rectangle, or nothing at all).
_NOTDEF_PROBE = "\U0010FFFF"

# Characters with an ASCII fallback, checked only when they occur in the text.
# The em-dash is special-cased in ``_apply_glyph_fallbacks`` (spacing-aware);
# its entry here is the bare fallback used at a text edge.
GLYPH_FALLBACKS: dict[str, str] = {
    "\u2026": "...",  # … horizontal ellipsis
    "\u2032": "'",  # ′ prime
    "\u2033": "''",  # ″ double prime
    "\u2019": "'",  # ’ right single quote / apostrophe
    "\u2018": "'",  # ‘ left single quote
    "\u201c": '"',  # “ left double quote
    "\u201d": '"',  # ” right double quote
    "\u2014": "-",  # — em dash (see _EM_DASH_BETWEEN_RE)
    "\u2013": "-",  # – en dash
}

# An em dash between two non-space characters becomes a spaced hyphen: an
# unspaced ``word-word`` would read as a hyphenated compound, and ``--`` cannot
# be used because ``normalize_dashes`` turns it straight back into an em dash.
_EM_DASH_BETWEEN_RE = re.compile(r"(?<=\S)\s*\u2014\s*(?=\S)")

# (font identity, char) -> True when the face has a real glyph. The cmap does
# not change with size or variation instance, so the key is the font file.
_GLYPH_PRESENT_CACHE: dict[tuple, bool] = {}


def _glyph_signature(font, ch: str) -> tuple:
    mask = font.getmask(ch)
    return (mask.size, bytes(mask), font.getbbox(ch))


def font_has_glyph(font, ch: str) -> bool:
    """Return True when ``font`` has a real glyph for ``ch`` (not ``.notdef``).

    Compares the rendered mask and bbox of ``ch`` against those of a codepoint
    no font maps, which PIL draws as the face's ``.notdef``. Works whether
    ``.notdef`` is a box or blank (a blank ``.notdef`` differs from any visible
    glyph). A real glyph drawn identically to ``.notdef`` would be misread as
    missing; none of the characters in ``GLYPH_FALLBACKS`` look like that.
    Memoised per (font file, char), so the cost is paid once per process.
    """
    ident = getattr(font, "path", None)
    key = ((ident, getattr(font, "index", 0)) if ident else ("id", id(font)), ch)
    cached = _GLYPH_PRESENT_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        present = _glyph_signature(font, ch) != _glyph_signature(font, _NOTDEF_PROBE)
    except (AttributeError, OSError, TypeError, ValueError):
        present = True  # can't tell: leave the text alone
    if ident:  # never cache on id() — a freed font's id can be reused
        _GLYPH_PRESENT_CACHE[key] = present
    return present


_GLYPH_FALLBACK_ROLES = ("quote_regular", "quote_bold")
_GLYPH_FALLBACK_FIELDS = ("display_quote", "matched_text", "author", "title")


def _missing_fallback_chars(theme: str, texts) -> set[str]:
    """Characters in ``texts`` with a fallback that a ``theme`` text face lacks."""
    wanted = {ch for text in texts for ch in GLYPH_FALLBACKS if ch in text}
    if any("--" in text for text in texts):
        wanted.add("\u2014")  # normalize_dashes will produce one
    if not wanted:
        return set()
    fonts = [load_font(theme_font_candidates(theme, role), size=32) for role in _GLYPH_FALLBACK_ROLES]
    return {ch for ch in wanted if not all(font_has_glyph(f, ch) for f in fonts)}


def _apply_glyph_fallbacks(text: str, missing: set[str]) -> str:
    if not text or not missing:
        return text
    if "\u2014" in missing:
        text = normalize_dashes(text)
        text = _EM_DASH_BETWEEN_RE.sub(" - ", text)
    for ch in missing:
        text = text.replace(ch, GLYPH_FALLBACKS[ch])
    return text


def apply_theme_glyph_fallbacks(quote_row: dict, theme: str) -> dict:
    """Return ``quote_row`` with characters ``theme``'s fonts lack made ASCII.

    Applied to ``display_quote`` / ``matched_text`` / ``author`` / ``title``
    with the *same* substitution set, so ``resolve_display_match`` still finds
    the matched phrase inside the rewritten quote. Returns the row itself,
    unchanged, when nothing needs substituting — the common case, and the one
    that keeps every theme whose faces carry the glyphs byte-identical.
    """
    texts = [v for v in (quote_row.get(k) for k in _GLYPH_FALLBACK_FIELDS) if isinstance(v, str) and v]
    missing = _missing_fallback_chars(theme, texts)
    if not missing:
        return quote_row
    row = dict(quote_row)
    for key in _GLYPH_FALLBACK_FIELDS:
        value = row.get(key)
        if isinstance(value, str) and value:
            row[key] = _apply_glyph_fallbacks(value, missing)
    return row


def _font_ascent(font) -> int:
    """Return the font's ascent in pixels, or 0 when unavailable.

    Used for per-chunk baseline alignment in the body draw loop: PIL's
    default anchor is ``"la"`` (ascender top), so mixing faces with different
    ascents on one line (gothic: EB Garamond + UnifrakturMaguntia) would
    float the bold phrase by ``body_ascent − bold_ascent`` pixels. The bitmap
    fallback doesn't expose ``getmetrics`` reliably; returning 0 gives every
    chunk the same offset instead of crashing.
    """
    try:
        return font.getmetrics()[0]
    except (AttributeError, OSError):
        return 0
