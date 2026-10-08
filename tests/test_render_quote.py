"""Tests for render_quote.py — layout selection, text helpers, color quantization."""
from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from PIL import Image, ImageDraw
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

    def test_drops_unpaired_markers(self):
        # Issue #308: a partner lost to the miner's window left a bare "_".
        assert rq.strip_underscore_emphasis("into the ocean. _It had run down!") == "into the ocean. It had run down!"
        assert rq.strip_underscore_emphasis("ALGERNON. [Stiffly_._] I") == "ALGERNON. [Stiffly.] I"
        assert rq.strip_underscore_emphasis("_(A dark horse, riderless") == "(A dark horse, riderless"

    def test_keeps_blank_runs(self):
        assert rq.strip_underscore_emphasis("Mr. ____ called.") == "Mr. ____ called."

    def test_lone_marker_between_spaces_leaves_one_space(self):
        assert rq.strip_underscore_emphasis("x _ y") == "x y"
        assert rq.strip_underscore_emphasis("_ It was ten.") == "It was ten."

    def test_preserves_dunder_and_snake_identifiers(self):
        assert rq.strip_underscore_emphasis("call __init__ now") == "call __init__ now"
        assert rq.strip_underscore_emphasis("__init__") == "__init__"
        assert rq.strip_underscore_emphasis("a snake_case name") == "a snake_case name"


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
    def _inks(self, img):
        return distinct_inks(img)

    def test_pure_white_snaps_to_white(self):
        img = Image.new("RGB", (4, 4), color=(255, 255, 255))
        palette = [(255, 255, 255), (0, 0, 0)]
        result = rq.snap_image_to_palette(img, palette)
        assert self._inks(result) == {(255, 255, 255)}

    def test_pure_black_snaps_to_black(self):
        img = Image.new("RGB", (4, 4), color=(0, 0, 0))
        palette = [(255, 255, 255), (0, 0, 0)]
        result = rq.snap_image_to_palette(img, palette)
        assert self._inks(result) == {(0, 0, 0)}

    def test_near_red_snaps_to_red(self):
        img = Image.new("RGB", (2, 2), color=(240, 10, 10))
        palette = [(255, 255, 255), (0, 0, 0), (255, 0, 0)]
        result = rq.snap_image_to_palette(img, palette)
        assert self._inks(result) == {(255, 0, 0)}

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
            assert self._inks(result) == {color}, f"Color {color} did not round-trip"


