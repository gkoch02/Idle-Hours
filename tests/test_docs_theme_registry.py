"""The documentation's theme rosters must agree with the theme registry.

A roster is real content: the README's per-theme table, its contact-sheet loop
and docs/runtime.md's button-B chain each enumerate themes because a reader
needs the list there. Each is checked against the registry it mirrors, so
adding a theme without its row, preview or loop entry fails here.

Counts are deliberately *not* fenced (issue #352). A spelled-out "eighty-nine
themes" is a cache of ``len(THEME_ORDER)``, and it used to be restated in seven
places and checked by a number speller. The docs now say "every theme in
``THEME_ORDER``" instead, so there is no count to drift and nothing here
parses prose for a number. Do not reintroduce one: point at the registry.

Each scan asserts that it found something, because a regex that quietly stops
matching would otherwise turn these into vacuous passes.
"""
from __future__ import annotations

import re
from pathlib import Path

from idle_hours import render_quote as rq
from idle_hours import theme_names

REPO_ROOT = Path(__file__).resolve().parent.parent


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

    def test_rows_follow_theme_order(self):
        rows = list(self._rows())
        assert rows == list(rq.THEME_ORDER), (
            "README theme table rows are not in THEME_ORDER order — first divergence: "
            + next(
                (f"row {i} is `{a}`, THEME_ORDER has `{b}`"
                 for i, (a, b) in enumerate(zip(rows, rq.THEME_ORDER, strict=False)) if a != b),
                "lengths differ",
            )
        )

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
    """docs/runtime.md's button-B chain must match the real cycle order.

    The chain documents what a physical button press actually does, so it tracks
    ``theme_cycle()`` — ``THEME_ORDER`` minus ``CYCLE_EXCLUDED_THEMES`` — not the
    full registry, and it wraps back to the first entry at the end.
    """

    CHAIN_RE = re.compile(r"advances one step through `render_quote\.THEME_ORDER` \(([^;)]+)\)?;")

    def test_chain_matches_the_cycle(self):
        text = (REPO_ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
        match = self.CHAIN_RE.search(text)
        assert match, "could not find the button-B cycle chain in docs/runtime.md"
        listed = [part.strip().strip("`") for part in match.group(1).split("→")]
        cycle = list(theme_names.theme_cycle())
        assert listed[-1] == cycle[0], (
            f"the chain should wrap back to `{cycle[0]}`, it ends at `{listed[-1]}`"
        )
        assert listed[:-1] == cycle, (
            "the button-B chain in docs/runtime.md no longer matches theme_cycle() — "
            f"missing {sorted(set(cycle) - set(listed))}, "
            f"unknown {sorted(set(listed) - set(cycle))}"
        )

    def test_excluded_themes_stay_out_of_the_chain(self):
        text = (REPO_ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
        listed = set(p.strip().strip("`") for p in self.CHAIN_RE.search(text).group(1).split("→"))
        for excluded in rq.CYCLE_EXCLUDED_THEMES:
            assert excluded not in listed, (
                f"`{excluded}` is in CYCLE_EXCLUDED_THEMES but the documented "
                "button-B chain still lists it"
            )
