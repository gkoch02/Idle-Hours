#!/usr/bin/env python3
"""Regenerate the per-theme preview thumbnails in ``idle_hours/assets/previews/``.

The README's theme table shows one 800x480 production render per registered
theme. Before this script those images were made by hand as each theme landed,
and nothing recorded how: not the commit that added them, not a script, not a
manifest. That had two costs.

**They went stale silently.** A theme's palette could change and its preview
would keep showing the old colours; the docs fences check only that a preview
*file exists* per theme, never that its contents still match the renderer.
That is how the ``betweenus`` "Hard No" chip stayed green in the README after
the theme stopped painting it green (issue #257).

**And fixing one meant archaeology.** Recovering the parameters of that single
preview took inverting a progress bar to find the time and grepping the corpus
for the passage. Measured across the whole set it is worse than that: sweeping
every canonical time against the current picker reproduces *none* of the
committed previews, because the corpus and the scorer have both moved since
they were made. There is nothing left to recover from.

So this script does not try to preserve the historical passages. It renders
every preview from **one pinned passage at one pinned time**, which is a
better object anyway: the README tells the reader to "compare palette and
typography, not line breaks", and that instruction is only honest once every
theme is showing the same words. The variety it currently apologises for was
an accident, not a design.

Usage::

    # What would change? (read-only, safe to run any time)
    python3 scripts/generate_theme_previews.py --check

    # Regenerate one theme — the common case after touching its palette.
    python3 scripts/generate_theme_previews.py --theme betweenus

    # Regenerate the whole set. Deliberately opt-in: it rewrites 60+ files.
    python3 scripts/generate_theme_previews.py --all

Exit codes: ``0`` clean, ``1`` a bad argument or a missing pin, ``2`` from
``--check`` when at least one preview differs from what the renderer now
produces.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import os
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageChops  # noqa: E402

from idle_hours import path_resolution  # noqa: E402
from idle_hours import pick_quote as pq  # noqa: E402
from idle_hours import render_quote as rq  # noqa: E402
from idle_hours.jsonl_io import iter_jsonl  # noqa: E402
from idle_hours.theme_names import known_theme_names  # noqa: E402

PREVIEW_DIR = REPO_ROOT / "idle_hours" / "assets" / "previews"

# The passage every preview shows.
#
# H. G. Wells, *The Time Machine* — chosen on four counts, in rough order of
# how much each mattered. It is on the nose for a literary clock, which a
# marketing thumbnail may as well be. It is `hero` layout (81 characters), so
# the type is set large and a reader comparing two rows of the table is
# actually looking at letterforms rather than at a grey block. It carries both
# an author and a title, so the attribution stack renders rather than being
# skipped. And it was already the passage in the `betweenus` preview, so that
# one file is unchanged by adopting it.
#
# 10:00 is `h10_exact`. Every theme that surfaces the hour as its own furniture
# — tarot's Roman numeral, vitrail's rose window, lieder's time signature,
# izakaya's lantern, bakelite's setting index — shows its hour-10 variant, and
# shows it consistently across the table.
PREVIEW_TIME = "10:00"
PREVIEW_SOURCE_ID = "35"
PREVIEW_LINE_NUMBER = 646
# `(source_id, line_number)` does not identify a corpus row — one source line
# can carry several time phrases, and the committed database holds 128
# duplicate keys. This pin's key happens to be unique today, but asserting the
# phrase costs nothing and stops a future corpus from silently swapping the
# passage under a preview run. Curly apostrophe: the corpus stores it that way.
PREVIEW_MATCHED_TEXT = "ten o’clock"

WIDTH, HEIGHT = 800, 480
MODE = "production"

# How much a committed preview may differ from a fresh render before --check
# calls it stale. Mirrors `tests/test_render_golden.py`'s budgets deliberately,
# and `TestToleranceMatchesTheGoldenSuite` fails if the two drift apart.
#
# Zero was the first cut and is wrong. `render` ends in `snap_image_to_palette`,
# so subpixel antialiasing collapses to the same palette index almost always —
# but not always, and the repo has the measurement: `diags` sets its small
# system-info labels in the host's DejaVu, and a Pillow/FreeType point release
# moves those glyph edges by roughly 0.14% of the canvas while every
# panel-scale shape is unchanged. CI resolves Pillow at install time against a
# `>=9.3` floor, so an exact check would redden this required job across every
# open PR the day a Pillow release lands, with no commit having caused it —
# the flake PR #229 already hit once.
#
# **What that costs, stated plainly:** at 0.1% the budget is 384 pixels of
# 384,000, so this check catches theme-scale staleness — a palette change, a
# new border painter, a font swap, anything that flips thousands of pixels —
# and NOT a single small ornament. The `betweenus` chip that motivated all of
# this moved 61 pixels and would sit under this budget. The golden fixtures
# have the same blind spot for the same reason and the repo has already
# accepted that trade; making this check tighter than the goldens would buy
# sensitivity nobody else has at the cost of being the one thing that breaks
# on a dependency bump. A change too small for this fence needs the eye, or a
# targeted assertion of the kind #258 added.
MAX_DIFF_RATIO = 0.001
THEME_MAX_DIFF_RATIOS = {"diags": 0.0015}


def tolerance_px(theme: str) -> int:
    """Pixels this theme may differ by before its preview counts as stale."""
    return int(THEME_MAX_DIFF_RATIOS.get(theme, MAX_DIFF_RATIO) * WIDTH * HEIGHT)

# A fixed instant for the renderer's wall-clock reads. `astrarium` prints the
# date in its header and derives its solar/lunar datums from the day of year;
# `vinyl` stamps a copyright year and seeds its sleeve wear from YYYYMMDD.
# Without a freeze their previews would differ on every run and re-render
# noisily forever.
#
# Deliberately applied to EVERY theme rather than to a list of the two that
# need it. The golden suite keeps such a list because it wants to detect a
# theme that reads the clock without being frozen; a generator has no such
# question to answer, and an unconditional freeze is one fewer thing to keep in
# sync as themes are added.
FROZEN_NOW = datetime.datetime(2026, 5, 19, 10, 0, 0)


def _frozen_datetime_module() -> types.SimpleNamespace:
    """A stand-in for the stdlib ``datetime`` pinned to ``FROZEN_NOW``.

    The classes subclass the real ones so ``isinstance`` and ordinary
    construction keep working; only ``now()`` / ``today()`` change.
    ``render_quote`` does ``import datetime`` and touches ``datetime.datetime``
    and ``datetime.date``, so swapping the module reference is enough.
    """

    class _FrozenDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return FROZEN_NOW if tz is None else FROZEN_NOW.replace(tzinfo=tz)

    class _FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return FROZEN_NOW.date()

    return types.SimpleNamespace(
        datetime=_FrozenDatetime,
        date=_FrozenDate,
        timedelta=datetime.timedelta,
        timezone=datetime.timezone,
    )


@contextlib.contextmanager
def frozen_clock():
    original = rq.datetime
    rq.datetime = _frozen_datetime_module()
    try:
        yield
    finally:
        rq.datetime = original


@contextlib.contextmanager
def _unset_photo_path():
    """Render the ``photo`` theme's bundled fallback, never an operator's photo.

    ``photo`` reads its picture from ``IDLE_HOURS_PHOTO_PATH``. A maintainer who
    exported that for their own appliance would otherwise commit their holiday
    photos into the README — the same trap ``tests/conftest.py`` unsets the
    variable to avoid for the golden fixtures.
    """
    original = os.environ.pop(path_resolution.PHOTO_PATH_ENV, None)
    try:
        yield
    finally:
        if original is not None:
            os.environ[path_resolution.PHOTO_PATH_ENV] = original


# What the `diags` panel's system strip shows in a preview.
#
# `diags` is the calibration panel, so it reads the real host name, the real
# outbound IP and the real uptime — correct on an appliance, wrong in a file
# committed to a public README twice over. It is **unreproducible**: uptime
# moves every minute, so the CI check below would fail on essentially every
# run. And it is a **leak**: generated on a maintainer's laptop the thumbnail
# carries their hostname and LAN IP into the repository. Stubbing is what
# makes this one theme fenceable at all.
#
# 192.0.2.x is TEST-NET-1 (RFC 5737), the range reserved for documentation, so
# the address cannot collide with anyone's real network.
DIAGS_STUB_SYSTEM_INFO = {"host": "idle-hours", "ip": "192.0.2.42", "uptime": "6d 4h 12m"}


@contextlib.contextmanager
def _stub_diags_system_info():
    original = rq._diags_system_info
    rq._diags_system_info = lambda: dict(DIAGS_STUB_SYSTEM_INFO)
    try:
        yield
    finally:
        rq._diags_system_info = original


def pinned_row(corpus_path: Path) -> dict:
    """The row every preview renders, resolved from the corpus by key.

    Resolved rather than embedded so a preview always shows a passage the
    appliance can actually display. If a re-bake drops the row (below the
    quality floor, banned, re-mined away) this raises instead of quietly
    rendering something else, because the fix is a human choosing a new pin.
    """
    wanted = (PREVIEW_SOURCE_ID, PREVIEW_LINE_NUMBER)
    key_seen = False
    for row in iter_jsonl(corpus_path):
        if (str(row.get("source_id")), row.get("line_number")) != wanted:
            continue
        key_seen = True
        if row.get("matched_text") == PREVIEW_MATCHED_TEXT:
            return row
    key = f"{PREVIEW_SOURCE_ID}:{PREVIEW_LINE_NUMBER}"
    if key_seen:
        raise SystemExit(
            f"preview pin {key} is in {corpus_path} but no copy of it carries the "
            f"matched phrase {PREVIEW_MATCHED_TEXT!r}. The row's time phrase changed; "
            "update PREVIEW_MATCHED_TEXT, or pin a different row."
        )
    raise SystemExit(
        f"preview pin {key} is not in {corpus_path}. The row was dropped from the "
        "corpus, so the previews would show a quote the clock can no longer "
        "display. Pick a replacement and update the PREVIEW_* constants."
    )


def render_preview(theme: str, row: dict, time_str: str = PREVIEW_TIME) -> Image.Image:
    """One preview frame, at the panel's native size in production mode."""
    with frozen_clock(), _unset_photo_path(), _stub_diags_system_info():
        return rq.render(time_str, dict(row), WIDTH, HEIGHT, mode=MODE, theme=theme)


