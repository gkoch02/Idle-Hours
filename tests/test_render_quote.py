"""Tests for render_quote.py — layout selection, text helpers, color quantization."""
from __future__ import annotations

from pathlib import Path

import pytest

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")

import render_quote as rq  # noqa: E402

# ---------------------------------------------------------------------------
# choose_layout
# ---------------------------------------------------------------------------

class TestChooseLayout:
    def test_short_text_is_hero(self):
        assert rq.choose_layout("Short quote.") == "hero"

    def test_exactly_90_chars_is_hero(self):
        assert rq.choose_layout("A" * 90) == "hero"

    def test_91_chars_is_standard(self):
        assert rq.choose_layout("A" * 91) == "standard"

    def test_exactly_170_chars_is_standard(self):
        assert rq.choose_layout("A" * 170) == "standard"

    def test_171_chars_is_dense(self):
        assert rq.choose_layout("A" * 171) == "dense"

    def test_empty_string_is_hero(self):
        assert rq.choose_layout("") == "hero"

    def test_none_handled(self):
        assert rq.choose_layout(None) == "hero"


# ---------------------------------------------------------------------------
# strip_underscore_emphasis
# ---------------------------------------------------------------------------

class TestStripUnderscoreEmphasis:
    def test_removes_single_word_emphasis(self):
        assert rq.strip_underscore_emphasis("my _Daily_ chronicle") == "my Daily chronicle"

    def test_removes_multi_word_emphasis(self):
        assert rq.strip_underscore_emphasis("my _Daily Chronicle_.") == "my Daily Chronicle."

    def test_passes_through_plain_text(self):
        assert rq.strip_underscore_emphasis("no markers here") == "no markers here"

    def test_handles_empty_and_none(self):
        assert rq.strip_underscore_emphasis("") == ""
        assert rq.strip_underscore_emphasis(None) == ""

    def test_preserves_intra_word_underscores(self):
        assert rq.strip_underscore_emphasis("var_name stays") == "var_name stays"


# ---------------------------------------------------------------------------
# normalize_dashes
# ---------------------------------------------------------------------------

class TestNormalizeDashes:
    def test_converts_double_dash_to_em_dash(self):
        assert rq.normalize_dashes("a shadowy furtiveness--and recognized") == "a shadowy furtiveness\u2014and recognized"

    def test_leaves_single_dash_alone(self):
        assert rq.normalize_dashes("well-known fact") == "well-known fact"

    def test_leaves_triple_dash_alone(self):
        assert rq.normalize_dashes("mystery of the---") == "mystery of the---"

    def test_passes_through_when_no_dashes(self):
        assert rq.normalize_dashes("plain text") == "plain text"

    def test_handles_empty_and_none(self):
        assert rq.normalize_dashes("") == ""
        assert rq.normalize_dashes(None) == ""


# ---------------------------------------------------------------------------
# resolve_display_match
# ---------------------------------------------------------------------------

