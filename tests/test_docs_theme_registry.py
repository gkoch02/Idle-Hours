"""The documentation's theme claims must agree with the theme registry.

Adding a theme touches a lot of prose, and none of it was checked. The count
alone is spelled out **as a word** in seven places across four files, and every
one of them silently went stale when the ``abyssal`` and ``pride`` branches
were merged: both had independently changed "Forty-seven themes" to
"Forty-eight", so git merged the sentences *cleanly* and the result claimed
forty-eight against a registry of forty-nine. Nothing failed. A reviewer had no
way to see it.

That is the whole class this module fences — a fact stated in prose that is
derivable from code, with nothing tying the two together:

* the spelled-out counts (``TestThemeCountWords``)
* the README's per-theme table and its preview images (``TestReadmeThemeTable``)
* the README's contact-sheet loop (``TestContactSheetLoop``)
* CLAUDE.md's button-B cycle chain (``TestButtonBCycleChain``)

Every expectation is *derived* from ``render_quote``, so adding theme fifty
means updating the docs and nothing here. Each scan also asserts a floor on how
much it found: a regex that quietly stops matching would otherwise turn these
into vacuous passes, which is the failure mode the tests exist to prevent.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from idle_hours import render_quote as rq
from idle_hours import theme_names

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every file that makes a claim about the theme registry in prose.
DOC_FILES = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "CLAUDE.md",
    *sorted((REPO_ROOT / "docs").glob("*.md")),
    REPO_ROOT / "idle_hours/assets/config.toml.example",
    REPO_ROOT / "idle_hours/assets/config.toml.defaults",
)

_UNITS = (
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty",
         60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"}


def _word_for(n: int) -> str:
    """Spell ``n`` (0..99) the way the docs do — "forty-nine", "twenty"."""
    assert 0 <= n < 100, n
    if n < 20:
        return _UNITS[n]
    tens, unit = divmod(n, 10)
    return _TENS[tens * 10] + (f"-{_UNITS[unit]}" if unit else "")


_NUMBER_WORDS = {_word_for(n): n for n in range(1, 100)}

# Claim sites are listed explicitly rather than discovered by scanning for
# "<number> themes", and that is a deliberate reversal. A scan was tried first
# and cannot work: the docs legitimately count *subsets* in the same shape —
# "`marquee`, `tarot`, and `vinyl` are three more custom-render themes",
# "… — one per theme" — and no amount of grammar tightening separates those
# from a claim about the registry, because the difference is semantic. An
# allowlist of exceptions to a scan would be strictly worse than this list: the
# same maintenance burden, plus the risk of silently excusing a real claim.
#
# Each entry anchors on distinctive surrounding words so it cannot drift onto a
# subset sentence, and ``offsets`` gives each capture group's expected value as
# a subtraction from the registry size — 0 for a total, 1 for a count that
# excludes ``diags``. The expected values are computed, so adding a theme means
# updating the prose and nothing here; rewording a sentence means updating the
# pattern, which is the point at which someone is looking at the claim anyway.
CLAIM_SITES = (
    ("README.md", "intro paragraph",
     re.compile(r"\b([\w-]+) themes ship built-in, all constrained"), (0,)),
    ("README.md", "curator UI thumbnail grid",
     re.compile(r"previews of all ([\w-]+) registered themes"), (0,)),
    ("README.md", "feature list",
     re.compile(r"- ([\w-]+) themes ship built-in \(full table"), (0,)),
    ("CLAUDE.md", "THEMES dict description",
     re.compile(r"The `THEMES` dict defines ([\w-]+) colou?r sets"), (0,)),
    ("CLAUDE.md", "theme preview endpoint",
     re.compile(r"compare all ([\w-]+) operator-choice themes \(([\w-]+) themes including"), (1, 0)),
    ("docs/CONTRIBUTING.md", "theme section",
     re.compile(r"([\w-]+) themes ship today"), (0,)),
    ("idle_hours/assets/config.toml.defaults", "theme key comment",
     re.compile(r"\(([\w-]+) themes ship today;"), (0,)),
)


class TestThemeCountWords:
    """Every spelled-out theme count must equal the size of the registry."""

    @pytest.mark.parametrize(
        "relative, description, pattern, offsets",
        CLAIM_SITES,
        ids=[f"{p}:{d}" for p, d, _, _ in CLAIM_SITES],
    )
    def test_claim_matches_the_registry(self, relative, description, pattern, offsets):
        path = REPO_ROOT / relative
        match = pattern.search(path.read_text(encoding="utf-8"))
        assert match, (
            f"the {description} claim in {relative} no longer matches its pattern — "
            "the sentence was reworded, so update CLAIM_SITES (and check the count "
            "while you are there)"
        )
        for index, offset in enumerate(offsets, start=1):
            word = match.group(index)
            expected = len(rq.THEMES) - offset
            assert _NUMBER_WORDS.get(word.lower()) == expected, (
                f'{relative} ({description}) says "{word}" where there are {expected} '
                f'{"themes" if not offset else "operator-choice themes (all but `diags`)"} '
                f'— spell it "{_word_for(expected)}"'
            )

    def test_every_doc_file_is_covered(self):
        """Each file that states a count must appear in CLAIM_SITES."""
        covered = {relative for relative, _, _, _ in CLAIM_SITES}
        assert covered == {
            "README.md", "CLAUDE.md", "docs/CONTRIBUTING.md",
            "idle_hours/assets/config.toml.defaults",
        }, f"CLAIM_SITES covers {sorted(covered)} — a file was added or dropped"

    def test_word_speller_round_trips(self):
        """The speller is load-bearing for the failure message, so pin it."""
        assert _word_for(48) == "forty-eight"
        assert _word_for(49) == "forty-nine"
        assert _word_for(50) == "fifty"
        assert _word_for(7) == "seven"
        assert all(_word_for(n) in _NUMBER_WORDS for n in range(1, 100))


class TestReadmeThemeTable:
    """The README's theme table must carry a row, and an image, per theme."""

    README = REPO_ROOT / "README.md"
    PREVIEW_DIR = REPO_ROOT / "idle_hours/assets/previews"
    ROW_RE = re.compile(r"^\| `([a-z_0-9]+)`\s*\|.*?previews/([a-z_0-9]+)\.png", re.M)

    def _rows(self) -> dict[str, str]:
        text = self.README.read_text(encoding="utf-8")
        return {name: image for name, image in self.ROW_RE.findall(text)}

    def test_a_row_per_registered_theme(self):
        rows = self._rows()
        missing = set(rq.THEMES) - set(rows)
        extra = set(rows) - set(rq.THEMES)
        assert not missing, f"README theme table is missing rows for: {sorted(missing)}"
        assert not extra, f"README theme table has rows for unregistered themes: {sorted(extra)}"

    def test_row_image_matches_its_theme(self):
        for name, image in self._rows().items():
            assert image == name, (
                f"README row for `{name}` shows previews/{image}.png — a copy-paste slip"
            )

    def test_every_preview_image_exists(self):
        for name in self._rows():
            path = self.PREVIEW_DIR / f"{name}.png"
            assert path.exists(), f"README references {path.relative_to(REPO_ROOT)}, which is missing"

    def test_no_orphaned_preview_images(self):
        on_disk = {p.stem for p in self.PREVIEW_DIR.glob("*.png")}
        orphans = on_disk - set(rq.THEMES)
        assert not orphans, (
            f"preview images with no registered theme: {sorted(orphans)} — delete them "
            "or the theme they belonged to was removed without cleaning up"
        )