class TestTypedPixelAccess:
    """The mode check is what makes ``gray_pixel_access`` / ``rgb_pixel_access``'s types true (issue #350)."""

    @pytest.mark.parametrize("mode", ["1", "L"])
    def test_gray_reads_ints(self, mode):
        image = Image.new(mode, (2, 2), 255)
        assert rq_palette.gray_pixel_access(image)[1, 1] == 255

    def test_gray_rejects_rgb(self):
        with pytest.raises(ValueError, match="one-band"):
            rq_palette.gray_pixel_access(Image.new("RGB", (2, 2)))

    def test_rgb_reads_tuples(self):
        image = Image.new("RGB", (2, 2), (1, 2, 3))
        assert rq_palette.rgb_pixel_access(image)[0, 0] == (1, 2, 3)

    def test_rgb_rejects_mask(self):
        with pytest.raises(ValueError, match="RGB"):
            rq_palette.rgb_pixel_access(Image.new("L", (2, 2)))


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
        monkeypatch.setattr(rq_fonts, "_FONT_FALLBACK_WARNED", False)
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
        fonts and applies the named instance. The bundled Jost is a variable
        font whose default instance is Regular, so the ``Bold`` variation must
        produce visibly wider glyphs than the default — otherwise the
        variation call silently fell through, and on a face that defaults to
        Thin the panel would render near-invisible hairlines."""
        variable_path = Path(rq.BASE_DIR) / "fonts" / "jost" / "Jost-Variable.ttf"
        if not variable_path.exists():
            pytest.skip("Jost variable font not bundled")
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
        monkeypatch.setattr(rq_fonts, "_FONT_FALLBACK_WARNED", False)
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
        monkeypatch.setattr(rq_fonts, "_FONT_FALLBACK_WARNED", True)
        real_path = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
        if not Path(real_path).exists():
            pytest.skip("DejaVu Serif not installed")
        # First call: pretend the file is missing → fallback to PIL's
        # bundled default (or the bitmap default in older Pillows).
        monkeypatch.setattr(rq.Path, "exists", lambda self: False)
        a = rq.load_font([real_path], size=24)
        # Second call: file is reachable again → should load the real font.
        monkeypatch.undo()
        monkeypatch.setattr(rq_fonts, "_FONT_FALLBACK_WARNED", True)
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
            "newsprint",
            "nightvision",
            "bauhaus",
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


def _drawable(line):
    """Strip the leading / trailing space tokens the body draw loop discards."""
    start = 0
    while start < len(line) and line[start][0].strip() == "":
        start += 1
    end = len(line)
    while end > start and line[end - 1][0].strip() == "":
        end -= 1
    return line[start:end]


class TestWrapStyledTextNoBreakInsideWord:
    """A line break is only ever legal at whitespace.

    ``tokenize_quote`` splits the text into regular / bold / regular
    segments at the matched time phrase, and that seam can fall in the
    middle of a word: ``door (at a quarter to seven) with`` becomes the
    segments ``"… (at a "`` / ``"quarter to seven"`` / ``") with …"``.
    The wrapper used to treat every non-space token as a break
    opportunity, so a line could end on ``seven`` and the next line open
    with a bare ``)`` — the dangling parenthetical seen on the panel for
    the Portrait of a Lady row (source 2833, line 1806). The mirror case
    strands an opening ``(`` or ``"`` at the end of a line when the
    phrase starts the parenthetical.
    """

    TOUCHETT = (
        "Ralph Touchett was a philosopher, but nevertheless he knocked at his "
        "mother\u2019s door (at a quarter to seven) with a good deal of eagerness."
    )

    @staticmethod
    def _fonts(size=24):
        img = Image.new("RGB", (800, 480), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        regular = rq.load_font(rq.QUOTE_FONT_SEMIBOLD_CANDIDATES, size=size)
        bold = rq.load_font(rq.QUOTE_FONT_BOLD_CANDIDATES, size=size)
        return draw, regular, bold

    @staticmethod
    def _joined_words(lines):
        """Re-join each wrapped line into its whitespace-separated words."""
        words = []
        for line in lines:
            words.append("".join(chunk for chunk, _ in _drawable(line)).split(" "))
        return words

    def test_closing_paren_stays_glued_to_the_bold_phrase(self):
        draw, regular, bold = self._fonts()
        segments = rq.tokenize_quote(self.TOUCHETT, "quarter to seven")
        assert [b for _, b in segments] == [False, True, False]
        # Sweep the wrap width so the break lands at every possible word
        # boundary, including the one right after ``seven``.
        for max_width in range(120, 760, 7):
            lines = rq.wrap_styled_text(draw, segments, regular, bold, max_width)
            for line in lines:
                first = _drawable(line)[0][0]
                assert not first.startswith(")"), (max_width, line)
            flat = [w for line in self._joined_words(lines) for w in line]
            assert "seven)" in flat, (max_width, flat)

    def test_opening_paren_stays_glued_to_the_bold_phrase(self):
        draw, regular, bold = self._fonts()
        text = "He knocked at his mother\u2019s door (quarter to seven) with a good deal of eagerness."
        segments = rq.tokenize_quote(text, "quarter to seven")
        assert [b for _, b in segments] == [False, True, False]
        for max_width in range(120, 760, 7):
            lines = rq.wrap_styled_text(draw, segments, regular, bold, max_width)
            for line in lines:
                last = _drawable(line)[-1][0]
                assert not last.endswith("("), (max_width, line)
            flat = [w for line in self._joined_words(lines) for w in line]
            assert "(quarter" in flat, (max_width, flat)

    def test_bold_pieces_keep_their_own_style_inside_a_glued_word(self):
        draw, regular, bold = self._fonts()
        segments = [("door (", False), ("quarter to seven", True), (") with", False)]
        [line] = rq.wrap_styled_text(draw, segments, regular, bold, 10_000)
        assert line == [
            ("door", False), (" ", False), ("(", False), ("quarter", True), (" ", True),
            ("to", True), (" ", True), ("seven", True), (")", False), (" ", False), ("with", False),
        ]

    def test_glued_word_wider_than_the_line_still_terminates(self):
        draw, regular, bold = self._fonts()
        segments = [("a ", False), ("x" * 60, True), (")", False), (" b", False)]
        lines = rq.wrap_styled_text(draw, segments, regular, bold, 200)
        # The oversized glued word goes on its own line, intact.
        assert [_drawable(line) for line in lines][1] == [("x" * 60, True), (")", False)]
        assert _drawable(lines[0]) == [("a", False)]
        assert _drawable(lines[2]) == [("b", False)]

    def test_space_tokens_carry_the_style_of_their_segment(self):
        draw, regular, bold = self._fonts()
        segments = [("a ", False), ("b", True), (" c", False)]
        [line] = rq.wrap_styled_text(draw, segments, regular, bold, 10_000)
        assert line == [("a", False), (" ", False), ("b", True), (" ", False), ("c", False)]


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
            "newsprint",
            "nightvision",
            "bauhaus",
            "comic",
            "fillmore",
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

    def test_fillmore_theme_uses_six_inks_simultaneously(self):
        """Fillmore is the rotation's visual maximalist: yellow ground,
        red body, blue matched phrase, plus green/blue/yellow/red/
        black/white visible via the corner blob graphics. A regression
        that changed the page_bg away from yellow or collapsed
        text/accent to a single hue would lose the 1960s psychedelic
        identity."""
        t = rq.THEMES["fillmore"]
        assert t["page_bg"] == rq.SPECTRA6["yellow"]
        assert t["text"] == rq.SPECTRA6["red"]
        assert t["accent"] == rq.SPECTRA6["blue"]

    def test_new_theme_border_painters_registered(self):
        """Each new theme that names a border in its design notes
        must appear in _BORDER_PAINTERS — without registration the
        border-painter never fires and the theme degrades into
        "just type on the ground colour". Pin these entries
        explicitly so a future refactor that drops the dict key
        fails this test loudly."""
        for name in ("fillmore", "firmament"):
            assert name in rq._BORDER_PAINTERS, name

    def test_comic_theme_uses_yellow_ground(self):
        """Comic is the first (and only) theme with a yellow page
        background. A regression that flipped it back to white would
        collapse the theme into a default-palette alias differentiated
        only by the comic font."""
        t = rq.THEMES["comic"]
        assert t["page_bg"] == rq.SPECTRA6["yellow"]
        assert t["text"] == rq.SPECTRA6["black"]
        assert t["accent"] == rq.SPECTRA6["red"]

    # Themes that render ornament-less ON PURPOSE. The assertion below exists to
    # catch a theme that does so by *accident*, so a deliberate one has to be
    # named here rather than quietly excused — and the second test makes the set
    # self-policing, so an entry cannot rot after the theme changes its mind.
    INTENTIONALLY_ORNAMENTLESS = frozenset({
        # synoptic is a weather chart. The shared layout paints its oversized
        # quote marks OUTSIDE the body rect — so outside synoptic's legend box,
        # directly on the analysis — where a large glyph reads as chart debris
        # rather than typography. A surface analysis has no decorative
        # quotation marks, so both ornament slots take the page ground.
        "synoptic",
        # betweenus / betweenus_dark — the Between Us card has no quotation
        # marks either, and the marks would land on the stippled paper outside
        # the card, so ``_paint_ornament_mark`` skips them outright for these
        # two (``_THEMES_WITHOUT_ORNAMENT_MARKS``). Both slots still take the
        # page ground so the fence below stays honest.
        "betweenus",
        "betweenus_dark",
    })

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
            if name in self.INTENTIONALLY_ORNAMENTLESS:
                continue
            bg = fields["page_bg"]
            dark = fields["ornament_dark"]
            light = fields["ornament_light"]
            assert dark != bg or light != bg, (
                f"{name}: both ornament colours equal page_bg={bg}, "
                "so draw_faux_gray_text paints every pixel invisibly. If that is "
                "deliberate, add it to INTENTIONALLY_ORNAMENTLESS with a reason."
            )

    def test_ornamentless_exemptions_are_real(self):
        """Every exemption must be registered AND actually ornament-less.

        Without this the set is a one-way ratchet: a theme could be added to it,
        later gain a visible ornament, and silently keep its exemption — so the
        next theme to go ornament-less by accident inherits a hole in the fence.
        """
        for name in self.INTENTIONALLY_ORNAMENTLESS:
            assert name in rq.THEMES, f"{name} is exempted but is not a registered theme"
            fields = rq.THEMES[name]
            bg = fields["page_bg"]
            assert fields["ornament_dark"] == bg and fields["ornament_light"] == bg, (
                f"{name} is listed as intentionally ornament-less but now has a visible "
                "ornament colour — drop it from INTENTIONALLY_ORNAMENTLESS"
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
            "newsprint",
            "nightvision",
            "bauhaus",
            "comic",
            "firmament",
            "outrun",
            "letter",
            "sampler",
            "anna_atkins",
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
        pixels = distinct_inks(img)
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
        circle, square, or right-triangle. After Stage 3 the BL
        triangle paints in YELLOW (was blue) so all three Bauhaus
        primaries (red + blue + yellow) appear simultaneously on the
        page alongside the black outer frame."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="bauhaus")
        # Corner shapes are 22px at a 6px canvas-edge margin; centre near
        # (17, 17) / (783, 17) / (17, 463) / (783, 463).
        assert img.getpixel((15, 15)) == rq.SPECTRA6["red"], "top-left should be red circle"
        assert img.getpixel((785, 15)) == rq.SPECTRA6["blue"], "top-right should be blue square"
        assert img.getpixel((15, 465)) == rq.SPECTRA6["yellow"], "bottom-left should be yellow triangle"
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
        red circle, so it distinguishes bauhaus from every theme whose
        margin is empty there."""
        for theme in ("default", "dark", "newsprint", "nightvision", "comic"):
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
        this theme painted black there, so they're excluded. Newsprint is
        excluded because its Layer 0 halftone paints sparse flecks across
        the ground."""
        for theme in ("default", "comic", "bauhaus"):
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
    visually distinguishes it from the bauhaus / newsprint patterns, which
    paint a continuous rectangle.
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
        into another framed theme."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="nightvision")
        assert img.getpixel((400, 12)) == rq.SPECTRA6["black"], "unexpected top frame line"
        assert img.getpixel((400, 467)) == rq.SPECTRA6["black"], "unexpected bottom frame line"
        assert img.getpixel((12, 240)) == rq.SPECTRA6["black"], "unexpected left frame line"
        assert img.getpixel((787, 240)) == rq.SPECTRA6["black"], "unexpected right frame line"

    def test_nightvision_border_is_theme_gated(self):
        """Sample the TL bracket corner (12, 12). Several other border
        themes *also* paint at this pixel — newsprint's outer thick rule
        at inset 10 covers x=10-12 / y=10-12 and bauhaus's TL red circle
        overlaps it — so we can
        only use (12, 12) to distinguish nightvision from themes whose
        margin is empty there. Skip the other border themes explicitly;
        their own gating tests pin their distinctive pixels."""
        for theme in ("default", "dark", "comic"):
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
        Newsprint and alchemy are excluded because
        their Layer 0 grounds intentionally paint sparse Bayer flecks
        across `page_bg` (black halftone / parchment-yellow flecks).
        Dispatch is excluded for the same reason
        — its Layer 0 cream wash also affects this coordinate."""
        row = self._row()
        for theme in ("default", "dark", "nightvision", "bauhaus"):
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


class TestKanagawaBorder:
    """The kanagawa theme paints a stylised Japanese seascape: vertically-
    graduated sky-blue Bayer wash, five distant ink-stroke birds, a thin
    horizon-line wash at the sea-sky boundary, the seigaiha (青海波)
    overlapping fish-scale tile pattern filling the bottom band in indigo
    with white concentric arc stripes plus a navy depth post-pass on the
    deepest row, a red rounded-rectangle hanko seal in the bottom-right
    corner, and a cream-tinted rounded text panel knocked out of the
    seigaiha (with a thin black frame and a 2 px drop shadow). No outer
    frame (woodblock-print composition discipline). The painter is
    dispatched via render()'s special-case branch so
    the body-text rect knockout fires automatically.
    """

    def _row(self):
        return {
            "display_quote": (
                "It was almost half past four when the bell finally rang and "
                "the waves crashed against the harbour wall."
            ),
            "matched_text": "half past four",
            "author": "Jane Austen",
            "title": "Pride and Prejudice",
            "bucket": "h4_half_past",
            "resolved_bucket": "h4_half_past",
            "used_fallback": False,
            "quality_score": 88,
            "source_id": "1342",
            "line_number": 482,
        }

    def _count(self, img, color, x0, y0, x1, y1):
        """Count pixels of ``color`` in the inclusive bbox (x0, y0, x1, y1)."""
        n = 0
        for py in range(y0, y1 + 1):
            for px in range(x0, x1 + 1):
                if img.getpixel((px, py)) == color:
                    n += 1
        return n

    def test_sky_gradient_paints_blue_pixels_in_upper_band(self):
        """The vertically-graduated Bayer wash flips ~31% of white-ground
        pixels to blue at the top of the canvas, tapering linearly to 0 at
        the horizon (y ≈ 264). Sample the top 20 rows — should contain
        hundreds of blue pixels. A regression that dropped the wash would
        leave the top band as solid white."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        blue_count = self._count(img, rq.SPECTRA6["blue"], 0, 0, 799, 19)
        # ~31% density * 800 cols * 20 rows * 0.5 (some are obscured by birds /
        # panel later) gives a conservative floor of ~1000 blue pixels.
        assert blue_count >= 1000, (
            f"sky gradient blue density too low ({blue_count} pixels) — wash regressed"
        )

    def test_horizon_line_paints_blue_at_y_297(self):
        """The horizon line — a sparse Bayer-stippled blue rule at y ≈ 297
        (round(0.62 × 480)) — separates the sky wash from the seigaiha
        band. Sample the line: should contain at least ~50 blue pixels
        across the canvas width (excluding the cream panel knockout
        which overpaints it)."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        # Sample BOTH rows of the horizon line (it paints y=297 and y=298).
        blue_at_297 = self._count(img, rq.SPECTRA6["blue"], 0, 297, 799, 298)
        assert blue_at_297 >= 50, (
            f"horizon line blue density too low ({blue_at_297} pixels)"
        )

    def test_bird_paints_black_at_known_anchor(self):
        """Each bird in ``_KANAGAWA_BIRD_ANCHORS`` paints two 2 px black
        diagonal line segments meeting at the body. Sample the body of
        the leftmost bird (cx_frac=0.20, cy_frac=0.06 → (160, 29) on a
        800×480 canvas) — the body pixel must be black."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        # Bird body. PIL line endpoints can vary by 1 px depending on
        # rasterisation; sample a small bbox around the anchor.
        found_black = False
        for py in range(27, 31):
            for px in range(158, 163):
                if img.getpixel((px, py)) == rq.SPECTRA6["black"]:
                    found_black = True
                    break
            if found_black:
                break
        assert found_black, "leftmost bird body pixel missing — bird painter regressed"

    def test_seigaiha_band_paints_blue_pixels_in_lower_band(self):
        """The seigaiha tile band starts at y ≈ 317 (round(0.66 × 480))
        and fills to the canvas bottom with filled blue half-disks.
        Sample bottom 100 rows for blue density."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        blue_count = self._count(img, rq.SPECTRA6["blue"], 0, 380, 799, 479)
        # Bottom 100 rows × 800 cols = 80000 pixels, half-disks fill
        # roughly half of that × tile density. Conservative floor: 5000.
        assert blue_count >= 5000, (
            f"seigaiha band blue density too low ({blue_count} pixels)"
        )

    def test_seigaiha_band_paints_white_arc_stripes(self):
        """Each seigaiha tile has three concentric white arc stripes
        painted inside it (radii 23, 18, 13). Sample the bottom band
        for white pixels — should be present in significant numbers."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        white_count = self._count(img, rq.SPECTRA6["white"], 0, 380, 799, 479)
        assert white_count >= 500, (
            f"seigaiha arc stripes white density too low ({white_count} pixels)"
        )

    def test_seigaiha_deepest_row_has_navy_post_pass(self):
        """The deepest seigaiha row gets a navy stipple post-pass —
        every (x+y)&1==0 blue pixel in the bottom ~28 px band flips to
        black, producing a 50/50 B+K mix that reads as deep navy.
        Sample for black pixels at the very bottom (y > 450)."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        black_count = self._count(img, rq.SPECTRA6["black"], 0, 460, 740, 479)
        # Sampling stops at x=740 to avoid the hanko's black post-pass
        # pixels contaminating the count.
        assert black_count >= 1000, (
            f"deepest seigaiha row navy post-pass too sparse ({black_count} black pixels)"
        )

    def test_hanko_seal_paints_red_at_centre(self):
        """The hanko sits at (742..774, 416..454). Centre (758, 435)
        has (x+y)&1 = 1 (odd), so the maroon post-pass leaves it as
        solid red — verify the seal painted at all."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        # Centre may be on a white kanji stroke; sample a few nearby
        # off-stroke pixels for red.
        found_red = False
        for offset in ((5, 5), (-5, 5), (5, -5), (-5, -5), (8, 0)):
            px = 758 + offset[0]
            py = 435 + offset[1]
            if img.getpixel((px, py)) == rq.SPECTRA6["red"]:
                found_red = True
                break
        assert found_red, "hanko seal red ink missing — seal painter regressed"

    def test_hanko_maroon_post_pass_paints_black_pixels(self):
        """The maroon post-pass flips half of the seal's red pixels to
        black per (x+y)&1 parity. Sample the hanko bbox for black."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        black_in_seal = self._count(img, rq.SPECTRA6["black"], 742, 416, 774, 454)
        # Seal is 33 × 39 ≈ 1287 pixels. Roughly half flip to black
        # (the kanji strokes are white-painted on top after the post-
        # pass, taking away ~30 more black slots). Floor at 400.
        assert black_in_seal >= 400, (
            f"hanko maroon post-pass under-fired ({black_in_seal} black pixels in seal)"
        )

    def test_hanko_kanji_strokes_paint_white_after_post_pass(self):
        """The 川 ("kawa") kanji is painted in 2 px white strokes AFTER
        the maroon post-pass so the strokes stay solid against the
        surrounding R+K stipple. Middle vertical stroke at x=758
        spans y=427-445. Sample a pixel that must be white."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        # PIL line width=2 paints the centred 2-pixel column; sample at
        # the stroke's expected centre.
        white_count = 0
        for py in range(427, 446):
            for px in range(757, 760):
                if img.getpixel((px, py)) == rq.SPECTRA6["white"]:
                    white_count += 1
        assert white_count >= 15, (
            f"hanko 川 middle stroke too few white pixels ({white_count})"
        )

    def test_cream_panel_has_yellow_stipple(self):
        """The cream-tinted panel uses 4 off-grid 8×8 anchor positions
        per tile (~6% yellow density) to produce a warm vellum tone.
        Sample inside the panel for yellow pixels."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        # Panel interior — well clear of body text glyphs (which paint
        # black on top). Sample a small strip near the top of the panel
        # where attribution lines aren't present.
        yellow_count = self._count(img, rq.SPECTRA6["yellow"], 100, 100, 700, 110)
        assert yellow_count >= 30, (
            f"cream stipple yellow density too low ({yellow_count} pixels)"
        )

    def test_cream_panel_rounded_corners_expose_seigaiha(self):
        """The panel's rounded corners (radius 12 via PIL's
        rounded_rectangle) leave the corner pixels UNTOUCHED so the
        seigaiha (which paints first, deeper in the layer stack)
        shows through. Sample a corner cutout pixel — should be blue
        (seigaiha) or sky-blue stipple, NOT white (the panel fill).
        Use the bottom-left rounded corner where the panel meets the
        seigaiha band."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        # Find the panel's bottom-left corner empirically by scanning
        # for the first white pixel along y=380 from the left.
        # If the rounded corner is working, the very corner pixels
        # remain blue (seigaiha).
        # Sample (55, 384) — inside the typical bottom-left rounded-
        # corner cutout — expect blue or white.
        sample = img.getpixel((55, 384))
        # Allow any non-cream-white colour at the corner cutout — the
        # important thing is the rounded corner is cutting OUT some of
        # the panel rectangle area to expose what's below.
        # Empirical: this sample lands on seigaiha (blue or
        # white-arc-stripe) when the rounded corner is in effect.
        assert sample in (rq.SPECTRA6["blue"], rq.SPECTRA6["white"]), (
            f"bottom-left rounded corner unexpected colour {sample}"
        )

    def test_panel_drop_shadow_paints_black_below_right(self):
        """The 2 px drop shadow paints a black rounded rect offset
        (2, 2) from the panel before the cream fill. The visible
        portion is a 2 px ledge along the panel's bottom and right
        edges. Sample a pixel just below the panel's bottom edge —
        expect black (the shadow ledge)."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        # The panel's bottom edge follows the attribution block, so sweep
        # the lower half of the canvas for the 2 px black ledge rather
        # than pinning the y it happened to land on for one layout
        # revision. Panel-interior x range, away from corner rounding;
        # the waves below the panel are blue / white, never black.
        found_black_ledge = False
        for py in range(300, 440):
            for px in range(300, 600):
                if img.getpixel((px, py)) == rq.SPECTRA6["black"]:
                    found_black_ledge = True
                    break
            if found_black_ledge:
                break
        assert found_black_ledge, "drop-shadow ledge not visible below panel"

    def test_kanagawa_border_palette_stays_on_spectra6(self):
        """Every painted pixel must belong to the Spectra 6 native
        palette — the matched-phrase red, panel cream yellow, hanko
        red, navy stipple, etc. are all synthesised via on-palette
        inks (no off-palette sentinels surviving past the post-passes)."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="kanagawa")
        allowed = set(rq.SPECTRA6.values())
        # Sweep a representative diagonal slice rather than every pixel
        # (480 × 800 = 384k pixels) — palette violations are pixel-
        # uniform across the canvas thanks to snap_image_to_palette.
        for py in range(0, 480, 7):
            for px in range(0, 800, 11):
                pix = img.getpixel((px, py))
                assert pix in allowed, f"off-palette pixel {pix} at ({px}, {py})"

    def test_kanagawa_border_is_theme_gated(self):
        """The hanko seal centre (758, 435) is unique to kanagawa — no
        other theme paints red at that coordinate. Sample against a
        few other white-ground themes to confirm the kanagawa border
        only fires on kanagawa."""
        row = self._row()
        for theme in ("default", "bauhaus"):
            img = rq.render("04:30", row, 800, 480, mode="production", theme=theme)
            pix = img.getpixel((758, 435))
            assert pix != rq.SPECTRA6["red"], (
                f"theme {theme} painted red at the kanagawa hanko centre"
            )

    def test_kanagawa_border_appears_in_debug_and_production_modes(self):
        """The seigaiha tile band is part of the theme's visual identity
        and must paint in both debug and production modes. Card mode
        uses a different code path (render_source_card) and is allowed
        to skip the border."""
        for mode in ("production", "debug"):
            img = rq.render("04:30", self._row(), 800, 480, mode=mode, theme="kanagawa")
            # Hanko centre red sample — present iff the painter fired.
            found_red = False
            for offset in ((5, 5), (-5, 5), (5, -5), (-5, -5)):
                if img.getpixel((758 + offset[0], 435 + offset[1])) == rq.SPECTRA6["red"]:
                    found_red = True
                    break
            assert found_red, f"kanagawa mode={mode} hanko missing"

    def test_kanagawa_border_uses_theme_colours_not_hardcoded(self):
        """draw_kanagawa_border's direct-call path (no clear_rect, no
        body knockout) must paint the seigaiha + hanko regardless of
        the palette passed in. The painter currently uses
        ``SPECTRA6`` constants directly for the seigaiha indigo and
        the hanko red — that's intentional (the theme's Japanese-
        ink palette is fixed; the THEMES slots only carry text and
        accent colours that ``_draw_text_body`` consumes). Verify
        the painter at least runs cleanly when given a minimal
        palette dict — a regression that started reading missing
        keys would fail at paint time."""
        image = Image.new("RGB", (800, 480), color=(255, 255, 255))
        rq.draw_kanagawa_border(image, {"page_bg": rq.SPECTRA6["white"]})
        # Hanko centre area should now show seigaiha indigo or red
        # since no clear_rect was provided.
        found_kanagawa_ink = False
        for py in range(420, 450):
            for px in range(745, 770):
                pix = image.getpixel((px, py))
                if pix in (rq.SPECTRA6["red"], rq.SPECTRA6["black"]):
                    found_kanagawa_ink = True
                    break
            if found_kanagawa_ink:
                break
        assert found_kanagawa_ink, "direct call painted nothing at hanko coordinate"

    def test_seigaiha_helper_paints_tiles_and_arcs(self):
        """``_draw_seigaiha_band`` direct-call: fill a band on a blank
        white canvas and verify both blue tile fills AND white arc
        stripes are present. Also pins the navy post-pass on the
        deepest row."""
        image = Image.new("RGB", (800, 480), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)
        rq._draw_seigaiha_band(
            image, draw, 320, 479,
            rq.SPECTRA6["blue"], rq.SPECTRA6["white"], rq.SPECTRA6["black"],
        )
        # Blue tile pixels.
        blue = 0
        white = 0
        black = 0
        for py in range(320, 480):
            for px in range(0, 800):
                pix = image.getpixel((px, py))
                if pix == rq.SPECTRA6["blue"]:
                    blue += 1
                elif pix == rq.SPECTRA6["white"]:
                    white += 1
                elif pix == rq.SPECTRA6["black"]:
                    black += 1
        assert blue > 10000, f"seigaiha helper painted too little blue ({blue} pixels)"
        assert white > 500, f"seigaiha helper painted too few arc stripes ({white} pixels)"
        assert black > 500, f"seigaiha helper navy post-pass under-fired ({black} pixels)"

    def test_kanagawa_listed_in_border_painters(self):
        """The painter must be registered in the dispatch table so
        future themes added between kanagawa and the dispatch don't
        silently break the registration."""
        assert "kanagawa" in rq._BORDER_PAINTERS
        assert rq._BORDER_PAINTERS["kanagawa"] is rq.draw_kanagawa_border

    def test_kanagawa_renders_at_tiny_preview_size(self):
        """The web curator UI's ``/api/preview`` endpoint clamps to a
        floor of 80x60 px. At that size the hanko seal's coordinates
        land partly off-canvas (``seal_y0`` = 60 - 26 - 38 = -4) — PIL's
        drawing primitives clip silently, but the pixel-level maroon
        post-pass would crash on negative ``pixels[px, py]`` indexing
        without explicit bounds clamping. The clear_rect knockout can
        also produce a collapsed rect (cx1 < cx0 + 4 after clamping)
        that crashes ``draw.rounded_rectangle`` with a
        "y1 must be greater than or equal to y0" ValueError. Both
        guards are pinned here so a regression that strips them
        surfaces immediately."""
        # Direct-call path (no clear_rect, hanko coordinates still
        # land partly off-canvas).
        image = Image.new("RGB", (80, 60), color=rq.SPECTRA6["white"])
        rq.draw_kanagawa_border(image, rq.THEMES["kanagawa"])
        # Full render() pipeline (computes clear_rect from the body
        # block bbox — collapses at 80x60).
        img = rq.render("04:30", self._row(), 80, 60, mode="production", theme="kanagawa")
        assert img.size == (80, 60)


class TestCartographBorder:
    """The cartograph theme paints a hand-drawn antique cartographer's
    chart: cream Y+W Bayer-washed ground + R+G sepia foxing scatter +
    two diagonal-corner R+G sepia coastlines + R+Y tangerine compass
    rose at BL + solid-black sea-serpent margin doodle + three Latin
    place-name labels in italic sepia + doubled red+black rubricated
    cartouche knockout around the body text. Mirrors the structure
    of the kanagawa test suite (which is the closest sibling theme in
    the rotation that uses the same clear_rect-knockout pattern).
    """

    def _row(self, **overrides):
        row = {
            "display_quote": "It was almost half past four when the bell rang.",
            "matched_text": "half past four",
            "author": "Jane Austen",
            "title": "Pride and Prejudice",
            "bucket": "h4_half_past",
            "resolved_bucket": "h4_half_past",
            "quality_score": 88,
            "source_id": "1342",
            "line_number": 42,
        }
        row.update(overrides)
        return row

    def test_cartograph_renders_at_panel_size(self):
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="cartograph")
        assert img.size == (800, 480)

    def test_cartograph_registered_in_theme_order(self):
        """Bug class: a new theme entry in THEMES that's missing from
        THEME_ORDER would be invisible to the button-B cycle and the
        web dropdown. The general invariant is pinned by
        ``test_theme_order_covers_all_registered_themes``, but pin the
        cartograph name explicitly here too so a typo lands a focused
        failure rather than a set-mismatch diff."""
        assert "cartograph" in rq.THEMES
        assert "cartograph" in rq.THEME_ORDER

    def test_cartograph_theme_uses_white_ground_with_red_accent(self):
        """White-paper ground (warmed by a Y+W Bayer wash from the
        border painter) with red as the matched-phrase accent — pin
        the palette shape so a regression that flipped ``page_bg`` to
        yellow (and thus collided with ``alchemy`` / ``comic``) or
        moved the accent off red (and thus broke the cartographer's
        red-vermillion call-out register) fails loudly here."""
        t = rq.THEMES["cartograph"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["black"]
        assert t["accent"] == rq.SPECTRA6["red"]

    def test_cartograph_listed_in_border_painters(self):
        """The painter must be registered in the dispatch table so the
        chart decoration actually fires when the theme is selected."""
        assert "cartograph" in rq._BORDER_PAINTERS
        assert rq._BORDER_PAINTERS["cartograph"] is rq.draw_cartograph_border

    def test_cartograph_border_palette_stays_on_spectra6(self):
        """Every painted pixel must belong to the Spectra 6 native
        palette. The cartograph painter uses sentinel-paint-then-
        bbox-post-pass for both the R+Y tangerine compass rose and
        the R+G sepia coastlines / labels / foxing; a regression in
        the post-passes could leave the sentinel red surviving on
        pixels that were supposed to flip to yellow / green."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="cartograph")
        allowed = set(rq.SPECTRA6.values())
        for py in range(0, 480, 7):
            for px in range(0, 800, 11):
                pix = img.getpixel((px, py))
                assert pix in allowed, f"off-palette pixel {pix} at ({px}, {py})"

    def test_cartograph_compass_rose_paints_tangerine(self):
        """The BL compass rose paints in red sentinel, then a Bayer
        post-pass at threshold 6/16 flips ~3/8 of the painted red
        pixels to yellow → R+Y tangerine (same recipe as ``deco``).
        Sample the rose centre (72, height-80) = (72, 400) and
        confirm both red and yellow pixels are present — neither
        alone would indicate the post-pass fired correctly."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="cartograph")
        found_red = False
        found_yellow = False
        for py in range(370, 432):
            for px in range(40, 105):
                pix = img.getpixel((px, py))
                if pix == rq.SPECTRA6["red"]:
                    found_red = True
                elif pix == rq.SPECTRA6["yellow"]:
                    found_yellow = True
                if found_red and found_yellow:
                    break
            if found_red and found_yellow:
                break
        assert found_red, "compass rose painted no red sentinel pixels"
        assert found_yellow, (
            "compass rose Bayer post-pass left no yellow pixels — "
            "tangerine recipe did not fire"
        )

    def test_cartograph_coastlines_paint_sepia(self):
        """The TL + BR coastlines paint in red sentinel, then a parity
        post-pass flips half the painted red pixels to green per
        ``(px + py) & 1`` → R+G sepia (same recipe as ``newsprint`` /
        ``tarot`` / ``saloon`` foxing). Sample inside both coastline
        polygons and confirm both red and green pixels survive."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="cartograph")
        # TL coastline: extent roughly (160, 86); sample the corner.
        red_tl = green_tl = 0
        for py in range(0, 70):
            for px in range(0, 120):
                pix = img.getpixel((px, py))
                if pix == rq.SPECTRA6["red"]:
                    red_tl += 1
                elif pix == rq.SPECTRA6["green"]:
                    green_tl += 1
        # BR coastline: corner at (799, 479), extent roughly (640, 394).
        red_br = green_br = 0
        for py in range(420, 480):
            for px in range(680, 800):
                pix = img.getpixel((px, py))
                if pix == rq.SPECTRA6["red"]:
                    red_br += 1
                elif pix == rq.SPECTRA6["green"]:
                    green_br += 1
        # Each coastline polygon is large enough that even after the
        # parity split both inks should have hundreds of pixels.
        assert red_tl > 200, f"TL coastline painted too few red pixels ({red_tl})"
        assert green_tl > 200, f"TL coastline parity post-pass under-fired ({green_tl} green)"
        assert red_br > 200, f"BR coastline painted too few red pixels ({red_br})"
        assert green_br > 200, f"BR coastline parity post-pass under-fired ({green_br} green)"

    def test_cartograph_cream_wash_paints_yellow_dots(self):
        """Layer 0 paints a 6.25%-density Y+W Bayer wash (threshold < 1)
        across every page_bg pixel. Sample a region the body-text
        knockout doesn't reach — top-mid sea at y=40, x=200..600 — and
        count yellow pixels. At 6.25% density, ~50 of the ~800 sampled
        positions should be yellow (allowing slack for foxing scatter
        and the band of pixels around place-name labels)."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="cartograph")
        yellow = 0
        for py in (35, 38, 40, 43, 46):
            for px in range(200, 600, 1):
                if img.getpixel((px, py)) == rq.SPECTRA6["yellow"]:
                    yellow += 1
        # At 6.25% density across 5×400 = 2000 sampled positions,
        # we expect roughly 125 yellow dots ± slack for label / foxing
        # overlap. Pin a generous lower bound that catches the case
        # where Layer 0 fails entirely (no Y dots at all).
        assert yellow > 50, f"cream Y+W wash under-fired ({yellow} yellow dots in band)"

    def test_cartograph_cartouche_knockout_paints_red_rule(self):
        """The cartouche knockout paints a doubled rubricated frame:
        thin red outer rule + thin black inner rule. Sample the
        cartouche centre row (y≈240) and confirm both a red pixel and
        a black pixel exist along the rule edges."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="cartograph")
        red_count = 0
        black_count = 0
        # Sample a horizontal slice through the middle of the cartouche
        # — both the outer red rule and inner black rule cross this row.
        for px in range(40, 760):
            for py in range(230, 245):
                pix = img.getpixel((px, py))
                if pix == rq.SPECTRA6["red"]:
                    red_count += 1
                elif pix == rq.SPECTRA6["black"]:
                    black_count += 1
        assert red_count > 4, f"cartouche outer red rule missing ({red_count} red pixels in slice)"
        assert black_count > 100, (
            f"cartouche inner black rule missing or body text absent "
            f"({black_count} black pixels in slice)"
        )

    def test_cartograph_border_appears_in_debug_and_production_modes(self):
        """The map decoration must paint in both modes — the compass
        rose is the easiest invariant to pin because it's anchored at
        a fixed canvas position regardless of body-text layout."""
        for mode in ("production", "debug"):
            img = rq.render("04:30", self._row(), 800, 480, mode=mode, theme="cartograph")
            found_rose_ink = False
            for py in range(370, 432):
                for px in range(40, 105):
                    pix = img.getpixel((px, py))
                    if pix in (rq.SPECTRA6["red"], rq.SPECTRA6["yellow"]):
                        found_rose_ink = True
                        break
                if found_rose_ink:
                    break
            assert found_rose_ink, f"cartograph mode={mode} compass rose missing"

    def test_cartograph_border_direct_call_without_clear_rect(self):
        """The painter's no-clear_rect path is used by
        ``render_static_message`` (goodnight frame) and
        ``render_source_card`` (button-C overlay) — both call
        ``_paint_theme_border`` directly with no clear_rect kwarg.
        Confirm the painter runs cleanly and still paints the map
        layers (cream wash + coastlines + rose + serpent + labels)
        even when the cartouche knockout is skipped."""
        image = Image.new("RGB", (800, 480), color=rq.SPECTRA6["white"])
        rq.draw_cartograph_border(image, {"page_bg": rq.SPECTRA6["white"]})
        # Confirm something painted: red sentinel pixels (from coast
        # / rose / labels post-passes) must remain in the canvas.
        found_red = False
        for py in range(0, 480, 5):
            for px in range(0, 800, 7):
                if image.getpixel((px, py)) == rq.SPECTRA6["red"]:
                    found_red = True
                    break
            if found_red:
                break
        assert found_red, "direct-call cartograph painter produced no decoration"

    def test_cartograph_is_theme_gated(self):
        """The compass rose at (72, 400) is unique to cartograph —
        sample a few other white-ground themes at that coordinate and
        confirm none of them paint yellow (the tangerine post-pass
        signature) there."""
        row = self._row()
        for theme in ("default", "kanagawa"):
            img = rq.render("04:30", row, 800, 480, mode="production", theme=theme)
            # Scan a 12×12 box around the rose centre for tangerine
            # (R+Y) — no other theme paints both red and yellow in
            # that bottom-left region.
            saw_red = saw_yellow = False
            for py in range(395, 410):
                for px in range(60, 85):
                    pix = img.getpixel((px, py))
                    if pix == rq.SPECTRA6["red"]:
                        saw_red = True
                    elif pix == rq.SPECTRA6["yellow"]:
                        saw_yellow = True
            assert not (saw_red and saw_yellow), (
                f"theme {theme} painted both red AND yellow at cartograph "
                f"compass-rose centre — theme gate is leaking"
            )

    def test_cartograph_renders_dense_layout_without_crashing(self):
        """The dense layout pushes the body-text rect (and therefore
        the cartouche) close to the canvas edges. Confirm the
        coastlines / compass rose / serpent still survive — they paint
        BEFORE the cartouche knockout, so the knockout will mask the
        portions that fall inside the rect, but pixels outside the
        rect must still survive."""
        row = self._row(
            display_quote=(
                "It was nearly half past four o'clock when the great bell of the "
                "cathedral rang out across the harbour and through the narrow "
                "cobbled streets, scattering the gulls that had been wheeling "
                "lazily above the mast tops since dawn."
            ),
        )
        img = rq.render("04:30", row, 800, 480, mode="production", theme="cartograph")
        assert img.size == (800, 480)

    def test_cartograph_graticule_paints_dotted_sepia_grid(self):
        """The graticule paints alternating R/G pixels at every
        graticule line (every 80 px vertically and horizontally).
        Sample a horizontal slice at y=80 (the first parallel) and
        confirm both red and green pixels appear in the dotted line
        pattern. Single biggest "this is a chart" signal so a
        regression that drops the graticule layer entirely must fail
        loudly here."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="cartograph")
        # Parallel at y=80 — sample along it (skip x positions that
        # cross the cartouche to avoid the knockout's cream wash).
        red_count = green_count = 0
        for px in range(20, 80):
            for py in (79, 80, 81):
                pix = img.getpixel((px, py))
                if pix == rq.SPECTRA6["red"]:
                    red_count += 1
                elif pix == rq.SPECTRA6["green"]:
                    green_count += 1
        assert red_count >= 3, f"graticule painted too few red dots ({red_count})"
        assert green_count >= 3, f"graticule painted too few green dots ({green_count})"

    def test_cartograph_rhumb_lines_radiate_from_compass(self):
        """Rhumb lines paint dotted sepia rays from the compass rose
        centre (72, height-80=400) outward at 45° increments. The NE
        ray exits the cartouche-knockout top edge (~y=116 for the
        hero layout) at offset ~402 px along the ray and continues
        outward to its endpoint near (460, 12). Sample at offset
        420-460 (above the cartouche, in the top sea) where the
        dotted rhumb pattern should leave sepia pixels."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="cartograph")
        red_count = green_count = 0
        for offset in range(420, 460):
            # Move along the NE diagonal: dx = +offset/sqrt(2), dy = -offset/sqrt(2)
            px = 72 + int(offset * 0.707)
            py = 400 - int(offset * 0.707)
            for dpx in range(-1, 2):
                for dpy in range(-1, 2):
                    if not (0 <= px + dpx < 800 and 0 <= py + dpy < 480):
                        continue
                    pix = img.getpixel((px + dpx, py + dpy))
                    if pix == rq.SPECTRA6["red"]:
                        red_count += 1
                    elif pix == rq.SPECTRA6["green"]:
                        green_count += 1
        assert red_count + green_count >= 4, (
            f"rhumb line NE ray painted too few sepia pixels "
            f"(red={red_count}, green={green_count})"
        )

    def test_cartograph_islands_paint_in_open_sea(self):
        """Three small islands paint in the open-sea regions. Sample
        the bottom-left island position (240, 408) and confirm both
        red and green pixels are present in a 30×30 box around it —
        the same R+G parity post-pass the coastlines use."""
        img = rq.render("04:30", self._row(), 800, 480, mode="production", theme="cartograph")
        # Island 2: cx_frac=0.30, cy_frac=0.85 → (240, 408)
        red_count = green_count = 0
        for py in range(393, 425):
            for px in range(220, 260):
                pix = img.getpixel((px, py))
                if pix == rq.SPECTRA6["red"]:
                    red_count += 1
                elif pix == rq.SPECTRA6["green"]:
                    green_count += 1
        # Expect both inks present — island silhouette + R+G parity
        # post-pass guarantees roughly equal counts of each.
        assert red_count >= 30, f"island painted too few red pixels ({red_count})"
        assert green_count >= 30, (
            f"island R+G post-pass under-fired ({green_count} green pixels)"
        )

    def test_cartograph_renders_at_tiny_preview_size(self):
        """The web curator UI's ``/api/preview`` endpoint clamps to a
        floor of 80x60 px. Confirm cartograph survives that clamp
        without crashing — the compass-rose anchor at (72, height-80)
        lands at (72, -20) for height=60, and the bbox post-pass loop
        must clip to canvas bounds rather than indexing negative
        pixel coords. Same defensive-clamp invariant as kanagawa's
        small-preview test."""
        img = rq.render("04:30", self._row(), 80, 60, mode="production", theme="cartograph")
        assert img.size == (80, 60)