class TestResolveDisplayMatch:
    def test_returns_original_when_no_expansion_found(self):
        text = "It was three o'clock in the hall."
        result = rq.resolve_display_match(text, "three o'clock")
        assert result == "three o'clock"

    def test_returns_direct_match_for_short_seed_when_present(self):
        text = "It was five minutes past three when she arrived."
        result = rq.resolve_display_match(text, "five")
        assert result.lower() == "five"

    def test_returns_direct_match_for_quarter_when_present(self):
        text = "Quarter past six the bell rang loudly."
        result = rq.resolve_display_match(text, "quarter")
        assert result.lower() == "quarter"

    def test_returns_direct_match_for_half_when_present(self):
        text = "Half past nine the carriage departed."
        result = rq.resolve_display_match(text, "half")
        assert result.lower() == "half"

    def test_returns_direct_match_when_full_seed_already_present(self):
        text = "It was ten minutes past five o'clock in the evening."
        result = rq.resolve_display_match(text, "ten minutes past")
        assert result.lower() == "ten minutes past"

    def test_does_not_switch_to_unrelated_longer_time_phrase(self):
        text = "It was a quarter past six when we left Baker Street, and it still wanted ten minutes to the hour when we found ourselves in Serpentine Avenue."
        result = rq.resolve_display_match(text, "quarter past six")
        assert result.lower() == "quarter past six"

    def test_empty_match_text(self):
        result = rq.resolve_display_match("Some text.", "")
        assert result == ""

    def test_match_text_with_newline_normalizes_for_lookup(self):
        text = "Do you think I should be standing here at five minutes to nine looking for it?"
        result = rq.resolve_display_match(text, "five\nminutes to nine")
        assert result.lower() == "five minutes to nine"

    def test_display_text_with_underscore_emphasis_still_matches_time_phrase(self):
        text = "I heard of it first about a quarter to nine when I went out to get my _Daily Chronicle_."
        result = rq.resolve_display_match(text, "quarter to nine")
        assert result.lower() == "quarter to nine"

    def test_em_dash_double_hyphen_is_valid_boundary(self):
        text = "Eleven--twelve--one o'clock had struck."
        result = rq.resolve_display_match(text, "one o'clock")
        assert result.lower() == "one o'clock"

    def test_compound_word_hyphen_still_blocks_substring_match(self):
        text = "Towards night-time the lady roused."
        # "night" on its own must not be picked up inside "night-time"
        assert rq.resolve_display_match(text, "Towards night") == "Towards night"
        tokens = rq.tokenize_quote(text, "Towards night")
        assert tokens == [(text, False)]

    def test_prefix_walk_extends_match_across_hyphen(self):
        """Path 2: direct regex fails (trailing hyphen blocks the isolation
        lookahead) but the prefix walk finds the fuller hyphenated form and
        returns it because it startswith the requested match."""
        text = "The clock read five minutes past three-fifteen that night."
        # Direct path fails: "three" is followed by "-fifteen" which trips the
        # (?!-[A-Za-z0-9]) lookahead. Prefix walk for "five minutes past" picks
        # up "five minutes past three-fifteen" and the startswith check accepts it.
        result = rq.resolve_display_match(text, "five minutes past three")
        assert result == "five minutes past three-fifteen"

    def test_fall_through_returns_normalized_match_when_nothing_found(self):
        """Path 3: match_text not in text and no prefix walk candidate starts
        with it — return the normalized match as-is so the caller has *some*
        phrase to bold, even if it never appears in the rendered quote."""
        text = "It was five minutes past three when the bell rang."
        # Prefix walk finds "five minutes past three" but that does not
        # startswith "five minutes past noon", so Path 2 rejects and we fall through.
        result = rq.resolve_display_match(text, "five minutes past noon")
        assert result == "five minutes past noon"


# ---------------------------------------------------------------------------
# tokenize_quote
# ---------------------------------------------------------------------------

class TestTokenizeQuote:
    def test_no_match_returns_single_plain_segment(self):
        tokens = rq.tokenize_quote("She arrived at noon.", "midnight")
        assert tokens == [("She arrived at noon.", False)]

    def test_match_at_start(self):
        tokens = rq.tokenize_quote("Three o'clock the bell rang.", "three o'clock")
        assert len(tokens) == 3
        assert tokens[0] == ("", False)
        bold_text = tokens[1][0]
        assert "three o'clock" in bold_text.lower()
        assert tokens[1][1] is True

    def test_match_in_middle(self):
        tokens = rq.tokenize_quote("It was three o'clock.", "three o'clock")
        assert len(tokens) == 3
        before, bold, after = tokens
        assert before[1] is False
        assert bold[1] is True
        assert after[1] is False

    def test_match_is_case_insensitive(self):
        tokens = rq.tokenize_quote("It was THREE O'CLOCK.", "three o'clock")
        bold_parts = [t for t in tokens if t[1]]
        assert len(bold_parts) == 1

    def test_prefers_actual_matched_phrase_when_multiple_time_phrases_exist(self):
        tokens = rq.tokenize_quote(
            "It was a quarter past six when we left Baker Street, and it still wanted ten minutes to the hour.",
            "quarter past six",
        )
        bold_parts = [t[0] for t in tokens if t[1]]
        assert bold_parts == ["quarter past six"]

    def test_newline_in_matched_text_does_not_break_highlight(self):
        tokens = rq.tokenize_quote(
            "Do you think I should be standing here at five minutes to nine looking for it if I had it in my pocket all the while?",
            "five\nminutes to nine",
        )
        bold_parts = [t[0] for t in tokens if t[1]]
        assert bold_parts == ["five minutes to nine"]


