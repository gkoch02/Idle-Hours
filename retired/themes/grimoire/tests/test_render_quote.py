"""Tests of the retired ``grimoire`` theme, moved verbatim from ``tests/test_render_quote.py``.

Not collected (pytest only collects ``tests/``); restore them with the theme.
"""
# Original module header, kept so the tests read as they did:
"""Tests for render_quote.py — layout selection, text helpers, color quantization."""
from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")

from idle_hours import render_quote as rq  # noqa: E402
from idle_hours.render_quote import core as rq_core  # noqa: E402
from idle_hours.render_quote import fonts as rq_fonts  # noqa: E402
from idle_hours.render_quote import palette as rq_palette  # noqa: E402
from idle_hours.render_quote import text as rq_text  # noqa: E402

from .pixel_helpers import distinct_inks, ink_counts  # noqa: E402


@pytest.fixture(autouse=True)


class TestGrimoireBorder:
    """The grimoire theme paints an alchemical spellbook border.

    Thin red outer rule, four corner *inscribed pentagrams* (five-pointed
    star + surrounding ring — the magic-circle composition), and four
    classical planetary sigils on the mid-edges (Sun ☉ top, Moon ☽
    bottom, Mars ♂ left, Venus ♀ right). Shares the black/white/red
    palette with ``gothic`` but is iconographically unrelated: gothic
    stacks a doubled rule with quatrefoils + mid-edge diamonds (cathedral
    tracery), grimoire is single-rule with pentagrams-in-circles +
    planetary alchemical sigils (occult diagram). Pin the painted
    pixels for each element here — the golden-image suite only covers
    default / dark / scholar so these are the regression seam for
    the grimoire decoration.
    """

    def _row(self):
        return {
            "display_quote": "It was three o'clock in the afternoon.",
            "matched_text": "three o'clock",
            "author": "Jane Austen",
            "title": "Mansfield Park",
            "bucket": "h3_exact",
            "resolved_bucket": "h3_exact",
            "used_fallback": False,
            "quality_score": 80,
            "source_id": "141",
        }

    def test_grimoire_outer_rule_paints_red_on_all_four_sides(self):
        """Single rectangle at outer_inset=14 — sample mid-side on each
        edge well clear of the corner pentagrams *and* of the mid-edge
        sigils (which sit centred on the frame at the midpoint of each
        side). x=200 / y=200 are off both."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="grimoire")
        red = rq.SPECTRA6["red"]
        assert img.getpixel((200, 14)) == red, "top outer rule missing"
        assert img.getpixel((200, 465)) == red, "bottom outer rule missing"
        assert img.getpixel((14, 200)) == red, "left outer rule missing"
        assert img.getpixel((785, 200)) == red, "right outer rule missing"

    def test_grimoire_corner_pentagrams_paint_red_top_vertex(self):
        """Each pentagram's top vertex (i=0, angle=-π/2) sits at
        ``(cx, cy - pent_radius)``. With centres at (30, 30) / (769, 30)
        / (30, 449) / (769, 449) (after the corner-offset bump to make
        room for the inscribing ring) and pent_radius=11, the top
        vertices land at the y-values below. A 2px stroke guarantees
        the exact endpoint pixel is painted."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="grimoire")
        red = rq.SPECTRA6["red"]
        assert img.getpixel((30, 19)) == red, "TL pentagram top vertex missing"
        assert img.getpixel((769, 19)) == red, "TR pentagram top vertex missing"
        assert img.getpixel((30, 438)) == red, "BL pentagram top vertex missing"
        assert img.getpixel((769, 438)) == red, "BR pentagram top vertex missing"

    def test_grimoire_pentagrams_inscribed_in_rings(self):
        """Each pentagram is wrapped in a 14-px-radius ring (the magic-
        circle composition). Sample the top of each ring at
        ``(cx, cy - ring_radius)`` — a position that's on the ring's
        outline but outside the pentagram's vertices (pent_radius=11),
        so a ring-missing regression would leave page_bg here even
        though the star tests still pass."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="grimoire")
        red = rq.SPECTRA6["red"]
        # Ring tops at (cx, cy - 14) for the four pentagram centres.
        assert img.getpixel((30, 16)) == red, "TL ring top missing"
        assert img.getpixel((769, 16)) == red, "TR ring top missing"
        assert img.getpixel((30, 435)) == red, "BL ring top missing"
        assert img.getpixel((769, 435)) == red, "BR ring top missing"

    def test_grimoire_sun_sigil_paints_at_top_midpoint(self):
        """☉ — outline circle + filled centre dot at (400, 14). The
        Sun's R+Y 5/8:3/8 tangerine post-pass flips Bayer-cell pixels
        below threshold 6 to yellow; `BAYER_4x4[14%4][400%4] = 3 < 6`,
        so the centre pixel lands in the flipped half — yellow rather
        than the pre-Stage-2 solid red. The sigil's centre dot is still
        painted (just in the recipe's lighter ink at this parity), so
        a regression that dropped the sigil entirely would still fail
        here."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="grimoire")
        assert img.getpixel((400, 14)) == rq.SPECTRA6["yellow"], "Sun centre dot missing"

    def test_grimoire_moon_sigil_paints_at_bottom_midpoint(self):
        """☽ — crescent carved from a filled disk by overdrawing with
        a page-bg disk shifted +4 px in x. The Moon now paints its
        outer disk in BLUE as a sentinel for the B+W 1:1 sky recipe:
        the post-pass flips half of the blue pixels to white per
        `(x+y)&1` parity. Sample (394, 465) — well inside the visible
        crescent for r=7 / bcx=400 — has `(394+465)&1 = 1`, the
        unflipped half, so it stays solid blue (the disc colour) and
        a regression that dropped the sigil entirely would still
        fail here."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="grimoire")
        assert img.getpixel((394, 465)) == rq.SPECTRA6["blue"], "Moon crescent missing"

    def test_grimoire_mars_sigil_paints_at_left_midpoint(self):
        """♂ — circle offset down-left + diagonal NE shaft + perpendicular
        V-barb. Mars's R+K 1:1 maroon post-pass flips half of the red
        pixels to black per `(x+y)&1` parity. Sample the arrow tip at
        (22, 232): `(22+232)&1 = 0`, the flipped half, so it lands as
        black rather than the pre-Stage-2 solid red. A regression that
        dropped the arrow would still fail (the bbox post-pass only
        flips pixels that were originally painted red — an unpainted
        page_bg pixel would stay as page_bg)."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="grimoire")
        assert img.getpixel((22, 232)) == rq.SPECTRA6["black"], "Mars arrow tip missing"

    def test_grimoire_venus_sigil_paints_at_right_midpoint(self):
        """♀ — circle offset up + descending shaft + horizontal crossbar.
        Sample the crossbar at (785, 246) — well below the circle body
        so a regression that dropped the cross would surface here."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="grimoire")
        assert img.getpixel((785, 246)) == rq.SPECTRA6["red"], "Venus crossbar missing"

    def test_grimoire_painter_is_registered(self):
        """A bad ``_BORDER_PAINTERS["grimoire"] = draw_atomic_border``
        typo would silently render grimoire with atomic's atom symbol
        rather than the pentagram. Pin the dispatch entry."""
        assert rq._BORDER_PAINTERS.get("grimoire") is rq.draw_grimoire_border, (
            "grimoire painter not registered in _BORDER_PAINTERS"
        )

    def test_grimoire_renders_differently_from_gothic_same_palette(self):
        """``grimoire`` and ``gothic`` share the black/white/red palette
        but must NOT produce identical frames — the silhouette difference
        comes from the matched-phrase font (Eagle Lake vs UnifrakturMaguntia)
        and the corner decoration (inscribed pentagram vs quatrefoil).
        A regression that pointed grimoire's painter at
        ``draw_gothic_border`` (or copied gothic's THEME_FONTS chain)
        would surface here as an identical-image hash."""
        row = self._row()
        gothic = rq.render("03:00", row, 800, 480, mode="production", theme="gothic")
        grimoire = rq.render("03:00", row, 800, 480, mode="production", theme="grimoire")
        diffs = sum(
            1
            for y in range(5, 45)
            for x in range(5, 45)
            if gothic.getpixel((x, y)) != grimoire.getpixel((x, y))
        )
        assert diffs > 20, (
            f"grimoire and gothic produce near-identical TL corners ({diffs} px differ)"
        )

    def test_grimoire_border_appears_in_debug_and_card_modes_too(self):
        """The decoration is part of the theme's identity and must paint
        in every render mode. Sample the TL ring top against the panel's
        black ground in each mode."""
        red = rq.SPECTRA6["red"]
        for mode in ("production", "debug", "card"):
            img = rq.render("03:00", self._row(), 800, 480, mode=mode, theme="grimoire")
            assert img.getpixel((30, 16)) == red, (
                f"grimoire mode={mode} missing TL inscribing ring"
            )

    def test_grimoire_border_uses_theme_colours_not_hardcoded_rgb(self):
        """``draw_grimoire_border`` must source its colour from
        ``colors['accent']``, not a baked-in red. Call the helper with
        a non-default palette and assert the painted pixels reflect it."""
        image = Image.new("RGB", (800, 480), color=(0, 0, 0))
        custom = {
            "page_bg": rq.SPECTRA6["black"],
            "text": rq.SPECTRA6["white"],
            "accent": rq.SPECTRA6["green"],
        }
        rq.draw_grimoire_border(image, custom)
        assert image.getpixel((200, 14)) == rq.SPECTRA6["green"], "outer rule should use accent"
        assert image.getpixel((30, 19)) == rq.SPECTRA6["green"], "TL pentagram should use accent"
        assert image.getpixel((30, 16)) == rq.SPECTRA6["green"], "TL ring should use accent"
        assert image.getpixel((400, 14)) == rq.SPECTRA6["green"], "Sun sigil should use accent"

    def test_grimoire_moon_carves_with_page_bg_not_hardcoded(self):
        """The crescent is carved from a filled red disk by overdrawing
        with a smaller disk in ``colors['page_bg']``. Switching the
        ground colour must show through the carved region — a
        regression that hardcoded ``black`` would still display a
        crescent against a white ground because the overlay would
        clash. Bug-defensive pin."""
        image = Image.new("RGB", (800, 480), color=(255, 255, 255))
        custom = {
            "page_bg": rq.SPECTRA6["white"],
            "text": rq.SPECTRA6["black"],
            "accent": rq.SPECTRA6["red"],
        }
        rq.draw_grimoire_border(image, custom)
        # Inside the carved area (centre + 4 right of the moon midpoint
        # at (400, 465), so around (403, 465)) should be page_bg=white,
        # not red or black.
        assert image.getpixel((403, 465)) == rq.SPECTRA6["white"], (
            "moon overlay didn't carve with page_bg"
        )

    @staticmethod
    def _covers(font_path: str, char: str) -> bool:
        """True when *font_path* has a real glyph for *char*.

        PIL exposes no glyph-index lookup, so this renders *char* and
        compares against a codepoint no font assigns (U+FFFF). A missing
        glyph draws ``.notdef``, so it comes back byte-identical; a real
        glyph does not. Dependency-free on purpose — the suite should not
        grow fontTools to assert a coverage invariant.
        """
        absent = "\uffff"

        def bitmap(text: str) -> bytes:
            font = ImageFont.truetype(font_path, 48)
            image = Image.new("L", (90, 90), 0)
            ImageDraw.Draw(image).text((10, 10), text, font=font, fill=255)
            return image.tobytes()

        return bitmap(char) != bitmap(absent)

    def test_grimoire_source_card_font_covers_the_characters_the_card_emits(self):
        """The card's face must carry the punctuation the card prints.

        ``render_source_card`` wraps the matched phrase in U+201C / U+201D
        curly quotes and runs the title through ``normalize_dashes`` (which
        emits U+2014). PIL's font fallback is file-level rather than
        glyph-level, so a face missing any of them paints ``.notdef`` boxes
        for every one — which is what TFoust did (95 glyphs, ASCII only) and
        why grimoire once carried a ``card_quote_bold`` override.

        Eagle Lake covers all three, so the override is gone. This asserts
        the *reason* it could go rather than the absence of a filename: a
        name check would pass against any face at all now that TFoust is
        not in the tree, including a future ASCII-only replacement.
        """
        chain = rq.theme_font_candidates("grimoire", "card_quote_bold")
        first = chain[0]
        first_path = first[0] if isinstance(first, tuple) else first
        assert Path(first_path).is_file(), f"card chain leads with a missing file: {first_path}"

        for char, name in (
            ("\u201c", "U+201C left curly quote"),
            ("\u201d", "U+201D right curly quote"),
            ("\u2014", "U+2014 em-dash"),
        ):
            assert self._covers(first_path, char), (
                f"{Path(first_path).name} has no glyph for {name}; the grimoire "
                f"source card would paint .notdef boxes. Either pick a face that "
                f"covers it or restore a card_quote_bold override for grimoire."
            )

        # Negative control: the probe must be able to report absence, or the
        # three assertions above would pass against any font whatsoever.
        assert not self._covers(first_path, "\u3042"), "glyph-coverage probe reports every codepoint as present"

    def test_no_theme_overrides_card_quote_bold(self):
        """``card_quote_bold`` is a per-theme escape hatch nobody needs today.

        It existed for grimoire alone, to keep TFoust off the source card;
        that face is gone and its replacement is unicode-safe, so every
        theme now falls through to ``quote_bold``. The seam stays because
        the hazard is a property of PIL rather than of that one font — but
        docs/themes.md states no theme uses it, so this fails the moment that
        stops being true and the doc needs updating with it.
        """
        for theme in sorted(rq.THEMES):
            bold = rq.theme_font_candidates(theme, "quote_bold")
            card = rq.theme_font_candidates(theme, "card_quote_bold")
            assert card == bold, (
                f"theme {theme} overrides card_quote_bold. That is a supported "
                f"escape hatch, but docs/themes.md says no theme uses it — update the "
                f"'no theme uses it today' note in the fonts section alongside it."
            )

    def test_card_role_fallback_chain_handles_unknown_themes(self):
        """``theme_font_candidates`` resolves a ``card_<base>`` role
        through three layers: theme's override, theme's base role, then
        default's base role. A typoed theme name should still produce
        the default's ``quote_bold`` chain rather than raising
        ``KeyError`` mid-render."""
        chain = rq.theme_font_candidates("nonexistent_theme", "card_quote_bold")
        assert chain == rq.THEME_FONTS["default"]["quote_bold"], (
            "unknown theme's card_quote_bold didn't fall through to default's quote_bold"
        )

    def test_grimoire_in_rigid_match_spacing_set(self):
        """``_THEMES_RIGID_MATCH_SPACING`` controls whether a line's
        bold-internal inter-word gaps absorb justification slack.
        Grimoire must be in this set; pin it explicitly so a future
        rename or reshuffle doesn't silently drop the rigid contract
        and reintroduce the "quarter past two" stretched-across-the-
        line readability bug."""
        assert "grimoire" in rq._THEMES_RIGID_MATCH_SPACING

    def test_rigid_match_spacing_keeps_bold_internal_spaces_at_zero(self):
        """The helper splits slack across only the elastic (non-bold)
        spaces when ``rigid_match`` is True. Two bold-internal spaces
        out of five must contribute zero; the remaining three split
        20 px of slack into 7 / 7 / 6 (base=6, remainder=2 distributed
        to the first two elastic positions)."""
        space_is_bold = [False, True, True, False, False]
        distribute = rq._justify_distribution(space_is_bold, slack=20, rigid_match=True)
        assert distribute == [7, 0, 0, 7, 6], distribute

    def test_loose_match_spacing_distributes_evenly(self):
        """Default contract (``rigid_match=False``) treats every space
        equally — slack=20 across 5 spaces is 4 each."""
        space_is_bold = [False, True, True, False, False]
        distribute = rq._justify_distribution(space_is_bold, slack=20, rigid_match=False)
        assert distribute == [4, 4, 4, 4, 4], distribute

    def test_rigid_match_falls_through_to_ragged_when_all_spaces_bold(self):
        """If every inter-word space on a line happens to sit inside
        the matched phrase (a long matched phrase wrapping onto its
        own line), there's nothing elastic left to absorb slack. The
        helper returns an empty list so the call site short-circuits
        to ragged-right rather than awkwardly stretching the bold
        face's gaps."""
        space_is_bold = [True, True, True]
        distribute = rq._justify_distribution(space_is_bold, slack=30, rigid_match=True)
        assert distribute == [], distribute

    def test_loose_match_falls_through_to_ragged_when_no_spaces(self):
        """Empty space list (no inter-word gaps on the line) → empty
        distribution either way; the call site uses
        ``space_is_bold and …`` to guard."""
        assert rq._justify_distribution([], slack=15, rigid_match=False) == []
        assert rq._justify_distribution([], slack=15, rigid_match=True) == []

    def test_grimoire_render_packs_matched_phrase_tighter_than_loose_baseline(self, monkeypatch):
        """End-to-end pin of the bold-internal-spacing contract.
        The test was originally driven through ``grimoire`` because the
        old candlelit-rubric matched phrase was the most red-dominant
        of the rigid-spacing themes; now that grimoire's matched
        phrase paints solid white (per the readability fix in
        ``_draw_text_body``), the matched-phrase line is no longer
        chromatically distinguishable from the body in grimoire, so we
        drive the test through its sister blackletter theme ``gothic``
        instead. ``gothic`` is also a member of
        ``_THEMES_RIGID_MATCH_SPACING`` and still paints its matched
        phrase as a candlelit-rubric red dither, so the red-pixel
        sweep below still identifies the matched-phrase line. The
        invariant under test (rigid bold-internal spacing packs the
        bold accent run tighter than loose justification) is
        theme-agnostic; this test happens to live in TestGrimoireBorder
        for adjacency reasons rather than because it's grimoire-only."""
        # Sized so the block justifies under ``justify_flags``: every
        # non-last line carries well over three gaps and stretches each
        # by far less than 0.45 em, and the phrase sits on the first,
        # justified line.
        row = {
            "display_quote": (
                "At a quarter past two the wind fell away to nothing, "
                "and such a stillness lay on the sea and on the men at "
                "the rail that no one of us spoke a word for an hour."
            ),
            "matched_text": "quarter past two",
            "title": "T",
            "author": "A",
            "source_id": "1",
            "bucket": "h2_quarter_past",
            "resolved_bucket": "h2_quarter_past",
            "quality_score": 80,
            "used_fallback": False,
        }
        rigid = rq.render("02:15", row, 800, 480, mode="production", theme="gothic")

        monkeypatch.setattr(rq_core, "_THEMES_RIGID_MATCH_SPACING", frozenset())
        loose = rq.render("02:15", row, 800, 480, mode="production", theme="gothic")

        red = rq.SPECTRA6["red"]

        def matched_phrase_span(img) -> tuple[int, int]:
            """Return (leftmost, rightmost) x-coordinate of the red
            band that holds the matched phrase. We skip the canvas
            border (gothic's outer red rectangle at y=14 and quatrefoil
            lobes at the corners) by sampling only the dense quote-body
            region (y in [80, 380]) and picking the row with the most
            red pixels — the matched-phrase line."""
            best_row = (0, 0, 0)  # (count, left, right)
            for y in range(80, 380):
                red_xs = [x for x in range(rq.SIDE_MARGIN, 800 - rq.SIDE_MARGIN) if img.getpixel((x, y)) == red]
                if len(red_xs) > best_row[0]:
                    best_row = (len(red_xs), red_xs[0], red_xs[-1])
            return best_row[1], best_row[2]

        rigid_l, rigid_r = matched_phrase_span(rigid)
        loose_l, loose_r = matched_phrase_span(loose)
        rigid_span = rigid_r - rigid_l
        loose_span = loose_r - loose_l
        # Rigid run must occupy strictly fewer x-pixels than the loose
        # baseline on this particular row (the matched-phrase line is
        # justified by construction — the test quote was sized so the
        # phrase lands on a non-last 75%+-full line). At least 4 px
        # narrower for the typical two-bold-spaces / ~30 px-of-slack
        # case; 1 px is too tight (PIL line-break math at the wrap
        # boundary can shift by ±1 due to the elastic-only base+1
        # distribution).
        assert rigid_span + 4 <= loose_span, (
            f"rigid bold-phrase span {rigid_span}px did not pack tighter than "
            f"loose baseline {loose_span}px — bold-internal spaces are still elastic"
        )

    def test_grimoire_debug_label_clears_top_right_pentagram(self):
        """The ``DEBUG MODE`` banner must not overlap the TR inscribed
        pentagram. The ring's leftmost pixel sits at
        ``cx - ring_radius - 1`` (centre 769, radius 14, plus the 2-px
        stroke half-width) = x=754; the label's right edge must end at
        x ≤ 750 for a 4-px breathing gap. ``inset = width - 750 = 50``.
        Pin the lower bound — a regression that left grimoire on the
        old 44-px inset (sized for bare pentagrams without the ring)
        would silently clip the label across the ring outline."""
        inset = rq._DEBUG_LABEL_RIGHT_INSET.get("grimoire")
        assert inset is not None, "grimoire missing from _DEBUG_LABEL_RIGHT_INSET"
        assert inset >= 46, (
            f"grimoire inset {inset} too small to clear the inscribing ring"
        )


def test_grimoire_border_paints_tria_prima_triads():
    """The upleveled grimoire border adds tria-prima triad dots flanking the
    Sun (top) and Moon (bottom) sigils, in the previously-empty interior
    bands."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_grimoire_border(img, rq.THEMES["grimoire"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    top_l = sum(1 for x in range(330, 352) for y in range(18, 40) if px[x, y] == red)
    bot_l = sum(1 for x in range(330, 352) for y in range(440, 462) if px[x, y] == red)
    assert top_l > 20, "top tria-prima triad missing"
    assert bot_l > 20, "bottom tria-prima triad missing"