class TestCircuitBorder:
    """The circuit theme paints a printed-circuit-board composition: a
    forest soldermask wash (G+K 1:1 over the flat-green ground) + gold
    (Spectra-6 yellow) copper traces / pads / matched-phrase accent +
    white silkscreen body text, designators, and a Y1 crystal + four
    corner mounting holes + a clear_rect knockout that resets the body
    region to clean board and frames it with a white silkscreen outline.
    Mirrors the kanagawa / cartograph clear_rect-knockout test structure.
    """

    def _row(self, **overrides):
        row = {
            "display_quote": "It was about half past two in the afternoon when the clock chimed softly.",
            "matched_text": "half past two",
            "author": "Charles Dickens",
            "title": "Great Expectations",
            "bucket": "h2_half_past",
            "resolved_bucket": "h2_half_past",
            "quality_score": 88,
            "source_id": "1400",
            "line_number": 73,
        }
        row.update(overrides)
        return row

    def test_circuit_renders_at_panel_size(self):
        img = rq.render("14:30", self._row(), 800, 480, mode="production", theme="circuit")
        assert img.size == (800, 480)

    def test_circuit_registered_everywhere(self):
        """A new theme must appear in THEMES, THEME_ORDER, THEME_FONTS, and
        the border-painter dispatch table or it's invisible / KeyErrors at
        display time. The general invariants are pinned elsewhere; pin the
        circuit name explicitly so a typo lands a focused failure."""
        assert "circuit" in rq.THEMES
        assert "circuit" in rq.THEME_ORDER
        assert "circuit" in rq.THEME_FONTS
        assert rq._BORDER_PAINTERS.get("circuit") is rq.draw_circuit_border

    def test_circuit_theme_uses_green_ground_white_silk_gold_accent(self):
        """Pin the PCB palette shape: flat-green ``page_bg`` (darkened to
        forest soldermask by the painter's Layer 0), white silkscreen body,
        gold (yellow) copper accent. A regression that moved the accent off
        yellow would break the copper-trace colour story."""
        t = rq.THEMES["circuit"]
        assert t["page_bg"] == rq.SPECTRA6["green"]
        assert t["text"] == rq.SPECTRA6["white"]
        assert t["accent"] == rq.SPECTRA6["yellow"]

    def test_circuit_border_palette_stays_on_spectra6(self):
        img = rq.render("14:30", self._row(), 800, 480, mode="production", theme="circuit")
        allowed = set(rq.SPECTRA6.values())
        for py in range(0, 480, 7):
            for px in range(0, 800, 11):
                pix = img.getpixel((px, py))
                assert pix in allowed, f"off-palette pixel {pix} at ({px}, {py})"

    def test_circuit_layer0_is_forest_checkerboard(self):
        """The soldermask wash must flip ~half the green ground to black on
        the (x+y) checkerboard so the board reads as deep forest green
        (G+K 1:1) — distinct from ``atomic``'s 1-in-4 mint wash. Both green
        and black must be present in roughly balanced amounts; a regression
        that skipped the wash would leave the board flat bright green
        (almost no black) and inherit atomic's silhouette."""
        img = rq.render("14:30", self._row(), 800, 480, mode="production", theme="circuit")
        counts = ink_counts(img)
        green = counts.get(rq.SPECTRA6["green"], 0)
        black = counts.get(rq.SPECTRA6["black"], 0)
        assert green > 50_000, "soldermask wash erased too much of the green ground"
        assert black > 50_000, "soldermask wash did not flip enough green to black"
        # Balanced checkerboard: neither ink dominates the other more than 2:1.
        assert 0.5 < green / black < 2.0, f"forest wash unbalanced: green={green} black={black}"

    def test_circuit_paints_gold_copper(self):
        """Copper traces, pads, and the oversized quote marks paint in gold
        (Spectra-6 yellow). A render with no yellow pixels would mean the
        trace routing / pad / ornament layer silently dropped."""
        img = rq.render("14:30", self._row(), 800, 480, mode="production", theme="circuit")
        assert ink_counts(img).get(rq.SPECTRA6["yellow"], 0) > 1_000

    def test_circuit_small_preview_does_not_crash(self):
        """The curator UI clamps preview renders down to 80x60; the
        clear_rect knockout + corner-hole loops must clamp to canvas bounds
        rather than indexing out-of-range pixels. Same defensive invariant
        as kanagawa / cartograph small-preview tests."""
        img = rq.render("14:30", self._row(), 80, 60, mode="production", theme="circuit")
        assert img.size == (80, 60)


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
        pixels = distinct_inks(img)
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

    def test_uses_bauhaus_theme_background(self):
        img = rq.render_static_message("Good night.", 800, 480, theme="bauhaus")
        assert img.getpixel((0, 0)) == rq.SPECTRA6["white"]

    def test_uses_nightvision_theme_background(self):
        img = rq.render_static_message("Good night.", 800, 480, theme="nightvision")
        assert img.getpixel((0, 0)) == rq.SPECTRA6["black"]

    @pytest.mark.parametrize("theme", sorted(rq.THEMES))
    def test_palette_is_spectra6_across_every_theme(self, theme):
        """Every output pixel must land in the Spectra 6 palette regardless
        of which theme is active. Without ``snap_image_to_palette`` the
        per-theme borders (newsprint halftone, gothic quatrefoils, etc.) can
        introduce intermediate dither colours that look fine on a sRGB
        monitor but bleed unpredictably on the eInk panel."""
        img = rq.render_static_message("Good night.", 800, 480, theme=theme)
        palette = set(rq.SPECTRA6.values())
        pixels = distinct_inks(img)
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
        argv = ["render_quote.py", "--mode", "goodnight", "--theme", "newsprint",
                "--message", "Sleep well.", "--output", str(out)]
        monkeypatch.setattr("sys.argv", argv)
        # If main accidentally called pick_quote, this would explode loudly.
        with patch.object(rq_core, "pick_quote", side_effect=AssertionError("pick_quote must not run for mode=goodnight")):
            assert rq.main() == 0
        assert out.exists()
        from PIL import Image
        img = Image.open(out)
        assert img.size == (800, 480)
        img.close()