# ---------------------------------------------------------------------------
# snap_image_to_palette
# ---------------------------------------------------------------------------

class TestSnapImageToPalette:
    def _pixels(self, img):
        return list(img.convert("RGB").getdata())

    def test_pure_white_snaps_to_white(self):
        img = Image.new("RGB", (4, 4), color=(255, 255, 255))
        palette = [(255, 255, 255), (0, 0, 0)]
        result = rq.snap_image_to_palette(img, palette)
        assert all(p == (255, 255, 255) for p in self._pixels(result))

    def test_pure_black_snaps_to_black(self):
        img = Image.new("RGB", (4, 4), color=(0, 0, 0))
        palette = [(255, 255, 255), (0, 0, 0)]
        result = rq.snap_image_to_palette(img, palette)
        assert all(p == (0, 0, 0) for p in self._pixels(result))

    def test_near_red_snaps_to_red(self):
        img = Image.new("RGB", (2, 2), color=(240, 10, 10))
        palette = [(255, 255, 255), (0, 0, 0), (255, 0, 0)]
        result = rq.snap_image_to_palette(img, palette)
        assert all(p == (255, 0, 0) for p in self._pixels(result))

    def test_output_size_matches_input(self):
        img = Image.new("RGB", (10, 8), color=(128, 128, 128))
        palette = [(255, 255, 255), (0, 0, 0)]
        result = rq.snap_image_to_palette(img, palette)
        assert result.size == (10, 8)

    def test_all_spectra6_colors_round_trip(self):
        palette = list(rq.SPECTRA6.values())
        for color in palette:
            img = Image.new("RGB", (2, 2), color=color)
            result = rq.snap_image_to_palette(img, palette)
            assert all(p == color for p in self._pixels(result)), f"Color {color} did not round-trip"


# ---------------------------------------------------------------------------
# render — smoke test (no assertion on pixels, just that it completes)
# ---------------------------------------------------------------------------

class TestDebugQuoteId:
    def test_uses_source_id_when_present(self):
        assert rq.debug_quote_id({"source_id": "1661"}) == "1661"

    def test_uses_source_id_and_line_number_when_present(self):
        assert rq.debug_quote_id({"source_id": "1661", "line_number": 12345}) == "1661:L12345"

    def test_falls_back_to_source_stem(self):
        assert rq.debug_quote_id({"source_path": "data/gutenberg/pg1661.txt"}) == "pg1661"


class TestFallbackTitle:
    def test_prefers_project_gutenberg_label_for_source_id(self):
        assert rq.fallback_title({"source_id": "119"}) == "Project Gutenberg #119"

    def test_falls_back_to_source_stem_without_source_id(self):
        assert rq.fallback_title({"source_path": "data/gutenberg/pg1661.txt"}) == "pg1661"

    def test_returns_none_when_no_metadata(self):
        assert rq.fallback_title({}) is None
        assert rq.fallback_title({"source_id": "", "source_path": ""}) is None


