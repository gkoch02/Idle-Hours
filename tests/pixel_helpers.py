"""Pillow-version-agnostic pixel inspection helpers for the image tests.

``Image.getdata()`` is deprecated and removed in Pillow 14 (2027-10-15); its
replacement, ``get_flattened_data()``, only landed in Pillow 11.1. Rather than
pin the suite to the narrow window where both exist, the assertions that used
it are expressed through APIs that have been stable across every Pillow
release — ``getcolors()`` for "which inks appear / how many of each", and
``tobytes()`` for "is this frame byte-identical".

That is also the better semantic fit. Most of these assertions are about the
*set* of inks on the page or about determinism, not about walking 384,000
pixels in order, and both replacements say so directly.
"""

from __future__ import annotations

from PIL import Image


def _colour_counts(image: Image.Image) -> list[tuple[int, tuple[int, int, int]]]:
    """``(count, colour)`` pairs for every distinct colour in ``image``.

    Converts to RGB first so a palette- or L-mode image yields comparable
    tuples, and caps ``maxcolors`` at the pixel count so the return is never
    ``None`` — an image cannot hold more distinct colours than it has pixels.
    """
    rgb = image.convert("RGB")
    return rgb.getcolors(maxcolors=max(1, rgb.width * rgb.height))


def distinct_inks(image: Image.Image) -> set[tuple[int, int, int]]:
    """The set of distinct RGB colours present in ``image``."""
    return {colour for _count, colour in _colour_counts(image)}


def ink_counts(image: Image.Image) -> dict[tuple[int, int, int], int]:
    """Pixel histogram of ``image`` keyed by RGB colour.

    Use ``.get(ink, 0)`` when asking about an ink that may be absent — an
    unused colour has no entry (``Counter``'s zero default is not reproduced,
    deliberately: a missing key is the honest answer).
    """
    return {colour: count for count, colour in _colour_counts(image)}


def pixel_bytes(image: Image.Image) -> bytes:
    """Raw RGB bytes of ``image``, for order-sensitive equality checks.

    Determinism assertions need full-sequence comparison, which ``getcolors``
    cannot provide (it is unordered). ``tobytes()`` is the version-agnostic
    way to say "the same pixels in the same places".
    """
    return image.convert("RGB").tobytes()
