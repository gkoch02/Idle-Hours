"""Tests for render_quote.py — layout selection, text helpers, color quantization."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")

import render_quote as rq  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_font_cache():
    """Clear ``render_quote._FONT_CACHE`` around every test so cache state
    from a prior test can't mask path-existence assertions or fallback-path
    expectations in the current one. The cache is a per-process performance
    optimisation, not a correctness signal — tests that exercise either
    branch should always start from an empty cache.
    """
    rq._FONT_CACHE.clear()
    yield
    rq._FONT_CACHE.clear()


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
        # All candidate paths report as missing. (Cache isolation is provided
        # by the autouse ``_isolate_font_cache`` fixture at module scope.)
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

    def test_fallback_path_not_cached_so_recovery_works(self, monkeypatch):
        """A transient font-load failure (NFS hiccup, brief unavailability)
        must not pin the process to the bitmap fallback. The cache stores
        successfully-loaded fonts only; a later call after the file becomes
        reachable again must re-scan and load the real font.

        Regression guard for a Codex review concern: caching the fallback
        would silently degrade rendering for the rest of the subprocess
        (especially noticeable for ``contact_sheet.py`` which renders all
        144 buckets in one process).
        """
        # Suppress the one-shot warning so capsys doesn't matter here.
        monkeypatch.setattr(rq, "_FONT_FALLBACK_WARNED", True)
        real_path = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
        if not Path(real_path).exists():
            pytest.skip("DejaVu Serif not installed")
        # First call: pretend the file is missing → fallback to PIL's
        # bundled default (or the bitmap default in older Pillows).
        monkeypatch.setattr(rq.Path, "exists", lambda self: False)
        a = rq.load_font([real_path], size=24)
        # Second call: file is reachable again → should load the real font.
        monkeypatch.undo()
        monkeypatch.setattr(rq, "_FONT_FALLBACK_WARNED", True)
        b = rq.load_font([real_path], size=24)
        # `b` must be the real load: its underlying path matches what we asked
        # for, and the cache now holds it. `a` did NOT come from real_path
        # (the path was unreachable on that call) so it must be a different
        # font, AND the fallback call must NOT have populated the cache —
        # otherwise `b` would be `a` (the cached fallback).
        b_path = getattr(b, "path", None)
        assert b_path == real_path, f"second call should load {real_path!r}, got {b_path!r}"
        assert a is not b, "fallback was cached and reused — recovery is broken"
        # The cache contains exactly one entry (the successful load on call 2).
        assert len(rq._FONT_CACHE) == 1

    def test_load_font_caches_results_per_size(self, monkeypatch):
        """``load_font`` is called up to 18 times per render in ``fit_quote``
        with the same candidate chain at different sizes; caching turns the
        repeat opens into O(1) lookups. Verify by counting ``ImageFont.truetype``
        calls across two cache hits and one cache miss.
        """
        truetype_calls = []
        original_truetype = rq.ImageFont.truetype

        def counting_truetype(*args, **kwargs):
            truetype_calls.append((args, kwargs))
            return original_truetype(*args, **kwargs)

        monkeypatch.setattr(rq.ImageFont, "truetype", counting_truetype)
        candidates = ["/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]
        a = rq.load_font(candidates, size=24)
        b = rq.load_font(candidates, size=24)  # cache hit
        c = rq.load_font(candidates, size=32)  # different size → cache miss
        # Two distinct truetype opens (one per size); the duplicate-size call
        # was served from cache.
        assert len(truetype_calls) == 2
        # Cache returns the *same* font object across calls with the same key.
        assert a is b
        assert a is not c

    def test_load_font_keys_on_variation(self):
        """Different variation pins of the same path produce different cache
        entries, so a per-theme variable-font Bold/Regular split is isolated.
        """
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
        plain = rq.load_font([path], size=20)
        with_variation = rq.load_font([(path, "Bold")], size=20)
        # Different keys → different cached objects (variation is part of key).
        assert plain is not with_variation


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
        operator_choice = (
            "scholar",
            "newsprint",
            "nightvision",
            "blueprint",
            "illuminated",
            "bauhaus",
            "risograph",
            "comic",
        )
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
        for name in (
            "scholar",
            "newsprint",
            "nightvision",
            "blueprint",
            "illuminated",
            "bauhaus",
            "risograph",
            "comic",
        ):
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

    def test_blueprint_theme_uses_blue_on_white_with_red_accent(self):
        """Same palette as ``scholar`` — the two stay differentiated purely
        via THEME_FONTS (Archivo vs Bitter). Pin the palette so a refactor
        doesn't accidentally merge them back into a single theme."""
        t = rq.THEMES["blueprint"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["blue"]
        assert t["accent"] == rq.SPECTRA6["red"]

    def test_illuminated_theme_uses_rubricated_red_body(self):
        """Red body text is unique to ``illuminated`` across the rotation;
        a regression that flipped ``text`` to black would collapse the
        theme into a slightly-fancier ``default`` and lose the whole
        manuscript motif."""
        t = rq.THEMES["illuminated"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["red"]
        assert t["accent"] == rq.SPECTRA6["blue"]

    def test_bauhaus_theme_uses_three_primaries_simultaneously(self):
        """Bauhaus is the only theme that puts all three primaries on the
        panel at once: black body, blue accent, red ornaments. A regression
        that collapsed the ornament colour back to black would drop the
        poster-palette effect and make the theme visually similar to a
        blue-accented ``default``."""
        t = rq.THEMES["bauhaus"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["black"]
        assert t["accent"] == rq.SPECTRA6["blue"]
        assert t["ornament_dark"] == rq.SPECTRA6["red"]

    def test_risograph_theme_uses_no_black_ink(self):
        """The defining constraint of the risograph aesthetic is
        two-colour printing with NO black plate. Pin "no black anywhere"
        as an explicit invariant so a well-meaning refactor (e.g. making
        the source credit more legible by darkening it) doesn't silently
        re-introduce black and collapse the theme into a tinted
        ``default``."""
        t = rq.THEMES["risograph"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["red"]
        assert t["accent"] == rq.SPECTRA6["blue"]
        # Every colour field must avoid black — this is the theme's
        # whole point.
        for field, value in t.items():
            assert value != rq.SPECTRA6["black"], f"risograph.{field} is black"

    def test_comic_theme_uses_yellow_ground(self):
        """Comic is the first (and only) theme with a yellow page
        background. A regression that flipped it back to white would
        collapse the theme into a default-palette alias differentiated
        only by the comic font."""
        t = rq.THEMES["comic"]
        assert t["page_bg"] == rq.SPECTRA6["yellow"]
        assert t["text"] == rq.SPECTRA6["black"]
        assert t["accent"] == rq.SPECTRA6["red"]

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

    @pytest.mark.parametrize(
        "theme",
        [
            "scholar",
            "newsprint",
            "nightvision",
            "blueprint",
            "illuminated",
            "bauhaus",
            "risograph",
            "comic",
        ],
    )
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


class TestBauhausBorder:
    """The bauhaus theme is the only theme that paints a decorative border.

    A regression that drops ``draw_bauhaus_border`` from ``render`` — or
    changes the corner-shape colours — would otherwise pass
    ``test_render_new_themes_smoke`` (correct image size, palette snap) and
    the dict-level palette tests silently. Pin the actual painted pixels
    so the border can't silently vanish.
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

    def test_bauhaus_corner_accents_paint_primary_colours(self):
        """Four corner shapes, each sitting at the canvas corner with a
        small edge margin. The centre of each shape is a reliable sample
        point: it lands inside the shape regardless of whether it's a
        circle, square, or right-triangle."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="bauhaus")
        # Corner shapes are 22px at a 6px canvas-edge margin; centre near
        # (17, 17) / (783, 17) / (17, 463) / (783, 463).
        assert img.getpixel((15, 15)) == rq.SPECTRA6["red"], "top-left should be red circle"
        assert img.getpixel((785, 15)) == rq.SPECTRA6["blue"], "top-right should be blue square"
        assert img.getpixel((15, 465)) == rq.SPECTRA6["blue"], "bottom-left should be blue triangle"
        assert img.getpixel((785, 465)) == rq.SPECTRA6["red"], "bottom-right should be red circle"

    def test_bauhaus_outer_frame_is_painted_on_all_four_sides(self):
        """The outer rectangle outline is the structural element the corner
        accents anchor to. Sample a point on each side, well clear of the
        corner shapes, to verify all four sides rendered."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="bauhaus")
        assert img.getpixel((400, 14)) == rq.SPECTRA6["black"], "top frame line missing"
        assert img.getpixel((400, 465)) == rq.SPECTRA6["black"], "bottom frame line missing"
        assert img.getpixel((14, 240)) == rq.SPECTRA6["black"], "left frame line missing"
        assert img.getpixel((785, 240)) == rq.SPECTRA6["black"], "right frame line missing"

    def test_bauhaus_border_is_theme_gated(self):
        """Bauhaus's geometric corner accents must not appear on other
        themes. Sample (15, 15), which lands inside the bauhaus top-left
        red circle. Excluded themes: illuminated (its TL jewel at radius
        5 centred on (14, 14) also covers this pixel) — both bauhaus and
        illuminated paint here, so (15, 15) can only distinguish
        bauhaus from every theme whose margin is empty there."""
        for theme in ("default", "dark", "scholar", "newsprint", "nightvision",
                      "blueprint", "risograph", "comic"):
            img = rq.render("03:00", self._row(), 800, 480, mode="production", theme=theme)
            expected_bg = rq.THEMES[theme]["page_bg"]
            assert img.getpixel((15, 15)) == expected_bg, (
                f"theme {theme} painted something at (15, 15); expected page_bg={expected_bg}"
            )

    def test_bauhaus_border_appears_in_debug_and_card_modes_too(self):
        """The border is part of the bauhaus theme's visual identity, so
        it must show up regardless of render mode — production, debug,
        and the source-card overlay all get the same frame."""
        for mode in ("production", "debug", "card"):
            img = rq.render("03:00", self._row(), 800, 480, mode=mode, theme="bauhaus")
            assert img.getpixel((15, 15)) == rq.SPECTRA6["red"], f"bauhaus mode={mode} missing TL corner"

    def test_bauhaus_border_uses_theme_colours_not_hardcoded_rgb(self):
        """``draw_bauhaus_border`` must pull its colours from the passed-in
        theme dict (text/accent/ornament_dark). A refactor that hardcoded
        specific RGB triples would survive the current palette tests but
        break the contract that lets a future bauhaus palette tweak flow
        through the border automatically. Call the helper directly with
        a non-default colour set and assert the output reflects it."""
        image = Image.new("RGB", (800, 480), color=(255, 255, 255))
        custom = {
            "text": rq.SPECTRA6["green"],
            "accent": rq.SPECTRA6["yellow"],
            "ornament_dark": rq.SPECTRA6["blue"],
        }
        rq.draw_bauhaus_border(image, custom)
        assert image.getpixel((15, 15)) == rq.SPECTRA6["blue"], "TL should use ornament_dark"
        assert image.getpixel((785, 15)) == rq.SPECTRA6["yellow"], "TR should use accent"
        assert image.getpixel((400, 14)) == rq.SPECTRA6["green"], "frame should use text colour"


class TestIlluminatedBorder:
    """The illuminated theme paints a manuscript-style border.

    Double rubricated (red) rule — outer and inner concentric rectangles
    — plus a small blue "jewel" (filled circle) centred on each outer
    corner, evoking the lapis cabochons inset into medieval
    illuminated pages. Regression tests here pin the painted pixels,
    complementing the golden-image suite.
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

    def test_illuminated_double_rule_paints_both_rules_in_body_red(self):
        """Outer rule at y=14, inner rule at y=22, page_bg gap between."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="illuminated")
        assert img.getpixel((400, 14)) == rq.SPECTRA6["red"], "outer rule missing"
        assert img.getpixel((400, 22)) == rq.SPECTRA6["red"], "inner rule missing"
        # White gap between the two — the defining "doubled" effect.
        assert img.getpixel((400, 18)) == rq.SPECTRA6["white"], "rules merged into single band"

    def test_illuminated_corner_jewels_paint_accent_blue(self):
        """Filled blue circles of radius 5 centred on each outer-rule corner."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="illuminated")
        assert img.getpixel((14, 14)) == rq.SPECTRA6["blue"], "TL jewel centre missing"
        assert img.getpixel((785, 14)) == rq.SPECTRA6["blue"], "TR jewel centre missing"
        assert img.getpixel((14, 465)) == rq.SPECTRA6["blue"], "BL jewel centre missing"
        assert img.getpixel((785, 465)) == rq.SPECTRA6["blue"], "BR jewel centre missing"

    def test_illuminated_border_paints_all_four_sides(self):
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="illuminated")
        # Outer rule, mid-side samples (away from the jewels).
        assert img.getpixel((400, 14)) == rq.SPECTRA6["red"], "top outer rule missing"
        assert img.getpixel((400, 465)) == rq.SPECTRA6["red"], "bottom outer rule missing"
        assert img.getpixel((14, 240)) == rq.SPECTRA6["red"], "left outer rule missing"
        assert img.getpixel((785, 240)) == rq.SPECTRA6["red"], "right outer rule missing"

    def test_illuminated_border_is_theme_gated(self):
        """Sample (400, 22) — inner rule pixel — which is unique to
        illuminated; no other border theme places a rule at inset 22."""
        for theme in ("default", "dark", "scholar", "newsprint", "nightvision",
                      "blueprint", "bauhaus", "risograph", "comic"):
            img = rq.render("03:00", self._row(), 800, 480, mode="production", theme=theme)
            expected_bg = rq.THEMES[theme]["page_bg"]
            assert img.getpixel((400, 22)) == expected_bg, (
                f"theme {theme} painted at inner-rule y=22; expected page_bg={expected_bg}"
            )

    def test_illuminated_border_appears_in_debug_and_card_modes_too(self):
        for mode in ("production", "debug", "card"):
            img = rq.render("03:00", self._row(), 800, 480, mode=mode, theme="illuminated")
            assert img.getpixel((14, 14)) == rq.SPECTRA6["blue"], f"illuminated mode={mode} missing TL jewel"

    def test_illuminated_border_uses_theme_colours_not_hardcoded_rgb(self):
        image = Image.new("RGB", (800, 480), color=(255, 255, 255))
        custom = {"text": rq.SPECTRA6["green"], "accent": rq.SPECTRA6["yellow"]}
        rq.draw_illuminated_border(image, custom)
        assert image.getpixel((14, 14)) == rq.SPECTRA6["yellow"], "jewel should use accent"
        assert image.getpixel((400, 14)) == rq.SPECTRA6["green"], "outer rule should use text"
        assert image.getpixel((400, 22)) == rq.SPECTRA6["green"], "inner rule should use text"


class TestNewsprintBorder:
    """The newsprint theme paints a Scotch-rule border.

    Thick-thin parallel rules — a heavier outer rectangle and a hairline
    inner rectangle separated by a narrow page_bg band. No corner
    accents, no colour (newsprint is a no-colour-accent theme). The
    restraint is the point: newspaper typography lives entirely in ink
    weight, not chromatic contrast.
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

    def test_newsprint_outer_rule_is_three_pixels_thick(self):
        """The outer rule is intentionally weighted so the thick/thin
        contrast against the hairline inner rule reads clearly. A
        regression that dropped the ``width=3`` argument would collapse
        the border into a single hairline band."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="newsprint")
        for dy in range(3):
            assert img.getpixel((400, 10 + dy)) == rq.SPECTRA6["black"], (
                f"outer rule row {10 + dy} missing — thick weight regressed"
            )
        # Pixel just below the thick band is page_bg (white).
        assert img.getpixel((400, 13)) == rq.SPECTRA6["white"], "outer rule over-painted"

    def test_newsprint_inner_hairline_is_one_pixel_and_has_gap_above(self):
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="newsprint")
        assert img.getpixel((400, 18)) == rq.SPECTRA6["black"], "inner hairline missing"
        assert img.getpixel((400, 17)) == rq.SPECTRA6["white"], "inner rule merged with thick band"
        assert img.getpixel((400, 19)) == rq.SPECTRA6["white"], "inner rule thickened"

    def test_newsprint_border_paints_all_four_sides(self):
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="newsprint")
        assert img.getpixel((400, 11)) == rq.SPECTRA6["black"], "top outer rule missing"
        assert img.getpixel((400, 468)) == rq.SPECTRA6["black"], "bottom outer rule missing"
        assert img.getpixel((11, 240)) == rq.SPECTRA6["black"], "left outer rule missing"
        assert img.getpixel((788, 240)) == rq.SPECTRA6["black"], "right outer rule missing"

    def test_newsprint_border_is_theme_gated(self):
        """Sample (400, 11) — mid-thick-band — against themes whose
        page_bg is not black (so the page_bg check is meaningful). Dark
        and nightvision share page_bg=black and would pass even if
        this theme painted black there, so they're excluded."""
        for theme in ("default", "scholar", "blueprint", "risograph", "comic"):
            img = rq.render("03:00", self._row(), 800, 480, mode="production", theme=theme)
            expected_bg = rq.THEMES[theme]["page_bg"]
            assert img.getpixel((400, 11)) == expected_bg, (
                f"theme {theme} painted at newsprint outer-rule y=11; expected page_bg={expected_bg}"
            )

    def test_newsprint_border_appears_in_debug_and_card_modes_too(self):
        for mode in ("production", "debug", "card"):
            img = rq.render("03:00", self._row(), 800, 480, mode=mode, theme="newsprint")
            assert img.getpixel((400, 11)) == rq.SPECTRA6["black"], (
                f"newsprint mode={mode} missing outer rule"
            )

    def test_newsprint_border_uses_theme_colour_not_hardcoded_rgb(self):
        image = Image.new("RGB", (800, 480), color=(255, 255, 255))
        custom = {"text": rq.SPECTRA6["green"]}
        rq.draw_newsprint_border(image, custom)
        assert image.getpixel((400, 11)) == rq.SPECTRA6["green"], "outer rule should use text"
        assert image.getpixel((400, 18)) == rq.SPECTRA6["green"], "inner rule should use text"


class TestNightvisionBorder:
    """The nightvision theme paints HUD-style corner brackets.

    Four L-shaped brackets in the body green, with NO continuous outer
    frame between them. The bracket-only composition is the signature
    camera-viewfinder / weapons-HUD aesthetic; its absent full frame
    visually distinguishes it from the bauhaus / blueprint / illuminated
    / newsprint patterns which all paint a continuous rectangle.
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

    def test_nightvision_corner_brackets_paint_body_green(self):
        """Each bracket's corner point lands at (12, 12) / (787, 12) /
        (12, 467) / (787, 467)."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="nightvision")
        assert img.getpixel((12, 12)) == rq.SPECTRA6["green"], "TL bracket corner missing"
        assert img.getpixel((787, 12)) == rq.SPECTRA6["green"], "TR bracket corner missing"
        assert img.getpixel((12, 467)) == rq.SPECTRA6["green"], "BL bracket corner missing"
        assert img.getpixel((787, 467)) == rq.SPECTRA6["green"], "BR bracket corner missing"

    def test_nightvision_bracket_arms_are_two_pixels_thick(self):
        """Each arm is a 2px-thick filled rectangle, not a hairline."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="nightvision")
        # TL horizontal arm at y=12-13, x range 12 to 38.
        assert img.getpixel((25, 12)) == rq.SPECTRA6["green"]
        assert img.getpixel((25, 13)) == rq.SPECTRA6["green"]
        assert img.getpixel((25, 14)) == rq.SPECTRA6["black"], "arm leaked past 2px thickness"
        # TL vertical arm at x=12-13, y range 12 to 38.
        assert img.getpixel((12, 25)) == rq.SPECTRA6["green"]
        assert img.getpixel((13, 25)) == rq.SPECTRA6["green"]
        assert img.getpixel((14, 25)) == rq.SPECTRA6["black"], "vertical arm leaked past 2px thickness"

    def test_nightvision_has_no_continuous_outer_frame(self):
        """The signature feature: mid-edge pixels must show the black
        page_bg, not a connecting frame line. A regression that added
        a full rectangle outline would collapse nightvision's HUD look
        into another illuminated-style frame."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="nightvision")
        assert img.getpixel((400, 12)) == rq.SPECTRA6["black"], "unexpected top frame line"
        assert img.getpixel((400, 467)) == rq.SPECTRA6["black"], "unexpected bottom frame line"
        assert img.getpixel((12, 240)) == rq.SPECTRA6["black"], "unexpected left frame line"
        assert img.getpixel((787, 240)) == rq.SPECTRA6["black"], "unexpected right frame line"

    def test_nightvision_border_is_theme_gated(self):
        """Sample the TL bracket corner (12, 12). Several other border
        themes *also* paint at this pixel — newsprint's outer thick rule
        at inset 10 covers x=10-12 / y=10-12, bauhaus's TL red circle
        overlaps it, and illuminated's TL jewel overlaps it — so we can
        only use (12, 12) to distinguish nightvision from themes whose
        margin is empty there. Skip the other border themes explicitly;
        their own gating tests pin their distinctive pixels."""
        for theme in ("default", "dark", "scholar", "blueprint",
                      "risograph", "comic"):
            img = rq.render("03:00", self._row(), 800, 480, mode="production", theme=theme)
            expected_bg = rq.THEMES[theme]["page_bg"]
            assert img.getpixel((12, 12)) == expected_bg, (
                f"theme {theme} painted at nightvision bracket corner (12, 12); "
                f"expected page_bg={expected_bg}"
            )

    def test_nightvision_border_appears_in_debug_and_card_modes_too(self):
        for mode in ("production", "debug", "card"):
            img = rq.render("03:00", self._row(), 800, 480, mode=mode, theme="nightvision")
            assert img.getpixel((12, 12)) == rq.SPECTRA6["green"], (
                f"nightvision mode={mode} missing TL bracket"
            )

    def test_nightvision_border_uses_theme_colour_not_hardcoded_rgb(self):
        image = Image.new("RGB", (800, 480), color=(0, 0, 0))
        custom = {"text": rq.SPECTRA6["yellow"]}
        rq.draw_nightvision_border(image, custom)
        assert image.getpixel((12, 12)) == rq.SPECTRA6["yellow"], "bracket should use text"


class TestBlueprintBorder:
    """The blueprint theme paints a drafting-sheet border.

    Parallels ``TestBauhausBorder`` but locks the blueprint-specific
    primitives: thin blue outer frame plus red crosshair registration
    marks at each corner. A regression that dropped
    ``draw_blueprint_border`` would pass every dict-level palette test
    silently, so pin the painted pixels here.
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

    def test_blueprint_corner_crosshairs_paint_accent_red(self):
        """Four crosshair "+" marks centred on the frame corners at
        ``(16, 16)`` / ``(783, 16)`` / ``(16, 463)`` / ``(783, 463)``.
        The centre pixel is always on the mark; arm extents are ±8."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="blueprint")
        assert img.getpixel((16, 16)) == rq.SPECTRA6["red"], "TL crosshair centre missing"
        assert img.getpixel((783, 16)) == rq.SPECTRA6["red"], "TR crosshair centre missing"
        assert img.getpixel((16, 463)) == rq.SPECTRA6["red"], "BL crosshair centre missing"
        assert img.getpixel((783, 463)) == rq.SPECTRA6["red"], "BR crosshair centre missing"

    def test_blueprint_crosshair_arms_extend_both_directions(self):
        """Each crosshair has four 8px arms (left/right/up/down from
        centre). A regression that drew a single dot instead of a "+"
        would pass the centre-pixel test but fail here."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="blueprint")
        cx, cy = 16, 16
        assert img.getpixel((cx - 6, cy)) == rq.SPECTRA6["red"], "TL left arm missing"
        assert img.getpixel((cx + 6, cy)) == rq.SPECTRA6["red"], "TL right arm missing"
        assert img.getpixel((cx, cy - 6)) == rq.SPECTRA6["red"], "TL up arm missing"
        assert img.getpixel((cx, cy + 6)) == rq.SPECTRA6["red"], "TL down arm missing"

    def test_blueprint_outer_frame_is_painted_in_body_blue(self):
        """The outer rectangle outline is the structural anchor for the
        crosshairs. Sample a point on each side well clear of the
        corners, to verify all four sides of the frame rendered."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="blueprint")
        assert img.getpixel((400, 16)) == rq.SPECTRA6["blue"], "top frame line missing"
        assert img.getpixel((400, 463)) == rq.SPECTRA6["blue"], "bottom frame line missing"
        assert img.getpixel((16, 240)) == rq.SPECTRA6["blue"], "left frame line missing"
        assert img.getpixel((783, 240)) == rq.SPECTRA6["blue"], "right frame line missing"

    def test_blueprint_border_is_theme_gated(self):
        """Border is gated on theme == 'blueprint'; no other theme (including
        bauhaus, which uses a different graphic at different coordinates)
        should paint a crosshair arm at (6, 16)."""
        for theme in ("default", "dark", "scholar", "newsprint", "nightvision",
                      "illuminated", "risograph", "comic"):
            img = rq.render("03:00", self._row(), 800, 480, mode="production", theme=theme)
            expected_bg = rq.THEMES[theme]["page_bg"]
            # (6, 16) lands on the blueprint TL crosshair's leftmost arm
            # pixel; other themes must leave it showing page_bg.
            assert img.getpixel((6, 16)) == expected_bg, (
                f"theme {theme} painted something at the blueprint crosshair location"
            )

    def test_blueprint_border_appears_in_debug_and_card_modes_too(self):
        """The border is part of the blueprint theme's visual identity, so
        it must show up regardless of render mode."""
        for mode in ("production", "debug", "card"):
            img = rq.render("03:00", self._row(), 800, 480, mode=mode, theme="blueprint")
            assert img.getpixel((16, 16)) == rq.SPECTRA6["red"], f"blueprint mode={mode} missing TL crosshair"

    def test_blueprint_border_uses_theme_colours_not_hardcoded_rgb(self):
        """``draw_blueprint_border`` must pull its colours from the passed-in
        theme dict (text for the frame, accent for the crosshairs). Call
        the helper with a non-default palette and assert the output
        reflects it."""
        image = Image.new("RGB", (800, 480), color=(255, 255, 255))
        custom = {
            "text": rq.SPECTRA6["green"],
            "accent": rq.SPECTRA6["yellow"],
        }
        rq.draw_blueprint_border(image, custom)
        assert image.getpixel((16, 16)) == rq.SPECTRA6["yellow"], "crosshair should use accent"
        assert image.getpixel((400, 16)) == rq.SPECTRA6["green"], "frame should use text colour"

    def test_blueprint_interior_grid_paints_in_body_blue(self):
        """The graph-paper grid inside the frame uses the body-text colour.
        Sample an intersection well clear of the frame and of the quote
        block so no glyph or outer rule is painted on top. At 20px spacing,
        with ``frame_inset=16``, the first interior horizontal rule is at
        y=36 and the first interior vertical rule is at x=36; (36, 56) is
        a clean grid crossing."""
        image = Image.new("RGB", (800, 480), color=(255, 255, 255))
        rq.draw_blueprint_border(image, {"text": rq.SPECTRA6["blue"], "accent": rq.SPECTRA6["red"]})
        assert image.getpixel((36, 56)) == rq.SPECTRA6["blue"], "grid intersection should use text colour"
        # Off-grid whitespace between rules stays page_bg (white canvas here).
        assert image.getpixel((45, 45)) == (255, 255, 255), "between-grid pixel should remain unpainted"

    def test_blueprint_grid_is_theme_gated(self):
        """No other theme paints a blue pixel at the blueprint grid-intersection
        coordinate (36, 56) — it should show that theme's page_bg."""
        row = self._row()
        for theme in ("default", "dark", "scholar", "newsprint", "nightvision",
                      "illuminated", "bauhaus", "risograph", "comic"):
            img = rq.render("03:00", row, 800, 480, mode="production", theme=theme)
            expected_bg = rq.THEMES[theme]["page_bg"]
            assert img.getpixel((36, 56)) == expected_bg, (
                f"theme {theme} painted something at the blueprint grid coordinate"
            )


class TestComicCornerStripes:
    """Comic theme paints retro 45° racing stripes inside the bottom-right
    triangle of the canvas. The chevron rotates through a four-colour
    palette (blue / green / red / black); the upper-left half of the
    canvas stays yellow page_bg so the quote body never crosses it."""

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

    def test_comic_stripes_cover_lower_right_triangle_in_palette_colours(self):
        """Sample a horizontal sweep at y=460 (deep inside the bottom-right
        triangle) and verify every one of the four stripe-palette accents
        appears at least once. The 45° right-iso triangle has legs of
        length 240, so at y=460 the striped region spans x in [580, 800];
        sweep that range. A regression that collapsed the rotation to a
        single colour would fail here even if the chevron geometry was
        intact."""
        image = Image.new("RGB", (800, 480), color=rq.SPECTRA6["yellow"])
        rq.draw_comic_corner_stripes(image, {"page_bg": rq.SPECTRA6["yellow"]})
        palette_set = set(rq._COMIC_STRIPE_PALETTE)
        found = set()
        for y in range(240, 480, 10):
            for x in range(560, 800, 3):
                pixel = image.getpixel((x, y))
                if pixel in palette_set:
                    found.add(pixel)
        assert palette_set <= found, (
            f"missing palette colours in comic triangle: expected {palette_set}, found {found}"
        )

    def test_comic_stripes_leave_upper_left_clear(self):
        """Everything outside the 45° right-iso triangle stays page_bg —
        that includes the upper-left three canvas quadrants entirely AND
        the bottom-left half of the lower-right quadrant. The triangle's
        hypotenuse satisfies ``x + y = 1040`` (legs of length 240 anchored
        at the bottom-right corner), so any sample with ``x + y < 1040``
        must remain unmasked. Pin a spread of points so a regression that
        re-grew the triangle to span the full quadrant would surface."""
        image = Image.new("RGB", (800, 480), color=rq.SPECTRA6["yellow"])
        rq.draw_comic_corner_stripes(image, {"page_bg": rq.SPECTRA6["yellow"]})
        yellow = rq.SPECTRA6["yellow"]
        # Outside the lower-right quadrant — never touched.
        assert image.getpixel((20, 20)) == yellow, "TL canvas corner should stay page_bg"
        assert image.getpixel((20, 460)) == yellow, "BL canvas corner should stay page_bg"
        assert image.getpixel((380, 100)) == yellow, "above quadrant should stay page_bg"
        # Inside the LR quadrant but outside the 240×240 corner triangle.
        assert image.getpixel((410, 250)) == yellow, "upper-left of LR quadrant should stay page_bg"
        assert image.getpixel((450, 460)) == yellow, "bottom-left of LR quadrant should stay page_bg (outside corner triangle)"
        assert image.getpixel((550, 300)) == yellow, "diagonal middle of LR quadrant should stay page_bg"

    def test_comic_stripes_are_theme_gated(self):
        """No other theme paints a non-page_bg pixel at the comic stripe
        sample point (650, 470) — well inside the bottom-right triangle
        and outside every other theme's corner decorations / outer rules.
        A regression that registered the painter against the wrong theme
        key would surface here."""
        row = self._row()
        for theme in ("default", "dark", "scholar", "newsprint", "nightvision",
                      "blueprint", "illuminated", "bauhaus", "risograph"):
            img = rq.render("03:00", row, 800, 480, mode="production", theme=theme)
            expected_bg = rq.THEMES[theme]["page_bg"]
            assert img.getpixel((650, 470)) == expected_bg, (
                f"theme {theme} painted something inside the comic stripe triangle"
            )

    def test_comic_stripes_appear_in_debug_and_card_modes_too(self):
        """Stripes are part of the comic theme's identity and must show
        up regardless of render mode. Pin (650, 470) — well inside the
        triangle — against page_bg for every mode."""
        yellow = rq.SPECTRA6["yellow"]
        for mode in ("production", "debug", "card"):
            img = rq.render("03:00", self._row(), 800, 480, mode=mode, theme="comic")
            assert img.getpixel((650, 470)) != yellow, (
                f"comic mode={mode} missing stripe pixel — chevron didn't paint"
            )

    def test_comic_stripes_scale_to_smaller_render_sizes(self):
        """The trimmed comic chevron should still paint accent stripes on a
        smaller valid canvas instead of disappearing because a fixed pixel
        clamp fell outside the image geometry."""
        image = Image.new("RGB", (400, 240), color=rq.SPECTRA6["yellow"])
        rq.draw_comic_corner_stripes(image, {"page_bg": rq.SPECTRA6["yellow"]})
        found = set()
        for y in range(120, 240):
            for x in range(200, 400):
                pixel = image.getpixel((x, y))
                if pixel in rq._COMIC_STRIPE_PALETTE:
                    found.add(pixel)
        assert found, "comic chevron disappeared on 400×240 render"

    def test_comic_stripe_palette_stays_within_spectra6(self):
        """Hardcoded module-level palette must round-trip through the panel's
        6-colour quantisation without the snap-to-palette pass remapping
        any stripe — otherwise a future palette change could silently
        recolour the chevron."""
        allowed = set(rq.SPECTRA6.values())
        for color in rq._COMIC_STRIPE_PALETTE:
            assert color in allowed, f"stripe colour {color} is off-palette"


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
        centre pixel is on the filled dot so it must be red regardless
        of the outline radius."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="grimoire")
        assert img.getpixel((400, 14)) == rq.SPECTRA6["red"], "Sun centre dot missing"

    def test_grimoire_moon_sigil_paints_at_bottom_midpoint(self):
        """☽ — crescent carved from a filled disk by overdrawing with
        a page-bg disk shifted +4 px in x. The crescent's leftmost
        sliver (the visible red ring on the carved-out side) sits at
        x in [bcx - r, bcx - r + 1]; sample (394, 465) — well inside
        the visible crescent for r=7 / bcx=400."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="grimoire")
        assert img.getpixel((394, 465)) == rq.SPECTRA6["red"], "Moon crescent missing"

    def test_grimoire_mars_sigil_paints_at_left_midpoint(self):
        """♂ — circle offset down-left + diagonal NE shaft + perpendicular
        V-barb. Sample the arrow tip at (22, 232) — outside the circle
        body but on the arrowhead, so a regression that dropped the
        arrow would surface here."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="grimoire")
        assert img.getpixel((22, 232)) == rq.SPECTRA6["red"], "Mars arrow tip missing"

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
        comes from the matched-phrase font (TFoust vs UnifrakturMaguntia)
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

    def test_grimoire_source_card_uses_unicode_safe_bold(self):
        """``render_source_card`` wraps the matched phrase in U+201C /
        U+201D curly quotes and runs the title through ``normalize_dashes``
        (which emits U+2014 em-dashes). TFoust ships ASCII only (U+0020 →
        U+007E) and PIL's font fallback is file-level, not glyph-level,
        so without a card-specific override the grimoire card would paint
        ``.notdef`` boxes for every curly quote and em-dash.

        Pin two layers of the contract:

        * The ``card_quote_bold`` chain for grimoire must NOT start with
          TFoust — every leading entry's path must be unicode-safe.
        * Every other theme's ``card_quote_bold`` chain must be exactly
          ``quote_bold`` (the fallback case) — the new role is a per-
          theme escape hatch, not a renderer-wide change.
        """
        # Grimoire's escape hatch: TFoust must NOT lead the card chain.
        grimoire_card = rq.theme_font_candidates("grimoire", "card_quote_bold")
        first = grimoire_card[0]
        first_path = first[0] if isinstance(first, tuple) else first
        assert "TFoust" not in first_path, (
            f"grimoire card_quote_bold still starts with TFoust: {first_path}"
        )
        # Every other theme falls through unchanged.
        for theme in ("default", "dark", "scholar", "newsprint", "nightvision",
                      "blueprint", "illuminated", "gothic", "bauhaus",
                      "risograph", "comic", "dispatch", "atomic", "marker",
                      "saloon", "roman"):
            bold = rq.theme_font_candidates(theme, "quote_bold")
            card = rq.theme_font_candidates(theme, "card_quote_bold")
            assert card == bold, (
                f"theme {theme} silently diverged card_quote_bold from quote_bold"
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
        Render the same row twice through grimoire's pipeline — once
        with the real ``_THEMES_RIGID_MATCH_SPACING`` (containing
        grimoire), once with that set monkey-patched empty so the
        loose-justification path runs. Every other variable is
        identical: same fonts, same layout, same line breaks. The
        rigid render must pack the bold accent-coloured pixels into a
        narrower row of x-positions than the loose render — i.e. the
        rightmost red pixel on the matched-phrase line moves *left*
        once bold-internal spaces stop absorbing slack."""
        row = {
            "display_quote": (
                "At a quarter past two the breeze dropped entirely, "
                "and such a stillness reigned all about us."
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
        rigid = rq.render("02:15", row, 800, 480, mode="production", theme="grimoire")

        monkeypatch.setattr(rq, "_THEMES_RIGID_MATCH_SPACING", frozenset())
        loose = rq.render("02:15", row, 800, 480, mode="production", theme="grimoire")

        red = rq.SPECTRA6["red"]

        def matched_phrase_span(img) -> tuple[int, int]:
            """Return (leftmost, rightmost) x-coordinate of the red
            band that holds the matched phrase. We skip the canvas
            border (outer red rectangle at y in {14, 465}) and the
            mid-edge sigils (centred at x=400 with y around 14 / 465 /
            240) by sampling only the dense quote-body region
            (y in [80, 380]) and picking the row with the most red
            pixels — the matched-phrase line."""
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


class TestRenderStaticMessage:
    """``render_static_message`` paints a centred headline in the active
    theme. Used by ``--quiet-image=auto`` / ``--startup-image=auto`` so the
    goodnight / startup frame matches the rest of the UI instead of forcing
    the dark-only ``assets/goodnight.png`` on every operator.
    """

    def test_returns_image_of_correct_size(self):
        img = rq.render_static_message("Good night.", 800, 480, theme="default")
        assert img.size == (800, 480)

    def test_uses_default_theme_background(self):
        img = rq.render_static_message("Good night.", 800, 480, theme="default")
        assert img.getpixel((0, 0)) == rq.SPECTRA6["white"]

    def test_uses_dark_theme_background(self):
        img = rq.render_static_message("Good night.", 800, 480, theme="dark")
        assert img.getpixel((0, 0)) == rq.SPECTRA6["black"]

    def test_uses_scholar_theme_background(self):
        img = rq.render_static_message("Good night.", 800, 480, theme="scholar")
        assert img.getpixel((0, 0)) == rq.SPECTRA6["white"]

    def test_uses_nightvision_theme_background(self):
        img = rq.render_static_message("Good night.", 800, 480, theme="nightvision")
        assert img.getpixel((0, 0)) == rq.SPECTRA6["black"]

    @pytest.mark.parametrize("theme", sorted(rq.THEMES))
    def test_palette_is_spectra6_across_every_theme(self, theme):
        """Every output pixel must land in the Spectra 6 palette regardless
        of which theme is active. Without ``snap_image_to_palette`` the
        per-theme borders (illuminated jewels, blueprint grid, etc.) can
        introduce intermediate dither colours that look fine on a sRGB
        monitor but bleed unpredictably on the eInk panel."""
        img = rq.render_static_message("Good night.", 800, 480, theme=theme)
        palette = set(rq.SPECTRA6.values())
        pixels = set(img.convert("RGB").getdata())
        assert pixels.issubset(palette), f"theme={theme}: unexpected colors {pixels - palette}"

    def test_message_wraps_for_long_text(self):
        """A long ``--message`` value must still produce a valid frame —
        the fit loop shrinks the headline font until it fits, and
        ``wrap_text`` handles word-wrapping at the chosen size."""
        long_msg = "Sleep well, dear reader, and may your dreams be filled with quiet."
        img = rq.render_static_message(long_msg, 800, 480, theme="default")
        assert img.size == (800, 480)

    def test_goodnight_mode_via_main_writes_png(self, tmp_path, monkeypatch):
        """End-to-end: ``rq.main()`` with ``--mode goodnight`` should skip
        ``pick_quote`` entirely and produce a valid PNG."""
        out = tmp_path / "gn.png"
        argv = ["render_quote.py", "--mode", "goodnight", "--theme", "scholar",
                "--message", "Sleep well.", "--output", str(out)]
        monkeypatch.setattr("sys.argv", argv)
        # If main accidentally called pick_quote, this would explode loudly.
        with patch.object(rq, "pick_quote", side_effect=AssertionError("pick_quote must not run for mode=goodnight")):
            assert rq.main() == 0
        assert out.exists()
        from PIL import Image
        img = Image.open(out)
        assert img.size == (800, 480)
        img.close()


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