class TestLoadFontFallback:
    """When every TTF candidate is missing, ``load_font`` must log a one-shot
    warning and return the PIL bitmap default — never crash."""

    def test_missing_candidates_returns_default_and_warns_once(self, monkeypatch, capsys):
        # Force the fallback path by flipping the module-level guard.
        monkeypatch.setattr(rq, "_FONT_FALLBACK_WARNED", False)
        # All candidate paths report as missing.
        monkeypatch.setattr(rq.Path, "exists", lambda self: False)
        font = rq.load_font(["/nope/one.ttf", "/nope/two.ttf"], size=24)
        assert font is not None  # the bitmap default
        err = capsys.readouterr().err
        assert "no TrueType font found" in err
        # Second call must NOT warn again (one-shot).
        capsys.readouterr()  # drain
        rq.load_font(["/nope/three.ttf"], size=24)
        assert capsys.readouterr().err == ""

    def test_variation_tuple_candidate_loads(self):
        """``load_font`` accepts ``(path, variation_name)`` tuples for variable
        fonts and applies the named instance. The Bitter file bundled for the
        ``scholar`` theme is a variable font that defaults to Thin weight, so
        the ``Bold`` variation must produce visibly wider glyphs than the
        default — otherwise the variation call silently fell through and the
        panel would render near-invisible hairlines."""
        variable_path = Path(rq.BASE_DIR) / "fonts" / "bitter" / "Bitter-Variable.ttf"
        if not variable_path.exists():
            pytest.skip("Bitter variable font not bundled")
        regular = rq.load_font([str(variable_path)], size=60)
        bold = rq.load_font([(str(variable_path), "Bold")], size=60)
        img = Image.new("RGB", (400, 120), "white")
        draw = ImageDraw.Draw(img)
        rbbox = draw.textbbox((0, 0), "Bold", font=regular)
        bbbox = draw.textbbox((0, 0), "Bold", font=bold)
        # Bold instance must make the glyphs visibly wider; if the variation
        # silently fell through, both widths would be identical.
        assert (bbbox[2] - bbbox[0]) > (rbbox[2] - rbbox[0])

    def test_variation_tuple_missing_file_falls_through(self, monkeypatch, capsys):
        """A missing file referenced in a variation tuple falls through to the
        next candidate, exactly like a bare-path candidate would."""
        monkeypatch.setattr(rq, "_FONT_FALLBACK_WARNED", False)
        # First candidate is a tuple pointing at a missing file; second is a
        # plain path to a real system font that exists on the CI image.
        font = rq.load_font(
            [("/nope/variable.ttf", "Bold"), "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"],
            size=24,
        )
        # Should have loaded DejaVu without emitting the warning.
        assert font is not None
        assert "no TrueType font found" not in capsys.readouterr().err


class TestThemeFonts:
    """THEME_FONTS is the source of truth for per-theme typography. Every
    ``THEMES`` entry needs a matching ``THEME_FONTS`` entry with the full
    role set; otherwise ``render`` or ``render_source_card`` would KeyError
    at display time."""

    REQUIRED_ROLES = {"quote_regular", "quote_bold", "ornament"}

    def test_every_theme_has_a_font_mapping(self):
        for name in rq.THEMES:
            assert name in rq.THEME_FONTS, f"theme {name!r} missing from THEME_FONTS"

    def test_every_theme_font_entry_has_required_roles(self):
        for name, roles in rq.THEME_FONTS.items():
            assert self.REQUIRED_ROLES <= set(roles.keys()), (
                f"theme {name!r} font map missing roles: {self.REQUIRED_ROLES - set(roles.keys())}"
            )

    def test_every_theme_role_has_at_least_one_candidate(self):
        for name, roles in rq.THEME_FONTS.items():
            for role, candidates in roles.items():
                assert candidates, f"{name}.{role} candidate list is empty"

    def test_new_themes_pick_distinct_primary_faces(self):
        """Each operator-choice theme bundles a distinct typeface — a
        regression that made any of them alias to Playfair would defeat the
        whole point of adding per-theme fonts."""
        def primary(name: str, role: str) -> str:
            entry = rq.THEME_FONTS[name][role][0]
            return entry[0] if isinstance(entry, tuple) else entry
        operator_choice = ("scholar", "newsprint", "nightvision", "blueprint")
        default_primary = primary("default", "quote_regular")
        primaries = {name: primary(name, "quote_regular") for name in operator_choice}
        for name, face in primaries.items():
            assert face != default_primary, f"{name} aliases the default face"
        # And distinct from each other.
        unique = set(primaries.values())
        assert len(unique) == len(operator_choice), (
            f"operator-choice themes share primary fonts: {primaries}"
        )

    def test_theme_font_candidates_falls_back_for_unknown_theme(self):
        """An unregistered theme silently resolves to the default chain so a
        typo in a config file doesn't crash the render path."""
        unknown = rq.theme_font_candidates("does_not_exist", "quote_regular")
        assert unknown == rq.theme_font_candidates("default", "quote_regular")


# (TestResolveDisplayMatch extensions moved into the existing class above.)


