#!/usr/bin/env python3
"""Unified ``idle-hours`` command — single entry point for every script in the repo.

Replaces ``python3 run_clock.py …`` / ``python3 idle_hours_health.py …`` /
``python3 pick_quote.py …`` / etc. with a single discoverable command:

    idle-hours run --display-script display_inky.py
    idle-hours health --hours 24
    idle-hours pick --time 14:30
    idle-hours bake
    idle-hours --help          # lists every subcommand

**How dispatch works.** Each subcommand is a thin wrapper around the
existing module's ``main()`` function. The wrapper imports the target
module lazily and rewrites ``sys.argv`` so the existing ``parse_args()``
inside that module sees a sensible ``argv[0]`` plus the unmodified flag
list — no per-script refactor needed. Lazy import matters: ``idle-hours
--help`` must not pull Pillow / TOML / runtime_telemetry just to print
the subcommand list. Without it, an operator running ``idle-hours health``
on a dev host would also load the renderer.

**Backwards compat is preserved.** Every existing
``python3 <script>.py …`` invocation keeps working — this CLI is purely
additive. The systemd unit, the bootstrap script, and the docs that
reference the per-script paths don't need touching unless we want to
move them over (separate change).
"""
from __future__ import annotations

import importlib
import sys
from typing import Callable

# Subcommand → (module name, one-line description). Module is loaded lazily
# at dispatch time. Description is shown in ``idle-hours --help``.
#
# Order is operator-relevance: the runtime / QA / health commands first,
# then the corpus pipeline, then dev / debug helpers. Aim is "the things
# you'll grep ``idle-hours --help`` for are at the top."
SUBCOMMANDS: dict[str, tuple[str, str]] = {
    # Runtime / display
    "run": ("idle_hours.run_clock", "Run the clock loop (render + display + buttons + web UI)."),
    "render": ("idle_hours.render_quote", "Render one quote frame to a PNG."),
    "pick": ("idle_hours.pick_quote", "Pick the best quote for a time or bucket; print JSON."),
    "display": ("idle_hours.display_inky", "Push a PNG to the Inky Impression panel (Pi-only)."),
    # QA / health
    "health": ("idle_hours.idle_hours_health", "Summarise telemetry: render counts, latency, last error."),
    "contact-sheet": ("idle_hours.contact_sheet", "Render a 12×12 grid of every fuzzy bucket."),
    "probe-buttons": ("idle_hours.probe_buttons", "Diagnose which GPIO pin each Inky button fires (Pi-only)."),
    # Corpus pipeline
    "mine": ("idle_hours.gutenberg_time_miner", "Harvest time phrases from a Gutenberg ebook or local .txt."),
    "merge": ("idle_hours.merge_candidates", "Merge multiple harvest JSONLs, deduplicating."),
    "coverage": ("idle_hours.bucket_coverage", "Report how many candidates each fuzzy bucket has."),
    "target-sparse": ("idle_hours.target_sparse_buckets", "Mine targeted phrases for empty / sparse buckets."),
    "import-targeted": ("idle_hours.import_targeted_hits", "Reshape targeted hits for merge."),
    "clean": ("idle_hours.clean_display_quotes", "Pick a displayable excerpt from each row."),
    "quality": ("idle_hours.quality_filter", "Score and flag rows for display quality."),
    "enrich": ("idle_hours.enrich_metadata", "Attach Gutenberg title / author from cached headers."),
    "apply-overrides": ("idle_hours.apply_content_overrides", "Layer content_overrides.json onto the corpus."),
    "bake": ("idle_hours.bake_quote_database", "Bake the runtime quote database from the attributed corpus."),
    # Legacy fixers (kept reachable so the docstring's documented usage still works)
    "fix-substring-times": ("idle_hours.fix_substring_time_matches", "Legacy: repair substring-collision time tags."),
    "fix-legacy-buckets": ("idle_hours.fix_legacy_buckets", "Legacy: repair pre-buckets.py 8-state names."),
}