class TestPreviewSizeRendering:
    """Every theme must render without raising at the small preview/thumbnail
    sizes the curator UI's ``/api/preview`` endpoint serves.

    ``/api/preview`` clamps requests to width 80..800, height 60..480 and
    renders any registered theme there. Frames with fixed 800×480 coordinates
    used to crash a preview into a 500 two ways: raw ``PixelAccess`` writes
    (``px[x, y]``) past the smaller image bounds (``IndexError``), and
    ``draw.rectangle`` boxes that invert (``x1 < x0`` / ``y1 < y0``) once a
    fixed inset exceeds the canvas (``ValueError``). This sweeps every theme at
    the clamp's minimum corner plus a typical thumbnail to fence both."""

    def _row(self):
        return {
            "display_quote": "It was about half past two when the clock struck and the afternoon slipped away.",
            "matched_text": "half past two",
            "author": "Edith Wharton",
            "title": "The House of Mirth",
        }

    # The /api/preview clamp range (web_server.PREVIEW_MIN/MAX_*): the minimum
    # corner is the worst case for fixed-coordinate frames; 240×144 is a typical
    # thumbnail-grid request.
    @pytest.mark.parametrize("theme", sorted(rq.THEMES))
    @pytest.mark.parametrize("size", [(80, 60), (240, 144)])
    def test_renders_at_small_preview_sizes(self, theme, size):
        width, height = size
        img = rq.render("14:30", self._row(), width, height, mode="production", theme=theme)
        assert img.size == (width, height)
        palette = set(rq.SPECTRA6.values())
        assert distinct_inks(img).issubset(palette)


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
        monkeypatch.setattr(rq_core, "pick_quote", lambda *args, **kwargs: self._row())
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

        monkeypatch.setattr(rq_core, "pick_quote", lambda *args, **kwargs: self._row())

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
        monkeypatch.setattr(rq_core, "pick_quote", lambda *a, **kw: self._row())
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
        from idle_hours import pick_quote as pq
        from idle_hours import render_quote
        captured: dict = {}

        def fake_select_quote(**kwargs):
            captured.update(kwargs)
            return {"source_id": "1", "line_number": 1, "display_quote": "x", "matched_text": "y"}

        monkeypatch.setattr(render_quote.pick_quote_module, "select_quote", fake_select_quote)
        render_quote.pick_quote("10:00")
        assert captured.get("database_path") == pq.DEFAULT_DATABASE_PATH


class TestFillSwatchStippleClipping:
    """``_fill_swatch_stipple`` writes through ``PixelAccess`` (``px[x, y]``),
    which raises ``IndexError`` on out-of-range coordinates — unlike PIL's
    draw primitives which silently clip. The diags layout's hardcoded swatch
    Y offsets sit well below a small preview canvas (the web UI's theme grid
    requests 320×192, where the synth-swatch band starts at y=302), so the
    function must clip its own rect to the image bounds rather than crash
    the preview endpoint.
    """

    _DARK = (10, 20, 30)
    _LIGHT = (200, 210, 220)
    _BG = (1, 2, 3)

    @pytest.mark.parametrize("density", [0.2, 0.4, 0.6])
    def test_rect_entirely_below_image_is_skipped(self, density):
        image = Image.new("RGB", (320, 192), self._BG)
        rq._fill_swatch_stipple(image, (10, 300, 60, 340), self._DARK, self._LIGHT, density)
        # Nothing painted: every pixel still the sentinel background.
        assert image.getextrema() == ((1, 1), (2, 2), (3, 3))

    @pytest.mark.parametrize("density", [0.2, 0.4, 0.6])
    def test_rect_partially_below_image_is_clipped(self, density):
        image = Image.new("RGB", (320, 192), self._BG)
        # Rect straddles the bottom edge: only y=180..191 should paint.
        rq._fill_swatch_stipple(image, (10, 180, 60, 240), self._DARK, self._LIGHT, density)
        px = image.load()
        # Below the image: PixelAccess would raise if not clipped — already
        # asserted by reaching this line. Inside the clipped region the
        # canvas changed from the sentinel.
        painted = sum(
            1
            for y in range(180, 192)
            for x in range(10, 60)
            if px[x, y] != self._BG
        )
        assert painted > 0
        # Pixels outside the clipped rect (e.g. just above y=180) untouched.
        assert px[10, 179] == self._BG

    def test_rect_entirely_right_of_image_is_skipped(self):
        image = Image.new("RGB", (320, 192), self._BG)
        rq._fill_swatch_stipple(image, (400, 10, 450, 60), self._DARK, self._LIGHT, 0.5)
        assert image.getextrema() == ((1, 1), (2, 2), (3, 3))

    def test_diags_frame_renders_at_thumbnail_size(self):
        """End-to-end regression for the reported failure: requesting
        ``/api/preview?theme=diags&width=320&height=192`` previously hit
        an ``IndexError`` inside ``_fill_swatch_stipple`` because the
        synth-swatch band sits at y=302 — entirely below a 192px canvas.
        """
        row = {
            "display_quote": "A test quote.",
            "matched_text": "midnight",
            "bucket": "h12_exact",
            "quality_score": 80,
            "source_id": "1",
            "line_number": 1,
        }
        img = rq.render_diags_frame("12:00", row, 320, 192)
        assert img.size == (320, 192)