class TestTokenizeQuoteEdge:
    def test_empty_match_returns_plain_segment(self):
        segments = rq.tokenize_quote("Just a plain quote.", "")
        assert segments == [("Just a plain quote.", False)]

    def test_unmatched_text_returns_plain(self):
        segments = rq.tokenize_quote("Nothing matches here.", "three o'clock")
        assert segments == [("Nothing matches here.", False)]

    def test_trailing_punctuation_included_in_bold(self):
        # The match-end walker extends past ”/", '/', ., ;, :, !, ?
        segments = rq.tokenize_quote('It was "three o\'clock!"', "three o'clock")
        # One of the middle segments should end with trailing punctuation.
        bold_chunks = [text for text, is_bold in segments if is_bold]
        assert bold_chunks, "expected at least one bold chunk"


class TestFitQuoteExhaustion:
    """When the text is so long it can't fit even at ``font_min``, fit_quote
    must still return the font_min wrap rather than looping forever."""

    def test_returns_font_min_when_no_size_fits(self):
        img = Image.new("RGB", (800, 480), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        # An absurdly long "word" (no spaces) with impossibly tight max_height
        # forces the loop to exhaust without a fit.
        text = "Supercalifragilistic " * 40
        regular_font, bold_font, wrapped, line_height, size = rq.fit_quote(
            draw, text, match_text="",
            max_width=720, max_height=20,  # tiny height forces exhaustion
            font_max=30, font_min=12, line_height_mult=1.2,
        )
        assert size == 12  # floored at font_min
        assert wrapped  # still produced SOME wrapped output


class TestLineWidth:
    def test_sums_chunk_widths(self):
        img = Image.new("RGB", (400, 100), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = rq.load_font(rq.QUOTE_FONT_SEMIBOLD_CANDIDATES, size=20)
        bold = rq.load_font(rq.QUOTE_FONT_BOLD_CANDIDATES, size=20)
        line = [("Hello", False), (" ", False), ("world", True)]
        w = rq.line_width(draw, line, font, bold)
        assert w > 0

    def test_empty_line_is_zero(self):
        img = Image.new("RGB", (400, 100), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = rq.load_font(rq.QUOTE_FONT_SEMIBOLD_CANDIDATES, size=20)
        bold = rq.load_font(rq.QUOTE_FONT_BOLD_CANDIDATES, size=20)
        assert rq.line_width(draw, [], font, bold) == 0


class TestWrapTextEmpty:
    def test_empty_text_produces_no_lines(self):
        img = Image.new("RGB", (400, 100), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = rq.load_font(rq.QUOTE_FONT_SEMIBOLD_CANDIDATES, size=20)
        lines = rq.wrap_text(draw, "", font, 300)
        assert lines == []


class TestThemes:
    def test_dark_theme_palette_values(self):
        dark = rq.THEMES["dark"]
        assert dark["page_bg"] == rq.SPECTRA6["black"]
        assert dark["text"] == rq.SPECTRA6["white"]
        assert dark["accent"] == rq.SPECTRA6["yellow"]
        assert dark["ornament_dark"] == rq.SPECTRA6["black"]
        assert dark["ornament_light"] == rq.SPECTRA6["white"]

    def test_theme_order_covers_all_registered_themes(self):
        """THEME_ORDER is the single source of truth for the cycle; it must
        not get out of sync with the THEMES color dicts or button-B / web
        dropdown will silently skip (or crash on) themes that exist but
        aren't in the cycle."""
        assert set(rq.THEME_ORDER) == set(rq.THEMES.keys())

    def test_new_themes_registered(self):
        """Keep the operator-choice themes discoverable by name so a typo in
        the THEMES dict or THEME_ORDER tuple fails the test rather than
        ghosting downstream."""
        for name in ("scholar", "newsprint", "nightvision", "blueprint"):
            assert name in rq.THEMES, name
            assert name in rq.THEME_ORDER, name

    def test_every_theme_has_the_full_field_set(self):
        """Every render theme must populate the same field set — a missing
        key would raise KeyError deep inside ``render`` at display time,
        long after the typo landed in git."""
        required = set(rq.THEMES["default"].keys())
        for name, fields in rq.THEMES.items():
            assert set(fields.keys()) == required, f"{name} missing/extra fields"

    def test_theme_colors_stay_within_spectra6_palette(self):
        """Every theme colour must map to one of the six panel colours —
        otherwise the ``snap_image_to_palette`` pass silently remaps and the
        rendered result is not what the operator configured."""
        allowed = set(rq.SPECTRA6.values())
        for name, fields in rq.THEMES.items():
            for field, value in fields.items():
                assert value in allowed, f"{name}.{field}={value} is off-palette"

    def test_scholar_theme_uses_blue_text(self):
        t = rq.THEMES["scholar"]
        assert t["text"] == rq.SPECTRA6["blue"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["accent"] == rq.SPECTRA6["red"]

    def test_newsprint_theme_has_no_colour_accent(self):
        """``newsprint`` is intentionally monochrome — the bolded matched
        phrase carries weight differentiation but the same ink colour as
        the surrounding text, so no colour is used anywhere."""
        t = rq.THEMES["newsprint"]
        assert t["text"] == t["accent"]  # bold-only differentiation
        assert t["text"] == rq.SPECTRA6["black"]

    def test_nightvision_theme_uses_green_on_black(self):
        t = rq.THEMES["nightvision"]
        assert t["page_bg"] == rq.SPECTRA6["black"]
        assert t["text"] == rq.SPECTRA6["green"]
        assert t["accent"] == rq.SPECTRA6["yellow"]

    def test_every_theme_has_at_least_one_visible_ornament_colour(self):
        """``draw_faux_gray_text`` paints a 50% stipple of ornament_dark /
        ornament_light over the page background. If BOTH ornament colours
        equal ``page_bg``, every mask pixel disappears into the background
        and the curly quotation marks are literally invisible. The existing
        themes deliberately make one ornament colour match the background
        (to produce the faux-gray half-density effect) and the other
        contrast it; a future theme that accidentally sets BOTH to the bg
        colour would render ornament-less — catch that class of bug here.
        """
        for name, fields in rq.THEMES.items():
            bg = fields["page_bg"]
            dark = fields["ornament_dark"]
            light = fields["ornament_light"]
            assert dark != bg or light != bg, (
                f"{name}: both ornament colours equal page_bg={bg}, "
                "so draw_faux_gray_text paints every pixel invisibly"
            )


class TestRender:
    def _quote_row(self, text="It was three o'clock in the afternoon.", matched="three o'clock"):
        return {
            "display_quote": text,
            "matched_text": matched,
            "author": "Jane Austen",
            "title": "Mansfield Park",
            "bucket": "h3_exact",
            "resolved_bucket": "h3_exact",
            "used_fallback": False,
            "quality_score": 80,
            "source_id": "141",
        }

    def test_render_returns_image_of_correct_size(self):
        row = self._quote_row()
        img = rq.render("03:00", row, 800, 480, mode="debug")
        assert img.size == (800, 480)

    def test_render_production_mode(self):
        row = self._quote_row()
        img = rq.render("03:00", row, 800, 480, mode="production")
        assert img.size == (800, 480)

    def test_render_dark_theme(self):
        row = self._quote_row()
        img = rq.render("03:00", row, 800, 480, mode="production", theme="dark")
        assert img.size == (800, 480)

    @pytest.mark.parametrize("theme", ["scholar", "newsprint", "nightvision", "blueprint"])
    def test_render_new_themes_smoke(self, theme):
        """Each new theme must produce a correctly-sized frame without
        crashing — catches missing dict keys, off-palette colours that
        would error downstream, or ornament fonts that silently fail to
        load when the theme swap changes the duotone combination."""
        row = self._quote_row()
        img = rq.render("03:00", row, 800, 480, mode="production", theme=theme)
        assert img.size == (800, 480)

    def test_render_with_fallback_flag(self):
        row = self._quote_row()
        row["used_fallback"] = True
        row["resolved_bucket"] = "h3_just_after"
        img = rq.render("03:00", row, 800, 480, mode="debug")
        assert img.size == (800, 480)

    def test_render_short_quote_uses_hero_layout(self):
        row = self._quote_row(text="Three o'clock.", matched="Three o'clock")
        img = rq.render("03:00", row, 800, 480, mode="debug")
        assert img.size == (800, 480)

    def test_render_long_quote_uses_dense_layout(self):
        long_text = "A" * 180 + " three o'clock " + "B" * 40 + "."
        row = self._quote_row(text=long_text, matched="three o'clock")
        img = rq.render("03:00", row, 800, 480, mode="debug")
        assert img.size == (800, 480)

    def test_render_output_uses_spectra6_palette(self):
        row = self._quote_row()
        img = rq.render("03:00", row, 800, 480, mode="production")
        palette = set(rq.SPECTRA6.values())
        pixels = set(img.convert("RGB").getdata())
        assert pixels.issubset(palette), f"Unexpected colors: {pixels - palette}"

    def test_render_dark_theme_uses_black_background(self):
        row = self._quote_row()
        img = rq.render("03:00", row, 800, 480, mode="production", theme="dark")
        assert img.getpixel((0, 0)) == rq.SPECTRA6["black"]

    def test_render_without_metadata_does_not_need_source_path_attribution(self):
        row = self._quote_row()
        row["author"] = None
        row["title"] = None
        row["source_id"] = "119"
        row["source_path"] = "data/gutenberg/pg119.txt"
        img = rq.render("03:00", row, 800, 480, mode="production")
        assert img.size == (800, 480)

    def test_render_handles_newline_in_matched_text(self):
        row = self._quote_row(
            text="Do you think I should be standing here at five minutes to nine looking for it if I had it in my pocket all the while?",
            matched="five\nminutes to nine",
        )
        img = rq.render("08:55", row, 800, 480, mode="debug")
        assert img.size == (800, 480)

    def test_render_handles_gutenberg_underscore_emphasis_without_crashing(self):
        row = self._quote_row(
            text="I heard of it first from my newspaper boy about a quarter to nine when I went out to get my _Daily Chronicle_.",
            matched="quarter to nine",
        )
        img = rq.render("08:45", row, 800, 480, mode="debug")
        assert img.size == (800, 480)


class TestRenderCard:
    """The button-C source card uses mode='card' to render a centered metadata frame."""

    def _row(self, **overrides):
        row = {
            "display_quote": "It was three o'clock in the afternoon.",
            "matched_text": "three o'clock",
            "author": "Jane Austen",
            "title": "Mansfield Park",
            "source_id": "141",
        }
        row.update(overrides)
        return row

    def test_card_returns_image_of_correct_size(self):
        img = rq.render("03:00", self._row(), 800, 480, mode="card")
        assert img.size == (800, 480)

    def test_card_uses_dark_theme_background(self):
        img = rq.render("03:00", self._row(), 800, 480, mode="card", theme="dark")
        assert img.getpixel((0, 0)) == rq.SPECTRA6["black"]

    def test_card_uses_default_theme_background(self):
        img = rq.render("03:00", self._row(), 800, 480, mode="card", theme="default")
        assert img.getpixel((0, 0)) == rq.SPECTRA6["white"]

    def test_card_palette_is_spectra6(self):
        img = rq.render("03:00", self._row(), 800, 480, mode="card")
        palette = set(rq.SPECTRA6.values())
        pixels = set(img.convert("RGB").getdata())
        assert pixels.issubset(palette), f"Unexpected colors: {pixels - palette}"

    def test_card_without_author_or_title_falls_back_gracefully(self):
        row = self._row(author=None, title=None, source_path="data/gutenberg/pg141.txt")
        img = rq.render("03:00", row, 800, 480, mode="card")
        assert img.size == (800, 480)

    def test_card_without_source_id_does_not_crash(self):
        row = self._row(source_id=None)
        img = rq.render("03:00", row, 800, 480, mode="card")
        assert img.size == (800, 480)

    def test_card_strips_underscore_emphasis_from_matched_text(self):
        row = self._row(matched_text="_three o'clock_")
        img = rq.render("03:00", row, 800, 480, mode="card")
        assert img.size == (800, 480)


class TestMainAtomicSave:
    """``render_quote.main`` must never leave ``output/current.png`` truncated."""

    def _row(self):
        return {
            "display_quote": "It was three o'clock.",
            "matched_text": "three o'clock",
            "source_id": "141",
            "line_number": 482,
            "author": "A. Author",
            "title": "A Title",
            "quality_score": 90,
            "fuzzy_bucket": "h3_exact",
            "resolved_bucket": "h3_exact",
        }

    def test_successful_save_writes_valid_png(self, tmp_path, monkeypatch):
        """End-to-end: main() produces a file Pillow can re-open."""
        monkeypatch.setattr(rq, "pick_quote", lambda *args, **kwargs: self._row())
        output = tmp_path / "current.png"
        monkeypatch.setattr(
            "sys.argv",
            ["render_quote.py", "--time", "03:00", "--output", str(output)],
        )
        assert rq.main() == 0
        # Must be a readable PNG, not a truncated stub.
        with Image.open(output) as img:
            assert img.size == (800, 480)
        # No stray tmp sibling left behind.
        assert list(tmp_path.glob("*.tmp")) == []

    def test_save_failure_preserves_previous_output(self, tmp_path, monkeypatch):
        """A Pillow save failure must not truncate the existing current.png."""
        original_bytes = b"\x89PNG\r\n\x1a\nprior-valid-frame-bytes"
        output = tmp_path / "current.png"
        output.write_bytes(original_bytes)

        monkeypatch.setattr(rq, "pick_quote", lambda *args, **kwargs: self._row())

        # Make image.save raise mid-save by patching PIL.Image.Image.save.
        original_save = Image.Image.save

        def exploding_save(self, fp, format=None, **kwargs):  # noqa: A002
            raise OSError("simulated disk error mid-save")

        monkeypatch.setattr(Image.Image, "save", exploding_save)
        monkeypatch.setattr(
            "sys.argv",
            ["render_quote.py", "--time", "03:00", "--output", str(output)],
        )

        with pytest.raises(OSError):
            rq.main()

        # Crucially, the prior frame is intact; no truncation.
        assert output.read_bytes() == original_bytes
        assert list(tmp_path.glob("*.tmp")) == []

        # Restore so later tests aren't affected.
        monkeypatch.setattr(Image.Image, "save", original_save)


class TestDefaultOutputPath:
    """Default --output must be a stable filename so ad-hoc callers don't leak
    one PNG per HH:MM into output/ over time. run_clock always passes --output
    explicitly, so this only governs interactive/CLI use."""

    def _row(self):
        return {
            "display_quote": "It was three o'clock.",
            "matched_text": "three o'clock",
            "source_id": "141",
            "line_number": 482,
            "author": "A",
            "title": "T",
            "quality_score": 90,
            "fuzzy_bucket": "h3_exact",
            "resolved_bucket": "h3_exact",
        }

    def test_default_output_is_stable_current_png(self, tmp_path, monkeypatch):
        """No --output flag → stable ``output/current.png``, not ``output/render-HHMM.png``.

        Without this, a human running render_quote.py ad-hoc can leak up to
        1440 PNGs into output/ over the day — the loop's runtime path already
        overwrites a single ``current.png``, but the CLI default used to
        diverge and write a per-minute filename.
        """
        monkeypatch.setattr(rq, "pick_quote", lambda *a, **kw: self._row())
        monkeypatch.setattr("sys.argv", ["render_quote.py", "--time", "14:30"])
        written: list[Path] = []

        # Capture the target path but short-circuit the actual write so the
        # test doesn't pollute ``<repo>/output/`` for later runs of the suite.
        def spy(target, payload):
            written.append(Path(target))

        monkeypatch.setattr(rq.atomic_io, "atomic_write_bytes", spy)
        assert rq.main() == 0
        assert len(written) == 1
        # Filename must be the stable "current.png" default, not a per-HHMM one.
        assert written[0].name == "current.png"
        # Older default would have produced "render-1430.png" for this --time.
        assert written[0].name != "render-1430.png"


class TestPickQuoteUsesBakedDatabase:
    """``render_quote.pick_quote`` must forward ``database_path`` to
    ``select_quote`` so the fast baked-DB path is used. Without this, the
    curator hero image and one-shot renders silently fall back to the raw
    corpus even when a baked DB is present."""

    def test_forwards_database_path(self, monkeypatch):
        import pick_quote as pq
        import render_quote
        captured: dict = {}

        def fake_select_quote(**kwargs):
            captured.update(kwargs)
            return {"source_id": "1", "line_number": 1, "display_quote": "x", "matched_text": "y"}

        monkeypatch.setattr(render_quote.pick_quote_module, "select_quote", fake_select_quote)
        render_quote.pick_quote("10:00")
        assert captured.get("database_path") == pq.DEFAULT_DATABASE_PATH
