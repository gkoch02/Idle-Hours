#!/usr/bin/env python3
"""Push a rendered literary clock image to a Pimoroni Inky display.

This is intentionally a thin hardware bridge. It expects the render step to
already have produced an image file.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


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


def main() -> int:
    args = parse_args()
    image_path = Path(args.image).expanduser()
    if not image_path.exists():
        raise SystemExit(f"Image not found: {image_path}")

    try:
        from inky.auto import auto
    except Exception as exc:
        raise SystemExit(
            "Could not import Pimoroni Inky library. Install it on the Pi first. "
            f"Original error: {exc}"
        )

    inky = auto(ask_user=True, verbose=True)
    image = Image.open(image_path).convert("RGB")

    if image.size != (inky.width, inky.height):
        image = image.resize((inky.width, inky.height))

    inky.set_image(image, saturation=args.saturation)
    inky.show()
    print(f"Displayed {image_path} on Inky {inky.width}x{inky.height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
