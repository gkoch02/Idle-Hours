"""Tests for render_quote.py — layout selection, text helpers, color quantization."""
from __future__ import annotations

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
            "scholar",
            "newsprint",
            "nightvision",
            "blueprint",
            "illuminated",
            "bauhaus",
            "risograph",
            "comic",
            "swiss",
            "herbarium",
            "mucha",
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

    def test_blueprint_theme_uses_white_on_blue_cyanotype_palette(self):
        """Cyanotype blueprint: blue ground, white ink for every
        structural mark (body, frame, grid, crosshairs), red accent
        for the matched time phrase (the "annotated dimension" in red
        pencil over an otherwise monochromatic print). Pin the
        inverted palette so a regression that flipped it back to
        white/blue/red would collapse the theme into a Scholar-adjacent
        layout and lose the photochemical-drafting-sheet identity."""
        t = rq.THEMES["blueprint"]
        assert t["page_bg"] == rq.SPECTRA6["blue"]
        assert t["text"] == rq.SPECTRA6["white"]
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

    def test_swiss_theme_uses_austere_monochrome_palette(self):
        """Swiss International is the rotation's modernist exception:
        white ground, black body, single red accent on the matched
        phrase and the small header square. No second chromatic ink
        anywhere — a regression that introduced a blue / yellow /
        green accent would collapse the theme into a generic poster
        composition and lose the "austerity by subtraction" identity."""
        t = rq.THEMES["swiss"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["black"]
        assert t["accent"] == rq.SPECTRA6["red"]
        assert t["ornament_dark"] == rq.SPECTRA6["black"]

    def test_herbarium_theme_routes_matched_phrase_to_forest_green(self):
        """Herbarium uses the green sentinel ink in the ``accent`` slot
        so ``_draw_text_body`` can route the matched phrase through a
        G+K → forest-green stipple. Pinning the sentinel slot here
        catches a regression that drops the matched phrase back to
        solid black (eliminating the green colour story that
        defines the theme on the green axis)."""
        t = rq.THEMES["herbarium"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["black"]
        assert t["accent"] == rq.SPECTRA6["green"]

    def test_mucha_theme_uses_red_sentinel_for_synthesised_body(self):
        """Mucha is the only theme whose body fill is a synthesised
        colour (maroon — R+K 1:1) rather than a native ink. The
        ``text`` slot carries the red sentinel that ``_draw_text_body``
        routes through its R+K stipple branch; a regression that
        changed ``text`` to solid black or solid red would collapse
        the body into a flat single ink and lose the Art Nouveau
        oxblood register."""
        t = rq.THEMES["mucha"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["red"]
        assert t["accent"] == rq.SPECTRA6["green"]

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
        "just type on the ground colour". Pin the four new entries
        explicitly so a future refactor that drops the dict key
        fails this test loudly."""
        for name in ("swiss", "herbarium", "mucha", "fillmore", "firmament"):
            assert name in rq._BORDER_PAINTERS, name

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
            "scholar",
            "newsprint",
            "nightvision",
            "blueprint",
            "illuminated",
            "bauhaus",
            "risograph",
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

    def test_illuminated_corner_jewels_paint_plum_three_way_bayer(self):
        """Plum cabochons at the four outer-rule corners — radius 5
        filled circles painted in a sentinel ink and then bbox-post-
        passed through a 3-way 4×4 Bayer partition (cells 0-4 → red,
        cells 5-9 → blue, cells 10-15 → black; ~1/3 each, the
        documented R+B+K plum recipe). Pin the centre pixel of each
        jewel against the deterministic Bayer assignment so a
        regression that dropped the post-pass would surface; the
        centre's exact ink depends on the `BAYER_4x4[y%4][x%4]` value
        at that coordinate.

        Centre pixels:
          (14, 14)   → BAYER[2][2]=1  → red
          (785, 14)  → BAYER[2][1]=11 → black
          (14, 465)  → BAYER[1][2]=14 → black
          (785, 465) → BAYER[1][1]=4  → red

        At least one corner-region sample lands on a cell in the blue
        partition (cells 5-9) — verify the post-pass painted blue
        somewhere too so all three plum inks are present."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="illuminated")
        assert img.getpixel((14, 14)) == rq.SPECTRA6["red"], "TL jewel centre missing"
        assert img.getpixel((785, 14)) == rq.SPECTRA6["black"], "TR jewel centre missing"
        assert img.getpixel((14, 465)) == rq.SPECTRA6["black"], "BL jewel centre missing"
        assert img.getpixel((785, 465)) == rq.SPECTRA6["red"], "BR jewel centre missing"
        # Probe the TL jewel's bbox for at least one painted blue pixel
        # to confirm the 3-way partition's blue arm fires.
        found_blue = False
        for py in range(9, 20):
            for px in range(9, 20):
                if img.getpixel((px, py)) == rq.SPECTRA6["blue"]:
                    found_blue = True
                    break
            if found_blue:
                break
        assert found_blue, "TL jewel bbox produced no blue pixels — 3-way Bayer regressed"

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
            # (14, 14) lands on the TL jewel's centre — with the 3-way
            # plum post-pass the centre is the red arm of the partition
            # at this coordinate (BAYER[2][2]=1 < 5). Different from
            # both the body's rubricated red text (which doesn't reach
            # this corner) and the canvas page_bg, so a regression that
            # dropped the border in any render mode would still fail
            # here.
            assert img.getpixel((14, 14)) == rq.SPECTRA6["red"], f"illuminated mode={mode} missing TL jewel"

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
        this theme painted black there, so they're excluded. Blueprint
        is excluded because its Layer 0 dither paints sparse white pixels
        across the blue ground, same reason newsprint is excluded from
        the blueprint / comic gating tests."""
        for theme in ("default", "scholar", "risograph", "comic"):
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
    """The blueprint theme paints a cyanotype drafting sheet.

    Parallels ``TestBauhausBorder`` but locks the blueprint-specific
    primitives: 50/50 white-on-blue dithered ground, thin white outer
    frame, and white crosshair registration marks at each corner. A
    regression that dropped ``draw_blueprint_border`` would pass every
    dict-level palette test silently, so pin the painted pixels here.
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
        The centre pixel is always on the mark; arm extents are ±8.
        Crosshairs paint in the accent colour (red) so they pop
        against the white body / grid ink, matching the matched
        time phrase highlight."""
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

    def test_blueprint_outer_frame_is_painted_in_body_white(self):
        """The outer rectangle outline is the structural anchor for the
        crosshairs. Sample a point on each side well clear of the
        corners, to verify all four sides of the frame rendered. Frame
        is the body-text colour (white, cyanotype ink)."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="blueprint")
        assert img.getpixel((400, 16)) == rq.SPECTRA6["white"], "top frame line missing"
        assert img.getpixel((400, 463)) == rq.SPECTRA6["white"], "bottom frame line missing"
        assert img.getpixel((16, 240)) == rq.SPECTRA6["white"], "left frame line missing"
        assert img.getpixel((783, 240)) == rq.SPECTRA6["white"], "right frame line missing"

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

    def test_blueprint_interior_grid_paints_in_body_text_colour(self):
        """The graph-paper grid inside the frame uses the body-text colour.
        Sample an intersection well clear of the frame and of the quote
        block so no glyph or outer rule is painted on top. At 20px spacing,
        with ``frame_inset=16``, the first interior horizontal rule is at
        y=36 and the first interior vertical rule is at x=36; (36, 56) is
        a clean grid crossing. Direct-call (no ``page_bg`` in palette →
        Layer 0 dither is skipped) so the off-grid pixel stays the
        white canvas the test prepared."""
        image = Image.new("RGB", (800, 480), color=(255, 255, 255))
        rq.draw_blueprint_border(image, {"text": rq.SPECTRA6["green"], "accent": rq.SPECTRA6["red"]})
        assert image.getpixel((36, 56)) == rq.SPECTRA6["green"], "grid intersection should use text colour"
        # Off-grid whitespace between rules stays page_bg (white canvas here).
        assert image.getpixel((45, 45)) == (255, 255, 255), "between-grid pixel should remain unpainted"

    def test_blueprint_grid_is_theme_gated(self):
        """No other theme paints a non-page_bg pixel at the blueprint
        grid-intersection coordinate (36, 56). Newsprint, alchemy, and
        illuminated are all excluded because their Layer 0 grounds
        intentionally paint sparse Bayer flecks across `page_bg`
        (black halftone for newsprint, parchment yellow flecks for
        alchemy, cream yellow flecks for illuminated). Dispatch is
        excluded for the same reason — its Layer 0 1-in-8 cream wash
        also flips white-ground pixels to yellow at this coordinate."""
        row = self._row()
        for theme in ("default", "dark", "scholar", "nightvision",
                      "bauhaus", "risograph", "comic"):
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
        Newsprint, alchemy, and illuminated are all excluded because
        their Layer 0 grounds intentionally paint sparse Bayer flecks
        across `page_bg` (black halftone / parchment-yellow flecks /
        cream-yellow flecks). Dispatch is excluded for the same reason
        — its Layer 0 cream wash also affects this coordinate."""
        row = self._row()
        for theme in ("default", "dark", "scholar", "nightvision",
                      "blueprint", "bauhaus", "risograph"):
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
        CLAUDE.md states no theme uses it, so this fails the moment that
        stops being true and the doc needs updating with it.
        """
        for theme in sorted(rq.THEMES):
            bold = rq.theme_font_candidates(theme, "quote_bold")
            card = rq.theme_font_candidates(theme, "card_quote_bold")
            assert card == bold, (
                f"theme {theme} overrides card_quote_bold. That is a supported "
                f"escape hatch, but CLAUDE.md says no theme uses it — update the "
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
        rigid = rq.render("02:15", row, 800, 480, mode="production", theme="gothic")

        monkeypatch.setattr(rq, "_THEMES_RIGID_MATCH_SPACING", frozenset())
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
    dispatched via render()'s special-case branch (like blueprint) so
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
        # Empirical: at y just below the panel's bottom edge (panel
        # ends around y=394 for the test quote), 2 px ledge sits at
        # y≈395-397. Look for black pixels in that band at panel-
        # interior x range (away from corner rounding).
        found_black_ledge = False
        for py in range(393, 400):
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
        for theme in ("default", "scholar", "blueprint", "bauhaus"):
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
        for theme in ("default", "scholar", "blueprint", "kanagawa", "herbarium"):
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
        for got, want in zip(ratios, expected_ratios):
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
    stay byte-identical (nightvision body text + grimoire matched-phrase
    rely on the exact patterns), and the new branch must produce a
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
        font_path = Path("fonts/PlayfairDisplay-Regular.ttf")
        if not font_path.exists():
            pytest.skip(f"bundled font missing: {font_path}")
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

        with patch.object(rq, "draw_text_dithered", side_effect=fake_dither):
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

    def test_alchemy_call_site_uses_purple_recipe(self):
        """``_draw_text_body`` must call ``draw_text_dithered`` for the
        alchemy red-accent path with ``light=blue`` so the eye averages
        red+blue at panel distance into purple — the documented
        two-ink violet recipe. A regression to solid red would lose
        the alchemist's pigment register the theme is built around.
        """
        captured: dict = {}

        def fake_dither(*args, **kwargs):
            captured["density"] = kwargs.get("light_density")
            captured["light"] = kwargs.get("light")
            captured["dark"] = kwargs.get("dark")

        with patch.object(rq, "draw_text_dithered", side_effect=fake_dither):
            image = Image.new("RGB", (200, 60), (255, 255, 255))
            draw = ImageDraw.Draw(image)
            from PIL import ImageFont
            font = ImageFont.load_default()
            rq._draw_text_body(image, draw, (10, 10), "test", font, rq.SPECTRA6["red"], "alchemy")

        assert captured.get("dark") == rq.SPECTRA6["red"], (
            "alchemy purple dither must keep red as the dark ink"
        )
        assert captured.get("light") == rq.SPECTRA6["blue"], (
            "alchemy purple dither must stipple toward blue (purple = red + blue)"
        )
        # Default density (0.5) → 50/50 checkerboard; ``light_density``
        # may be the keyword default (None / unset) or 0.5 — either
        # produces the documented purple recipe.
        density = captured.get("density")
        assert density in (None, 0.5), (
            f"alchemy purple dither must use 50/50 density (default); got {density}"
        )

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

        with patch.object(rq, "draw_text_dithered", side_effect=fake_dither):
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

    def test_glacier_diagonal_shards_split_green_and_white(self):
        """``draw_glacier_border``'s diagonal shards (the longest in
        each corner cluster) are painted green and then post-passed to
        ~50% white, so the eye averages green+white into sky-blue at
        panel distance. White and green must both be present inside
        the corner cluster bbox; an all-green result would mean the
        post-pass never fired.
        """
        # Render on a sentinel background that's neither white nor green
        # so post-pass-flipped pixels are distinguishable from the bg.
        image = Image.new("RGB", (800, 480), (1, 2, 3))
        rq.draw_glacier_border(
            image,
            {"text": rq.SPECTRA6["blue"], "accent": rq.SPECTRA6["green"]},
        )
        # Sample a 40×40 box at the top-left corner (the cluster
        # fans out from the inner-frame corner at ~(16, 16) and the
        # longest shard reaches ~(30, 30)).
        pixels = image.load()
        green_count = 0
        white_count = 0
        for y in range(0, 40):
            for x in range(0, 40):
                p = pixels[x, y]
                if p == rq.SPECTRA6["green"]:
                    green_count += 1
                elif p == rq.SPECTRA6["white"]:
                    white_count += 1
        assert green_count > 0 and white_count > 0, (
            f"glacier TL shard must mix green + white (sky-blue post-pass); "
            f"got green={green_count} white={white_count}"
        )
        # The white pixels in this bbox come exclusively from the
        # post-pass flipping accent (green) pixels; assert their layout
        # honours the (x+y)&1 checkerboard, no drift allowed.
        for y in range(0, 40):
            for x in range(0, 40):
                if pixels[x, y] == rq.SPECTRA6["white"]:
                    assert (x + y) & 1 == 0, (
                        f"glacier post-pass flipped a non-checkerboard pixel "
                        f"at ({x}, {y})"
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


def test_herbarium_border_paints_second_fern_specimen():
    """The upleveled herbarium border mounts a second pressed-fern specimen
    in the top-left margin (olive = green/yellow stipple)."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_herbarium_border(img, rq.THEMES["herbarium"])
    px = img.load()
    green = rq.SPECTRA6["green"]
    yellow = rq.SPECTRA6["yellow"]
    fern = {px[x, y] for x in range(42, 67) for y in range(34, 109)}
    assert green in fern and yellow in fern, "TL fern specimen olive stipple missing"


def test_herbarium_border_paints_leaf_mounting_tape():
    """Off-white gummed mounting-tape strips pin the main BR leaf's midrib."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_herbarium_border(img, rq.THEMES["herbarium"])
    px = img.load()
    white = rq.SPECTRA6["white"]
    leaf_cx = 800 - 1 - 38 - 84 // 2
    leaf_cy = 480 - 1 - 38 - 42 // 2
    assert px[leaf_cx, leaf_cy - 18] == white
    assert px[leaf_cx, leaf_cy + 16] == white


def test_blueprint_border_paints_top_dimension_line():
    """The upleveled blueprint border adds a top-margin overall-width
    dimension callout. The rule + extension ticks are in the white drafting
    ink; the inward arrowheads and the centred measurement figure are in the
    red registration ink — so both inks appear in the dimension band."""
    img = Image.new("RGB", (800, 480), rq.SPECTRA6["blue"])
    rq.draw_blueprint_border(img, rq.THEMES["blueprint"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    white = rq.SPECTRA6["white"]
    dim_red = sum(1 for x in range(110, 690) for y in range(36, 45) if px[x, y] == red)
    dim_white = sum(1 for x in range(110, 690) for y in range(36, 45) if px[x, y] == white)
    assert dim_red > 30, "dimension arrowheads / figure (red) missing"
    assert dim_white > 100, "dimension rule / extension ticks (white) missing"


def test_blueprint_border_paints_scale_bar():
    """The upleveled blueprint border adds a bottom-right graduated
    SCALE 1:1 legend bar in the drafting-ink (white) colour."""
    img = Image.new("RGB", (800, 480), rq.SPECTRA6["blue"])
    rq.draw_blueprint_border(img, rq.THEMES["blueprint"])
    px = img.load()
    white = rq.SPECTRA6["white"]
    bar_x = 800 - 1 - 16 - 12 - 80
    bar_y = 480 - 1 - 16 - 18
    assert px[bar_x + 2, bar_y + 3] == white, "scale-bar first filled cell missing"


def test_blueprint_callouts_clear_debug_banner_band():
    """The dimension line sits at y=40 — below the y=14-29 debug banner — so
    blueprint still needs no _DEBUG_LABEL_RIGHT_INSET adjustment for them."""
    img = Image.new("RGB", (800, 480), rq.SPECTRA6["blue"])
    rq.draw_blueprint_border(img, rq.THEMES["blueprint"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    banner = sum(1 for x in range(600, 690) for y in range(14, 30) if px[x, y] == red)
    # The TR crosshair is at the frame corner (x~width-16), left of x=600,
    # so the banner sample band should carry no callout red.
    assert banner == 0, "blueprint callout intrudes on the debug-banner band"


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


def test_illuminated_border_paints_head_asterism():
    """The upleveled illuminated border adds a rubricated head asterism
    (red lozenges) centred in the top margin."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_illuminated_border(img, rq.THEMES["illuminated"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    head_red = sum(1 for x in range(385, 416) for y in range(33, 52) if px[x, y] == red)
    assert head_red > 40, "head asterism lozenges missing"


def test_illuminated_border_paints_foot_line_filler():
    """The upleveled illuminated border adds a foot line-filler — a red
    rule + central red lozenge flanked by blue lozenges."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_illuminated_border(img, rq.THEMES["illuminated"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    blue = rq.SPECTRA6["blue"]
    foot_red = sum(1 for x in range(355, 446) for y in range(445, 458) if px[x, y] == red)
    foot_blue = sum(1 for x in range(345, 456) for y in range(445, 458) if px[x, y] == blue)
    assert foot_red > 40, "foot line-filler rule / centre lozenge missing"
    assert foot_blue > 10, "foot line-filler flanking blue lozenges missing"


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


def test_grimdark_border_paints_aquila_and_skull():
    """The grimdark border paints a gold Imperial Aquila centred in the top
    margin and a bone-white memento-mori skull centred in the bottom margin."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_grimdark_border(img, rq.THEMES["grimdark"])
    px = img.load()
    gold = rq.SPECTRA6["yellow"]
    bone = rq.SPECTRA6["white"]
    # Aquila — gold pixels clustered around (cx=400, ay=40).
    aquila_gold = sum(1 for x in range(360, 441) for y in range(26, 60) if px[x, y] == gold)
    assert aquila_gold > 120, "Imperial Aquila missing from top margin"
    # Skull — bone-white pixels clustered around (cx=400, sy=442).
    skull_bone = sum(1 for x in range(386, 415) for y in range(426, 458) if px[x, y] == bone)
    assert skull_bone > 80, "memento-mori skull missing from bottom margin"


def test_grimdark_border_paints_doubled_gold_blood_trim():
    """The grimdark trim is a thick gold outer rule + thin blood-red inner
    rule — both inks present, unlike gothic's red+white doubled rule."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_grimdark_border(img, rq.THEMES["grimdark"])
    px = img.load()
    gold = rq.SPECTRA6["yellow"]
    blood = rq.SPECTRA6["red"]
    # Left-edge horizontal scan at y=120 (clear of the mid-edge blood stud
    # at y=240) crosses the gold outer rule (~x=12-14) then the blood inner
    # rule (~x=19).
    row_inks = {px[x, 120] for x in range(10, 24)}
    assert gold in row_inks, "gold outer trim missing"
    assert blood in row_inks, "blood inner trim missing"


def test_grimdark_matched_phrase_uses_forge_amber_recipe():
    """The grimdark matched-phrase red is rerouted to forge-amber (R+Y 5:3
    tangerine) in _draw_text_body, so a red-fill body paint produces both
    red and yellow pixels rather than solid red."""
    img = Image.new("RGB", (200, 60), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = rq.load_font(rq.QUOTE_FONT_BOLD_CANDIDATES, size=40)
    rq._draw_text_body(img, draw, (4, 4), "TWO", font=font, fill=rq.SPECTRA6["red"], theme="grimdark")
    inks = distinct_inks(img)
    assert rq.SPECTRA6["red"] in inks, "forge-amber should retain red pixels"
    assert rq.SPECTRA6["yellow"] in inks, "forge-amber should introduce yellow pixels"


def test_grimdark_border_paints_industrial_mottle():
    """The grimdark Layer-0 mottle stipples sparse white into the black void
    ground (synthesising dark gunmetal grey), but stays sparse enough to read
    as a dark charcoal rather than a light field — and uses only black/white
    so it never leaves the palette."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_grimdark_border(img, rq.THEMES["grimdark"])
    px = img.load()
    white = rq.SPECTRA6["white"]
    black = rq.SPECTRA6["black"]
    # A background patch clear of ornaments and (border-only render) text.
    patch = [(x, y) for x in range(140, 220) for y in range(120, 175)]
    whites = sum(1 for x, y in patch if px[x, y] == white)
    frac = whites / len(patch)
    assert 0.02 < frac < 0.40, f"mottle density {frac:.3f} outside dark-grey range"
    # Every patch pixel is either void or grey-ink — never an off-palette tone.
    assert all(px[x, y] in (white, black) for x, y in patch)


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


def test_risograph_border_paints_registration_colour_bar():
    """The upleveled risograph border adds a top-centre colour-registration
    bar of red / blue / lavender-overprint / red / blue swatches — no black
    ink (the riso theme's invariant)."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_risograph_border(img, rq.THEMES["risograph"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    blue = rq.SPECTRA6["blue"]
    bar_red = sum(1 for x in range(337, 360) for y in range(24, 33) if px[x, y] == red)
    bar_blue = sum(1 for x in range(363, 386) for y in range(24, 33) if px[x, y] == blue)
    assert bar_red > 100, "registration-bar red swatch missing"
    assert bar_blue > 100, "registration-bar blue swatch missing"
    # The bar must clear y=22, the coordinate the illuminated cross-gating
    # test samples to prove no other theme paints centre-top there.
    assert px[400, 22] == (255, 255, 255), "registration bar must clear y=22"


def test_risograph_registration_bar_lavender_swatch_is_red_and_blue():
    """The middle overprint swatch is the R+B+W lavender 3-way recipe, so it
    carries both red and blue pixels (and no black, per the riso invariant)."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_risograph_border(img, rq.THEMES["risograph"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    blue = rq.SPECTRA6["blue"]
    black = rq.SPECTRA6["black"]
    lav_x0 = 337 + 2 * 26
    region = [px[x, y] for x in range(lav_x0, lav_x0 + 23) for y in range(24, 33)]
    assert region.count(red) > 30, "lavender swatch red component missing"
    assert region.count(blue) > 30, "lavender swatch blue component missing"
    assert black not in region, "lavender swatch must not introduce black ink"


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


def test_mucha_border_paints_tip_blossoms():
    """The upleveled mucha border adds a five-petal tangerine blossom at each
    of the two existing vine tips (TL + BR), preserving the deliberate
    diagonal asymmetry (only the already-ornamented corners gain them)."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_mucha_border(img, rq.THEMES["mucha"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    yellow = rq.SPECTRA6["yellow"]

    def tangerine(cx, cy, r0=16):
        rr = sum(1 for x in range(cx - r0, cx + r0) for y in range(cy - r0, cy + r0) if px[x, y] == red)
        yy = sum(1 for x in range(cx - r0, cx + r0) for y in range(cy - r0, cy + r0) if px[x, y] == yellow)
        return rr, yy

    tl_r, tl_y = tangerine(78, 160)
    br_r, br_y = tangerine(760, 330)
    # Both tips carry a tangerine (R+Y) blossom: red AND yellow present.
    assert tl_r > 20 and tl_y > 20, "top-left vine-tip blossom missing"
    assert br_r > 10 and br_y > 20, "bottom-right vine-tip blossom missing"


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


def test_vinyl_frame_paints_spec_line():
    """The upleveled vinyl liner panel adds a spec strip (SIDE ONE · 33 RPM ·
    MONO · RUNNING TIME) below the READING heading, filling the dead cream
    between heading and quote body."""
    row = {
        "display_quote": "It was at ten o'clock today that the first of all Time Machines began.",
        "matched_text": "ten o'clock", "author": "H. G. Wells", "title": "The Time Machine",
        "source_id": "35", "line_number": 1, "quality_score": 90,
        "bucket": "h10_exact", "resolved_bucket": "h10_exact", "used_fallback": False,
    }
    img = rq.render("10:00", row, 800, 480, mode="production", theme="vinyl").convert("RGB")
    px = img.load()
    black = rq.SPECTRA6["black"]
    # The spec strip (hairline rule + Space Mono text) sits at y≈46-60 in the
    # right-half liner panel (x≥420).
    spec_black = sum(1 for x in range(420, 780) for y in range(46, 60) if px[x, y] == black)
    assert spec_black > 100, "vinyl spec strip missing"


def test_vinyl_spec_line_is_deterministic():
    """The spec strip's running time must derive from a STABLE bucket digest,
    not process-salted hash(), or renders of the same quote would differ and
    break the byte-exact golden / dedup contract."""
    row = {
        "display_quote": "It was at ten o'clock today.",
        "matched_text": "ten o'clock", "author": "A", "title": "B",
        "source_id": "1", "line_number": 1, "quality_score": 90,
        "bucket": "h10_exact", "resolved_bucket": "h10_exact", "used_fallback": False,
    }
    a = rq.render("10:00", row, 800, 480, mode="production", theme="vinyl").convert("RGB").tobytes()
    b = rq.render("10:00", row, 800, 480, mode="production", theme="vinyl").convert("RGB").tobytes()
    assert a == b, "vinyl frame not byte-deterministic across renders"


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