class TestContactSheetLoop:
    """The README's copy-pasteable contact-sheet loop must list every theme."""

    LOOP_RE = re.compile(r"for theme in ([a-z_0-9 ]+); do")

    def test_loop_enumerates_theme_order(self):
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        matches = self.LOOP_RE.findall(text)
        assert matches, "could not find the contact-sheet loop in README.md"
        for listed in matches:
            assert tuple(listed.split()) == rq.THEME_ORDER, (
                "the README contact-sheet loop no longer matches THEME_ORDER — "
                f"missing {sorted(set(rq.THEME_ORDER) - set(listed.split()))}, "
                f"unknown {sorted(set(listed.split()) - set(rq.THEME_ORDER))}"
            )


class TestButtonBCycleChain:
    """CLAUDE.md's button-B chain must match the real cycle order.

    The chain documents what a physical button press actually does, so it tracks
    ``theme_cycle()`` — ``THEME_ORDER`` minus ``CYCLE_EXCLUDED_THEMES`` — not the
    full registry, and it wraps back to the first entry at the end.
    """

    CHAIN_RE = re.compile(r"advances one step through `render_quote\.THEME_ORDER` \(([^;)]+)\)?;")

    def test_chain_matches_the_cycle(self):
        text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        match = self.CHAIN_RE.search(text)
        assert match, "could not find the button-B cycle chain in CLAUDE.md"
        listed = [part.strip().strip("`") for part in match.group(1).split("→")]
        cycle = list(theme_names.theme_cycle())
        assert listed[-1] == cycle[0], (
            f"the chain should wrap back to `{cycle[0]}`, it ends at `{listed[-1]}`"
        )
        assert listed[:-1] == cycle, (
            "the button-B chain in CLAUDE.md no longer matches theme_cycle() — "
            f"missing {sorted(set(cycle) - set(listed))}, "
            f"unknown {sorted(set(listed) - set(cycle))}"
        )

    def test_excluded_themes_stay_out_of_the_chain(self):
        text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        listed = set(p.strip().strip("`") for p in self.CHAIN_RE.search(text).group(1).split("→"))
        for excluded in rq.CYCLE_EXCLUDED_THEMES:
            assert excluded not in listed, (
                f"`{excluded}` is in CYCLE_EXCLUDED_THEMES but the documented "
                "button-B chain still lists it"
            )


@pytest.mark.parametrize("path", [p for p in DOC_FILES])
def test_doc_files_exist(path):
    """A renamed doc would otherwise silently drop out of every scan above."""
    assert path.exists(), f"{path} is in DOC_FILES but does not exist"