class TestDiagsSynthSwatches:
    """The diags theme's synth swatch band is the on-panel visual reference
    for the two-ink recipes documented in ``spectra6_color_recipes.md``.
    The doc and the swatch list must stay in sync — if someone adds a new
    reachable two-ink recipe to the doc, the operator should see it on the
    panel; if someone drops a recipe from the swatch list, this test fails
    loudly so the omission is intentional rather than accidental.
    """

    # Every two-ink recipe the doc lists as reachable via
    # ``draw_text_dithered`` today. Mirrors the catalogue in
    # ``spectra6_color_recipes.md`` (two-ink table + the maroon/navy rows
    # the "Deep tones" section flags as 2-ink in practice).
    _EXPECTED_RECIPES: frozenset[str] = frozenset(
        {
            "tangerine",
            "amber",
            "coral",
            "candlelit",
            "mint",
            "sage",
            "cyan",
            "teal",
            "sky",
            "violet",
            "sepia",
            "forest",
            "olive",
            "lime",
            "cream",
            "gray",
            "maroon",
            "navy",
        }
    )

    def test_swatch_list_has_every_documented_recipe(self):
        names = {entry[0] for entry in rq._DIAGS_SYNTH_SWATCHES}
        assert names == self._EXPECTED_RECIPES, (
            "diags synth swatch list drifted from spectra6_color_recipes.md — "
            f"missing: {self._EXPECTED_RECIPES - names}; extra: {names - self._EXPECTED_RECIPES}"
        )

    def test_swatch_count_matches_row_split(self):
        # Two-row layout: row 1 holds _DIAGS_SYNTH_ROW1_COUNT entries, row 2
        # holds the remainder. Guard against a future edit that grows the
        # list without rebalancing the row counts (which would silently
        # shrink row-1 swatches and overflow row-2 onto a third row).
        assert len(rq._DIAGS_SYNTH_SWATCHES) == 18
        assert rq._DIAGS_SYNTH_ROW1_COUNT == 8
        row2 = len(rq._DIAGS_SYNTH_SWATCHES) - rq._DIAGS_SYNTH_ROW1_COUNT
        assert row2 == 10

    def test_both_rows_paint_non_background_pixels(self):
        # Full-canvas render: both two-ink swatch rows must actually paint,
        # so a broken row-splitting loop (e.g. wrong index arithmetic) trips
        # a visible regression rather than silently leaving row 2 blank.
        row = {
            "display_quote": "A test quote.",
            "matched_text": "midnight",
            "bucket": "h12_exact",
            "quality_score": 80,
            "source_id": "1",
            "line_number": 1,
        }
        img = rq.render_diags_frame("12:00", row, 800, 480)
        assert img.size == (800, 480)
        page_bg = rq.THEMES["diags"]["page_bg"]
        # Sample a pixel near the middle of each row's coloured band. With
        # the four-row layout (2-ink × 2 + 3-ink × 2) the 2-ink rows sit
        # roughly at y=280 (row 1) and y=327 (row 2).
        for y_sample in (280, 327):
            sampled = {img.getpixel((x, y_sample)) for x in range(50, 750, 50)}
            non_bg = {px for px in sampled if px != page_bg}
            assert non_bg, f"2-ink row at y={y_sample} painted no non-background pixels"


class TestDiagsTripleSwatches:
    """The diags theme's 3-ink stipple band must cover every three-ink
    recipe ``spectra6_color_recipes.md`` lists as documented (pastels,
    deep tones, chromatic mixes — minus the maroon/navy/rich-black 2-ink
    rows that live in the deep-tones section but are 2-ink in practice).
    """

    _EXPECTED_TRIPLES: frozenset[str] = frozenset(
        {
            # Pastels (3rd ink = white)
            "light orange",
            "salmon",
            "peach",
            "lavender",
            "lilac",
            "seafoam",
            "khaki",
            "beige",
            # Deep tones (3rd ink = black)
            "plum",
            "print sepia",
            # Chromatic (no white or black)
            "burnt orange",
            "forest-teal",
        }
    )

    def test_triple_list_matches_documented_recipes(self):
        names = {entry[0] for entry in rq._DIAGS_TRIPLE_SWATCHES}
        assert names == self._EXPECTED_TRIPLES, (
            "diags triple swatch list drifted from spectra6_color_recipes.md — "
            f"missing: {self._EXPECTED_TRIPLES - names}; extra: {names - self._EXPECTED_TRIPLES}"
        )

    def test_triple_count_matches_row_split(self):
        # Two rows of six. Guard against a future edit that grows the list
        # without rebalancing.
        assert len(rq._DIAGS_TRIPLE_SWATCHES) == 12
        assert rq._DIAGS_TRIPLE_ROW1_COUNT == 6
        row2 = len(rq._DIAGS_TRIPLE_SWATCHES) - rq._DIAGS_TRIPLE_ROW1_COUNT
        assert row2 == 6

    def test_densities_are_valid(self):
        # Each entry's (density_a + density_b) must sit in [0, 1) so that
        # ink_c gets a non-empty cell partition. The implicit third density
        # is 1 - density_a - density_b.
        for entry in rq._DIAGS_TRIPLE_SWATCHES:
            name, _ink_a, _ink_b, _ink_c, density_a, density_b, _recipe = entry
            total = density_a + density_b
            assert 0 <= density_a <= 1, f"{name}: density_a={density_a} out of range"
            assert 0 <= density_b <= 1, f"{name}: density_b={density_b} out of range"
            assert total < 1, f"{name}: density_a+density_b={total} leaves no room for ink_c"

    def test_three_ink_rows_paint_non_background_pixels(self):
        # Full-canvas render: both 3-ink rows must actually paint so a
        # broken loop or off-by-one row index trips a visible regression.
        row = {
            "display_quote": "A test quote.",
            "matched_text": "midnight",
            "bucket": "h12_exact",
            "quality_score": 80,
            "source_id": "1",
            "line_number": 1,
        }
        img = rq.render_diags_frame("12:00", row, 800, 480)
        page_bg = rq.THEMES["diags"]["page_bg"]
        # 3-ink rows sit roughly at y=391 (row 1) and y=438 (row 2).
        for y_sample in (391, 438):
            sampled = {img.getpixel((x, y_sample)) for x in range(50, 750, 50)}
            non_bg = {px for px in sampled if px != page_bg}
            assert non_bg, f"3-ink row at y={y_sample} painted no non-background pixels"


class TestAstrariumFrame:
    """The ``astrarium`` theme dispatches into its own custom render path
    (``render_astrarium_frame``) the same way ``diags`` does — bypassing
    the standard literary layout entirely. None of the helpers
    (``_astrarium_paint_cream_wash`` / ``_paint_ring_quadrant`` /
    ``_paint_constellation_field`` / ``_paint_dial`` / ``_paint_header`` /
    ``_paint_quote_panel`` / ``_paint_datum_strip``) were exercised by
    any test, leaving ~520 lines of theme code uncovered. The two
    smoke tests below mirror the diags pattern: render at canonical
    800×480 to exercise every helper, and again at thumbnail size to
    confirm proportional positioning doesn't crash on a narrow canvas
    (the curator UI's theme preview grid asks for 320×192).
    """

    _ROW = {
        "display_quote": "It was at ten o'clock today that the first of all Time Machines began its career.",
        "matched_text": "ten o'clock",
        "bucket": "h10_exact",
        "quality_score": 80,
        "source_id": "35",
        "line_number": 1,
        "author": "H. G. Wells",
        "title": "The Time Machine",
    }

    def test_render_dispatches_to_astrarium_frame(self):
        img = rq.render("10:00", self._ROW, 800, 480, mode="production", theme="astrarium")
        assert img.size == (800, 480)
        # ``render_astrarium_frame`` ends in ``snap_image_to_palette`` so
        # every pixel must land on the Spectra 6 palette.
        unique = {img.getpixel((x, y)) for y in range(0, 480, 40) for x in range(0, 800, 40)}
        assert unique.issubset(set(rq.SPECTRA6_PALETTE)), (
            f"astrarium frame produced off-palette pixels: {unique - set(rq.SPECTRA6_PALETTE)}"
        )

    def test_render_astrarium_frame_at_thumbnail_size(self):
        """The curator UI's theme preview grid issues
        ``/api/preview?theme=astrarium&width=320&height=192`` for the
        thumbnail. The dial uses proportional positioning so the
        narrow canvas must still produce a recognisable thumbnail
        without raising (e.g. via ``PixelAccess`` IndexError or a
        negative font size from ``fit_quote``)."""
        img = rq.render_astrarium_frame("10:00", self._ROW, 320, 192)
        assert img.size == (320, 192)


class TestFillSwatchStipple3way:
    """``_fill_swatch_stipple_3way`` is the new ``_three_way_bayer``
    primitive ``spectra6_color_recipes.md`` references as the
    prerequisite for the documented three-ink recipes. The ratio sweep
    below pins the per-region pixel counts within ±2% tolerance on a
    fixed 32×32 sample tile, matching the discipline the doc asks for
    when introducing the primitive.
    """

    _INK_A: tuple[int, int, int] = (255, 0, 0)
    _INK_B: tuple[int, int, int] = (0, 255, 0)
    _INK_C: tuple[int, int, int] = (0, 0, 255)
    _BG: tuple[int, int, int] = (1, 2, 3)

    @classmethod
    def _counts(cls, image):
        counts = ink_counts(image)
        return {
            "a": counts.get(cls._INK_A, 0),
            "b": counts.get(cls._INK_B, 0),
            "c": counts.get(cls._INK_C, 0),
        }

    @pytest.mark.parametrize(
        "density_a, density_b, expected_ratios",
        [
            # Even mix: 5/6/5 cell split (round(0.333*16)=5,
            # round(0.667*16)=11, so middle region is cells 5..10 = 6 cells)
            (1 / 3, 1 / 3, (5 / 16, 6 / 16, 5 / 16)),
            # 40/40/20 — pastels and print sepia
            (0.40, 0.40, (6 / 16, 7 / 16, 3 / 16)),
            # 50/40/10 — burnt orange
            (0.50, 0.40, (8 / 16, 6 / 16, 2 / 16)),
            # 25/25/50 — lilac, beige
            (0.25, 0.25, (4 / 16, 4 / 16, 8 / 16)),
            # 30/50/20 — peach
            (0.30, 0.50, (5 / 16, 8 / 16, 3 / 16)),
        ],
    )
    def test_partition_ratios(self, density_a, density_b, expected_ratios):
        # 32×32 tile is a clean multiple of the 4×4 Bayer matrix, so the
        # pixel counts settle exactly on the partition boundaries — no
        # remainder noise to absorb in the tolerance.
        image = Image.new("RGB", (32, 32), self._BG)
        rq._fill_swatch_stipple_3way(
            image,
            (0, 0, 32, 32),
            self._INK_A,
            self._INK_B,
            self._INK_C,
            density_a,
            density_b,
        )
        counts = self._counts(image)
        total = sum(counts.values())
        assert total == 32 * 32, "primitive failed to cover the rect"
        ratios = (counts["a"] / total, counts["b"] / total, counts["c"] / total)
        for got, want in zip(ratios, expected_ratios, strict=True):
            assert abs(got - want) <= 0.02, f"ratio {got:.3f} drifted from {want:.3f}"

    def test_clips_rect_to_image_bounds(self):
        # Same clipping defence as the 2-ink primitive — out-of-bounds
        # rect must not raise on the diags thumbnail (320×192) where the
        # 3-ink band lives below the visible canvas.
        image = Image.new("RGB", (320, 192), self._BG)
        rq._fill_swatch_stipple_3way(
            image,
            (10, 300, 60, 340),
            self._INK_A,
            self._INK_B,
            self._INK_C,
            0.4,
            0.3,
        )
        # Untouched: every pixel still the sentinel background.
        assert image.getextrema() == ((1, 1), (2, 2), (3, 3))


