"""Render a picked literary clock quote to an 800x480 Spectra 6 PNG.

The package is layered, lowest first (``tests/test_render_quote_layering.py``
holds the order): ``_paths`` (font files and fallback chains), ``clock`` (the
wall-clock seam), ``palette``, ``theme_tables`` (each theme's colours, fonts
and text flags), ``fonts``, ``layout``, ``text``, ``primitives``, ``furniture``
and ``spec`` (what a theme declares), then ``themes._shared`` and
``themes._culture_common`` (code several themes use), one module per theme
under ``themes/``, ``registry`` (the dispatch tables, built from each theme's
``SPEC``) and ``core`` (``render``, the sleep and source-card frames and the
command line). Issue #335 split it out of one 34,000-line module;
``docs/render_quote_split.md`` records how.

``__all__`` is the public API. Every other name still reads through the
package from the submodule that binds it, for tests and scripts, but nothing
can be written through it: patch the module whose code reads the name (see
``_facade``).
"""

from typing import TYPE_CHECKING

from . import (
    _facade,
    _paths,
    clock,
    core,
    fonts,
    furniture,
    layout,
    palette,
    primitives,
    registry,
    spec,
    text,
    theme_tables,
    themes,
)
from .themes import _culture_common as _themes_culture_common
from .themes import _shared as _themes_shared

__all__ = [
    "BASE_DIR",
    "BORDER_SPECS",
    "CYCLE_EXCLUDED_THEMES",
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "FRAME_SPECS",
    "META_FONT_CANDIDATES",
    "PLAIN_THEMES",
    "SLEEP_QUOTE_ROW",
    "SPECTRA6",
    "SPECTRA6_PALETTE",
    "THEMES",
    "THEME_FONTS",
    "THEME_ORDER",
    "BorderSpec",
    "FrameSpec",
    "clear_photo_cache",
    "clock",
    "dither_image_to_palette",
    "load_font",
    "main",
    "parse_args",
    "photo_source_stamp",
    "pick_quote",
    "render",
    "render_sleep_frame",
    "render_source_card",
    "render_static_message",
    "snap_image_to_palette",
    "theme_font_candidates",
]

if TYPE_CHECKING:
    # The facade resolves names at runtime, which editors and type checkers
    # cannot see; this shows them the public API.
    from ._paths import BASE_DIR, META_FONT_CANDIDATES
    from .core import (
        clear_photo_cache,
        main,
        parse_args,
        pick_quote,
        render,
        render_sleep_frame,
        render_source_card,
        render_static_message,
    )
    from .fonts import load_font, theme_font_candidates
    from .furniture import SLEEP_QUOTE_ROW
    from .palette import DEFAULT_HEIGHT, DEFAULT_WIDTH, SPECTRA6, SPECTRA6_PALETTE, dither_image_to_palette, snap_image_to_palette
    from .registry import BORDER_SPECS, FRAME_SPECS, PLAIN_THEMES
    from .spec import BorderSpec, FrameSpec
    from .theme_tables import CYCLE_EXCLUDED_THEMES, THEME_FONTS, THEME_ORDER, THEMES
    from .themes.photo import photo_source_stamp
del TYPE_CHECKING

# Lowest layer first, so a name bound in several modules reads from where it is
# defined; core last, since it imports from all of them.
_facade.install(
    __name__,
    (
        _paths, clock, palette, theme_tables, fonts, layout, text, primitives, furniture, spec,
        _themes_shared, _themes_culture_common, *themes.THEME_MODULES, registry, core,
    ),
)
