"""Fence the theme counts and theme lists the docs state against the registries.

CLAUDE.md, README.md and CONTRIBUTING.md each restate facts that live in code:
how many themes are registered, how many bypass the literary layout, which
themes button B cycles through, and the full roster in three separate places.
Every one of those had drifted at least once — the README's own reference list
enumerated sixty-two of the sixty-three themes while its count sentence
correctly said "Sixty-three", and CLAUDE.md's decoration paragraph claimed 33
border painters and thirteen frames against an actual 36 and 25.

A count is worth fencing where an *ordinal per theme* was not (see the
"Themes" preamble in CLAUDE.md): it is one number, in one place, checked
against a list that already exists in code, rather than a whole-set fact
smeared across a dozen member paragraphs.

**Every assertion here must fail when its sentence goes missing, not pass
vacuously.** A regex over prose that silently matches nothing is worse than no
test at all, so `_find` fails loudly on a miss and tells the author which
sentence it could not locate. Rewording a fenced sentence therefore costs a
deliberate update here, which is the intended trade: these sentences are load
bearing, and the alternative is that they quietly stop being true.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from idle_hours import render_quote as rq
from idle_hours.theme_names import theme_cycle

from .test_theme_decoration import CUSTOM_FRAME_THEMES

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
README_MD = REPO_ROOT / "README.md"
CONTRIBUTING_MD = REPO_ROOT / "docs" / "CONTRIBUTING.md"

_UNITS = (
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = {
    2: "twenty",
    3: "thirty",
    4: "forty",
    5: "fifty",
    6: "sixty",
    7: "seventy",
    8: "eighty",
    9: "ninety",
}


def spell(n: int) -> str:
    """Render 0..99 the way the docs write a count ("twenty-five")."""
    if n < 0 or n > 99:  # pragma: no cover - the theme registry cannot reach here
        raise ValueError(f"no spelling for {n}")
    if n < 20:
        return _UNITS[n]
    tens, unit = divmod(n, 10)
    return _TENS[tens] if unit == 0 else f"{_TENS[tens]}-{_UNITS[unit]}"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _roster_diff(found: list[str], expected: list[str]) -> str:
    """Describe how an extracted roster differs from the registry it mirrors.

    Four distinguishable faults, because a one-directional membership check
    only catches the first: a theme missing from the doc, a stale entry left
    behind after a rename or removal, a name listed twice, and the same names
    in the wrong order.
    """
    missing = [t for t in expected if t not in found]
    stale = [t for t in found if t not in expected]
    dupes = sorted({t for t in found if found.count(t) > 1})
    lines = []
    if missing:
        lines.append(f"  missing (in code, absent from the doc): {missing}")
    if stale:
        lines.append(f"  stale (in the doc, absent from code):   {stale}")
    if dupes:
        lines.append(f"  listed more than once:                  {dupes}")
    if not lines:
        i = next(i for i, (a, b) in enumerate(zip(found, expected)) if a != b)
        lines.append(
            f"  same names, wrong order — first divergence at index {i}: "
            f"the doc has {found[i]!r}, code has {expected[i]!r}"
        )
    return "\n".join(lines)


def _find(path: Path, pattern: str, sentence: str) -> re.Match:
    """Locate a fenced sentence, failing loudly rather than vacuously."""
    match = re.search(pattern, _read(path))
    if match is None:
        pytest.fail(
            f"{path.name}: could not find the sentence this test fences.\n"
            f"  looking for: {sentence}\n"
            f"  pattern:     {pattern}\n"
            "If you reworded it deliberately, update the pattern here too. This "
            "test is useless if it can silently match nothing."
        )
    return match


class TestDocumentedThemeCounts:
    """Spelled-out and numeric theme counts must match the live registries."""

    def test_claude_md_theme_count(self):
        m = _find(
            CLAUDE_MD,
            r"The `THEMES` dict defines ([a-z-]+) color sets",
            "The `THEMES` dict defines <N> color sets",
        )
        assert m.group(1) == spell(len(rq.THEMES)), (
            f"CLAUDE.md says the THEMES dict defines {m.group(1)!r} color sets; "
            f"there are {len(rq.THEMES)} ({spell(len(rq.THEMES))!r})."
        )

    def test_claude_md_custom_frame_count(self):
        m = _find(
            CLAUDE_MD,
            r"\b([A-Za-z-]+) themes bypass the literary layout entirely",
            "<N> themes bypass the literary layout entirely",
        )
        assert m.group(1).lower() == spell(len(CUSTOM_FRAME_THEMES)), (
            f"CLAUDE.md says {m.group(1)!r} themes bypass the literary layout; "
            f"CUSTOM_FRAME_THEMES holds {len(CUSTOM_FRAME_THEMES)} "
            f"({spell(len(CUSTOM_FRAME_THEMES))!r})."
        )

    def test_claude_md_operator_choice_count(self):
        # diags surfaces swatches instead of a quote, so it is the one theme an
        # operator is not really choosing between.
        m = _find(
            CLAUDE_MD,
            r"all ([a-z-]+) operator-choice themes \(([a-z-]+) themes including",
            "all <N> operator-choice themes (<N+1> themes including `diags`)",
        )
        assert m.group(1) == spell(len(rq.THEMES) - 1)
        assert m.group(2) == spell(len(rq.THEMES))

    def test_claude_md_decoration_counts(self):
        m = _find(
            CLAUDE_MD,
            r"The (\d+) border-painted themes in `_BORDER_PAINTERS` "
            r"and (\d+) `render_\*_frame` compositions",
            "The <N> border-painted themes in `_BORDER_PAINTERS` and <M> "
            "`render_*_frame` compositions",
        )
        assert int(m.group(1)) == len(rq._BORDER_PAINTERS), (
            f"CLAUDE.md says {m.group(1)} border-painted themes; "
            f"_BORDER_PAINTERS holds {len(rq._BORDER_PAINTERS)}."
        )
        assert int(m.group(2)) == len(CUSTOM_FRAME_THEMES), (
            f"CLAUDE.md says {m.group(2)} render_*_frame compositions; "
            f"CUSTOM_FRAME_THEMES holds {len(CUSTOM_FRAME_THEMES)}."
        )

    def test_readme_ship_built_in_counts(self):
        text = _read(README_MD)
        found = re.findall(r"([A-Za-z-]+) themes ship built-in", text)
        assert found, "README.md: no '<N> themes ship built-in' sentence found."
        want = spell(len(rq.THEMES))
        assert [f.lower() for f in found] == [want] * len(found), (
            f"README.md 'themes ship built-in' says {found}; there are "
            f"{len(rq.THEMES)} themes ({want!r})."
        )

    def test_readme_preview_regeneration_count(self):
        m = _find(
            README_MD,
            r"one passage shown ([a-z-]+) ways",
            "the table reads as one passage shown <N> ways",
        )
        assert m.group(1) == spell(len(rq.THEME_ORDER))

    def test_readme_thumbnail_grid_count(self):
        m = _find(
            README_MD,
            r"previews of all ([a-z-]+) registered themes",
            "side-by-side previews of all <N> registered themes",
        )
        assert m.group(1) == spell(len(rq.THEMES))

    def test_contributing_theme_count(self):
        m = _find(
            CONTRIBUTING_MD,
            r"([A-Za-z-]+) themes ship today",
            "<N> themes ship today",
        )
        assert m.group(1).lower() == spell(len(rq.THEMES))


class TestDocumentedThemeRosters:
    """Docs that enumerate every theme must enumerate every theme.

    The count and the roster fail independently: the README correctly said
    "Sixty-three themes ship built-in" while the list beside it named
    sixty-two, omitting `bakelite`.
    """

    def test_readme_preview_table_matches_theme_order(self):
        rows = re.findall(r"previews/([a-z_]+)\.png", _read(README_MD))
        assert rows, "README.md: no preview-table rows found."
        assert rows == list(rq.THEME_ORDER), (
            "README.md theme table is out of sync with THEME_ORDER.\n"
            + _roster_diff(rows, list(rq.THEME_ORDER))
        )

    def test_readme_regeneration_loop_matches_theme_order(self):
        m = _find(
            README_MD,
            r"for theme in ([a-z_ ]+); do",
            "for theme in <every theme>; do  (the preview-regeneration snippet)",
        )
        assert m.group(1).split() == list(rq.THEME_ORDER), (
            "README.md preview-regeneration loop is out of sync with THEME_ORDER."
        )

    def test_readme_reference_list_matches_theme_order(self):
        line = next(
            (
                ln
                for ln in _read(README_MD).splitlines()
                if re.match(r"- [A-Za-z-]+ themes ship built-in", ln)
            ),
            None,
        )
        assert line, "README.md: no '- <N> themes ship built-in' reference bullet."
        # Every backticked snake_case token on this line is a theme name: the
        # parenthetical descriptions quote flags and paths, which carry hyphens,
        # dots or slashes and so fall outside `[a-z_]+`.
        named = re.findall(r"`([a-z_]+)`", line)
        assert named == list(rq.THEME_ORDER), (
            "README.md reference list is out of sync with THEME_ORDER.\n"
            + _roster_diff(named, list(rq.THEME_ORDER))
        )

    def test_claude_md_button_b_cycle_matches_theme_cycle(self):
        m = _find(
            CLAUDE_MD,
            # Stop at the ';' that ends the chain — the clause after it names the
            # CYCLE_EXCLUDED_THEMES, which are precisely not in the cycle.
            r"advances one step through `render_quote\.THEME_ORDER` \(([^);]+)",
            "Cycle theme — advances one step through THEME_ORDER (<the chain>)",
        )
        chain = re.findall(r"[a-z_]+", m.group(1))
        # The chain is written as a loop, closing on the theme it opened with.
        assert chain and chain[-1] == chain[0], (
            "CLAUDE.md button-B chain should close back on its first theme."
        )
        assert chain[:-1] == list(theme_cycle()), (
            "CLAUDE.md button-B chain is out of sync with theme_cycle().\n"
            + _roster_diff(chain[:-1], list(theme_cycle()))
        )


class TestSpell:
    """The number speller is the only novel logic here, so pin it."""

    @pytest.mark.parametrize(
        ("n", "word"),
        [
            (0, "zero"),
            (7, "seven"),
            (13, "thirteen"),
            (20, "twenty"),
            (25, "twenty-five"),
            (36, "thirty-six"),
            (40, "forty"),
            (62, "sixty-two"),
            (63, "sixty-three"),
            (99, "ninety-nine"),
        ],
    )
    def test_spells_the_way_the_docs_write_counts(self, n, word):
        assert spell(n) == word