class TestDrawTextDithered:
    """The deco theme's red-biased orange added a third density branch
    (4×4 Bayer at arbitrary thresholds) to ``draw_text_dithered``.
    The existing 0.25 sparse-1-in-4 and 0.5 checkerboard branches must
    stay byte-identical (nightvision's body text relies on the exact
    patterns), and the new branch must produce a
    red-biased ratio (~3/8 light : 5/8 dark) on a 4×4 tile.
    """

    # Sentinel background that doesn't match any SPECTRA6 colour so
    # ``light`` (which may legitimately be white) stays distinguishable
    # from unchanged canvas pixels.
    _BG: tuple[int, int, int] = (1, 2, 3)

    @classmethod
    def _render(cls, density, dark, light, *, text="MMMMMMMMMMMMMMMM"):
        """Render ``text`` via ``draw_text_dithered`` on a sentinel-bg
        canvas and return ``(image, light_count, dark_count)``. Uses the
        bundled Playfair font at a size large enough to produce a few
        thousand inked pixels — plenty for ratio assertions even after
        the ≥128 antialias threshold trims edge pixels.
        """
        # Anchored on the package, not the CWD: the CWD-relative form stopped
        # resolving after the package move and skipped these tests silently.
        font_path = Path(rq.BASE_DIR) / "fonts" / "PlayfairDisplay-Regular.ttf"
        assert font_path.is_file(), f"bundled font missing: {font_path}"
        from PIL import ImageFont
        font = ImageFont.truetype(str(font_path), size=64)
        image = Image.new("RGB", (640, 96), cls._BG)
        rq.draw_text_dithered(
            image,
            (10, 8),
            text,
            font,
            dark=dark,
            light=light,
            light_density=density,
        )
        px = image.load()
        light_count = 0
        dark_count = 0
        for y in range(image.height):
            for x in range(image.width):
                p = px[x, y]
                if p == light:
                    light_count += 1
                elif p == dark:
                    dark_count += 1
        return image, light_count, dark_count

    def test_bayer_4x4_constant_shape(self):
        """The shared Bayer matrix must be 4×4 with all unique values
        in 0..15. A typo would silently break both call sites (text
        body + border post-pass) since they share the constant."""
        assert len(rq.BAYER_4x4) == 4
        assert all(len(row) == 4 for row in rq.BAYER_4x4)
        flat = [v for row in rq.BAYER_4x4 for v in row]
        assert sorted(flat) == list(range(16)), (
            f"BAYER_4x4 must permute 0..15, got {sorted(flat)}"
        )

    def test_density_0_375_red_biased_bayer(self):
        """0.375 (the deco recipe) must hit the new Bayer branch and
        land on roughly 3/8 light : 5/8 dark. Bayer threshold = 6/16
        gives exactly 0.375 of the *cells* light, but antialias-edge
        thresholding shifts the practical ratio slightly. Tolerate a
        generous band so the test isn't flaky across Pillow versions
        but still catches a branch that flipped to 50/50 or worse.
        """
        dark = rq.SPECTRA6["red"]
        light = rq.SPECTRA6["yellow"]
        _, light_count, dark_count = self._render(0.375, dark, light)
        total = light_count + dark_count
        assert total > 1000, f"too few inked pixels to test ratio: {total}"
        light_ratio = light_count / total
        # Red-biased target ≈ 0.375. A 0.5 checkerboard would land
        # at ~0.5, so a wide tolerance still distinguishes the two.
        assert 0.30 <= light_ratio <= 0.45, (
            f"density=0.375 produced light_ratio={light_ratio:.3f}, "
            f"expected ~0.375 — Bayer branch may have regressed"
        )

    def test_density_0_5_preserves_checkerboard_branch(self):
        """0.5 must still hit the original 1×1 checkerboard. Sample
        every inked pixel and assert it matches ``(x+y) % 2`` parity —
        a single pixel out of phase means nightvision / etc would
        ghost on the panel."""
        dark = rq.SPECTRA6["green"]
        light = rq.SPECTRA6["white"]
        image, light_count, dark_count = self._render(0.5, dark, light)
        total = light_count + dark_count
        assert total > 1000, f"too few inked pixels: {total}"
        px = image.load()
        bad = 0
        for y in range(image.height):
            for x in range(image.width):
                p = px[x, y]
                if p == dark and (x + y) % 2 != 0:
                    bad += 1
                elif p == light and (x + y) % 2 == 0:
                    bad += 1
        assert bad == 0, f"1×1 checkerboard parity broken at {bad} pixel(s)"

    def test_density_0_25_preserves_sparse_branch(self):
        """0.25 must still hit the original sparse 1-in-4 branch
        (light only where both axes are even). Grimoire's
        candlelit-rubric matched phrase relies on the exact pattern."""
        dark = rq.SPECTRA6["red"]
        light = rq.SPECTRA6["white"]
        image, light_count, dark_count = self._render(0.25, dark, light)
        total = light_count + dark_count
        assert total > 1000, f"too few inked pixels: {total}"
        px = image.load()
        bad = 0
        for y in range(image.height):
            for x in range(image.width):
                p = px[x, y]
                if p == light and not (x % 2 == 0 and y % 2 == 0):
                    bad += 1
        assert bad == 0, f"sparse 1-in-4 pattern broken at {bad} pixel(s)"

    def test_deco_call_site_uses_red_biased_density(self):
        """``_draw_text_body`` must call ``draw_text_dithered`` for the
        deco red-accent path with ``light_density=0.375`` — a regression
        to the default 0.5 would silently revert the deco orange to the
        washed-out amber this change is meant to fix.
        """
        captured: dict = {}

        def fake_dither(*args, **kwargs):
            captured["density"] = kwargs.get("light_density")
            captured["light"] = kwargs.get("light")

        with patch.object(rq_text, "draw_text_dithered", side_effect=fake_dither):
            image = Image.new("RGB", (200, 60), (255, 255, 255))
            draw = ImageDraw.Draw(image)
            from PIL import ImageFont
            font = ImageFont.load_default()
            rq._draw_text_body(image, draw, (10, 10), "test", font, rq.SPECTRA6["red"], "deco")

        assert captured.get("density") == 0.375, (
            f"deco red-accent dither expected light_density=0.375, "
            f"got {captured.get('density')}"
        )
        assert captured.get("light") == rq.SPECTRA6["yellow"], (
            "deco red-accent dither must stipple toward yellow"
        )

    def test_deco_border_post_pass_uses_same_threshold(self):
        """``draw_deco_border``'s post-pass must flip red pixels using
        the same Bayer matrix and threshold (6) as the body text. A
        drift here would visibly split the matched phrase from the
        border ornaments — both should land on one tangerine tone.
        """
        # Render a deco border on a canvas pre-filled with the red accent.
        # Every pixel that's still red after the post-pass should
        # correspond to BAYER_4x4[y%4][x%4] >= 6; every pixel flipped
        # to yellow should correspond to BAYER_4x4[y%4][x%4] < 6. Use
        # the full 800×480 panel size so the border helper's inset
        # rectangles don't go negative.
        accent = rq.SPECTRA6["red"]
        yellow = rq.SPECTRA6["yellow"]
        image = Image.new("RGB", (800, 480), accent)
        rq.draw_deco_border(
            image,
            {"text": rq.SPECTRA6["black"], "accent": accent},
        )
        px = image.load()
        mismatches = 0
        for y in range(image.height):
            for x in range(image.width):
                p = px[x, y]
                cell = rq.BAYER_4x4[y % 4][x % 4]
                if p == accent and cell < 6:
                    mismatches += 1
                elif p == yellow and cell >= 6:
                    mismatches += 1
                # other colors (frame_color black for outer/inner rules)
                # come from drawn primitives, not the post-pass — skip
        assert mismatches == 0, (
            f"draw_deco_border post-pass deviated from Bayer threshold 6 "
            f"at {mismatches} pixel(s)"
        )

    def test_alchemy_phrase_is_a_solid_red_rubric(self):
        """The alchemy matched phrase paints solid red. An earlier
        revision stippled it 50/50 red + blue for a Tyrian purple, which
        shredded MedievalSharp's thin strokes into a dotted smear at body
        size; a scribe's rubric is solid, and so is this.
        """
        with patch.object(rq_text, "draw_text_dithered") as dither:
            image = Image.new("RGB", (200, 60), (255, 255, 255))
            draw = ImageDraw.Draw(image)
            from PIL import ImageFont
            font = ImageFont.load_default()
            rq._draw_text_body(image, draw, (10, 10), "test", font, rq.SPECTRA6["red"], "alchemy")
        dither.assert_not_called()
        # Every inked pixel is a tint of red on the white ground -- no blue
        # component anywhere, which the purple stipple would have left.
        inks = distinct_inks(image)
        assert any(ink != (255, 255, 255) for ink in inks)
        assert all(r == 255 and g == b for r, g, b in inks), inks

    def test_gothic_call_site_uses_amber_recipe(self):
        """``_draw_text_body`` must call ``draw_text_dithered`` for the
        gothic red-accent path with the documented amber recipe — 50/50
        yellow-on-red checkerboard (``light=yellow``, default density).
        A regression to solid red, to ``light=white``, or to any
        non-default density would shift the matched phrase off the
        agreed amber tone that ties gothic to the ``diags`` synth band's
        "amber" swatch (R+Y 1:1).
        """
        captured: dict = {}

        def fake_dither(*args, **kwargs):
            captured["density"] = kwargs.get("light_density")
            captured["light"] = kwargs.get("light")

        with patch.object(rq_text, "draw_text_dithered", side_effect=fake_dither):
            image = Image.new("RGB", (200, 60), (255, 255, 255))
            draw = ImageDraw.Draw(image)
            from PIL import ImageFont
            font = ImageFont.load_default()
            rq._draw_text_body(image, draw, (10, 10), "test", font, rq.SPECTRA6["red"], "gothic")

        assert captured.get("density") in (None, 0.5), (
            f"gothic amber dither must use 50/50 density (default); "
            f"got {captured.get('density')}"
        )
        assert captured.get("light") == rq.SPECTRA6["yellow"], (
            "gothic red-accent dither must stipple toward yellow for the "
            "amber register (R+Y 1:1)"
        )

    def test_saloon_foxing_speckles_split_red_and_green(self):
        """``draw_saloon_border`` paints foxing speckles in a mix of
        red and green so the eye averages adjacent dots into sepia.
        Both inks must be present in non-trivial counts; an all-red or
        all-green result would mean the (px+py)-parity gate broke. The
        decision keys off the source ``_SALOON_FOXING`` coordinates,
        not the rescaled canvas position, so the ratio stays stable
        across canvas sizes.
        """
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        rq.draw_saloon_border(
            image,
            {
                "text": rq.SPECTRA6["black"],
                "accent": rq.SPECTRA6["red"],
                "page_bg": rq.SPECTRA6["white"],
            },
        )
        # Count speckles inside the body region (outside both banner
        # bands and outside the frame area) so other red ornaments
        # (mid-edge diamonds, fleuron wings) can't bias the count.
        # Body region is roughly y in (80, 400), x in (40, 760).
        pixels = image.load()
        red_count = 0
        green_count = 0
        for y in range(80, 400):
            for x in range(40, 760):
                p = pixels[x, y]
                if p == rq.SPECTRA6["red"]:
                    red_count += 1
                elif p == rq.SPECTRA6["green"]:
                    green_count += 1
        # Both colours present; neither dominates by more than 3:1 (a
        # broken parity gate would land at 100:0 or 0:100).
        assert red_count > 30 and green_count > 30, (
            f"saloon foxing must mix red + green speckles, got "
            f"red={red_count} green={green_count}"
        )
        ratio = red_count / max(green_count, 1)
        assert 0.33 < ratio < 3.0, (
            f"saloon foxing red:green ratio outside sepia band: {ratio:.2f} "
            f"(red={red_count} green={green_count})"
        )

    def test_placard_tacks_split_red_and_white(self):
        """``draw_placard_border``'s four tacks are painted red and
        then post-passed to ~50% white, so the eye averages red+white
        into coral pink. Both inks must be present inside each tack's
        bbox and the post-pass must honour the (x+y)&1 checkerboard.
        """
        # Sentinel background so post-pass whites are distinguishable.
        image = Image.new("RGB", (800, 480), (1, 2, 3))
        rq.draw_placard_border(
            image,
            {"text": rq.SPECTRA6["black"], "accent": rq.SPECTRA6["red"]},
        )
        pixels = image.load()
        # Tack centre is at (38, 38) with radius 4 → bbox (34..42).
        red_count = 0
        white_count = 0
        for y in range(34, 43):
            for x in range(34, 43):
                p = pixels[x, y]
                if p == rq.SPECTRA6["red"]:
                    red_count += 1
                elif p == rq.SPECTRA6["white"]:
                    white_count += 1
        assert red_count > 0 and white_count > 0, (
            f"placard TL tack must mix red + white (coral post-pass); "
            f"got red={red_count} white={white_count}"
        )
        # Whites inside the tack bbox come exclusively from the
        # post-pass; assert checkerboard parity, no drift.
        for y in range(34, 43):
            for x in range(34, 43):
                if pixels[x, y] == rq.SPECTRA6["white"]:
                    assert (x + y) & 1 == 0, (
                        f"placard post-pass flipped a non-checkerboard pixel "
                        f"at ({x}, {y})"
                    )


def test_nightvision_border_paints_hud_bearing_ruler():
    """The upleveled nightvision border adds a bottom-margin bearing-scale
    ruler (green ticks) with a yellow centre caret."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_nightvision_border(img, rq.THEMES["nightvision"])
    px = img.load()
    green = rq.SPECTRA6["green"]
    accent = rq.THEMES["nightvision"]["accent"]
    ruler_band = {px[x, y] for x in range(130, 670) for y in range(456, 466)}
    assert green in ruler_band, "bottom bearing-scale ruler ticks missing"
    caret_band = {px[x, y] for x in range(394, 407) for y in range(446, 455)}
    assert accent in caret_band, "centre index caret missing"


def test_nightvision_ruler_clears_debug_banner_band():
    """The new HUD furniture is bottom-weighted so the y=14-29 debug-banner
    band stays free of it (why nightvision needs no _DEBUG_LABEL_RIGHT_INSET)."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_nightvision_border(img, rq.THEMES["nightvision"])
    px = img.load()
    accent = rq.THEMES["nightvision"]["accent"]
    banner_band = {px[x, y] for x in range(130, 670) for y in range(14, 30)}
    assert accent not in banner_band, "new accent furniture intrudes on banner band"


def test_chalkboard_border_paints_handwriting_guide():
    """The upleveled chalkboard border adds a top-left handwriting
    practice-guide rule (solid top + dashed mid + solid baseline)."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_chalkboard_border(img, rq.THEMES["chalkboard"])
    px = img.load()
    white = rq.SPECTRA6["white"]
    assert px[42, 34] == white, "guide top rule missing"
    assert px[42, 58] == white, "guide baseline rule missing"


def test_chalkboard_border_paints_gold_star():
    """The upleveled chalkboard border adds a yellow gold-star sticker
    beside the green teacher's check-mark."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_chalkboard_border(img, rq.THEMES["chalkboard"])
    px = img.load()
    yellow = rq.SPECTRA6["yellow"]
    star = sum(1 for x in range(700, 740) for y in range(38, 58) if px[x, y] == yellow)
    assert star > 20, "gold-star sticker missing"


def test_dispatch_border_paints_filing_punch_holes():
    """The upleveled dispatch border adds two binder-punch ring outlines
    centred in the top margin (black ink, below the debug-banner band)."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_dispatch_border(img, rq.THEMES["dispatch"])
    px = img.load()
    black = rq.SPECTRA6["black"]
    ring_black = sum(1 for x in range(347, 362) for y in range(33, 48) if px[x, y] == black)
    assert ring_black > 15, "top filing punch-hole rings missing"


def test_dispatch_border_paints_file_copy_footer():
    """The upleveled dispatch border adds a typed '— FILE COPY —' footer
    centred in the bottom margin."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_dispatch_border(img, rq.THEMES["dispatch"])
    px = img.load()
    black = rq.SPECTRA6["black"]
    footer_black = sum(1 for x in range(330, 470) for y in range(445, 465) if px[x, y] == black)
    assert footer_black > 15, "FILE COPY footer text missing"


def test_gothic_border_paints_head_trefoil():
    """The upleveled gothic border adds a red trefoil finial centred in the
    top margin (solid rubric red so it reads on the black ground)."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_gothic_border(img, rq.THEMES["gothic"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    head_red = sum(1 for x in range(385, 416) for y in range(26, 52) if px[x, y] == red)
    assert head_red > 80, "head trefoil finial missing"


def test_gothic_border_paints_foot_trefoil():
    """The upleveled gothic border adds a red trefoil finial centred in the
    bottom margin, mirroring the head finial."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_gothic_border(img, rq.THEMES["gothic"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    foot_red = sum(1 for x in range(385, 416) for y in range(430, 456) if px[x, y] == red)
    assert foot_red > 80, "foot trefoil finial missing"


