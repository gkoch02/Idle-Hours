#!/usr/bin/env python3
"""Push a rendered literary clock image to a Pimoroni Inky display.

This is intentionally a thin hardware bridge. It expects the render step to
already have produced an image file.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PIL import Image

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1, 4)  # sleeps between attempt 1→2 and 2→3

# Per-theme saturation defaults. The Spectra 6 panel renders dark backgrounds with
# a different waveform than light ones; pushing saturation slightly higher on the
# dark theme keeps accent colours from looking muddy. Unknown themes fall back to
# the ``default`` entry via ``resolve_saturation``.
#
# Light themes keep the gentler 0.5 to avoid blown-out accent reds / blues; dark
# themes and the green-on-black ``nightvision`` use 0.7 to keep the accent pop.
# ``newsprint`` is intentionally low-contrast (no colour accent) so 0.5 matches
# the perceptual brief — pushing it higher would start tinting the blacks.
THEME_SATURATION: dict[str, float] = {
    "default": 0.5,
    "dark": 0.7,
    "scholar": 0.5,
    "newsprint": 0.5,
    "nightvision": 0.7,
    # Light background, blue ink, red dimension marks — same gentle saturation
    # as the other light themes so the red accent stays bright without bleeding.
    "blueprint": 0.5,
    # Rubricated manuscript — red body text on white, lapis-blue accent.
    # Light-background themes stay at 0.5 so the red body doesn't bloom into
    # orange on the panel.
    "illuminated": 0.5,
    # Bauhaus poster — white bg, black body, blue + red as the two accents.
    # Light background stays at the gentler 0.5 saturation so the red
    # ornament marks don't bloom into orange next to the crisp black body.
    "bauhaus": 0.5,
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


def _push_to_panel(image_path: Path, saturation: float) -> tuple[int, int]:  # pragma: no cover - hardware only
    """Open the image and push it to the Inky panel. Returns the panel resolution.

    Raises any underlying exception from the Inky library so the caller can decide
    whether to retry. Body excluded from coverage because the real ``inky.auto``
    import requires a physical Pimoroni panel; tests mock this function out via
    ``patch("display_inky._push_to_panel", ...)`` and exercise the retry wrapper.
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
            last_error = exc
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