def _format_help() -> str:
    """Render the top-level ``idle-hours --help`` message.

    We hand-roll this rather than letting argparse do it because argparse's
    subparser help is verbose (one block per subcommand including its full
    flag list), and we want the equivalent of ``git help`` — a one-line
    summary per command and a pointer to ``idle-hours <cmd> --help`` for
    details. The lazy-import contract is also incompatible with argparse
    subparsers (which would have to import every module up front to register
    the parsers).
    """
    width = max(len(name) for name in SUBCOMMANDS) + 2
    lines = [
        "Usage: idle-hours <subcommand> [args...]",
        "",
        "Run any Idle Hours pipeline / runtime / QA script through one entry point.",
        "Subcommands accept the same flags as their backing scripts; pass",
        "`idle-hours <subcommand> --help` for the full per-subcommand argument list.",
        "",
        "Subcommands:",
    ]
    for name, (_module, description) in SUBCOMMANDS.items():
        lines.append(f"  {name:<{width}} {description}")
    lines.extend([
        "",
        "Backwards-compat: `python3 <script>.py …` continues to work for every",
        "subcommand listed above; this umbrella CLI is purely additive.",
    ])
    return "\n".join(lines)


def _resolve_main(module_name: str) -> Callable[[], int]:
    """Import the target module and return its ``main`` callable.

    We require ``main`` to exist (every script in this repo has one). A
    missing ``main`` is a configuration bug — ``SUBCOMMANDS`` should not
    point at a module that doesn't expose one — so we surface it with a
    clear error rather than ``AttributeError`` from an obscure place.
    """
    module = importlib.import_module(module_name)
    main = getattr(module, "main", None)
    if not callable(main):
        raise SystemExit(
            f"idle-hours: backing module {module_name!r} has no callable main(); "
            "this is a packaging bug — please report it."
        )
    return main


def main(argv: list[str] | None = None) -> int:
    """Dispatch to a subcommand. Returns the subcommand's exit code.

    ``argv`` defaults to ``sys.argv[1:]`` (the args after the program name)
    so tests can drive the CLI without monkey-patching ``sys.argv``. The
    important subtlety: we MUTATE the global ``sys.argv`` after the
    dispatch decision so the backing module's own ``parse_args()`` still
    works — every script in the repo uses ``argparse.ArgumentParser`` which
    reads from ``sys.argv`` directly.
    """
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(_format_help())
        return 0
    if argv[0] in {"-V", "--version"}:
        # Read the installed version metadata. Falls back to the literal
        # in pyproject.toml if importlib.metadata can't find the dist
        # (e.g. running from a fresh checkout without `pip install -e .`).
        try:
            from importlib.metadata import PackageNotFoundError, version
            print(f"idle-hours {version('idle-hours')}")
        except PackageNotFoundError:
            print("idle-hours (unreleased; running from source checkout)")
        return 0

    subcommand = argv[0]
    if subcommand not in SUBCOMMANDS:
        print(
            f"idle-hours: unknown subcommand {subcommand!r}\n\n"
            f"{_format_help()}",
            file=sys.stderr,
        )
        return 2

    module_name, _description = SUBCOMMANDS[subcommand]
    # Rewrite sys.argv so the backing module's parse_args() sees a clean
    # invocation. argv[0] becomes the script-style name so error messages
    # mention "idle-hours run" rather than the umbrella entry point.
    sys.argv = [f"idle-hours {subcommand}", *argv[1:]]

    backing_main = _resolve_main(module_name)
    result = backing_main()
    # Most main() functions return ``None`` for success or an int exit code.
    # Normalise to int: None → 0 so ``raise SystemExit(main())`` doesn't
    # become ``raise SystemExit(None)`` (which is fine but shows up as
    # status 0 anyway, just unintuitive).
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
