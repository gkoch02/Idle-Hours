#!/usr/bin/env python3
"""Push a rendered literary clock image to a Pimoroni Inky display.

This is intentionally a thin hardware bridge. It expects the render step to
already have produced an image file.
"""
from __future__ import annotations

import argparse
import gc
import sys
import time
from pathlib import Path

from PIL import Image

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1, 4)  # sleeps between attempt 1→2 and 2→3
NON_RETRYABLE_EXCEPTIONS = (FileNotFoundError, PermissionError)

# Per-theme saturation passed to ``inky.set_image``. One rule sets the tier:
# a light page ground takes 0.5, which keeps accents from blowing out on white;
# a dark or coloured ground, or one dominated by falling-density blooms, takes
# 0.7, which stops accents going muddy against it. Entries carry a comment only
# where they depart from that rule. These are starting values, not measured on
# a panel; ``--saturation`` overrides them. Every theme in
# ``render_quote.THEMES`` must have an entry (a test enforces it).
THEME_SATURATION: dict[str, float] = {
    # Light ground.
    "astrarium": 0.5,
    "autochrome": 0.5,
    "bauhaus": 0.5,
    "beksinski": 0.5,
    "betweenus": 0.5,
    "bosch": 0.5,
    "cardcatalog": 0.5,
    "cartograph": 0.5,
    "codex": 0.5,
    "control": 0.5,
    "daguerreotype": 0.5,
    "deco": 0.5,
    "default": 0.5,
    "diags": 0.5,
    "dispatch": 0.5,
    "escritoire": 0.5,
    "glacier": 0.5,
    "herbarium": 0.5,
    "illuminated": 0.5,
    "intaglio": 0.5,
    "kanagawa": 0.5,
    "letter": 0.5,
    "lieder": 0.5,
    "metro": 0.5,
    "mucha": 0.5,
    "newsprint": 0.5,
    "oblivion": 0.5,
    "orbital": 0.5,
    "photo": 0.5,
    "placard": 0.5,
    "pride": 0.5,
    "roman": 0.5,
    "saloon": 0.5,
    "sampler": 0.5,
    "scholar": 0.5,
    "swiss": 0.5,
    "synoptic": 0.5,
    "tarot": 0.5,
    "vinyl": 0.5,
    "witcher": 0.5,
    "yorha": 0.5,
    # Dark, coloured or bloom-heavy ground.
    "abyssal": 0.7,
    "alchemy": 0.7,
    "anna_atkins": 0.7,
    "atomic": 0.7,
    "atropos": 0.7,
    "bakelite": 0.7,
    "betweenus_dark": 0.7,
    "biomech": 0.7,
    "blueprint": 0.7,
    "carcosa": 0.7,
    "chalkboard": 0.7,
    "chanbara": 0.7,
    "chrono": 0.7,
    "circuit": 0.7,
    "comic": 0.7,
    "culture": 0.7,
    "dark": 0.7,
    "dsky": 0.7,
    "expanse": 0.7,
    "expedition": 0.7,
    "fillmore": 0.7,
    "firmament": 0.7,
    "furies": 0.7,
    "gothic": 0.7,
    "goya": 0.7,
    "grimdark": 0.7,
    "grimoire": 0.7,
    "hades": 0.7,
    "hal": 0.7,
    "hitchhiker": 0.7,
    "izakaya": 0.7,
    "lcars": 0.7,
    "lumon": 0.7,
    "marker": 0.7,  # white ground, but the border uses every chromatic ink and green reads mint at 0.5
    "marquee": 0.7,
    "nightvision": 0.7,
    "nocturne": 0.7,
    "observation": 0.7,
    "outrun": 0.7,
    "plaque": 0.7,
    "pulp": 0.7,
    "questline": 0.7,
    "risograph": 0.7,  # two spot inks and no black to anchor them
    "saros": 0.7,
    "semiotic": 0.7,  # the frame paints a black bulkhead over the white page ground
    "trisolaris": 0.7,
    "vhs": 0.7,
    "vitrail": 0.7,  # coloured glass covers nearly the whole canvas around a white cartouche
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Display a rendered image on Inky Impression.")
    parser.add_argument("image", help="Path to rendered image (PNG)")
    parser.add_argument(
        "--saturation",
        type=float,
        default=None,
        help=(
            "Saturation/quantization hint passed to Inky where supported. "
            "Overrides the per-theme default if set."
        ),
    )
    parser.add_argument(
        "--theme",
        choices=sorted(THEME_SATURATION),
        default="default",
        help="Theme being displayed; selects the default saturation when --saturation is unset.",
    )
    return parser.parse_args()


def resolve_saturation(theme: str, override: float | None) -> float:
    """Return the saturation value to push to the panel.

    Explicit ``--saturation`` overrides the per-theme default. Unknown themes fall
    back to the ``default`` theme's saturation.
    """
    if override is not None:
        return override
    return THEME_SATURATION.get(theme, THEME_SATURATION["default"])


def _release_failed_attempt(exc: Exception) -> Exception:
    """Drop traceback-owned hardware objects before another panel attempt.

    An exception traceback retains the failed ``_push_to_panel`` frame, which
    in turn retains the Inky object and its gpiod line requests. Keeping that
    exception in ``last_error`` poisoned the next attempt with a misleading
    "pins are in use" failure. Preserve the exception for the final message,
    but sever traceback/context references and collect any hardware wrapper
    cycles before retrying.
    """
    exc.__traceback__ = None
    exc.__context__ = None
    exc.__cause__ = None
    gc.collect()
    return exc


def _push_to_panel(image_path: Path, saturation: float) -> tuple[int, int]:  # pragma: no cover - hardware only
    """Open the image and push it to the Inky panel. Returns the panel resolution.

    Raises any underlying exception from the Inky library so the caller can decide
    whether to retry. Body excluded from coverage because the real ``inky.auto``
    import requires a physical Pimoroni panel; tests mock this function out via
    ``patch("idle_hours.display_inky._push_to_panel", ...)`` and exercise the retry wrapper.
    """
    from inky.auto import auto

    inky = auto(ask_user=True, verbose=True)
    image = Image.open(image_path).convert("RGB")
    if image.size != (inky.width, inky.height):
        image = image.resize((inky.width, inky.height))
    inky.set_image(image, saturation=saturation)
    inky.show()
    return inky.width, inky.height


def main() -> int:
    args = parse_args()
    image_path = Path(args.image).expanduser()
    if not image_path.exists():
        raise SystemExit(f"Image not found: {image_path}")

    try:
        from inky.auto import auto  # noqa: F401 — surface the import error up front
    except Exception as exc:
        raise SystemExit(
            "Could not import Pimoroni Inky library. Install it on the Pi first. "
            f"Original error: {exc}"
        )

    saturation = resolve_saturation(args.theme, args.saturation)
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            width, height = _push_to_panel(image_path, saturation)
        except Exception as exc:
            last_error = _release_failed_attempt(exc)
            if isinstance(exc, NON_RETRYABLE_EXCEPTIONS):
                raise SystemExit(f"Inky push failed (non-retryable setup error): {exc!r}") from None
            if attempt < MAX_ATTEMPTS:
                backoff = RETRY_BACKOFF_SECONDS[attempt - 1]
                print(
                    f"Inky push failed (attempt {attempt}/{MAX_ATTEMPTS}): {exc!r}; "
                    f"retrying in {backoff}s",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(backoff)
            continue
        print(f"Displayed {image_path} on Inky {width}x{height}")
        return 0

    raise SystemExit(f"Inky push failed after {MAX_ATTEMPTS} attempts: {last_error!r}")


if __name__ == "__main__":
    raise SystemExit(main())