def differing_pixels(a: Image.Image, b: Image.Image) -> int:
    if a.size != b.size:
        return a.size[0] * a.size[1]
    return sum(ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L").histogram()[1:])


def display_path(path: Path) -> str:
    """A path for the log line, without assuming it lives under the repo.

    ``--output-dir`` accepts anything — a relative ``scratch``, an absolute
    ``/tmp/previews`` — and ``Path.relative_to`` raises for both. It raised
    *after* the first image was written, so the advertised override could not
    complete and left a partial directory behind.
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenerate the per-theme README preview thumbnails.",
        epilog="Pass --check to see what would change without writing anything.",
    )
    parser.add_argument(
        "--theme", action="append", metavar="NAME",
        help="Theme to act on; repeatable. Defaults to every registered theme.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Write every theme's preview. Required to rewrite the whole set, "
             "since that is 60+ files and rarely what you meant.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Report which previews differ from a fresh render; write nothing. "
             "Exits 2 if any differ.",
    )
    parser.add_argument("--output-dir", type=Path, default=PREVIEW_DIR)
    parser.add_argument("--corpus", type=Path, default=Path(pq.DEFAULT_DATABASE_PATH))
    parser.add_argument("--time", default=PREVIEW_TIME, metavar="HH:MM")
    return parser.parse_args(argv)


def select_themes(args: argparse.Namespace) -> list[str]:
    known = known_theme_names()
    if args.theme:
        unknown = sorted(set(args.theme) - set(known))
        if unknown:
            raise SystemExit(f"unknown theme(s): {', '.join(unknown)}")
        # Preserve the caller's order, drop duplicates.
        return list(dict.fromkeys(args.theme))
    if not (args.all or args.check):
        raise SystemExit(
            "refusing to rewrite every preview by accident: pass --all to do that, "
            "--theme NAME for one, or --check to see what would change."
        )
    return sorted(known)


def main(argv=None) -> int:
    args = parse_args(argv)
    themes = select_themes(args)
    row = pinned_row(args.corpus)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    drifted: list[tuple[str, int]] = []
    written: list[str] = []
    for theme in themes:
        path = args.output_dir / f"{theme}.png"
        image = render_preview(theme, row, args.time)
        if args.check:
            if not path.exists():
                drifted.append((theme, WIDTH * HEIGHT))
                print(f"MISSING  {theme}")
                continue
            with Image.open(path) as existing:
                delta = differing_pixels(image, existing)
            budget = tolerance_px(theme)
            if delta > budget:
                drifted.append((theme, delta))
                print(f"DIFFERS  {theme:20s} {delta:7d} px (budget {budget})")
            continue
        image.save(path)
        written.append(theme)
        print(f"wrote    {theme:20s} {display_path(path)}")

    if args.check:
        if drifted:
            print(f"\n{len(drifted)} of {len(themes)} previews differ from a fresh render.")
            print("Regenerate with: python3 scripts/generate_theme_previews.py --theme <name>")
            return 2
        print(f"all {len(themes)} previews match a fresh render")
        return 0
    print(f"\nwrote {len(written)} preview(s) to {display_path(args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