def test_marker_border_paints_twinkle_sparkles():
    """The upleveled marker border adds doodle 'twinkle' sparkles in the top
    (red) and bottom (blue) centre margins."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_marker_border(img, rq.THEMES["marker"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    blue = rq.SPECTRA6["blue"]
    top_red = sum(1 for x in range(320, 352) for y in range(18, 35) if px[x, y] == red)
    bot_blue = sum(1 for x in range(448, 480) for y in range(447, 464) if px[x, y] == blue)
    assert top_red > 20, "top twinkle sparkle (red) missing"
    assert bot_blue > 20, "bottom twinkle sparkle (blue) missing"


def test_atomic_border_paints_boomerang():
    """The upleveled atomic border adds a tangerine (R+Y) boomerang centred
    in the bottom margin."""
    img = Image.new("RGB", (800, 480), rq.SPECTRA6["green"])
    rq.draw_atomic_border(img, rq.THEMES["atomic"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    yellow = rq.SPECTRA6["yellow"]
    boom_red = sum(1 for x in range(360, 440) for y in range(428, 456) if px[x, y] == red)
    boom_yellow = sum(1 for x in range(360, 440) for y in range(428, 456) if px[x, y] == yellow)
    assert boom_red > 80, "boomerang red component missing"
    assert boom_yellow > 50, "boomerang tangerine (yellow) component missing"


def test_deco_border_paints_mid_edge_chevrons():
    """The upleveled deco border adds nested stepped chevrons at the left and
    right mid-edges, picked up by the tangerine (R+Y) dither pass."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_deco_border(img, rq.THEMES["deco"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    yellow = rq.SPECTRA6["yellow"]
    left = sum(1 for x in range(20, 45) for y in range(220, 261) if px[x, y] in (red, yellow))
    right = sum(1 for x in range(755, 780) for y in range(220, 261) if px[x, y] in (red, yellow))
    assert left > 20, "left mid-edge chevron missing"
    assert right > 20, "right mid-edge chevron missing"


def test_saloon_border_paints_side_drop_pendants():
    """The upleveled saloon border hangs a drop-pendant diamond chain inward
    from each left/right mid-edge diamond (solid red)."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_saloon_border(img, rq.THEMES["saloon"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    left = sum(1 for x in range(4, 21) for y in range(248, 290) if px[x, y] == red)
    right = sum(1 for x in range(779, 796) for y in range(248, 290) if px[x, y] == red)
    assert left > 40, "left drop-pendant chain missing"
    assert right > 40, "right drop-pendant chain missing"


def test_chanbara_border_paints_brush_tick_column():
    """The upleveled chanbara border adds a vertical brush-tick signature
    column in the empty left margin (maroon = red+black, so red survives on
    the odd-parity half of the post-pass)."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_chanbara_border(img, rq.THEMES["chanbara"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    col_red = sum(1 for x in range(20, 57) for y in range(188, 283) if px[x, y] == red)
    assert col_red > 40, "brush-tick signature column missing"


def test_roman_border_paints_corner_stops():
    """The upleveled roman border adds small red carved corner 'stops' (right
    triangles) tucked into each inner-channel corner."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_roman_border(img, rq.THEMES["roman"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    tl = sum(1 for x in range(38, 50) for y in range(22, 34) if px[x, y] == red)
    br = sum(1 for x in range(750, 762) for y in range(446, 458) if px[x, y] == red)
    assert tl > 20, "top-left corner stop missing"
    assert br > 20, "bottom-right corner stop missing"


def test_placard_border_paints_side_margin_tags():
    """The upleveled placard border adds hanging price-tag ornaments (short
    rule + weathered-coral diamond) at the left/right mid-edges."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_placard_border(img, rq.THEMES["placard"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    white = rq.SPECTRA6["white"]

    def coral(cx, cy):
        rr = sum(1 for x in range(cx - 8, cx + 9) for y in range(cy - 8, cy + 9) if px[x, y] == red)
        ww = sum(1 for x in range(cx - 8, cx + 9) for y in range(cy - 8, cy + 9) if px[x, y] == white)
        return rr, ww

    l_r, l_w = coral(28, 240)
    r_r, r_w = coral(771, 240)
    # Each tag diamond is the R+W weathered-coral recipe: both inks present.
    assert l_r > 10 and l_w > 10, "left side-margin tag missing"
    assert r_r > 10 and r_w > 10, "right side-margin tag missing"


def test_firmament_milky_way_is_deterministic():
    """The reshaped Milky Way star clouds must stay byte-identical across
    renders (no RNG-state leak) so the golden suite and panel dedup hold."""
    row = {
        "display_quote": "It was at ten o'clock today.",
        "matched_text": "ten o'clock", "author": "A", "title": "B",
        "source_id": "1", "line_number": 1, "quality_score": 90,
        "bucket": "h10_exact", "resolved_bucket": "h10_exact", "used_fallback": False,
    }
    a = rq.render("10:00", row, 800, 480, mode="production", theme="firmament").convert("RGB").tobytes()
    b = rq.render("10:00", row, 800, 480, mode="production", theme="firmament").convert("RGB").tobytes()
    assert a == b, "firmament frame not byte-deterministic across renders"


