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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Display a rendered image on Inky Impression.")
    parser.add_argument("image", help="Path to rendered image (PNG)")
    parser.add_argument(
        "--saturation",
        type=float,
        default=0.5,
        help="Saturation/quantization hint passed to Inky where supported.",
    )
    return parser.parse_args()


def _push_to_panel(image_path: Path, saturation: float) -> tuple[int, int]:
    """Open the image and push it to the Inky panel. Returns the panel resolution.

    Raises any underlying exception from the Inky library so the caller can decide
    whether to retry.
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

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            width, height = _push_to_panel(image_path, args.saturation)
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
