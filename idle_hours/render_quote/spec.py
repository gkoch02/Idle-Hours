"""What each theme module declares about itself (issue #335).

Every module under ``themes/`` ends with one ``SPEC``: a :class:`BorderSpec`
for a theme that paints a border round the shared quote layout, or a
:class:`FrameSpec` for one that composes its whole frame. ``registry`` collects
them into the dispatch tables ``render`` reads, so a theme is wired up by its
own module rather than by entries kept by hand elsewhere.

A spec carries dispatch only. A theme's colours, fonts and text flags stay in
``theme_tables``, because ``fonts``, ``layout`` and ``text`` read them from
below the theme modules.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


@dataclass(frozen=True)
class BorderSpec:
    """A theme that paints a border, then lays the shared quote out over it.

    ``render`` paints a border once, after the quote is laid out (the
    *knockout pass*); layout only measures text, so nothing is lost by
    waiting. The source card and the static message paint it once on the bare
    page with ``paint``.

    ``paints_twice`` keeps the old first paint on the bare page ahead of the
    knockout pass, for a painter that does not reproduce its own output when
    run again over a painted page: that theme's look is the composite of the
    two paints, so dropping the first would change it (issue #361). It is a
    recorded quirk, not a feature to opt into; ``TestPaintsTwice`` fails if a
    flag is missing or no longer changes anything.

    ``clear_rect_pad`` is ``(x, top, bottom)``: how far the knockout rect
    reaches past the quote and attribution block, wide enough that the
    theme's framing clears the body text. A theme with a pad gets that rect in
    the knockout pass as ``clear_rect`` (``None`` when the layout leaves no
    usable rect), plus ``time_str`` if it sets ``wants_time``. A theme without
    a pad is painted the same way both times.

    ``knockout`` replaces ``paint`` for the knockout pass, for a theme that
    needs more than one call there (blueprint repaints its grid inside the
    rect).

    ``debug_label_inset`` pushes the debug-mode "DEBUG MODE" banner inward,
    measured from the right canvas edge, for a border that paints a graphic
    in the banner's top-right y=14-29 band. Leave it ``None`` when the border
    clears that band; ``test_debug_label_does_not_clip_border`` catches a
    missing inset.
    """

    themes: tuple[str, ...]
    paint: Callable[..., None]
    clear_rect_pad: tuple[int, int, int] | None = None
    wants_time: bool = False
    knockout: Callable[..., None] | None = None
    debug_label_inset: int | None = None
    paints_twice: bool = False

    def __post_init__(self) -> None:
        if not self.themes:
            raise ValueError("a BorderSpec must name at least one theme")
        if self.clear_rect_pad is None and (self.wants_time or self.knockout is not None):
            raise ValueError(f"{self.themes}: wants_time and knockout only apply to the knockout pass, which needs a clear_rect_pad")

    def paint_knockout(self, image, colors: dict, clear_rect, time_str: str) -> None:
        """The paint ``render`` makes once the quote is laid out."""
        if self.clear_rect_pad is None:
            self.paint(image, colors)
            return
        kwargs: dict = {"clear_rect": clear_rect}
        if self.wants_time:
            kwargs["time_str"] = time_str
        (self.knockout or self.paint)(image, colors, **kwargs)


@dataclass(frozen=True)
class FrameSpec:
    """A theme that composes its whole frame: ``render(time_str, row, width, height)``."""

    themes: tuple[str, ...]
    render: Callable[..., Image.Image]

    def __post_init__(self) -> None:
        if not self.themes:
            raise ValueError("a FrameSpec must name at least one theme")