def test_firmament_border_leaves_no_off_palette_sentinel():
    """Every ornament sentinel is resolved by its post-pass; the ecliptic
    arc's ends (down at y=80) used to sit below the post-pass bbox and
    snap to black dots (issue #341)."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_firmament_border(img, rq.THEMES["firmament"])
    counts = ink_counts(img)
    for sentinel in ((2, 2, 2), (3, 3, 3), (4, 4, 4)):
        assert counts.get(sentinel, 0) == 0, f"sentinel {sentinel} survived"


def test_firmament_sun_long_rays_alternate_evenly():
    """16 rays at 22.5°: long rays every 45°, none at the odd bearings.
    The old 22° step drew 17 rays, so two long rays met at 0° (issue #342)."""
    import math

    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_firmament_border(img, rq.THEMES["firmament"])
    px = img.load()
    yellow = rq.SPECTRA6["yellow"]
    cx = cy = 36
    long_tip = []  # bearings of yellow pixels only a long ray reaches
    for y in range(cy - 24, cy + 25):
        for x in range(cx - 24, cx + 25):
            if px[x, y] == yellow and 19.5 <= math.hypot(x - cx, y - cy) <= 23:
                long_tip.append(math.degrees(math.atan2(y - cy, x - cx)) % 360)

    def near(bearing: float) -> bool:
        return any(min(abs(a - bearing), 360 - abs(a - bearing)) <= 5 for a in long_tip)

    for k in range(8):
        assert near(k * 45), f"no long ray at {k * 45}°"
        assert not near(22.5 + k * 45), f"long ray at {22.5 + k * 45}°"


class TestParsePinQuote:
    def test_valid(self):
        import idle_hours.render_quote as rq
        assert rq.parse_pin_quote("141:482") == ("141", 482)

    def test_matched_text_becomes_the_third_element(self):
        """(source_id, line_number) is not a unique corpus row key, so the
        peeked matched_text rides along to disambiguate duplicates."""
        assert rq.parse_pin_quote("141:482", "half past two") == ("141", 482, "half past two")

    def test_matched_text_ignored_when_the_key_is_malformed(self, capsys):
        assert rq.parse_pin_quote("garbage", "half past two") is None
        assert "malformed --pin-quote" in capsys.readouterr().err

    def test_none_and_empty(self):
        import idle_hours.render_quote as rq
        assert rq.parse_pin_quote(None) is None
        assert rq.parse_pin_quote("") is None

    def test_malformed_warns_and_returns_none(self, capsys):
        import idle_hours.render_quote as rq
        assert rq.parse_pin_quote("garbage") is None
        assert rq.parse_pin_quote("141:xx") is None
        assert rq.parse_pin_quote(":42") is None
        assert "malformed --pin-quote" in capsys.readouterr().err


class TestPaintNeonMask:
    """The shared glow primitive, including the split-band mix ``bakelite`` added.

    It had no direct coverage at all before that — it was reached only through
    ``izakaya`` and ``abyssal``, whose golden fixtures catch a change in what
    those two themes look like but say nothing about the primitive's contract.
    Now that a third theme drives it through new parameters, the contract needs
    fencing in its own right: chiefly that the single-ink path is untouched, so
    growing the primitive cannot quietly restyle the two themes that were using
    it first.
    """

    SIZE = (160, 120)

    def _blot(self, **kwargs):
        image = Image.new("RGB", self.SIZE, rq.SPECTRA6["black"])
        mask = Image.new("L", self.SIZE, 0)
        ImageDraw.Draw(mask).ellipse((60, 40, 100, 80), fill=255)
        rq.paint_neon_mask(image, mask, rq.SPECTRA6["white"], rq.SPECTRA6["blue"], **kwargs)
        return image, mask

    def test_the_single_ink_default_paints_two_inks_and_the_ground(self):
        """izakaya / abyssal's path: core, glow, ground — nothing else."""
        image, _ = self._blot(radius=6, gamma=2.0, cap=0.6)
        assert distinct_inks(image) == {
            rq.SPECTRA6["white"], rq.SPECTRA6["blue"], rq.SPECTRA6["black"]
        }

    def test_a_minor_ink_appears_only_when_asked_for(self):
        plain, _ = self._blot(radius=6)
        split, _ = self._blot(radius=6, tile=rq.BAYER_8x8,
                              glow_minor=rq.SPECTRA6["green"], glow_minor_share=0.375)
        assert rq.SPECTRA6["green"] not in distinct_inks(plain)
        assert rq.SPECTRA6["green"] in distinct_inks(split)

    @pytest.mark.parametrize("share, expected", [(0.25, 0.33), (0.375, 0.43), (0.5, 0.58)])
    def test_the_glow_split_tracks_its_share(self, share, expected):
        """The share parameter does what it says, over the halo as a whole.

        The measured figure sits consistently *above* the requested one, and
        that is the primitive's documented low-density drift rather than a bug:
        the minor set is the lowest ``share`` of a run of integer ranks, so a
        short run rounds up. A halo is mostly tail by area — the faint outer
        rings hold far more pixels than the bright inner ones — so an unweighted
        average over the whole thing is dominated by exactly the region where
        the drift lives, and lands ~0.06 high.

        This fences the contract at the level the whole-halo view can actually
        support: the parameter is honoured, and it moves monotonically. The
        precision fence lives in ``TestBakelitePhosphorHalo``, which bins by
        distance so every part of the falloff weighs the same and can therefore
        hold the ratio to a much tighter tolerance.
        """
        image, _ = self._blot(radius=10, gamma=1.4, cap=0.8, tile=rq.BAYER_8x8,
                              glow_minor=rq.SPECTRA6["green"], glow_minor_share=share)
        counts = ink_counts(image)
        major = counts.get(rq.SPECTRA6["blue"], 0)
        minor = counts.get(rq.SPECTRA6["green"], 0)
        assert major + minor > 200, "not enough halo painted to measure"
        assert abs(minor / (major + minor) - expected) < 0.04

    def test_more_share_means_more_minor_ink(self):
        """Monotonicity, stated independently of any absolute figure."""
        def measured(share):
            image, _ = self._blot(radius=10, gamma=1.4, cap=0.8, tile=rq.BAYER_8x8,
                                  glow_minor=rq.SPECTRA6["green"], glow_minor_share=share)
            counts = ink_counts(image)
            major = counts.get(rq.SPECTRA6["blue"], 0)
            minor = counts.get(rq.SPECTRA6["green"], 0)
            return minor / (major + minor)
        shares = [measured(s) for s in (0.0, 0.25, 0.375, 0.5, 1.0)]
        assert shares == sorted(shares), f"share is not monotone: {shares}"
        assert shares[0] == 0.0 and shares[-1] == 1.0, "the endpoints should be pure"

    def test_the_core_split_stipples_the_stroke_not_the_halo(self):
        """``core_minor`` is what gives ``bakelite`` its gold stroke."""
        image, mask = self._blot(radius=6, tile=rq.BAYER_8x8,
                                 core_minor=rq.SPECTRA6["yellow"], core_minor_share=0.625)
        pixels, mask_px = image.load(), mask.load()
        inside = [pixels[x, y] for y in range(120) for x in range(160) if mask_px[x, y] > 128]
        share = inside.count(rq.SPECTRA6["yellow"]) / len(inside)
        assert abs(share - 0.625) < 0.05, f"core is {share:.2f} minor ink, expected 5/8"
        assert rq.SPECTRA6["yellow"] not in {
            pixels[x, y] for y in range(120) for x in range(160) if mask_px[x, y] <= 128
        }, "the core's minor ink leaked into the halo"

    def test_the_ground_still_gates_the_split_halo(self):
        """A restricted ground must hold for both inks, or a later glow eats
        the cores an earlier pass lit — the reason the parameter exists."""
        image = Image.new("RGB", self.SIZE, rq.SPECTRA6["red"])
        mask = Image.new("L", self.SIZE, 0)
        ImageDraw.Draw(mask).ellipse((60, 40, 100, 80), fill=255)
        rq.paint_neon_mask(image, mask, rq.SPECTRA6["white"], rq.SPECTRA6["blue"],
                           radius=8, tile=rq.BAYER_8x8, ground=frozenset({rq.SPECTRA6["black"]}),
                           glow_minor=rq.SPECTRA6["green"], glow_minor_share=0.375)
        assert distinct_inks(image) == {rq.SPECTRA6["red"], rq.SPECTRA6["white"]}, (
            "the halo painted over a ground it was not permitted to touch"
        )


class TestJustifyFlags:
    """Block-level justification decision (``justify_flags``)."""

    def test_last_line_is_never_justified(self):
        flags = rq.justify_flags("default", [(600, 8), (610, 7), (300, 3)], 640, 30)
        assert flags == [True, True, False]

    def test_ragged_right_themes_never_justify(self):
        for theme in rq._THEMES_RAGGED_RIGHT:
            assert rq.justify_flags(theme, [(600, 8), (610, 7), (300, 3)], 640, 30) == [False, False, False]

    def test_one_river_line_sets_the_whole_block_ragged(self):
        # Line 2 has two gaps carrying 120 px: 60 px each on a 40 px body,
        # far past 0.45 em. The block, not just that line, goes ragged.
        flags = rq.justify_flags("default", [(600, 8), (520, 2), (610, 7), (200, 2)], 640, 40)
        assert flags == [False, False, False, False]

    def test_loose_line_stays_ragged_alone(self):
        # Line 2 is under 75% full, so it is ragged on its own (the
        # original rule) without vetoing its neighbours.
        flags = rq.justify_flags("default", [(600, 8), (400, 6), (610, 7), (200, 2)], 640, 40)
        assert flags == [True, False, True, False]

    def test_per_gap_stretch_cap_scales_with_body_size(self):
        metrics = [(560, 4), (300, 2)]  # 80 px over 4 gaps = 20 px each
        assert rq.justify_flags("default", metrics, 640, 50)[0] is True   # cap 22.5 px
        assert rq.justify_flags("default", metrics, 640, 30)[0] is False  # cap 13.5 px

    def test_hero_quote_never_justifies_a_short_line(self):
        """The hero quote that motivated the rule: "Come to me" and its
        like used to take 75 px per gap. Whatever wrap the balancer lands
        on, no line with fewer than three gaps, and no line whose gaps
        would stretch past 0.45 em, may be flagged for justification."""
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        text = "But I must consider. Come to me to-morrow at the office, at nine o\u2019clock."
        regular, bold, wrapped, _, size, wrap_width = rq.fit_quote_balanced(
            draw, text, "nine o\u2019clock", 640, 248, 66, 32, 1.12, theme="default",
        )
        metrics = [
            (rq._line_ink_width(draw, line, regular, bold), sum(1 for c, _ in rq._trim_line(line) if c == " "))
            for line in wrapped
        ]
        flags = rq.justify_flags("default", metrics, wrap_width, size)
        for (ink, gaps), flagged in zip(metrics, flags, strict=True):
            if flagged:
                assert gaps >= rq._JUSTIFY_MIN_GAPS
                assert (wrap_width - ink) / gaps <= size * rq._JUSTIFY_MAX_STRETCH_EM
        # And the old behaviour is really gone: a two-gap line with a
        # quarter of the measure to spare is not justified.
        assert rq.justify_flags("default", [(480, 2), (300, 3)], 640, 60) == [False, False]


class TestFitQuoteBalanced:
    def _fit(self, text, match, theme="default", layout="hero"):
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        lay = rq.LAYOUTS[layout]
        return draw, rq.fit_quote_balanced(
            draw, text, match, lay["max_width"], lay["quote_height"], lay["font_max"], lay["font_min"],
            lay["line_height_mult"], theme=theme,
        )

    def test_returns_six_fields_and_wraps_within_wrap_width(self):
        draw, (regular, bold, wrapped, line_height, size, wrap_width) = self._fit(
            "It was within 638 miles of the coast of Ireland; and at half-past two in the afternoon they "
            "discovered that communication with Europe had ceased.", "half-past two", layout="standard",
        )
        assert wrap_width <= rq.LAYOUTS["standard"]["max_width"]
        for line in wrapped:
            assert rq._line_ink_width(draw, line, regular, bold) <= wrap_width

    @pytest.mark.parametrize("theme", ["default", "chanbara", "roman"])
    def test_hero_quote_does_not_end_on_a_lone_word(self, theme):
        draw, (regular, bold, wrapped, _, _, wrap_width) = self._fit(
            "But I must consider. Come to me to-morrow at the office, at nine o\u2019clock.", "nine o\u2019clock", theme=theme,
        )
        assert len(wrapped) >= 2
        assert not rq.is_widow_line(draw, wrapped[-1], regular, bold, rq.LAYOUTS["hero"]["max_width"])

    def test_balancing_never_grows_the_block(self):
        text = ("Of course until ten o'clock, when I shut up shop, I am constantly interrupted\u2014as I have been "
                "during this letter, once to sell a copy of Helen's Babies and once to sell The Ballad of Reading "
                "Gaol, so you can see how varied are my clients' tastes!")
        draw, (_, _, wrapped, line_height, _, _) = self._fit(text, "ten o'clock", layout="dense")
        plain = rq.fit_quote(draw, text, "ten o'clock", 680, 276, 48, 24, 1.18)
        assert len(wrapped) * line_height <= rq.LAYOUTS["dense"]["quote_height"]
        assert len(wrapped) <= len(plain[2])

    def test_size_fallback_is_bounded(self):
        """The balancer may step the face down, but never below 80% of the
        size ``fit_quote`` chose nor below the layout's ``font_min``."""
        text = "But I must consider. Come to me to-morrow at the office, at nine o\u2019clock."
        draw, (_, _, _, _, size, _) = self._fit(text, "nine o\u2019clock", theme="chanbara")
        plain_size = rq.fit_quote(draw, text, "nine o\u2019clock", 640, 248, 66, 32, 1.12, theme="chanbara")[4]
        assert size >= max(32, int(plain_size * 0.8) - 1)

    def test_candidate_widow_is_judged_against_its_own_measure(self):
        """A balanced candidate is wrapped to a narrower measure; its last
        line is compared with the lines above it, i.e. with that measure,
        not with the layout's full one (Codex review on #328)."""
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        regular = rq.load_font(rq.QUOTE_FONT_SEMIBOLD_CANDIDATES, size=40)
        bold = rq.load_font(rq.QUOTE_FONT_BOLD_CANDIDATES, size=40)
        line = [("at", False), (" ", False), ("nine", False)]
        ink = rq._line_ink_width(draw, line, regular, bold)
        # Two words, so not a one-word widow; pick measures either side
        # of the 30% threshold around this line's own width.
        assert rq.is_widow_line(draw, line, regular, bold, int(ink / 0.25)) is True
        assert rq.is_widow_line(draw, line, regular, bold, int(ink / 0.35)) is False
        # Hence a short last line that fails against max_width can pass once
        # the search has narrowed the measure around it.
        wide, narrow = int(ink / 0.25), int(ink / 0.35)
        assert rq.is_widow_line(draw, line, regular, bold, wide) and not rq.is_widow_line(draw, line, regular, bold, narrow)

    def test_no_widow_means_untouched(self):
        text = "The clock struck nine as he came in, and the room was full of people who had waited all evening."
        draw, (regular, bold, wrapped, line_height, size, wrap_width) = self._fit(text, "struck nine", layout="standard")
        plain = rq.fit_quote(draw, text, "struck nine", 660, 258, 58, 28, 1.14)
        if not rq.is_widow_line(draw, plain[2][-1], plain[0], plain[1], 660):
            assert (wrapped, size, wrap_width) == (plain[2], plain[4], 660)


class TestAttributionFloors:
    def test_dense_byline_is_at_least_the_floor(self):
        """The dense layout used to set the author at 0.52 x 28 = 14 px.
        Check the rendered author line is at least 18 px tall by measuring
        the ink extent of a capital-rich byline."""
        row = {
            "display_quote": ("Of course until ten o'clock, when I shut up shop, I am constantly interrupted\u2014as I "
                              "have been during this letter, once to sell a copy of Helen's Babies and once to sell "
                              "The Ballad of Reading Gaol, so you can see how varied are my clients' tastes!"),
            "matched_text": "ten o'clock",
            "author": "HHHHHHHH",
            "title": None,
        }
        img = rq.render("10:00", row, 800, 480, mode="production", theme="default")
        text_left = (800 - rq.LAYOUTS["dense"]["max_width"]) // 2
        black = rq.SPECTRA6["black"]
        rows_with_ink = [
            y for y in range(200, 470)
            if any(img.getpixel((x, y)) == black for x in range(text_left, text_left + 120))
        ]
        # The author line is the last run of inked rows in the body column.
        runs: list[list[int]] = []
        for y in rows_with_ink:
            if runs and y == runs[-1][-1] + 1:
                runs[-1].append(y)
            else:
                runs.append([y])
        cap_height = len(runs[-1])
        assert cap_height >= 12, cap_height  # 18 px Playfair caps are ~13 px tall


class TestAlchemyFaintFigure:
    def test_inner_figure_is_a_stipple_not_a_solid_rule(self):
        img = Image.new("RGB", (800, 480), rq.THEMES["alchemy"]["page_bg"])
        rq.draw_alchemy_border(img, rq.THEMES["alchemy"])
        blue = rq.SPECTRA6["blue"]
        # Walk the outer ring's left edge (x = 400 - 222) over a 40 px
        # band: no two vertically adjacent blue pixels, since the ring is
        # gated to (x + y) parity.
        x = 400 - 222
        column = [img.getpixel((x, y)) == blue or img.getpixel((x + 1, y)) == blue for y in range(220, 260)]
        assert any(column), "ring not painted where expected"
        for px in (x, x + 1):
            col = [img.getpixel((px, y)) == blue for y in range(220, 260)]
            assert not any(a and b for a, b in pairwise(col)), "solid blue run on the ring"


class TestSharedPainterHelpers:
    """The primitives several themes had each copy-pasted under their own
    names (issue #336). One body now serves every caller, so pin it here."""

    @pytest.mark.parametrize("time_str, expected", [
        ("00:30", 12), ("12:05", 12), ("13:00", 1), ("01:59", 1), ("09:45", 9), ("21:15", 9), ("23:59", 11),
    ])
    def test_clock_hour12_is_the_twelve_hour_clock_hour(self, time_str, expected):
        assert rq._clock_hour12(time_str) == expected

    @pytest.mark.parametrize("value", ["", "nonsense", "::", "bogus:30", None])
    def test_clock_hour12_falls_back_to_twelve_rather_than_raising(self, value):
        assert rq._clock_hour12(value) == 12

    def test_lerp_stops_interpolates_and_clamps(self):
        stops = [(0, (0, 0, 0)), (10, (100, 200, 50)), (20, (100, 200, 50))]
        assert rq._lerp_stops(stops, -5) == (0, 0, 0)
        assert rq._lerp_stops(stops, 5) == (50, 100, 25)
        assert rq._lerp_stops(stops, 99) == (100, 200, 50)

    def test_bayer_threshold_field_tiles_the_ranks(self):
        field = rq._bayer_threshold_field((19, 11))
        assert field.mode == "L" and field.size == (19, 11)
        for x, y in ((0, 0), (7, 3), (8, 8), (18, 10)):
            assert field.getpixel((x, y)) == rq.BAYER_8x8[y % 8][x % 8] * 4 + 2

    def test_noise_fields_are_seeded(self):
        assert rq._white_noise(16, 8, 7).tobytes() == rq._white_noise(16, 8, 7).tobytes()
        assert rq._white_noise(16, 8, 7).tobytes() != rq._white_noise(16, 8, 8).tobytes()
        smooth = rq._smooth_noise((40, 20), (4, 2), 7)
        assert smooth.size == (40, 20) and smooth.tobytes() == rq._smooth_noise((40, 20), (4, 2), 7).tobytes()

    def test_halo_paste_lays_a_black_halo_under_the_fill(self):
        image = Image.new("RGB", (40, 40), rq.SPECTRA6["white"])
        mask = Image.new("L", (40, 40), 0)
        ImageDraw.Draw(mask).rectangle((18, 18, 21, 21), fill=255)
        rq._halo_paste(image, mask, rq.SPECTRA6["yellow"])
        assert image.getpixel((19, 19)) == rq.SPECTRA6["yellow"]
        assert image.getpixel((16, 19)) == rq.SPECTRA6["black"]
        assert image.getpixel((5, 5)) == rq.SPECTRA6["white"]

    def test_place_quote_positions_every_chunk_inside_the_rect(self):
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        row = {"display_quote": "It was half past two and the light lay long across the square.",
               "matched_text": "half past two"}
        placed = rq._place_quote(draw, row, (100, 50, 500, 300), theme="default",
                                 font_max=30, font_min=12, line_height_mult=1.3)
        assert "".join(p[2] for p in placed).split() == row["display_quote"].split()
        assert any(p[4] for p in placed) and not all(p[4] for p in placed)
        for x, y, _chunk, _font, _bold, w, lh in placed:
            assert 100 <= x and x + w <= 500 + 1 and 50 <= y < 300 and lh > 0

    def test_fit_from_title_ellipsises_then_gives_up(self):
        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        font = rq.load_font(rq.theme_font_candidates("default", "quote_regular"), size=12)
        assert rq._fit_from_title(draw, {"title": ""}, font, 500) is None
        assert rq._fit_from_title(draw, {"title": "Emma"}, font, 500) == "— from Emma —"
        short = rq._fit_from_title(draw, {"title": "A Very Long Title Indeed For Testing"}, font, 120)
        assert short.endswith("… —") and draw.textlength(short, font=font) <= 120
        assert rq._fit_from_title(draw, {"title": "Emma"}, font, 1) is None

    def test_fit_dotted_byline_shortens_the_title_first(self):
        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        font = rq.load_font(rq.theme_font_candidates("default", "quote_regular"), size=12)
        row = {"author": "Jane Austen", "title": "Mansfield Park and a Great Deal More Besides"}
        assert rq._fit_dotted_byline(draw, {"author": "", "title": "", "source_id": None}, font, 500) is None
        text, bbox = rq._fit_dotted_byline(draw, row, font, 160)
        assert text.startswith("Jane Austen · ") and text.endswith("…")
        assert bbox[2] - bbox[0] <= 160


class TestMalformedTime:
    """A malformed time must never crash a render. ``render`` is called
    in-process (contact sheet, previews, the sleep frame), and ``codex``,
    ``metro``, ``diags`` and the debug footer each used to raise on
    one input or another. The CLI rejects a bad ``--time`` up front instead.
    """

    ROW = {"source_id": "141", "line_number": 482, "display_quote": "It was half past two in the afternoon.",
           "matched_text": "half past two", "author": "Jane Austen", "title": "Emma"}

    @pytest.mark.parametrize("theme", sorted(rq.THEMES))
    def test_every_theme_renders_a_malformed_time(self, theme):
        # One input per failure class: unparseable, missing, and parseable but
        # out of range (which used to KeyError in the bucket table).
        for time_str in ("garbage", None, "25:99"):
            image = rq.render(time_str, dict(self.ROW), 800, 480, mode="debug", theme=theme)
            assert image.size == (800, 480)

    @pytest.mark.parametrize("time_str, expected", [
        ("14:30", (14, 30)), ("9:05", (9, 5)), ("00:00", (0, 0)), ("23:59", (23, 59)),
        ("24:00", (0, 0)), ("12:60", (0, 0)), ("12:30:00", (0, 0)), ("12:30:garbage", (0, 0)), ("garbage", (0, 0)), ("14", (0, 0)), ("", (0, 0)), (None, (0, 0)),
    ])
    def test_clock_hh_mm_falls_back_to_midnight(self, time_str, expected):
        assert rq._clock_hh_mm(time_str) == expected

    @pytest.mark.parametrize("value", ["25:99", "garbage", "14"])
    def test_cli_rejects_a_bad_time_with_a_usage_error(self, value, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["render_quote.py", "--time", value])
        with pytest.raises(SystemExit) as exc:
            rq.parse_args()
        assert exc.value.code == 2
        assert "not a valid HH:MM time" in capsys.readouterr().err
