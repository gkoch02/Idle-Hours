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
    # Cyanotype blueprint: blue ground (the only theme to claim Spectra 6's
    # blue as a *page background*), white ink for every mark. Same coloured-
    # ground tier as ``atomic`` / ``comic`` so the white-on-blue marks stay
    # crisp against the panel's anchored blue.
    "blueprint": 0.7,
    # Light white-background themes inherit the default 0.5 starting point —
    # same empirical tier as ``default`` / ``scholar`` / ``newsprint``. These
    # defaults are sensible initial values and are easy to override at runtime
    # via ``--saturation`` if real-panel calibration suggests otherwise.
    "illuminated": 0.5,
    "bauhaus": 0.5,
    # Black ground with a chromatic accent — same tier as ``dark`` /
    # ``nightvision`` so the rubric red and white body don't desaturate
    # against the panel's anchored black.
    "gothic": 0.7,
    # Non-standard grounds (``risograph`` has no black ink to anchor the
    # two spot colours; ``comic`` has a high-chroma yellow ground rather
    # than white) start at the 0.7 tier used by dark-background themes,
    # on the reasoning that the accent hues need a little more push to
    # stay visibly distinct from a non-white, non-black neighbour.
    # Revisit once we have real-panel samples — `--saturation` overrides.
    "risograph": 0.7,
    "comic": 0.7,
    # White ground with chromatic accent — same tier as ``default`` /
    # ``scholar`` / ``newsprint`` / ``blueprint`` / ``illuminated`` /
    # ``bauhaus``. Black typewriter ink + red rubber stamp on white
    # paper sits squarely in the light-background tier.
    "dispatch": 0.5,
    # Saturated green ground (the only theme whose page_bg is green) —
    # same tier as other coloured-ground / non-white themes (`comic` /
    # `risograph` / `dark` / `nightvision`) so the red atomic accents
    # and oversized red quote marks don't desaturate against the
    # vivid Sputnik-green background.
    "atomic": 0.7,
    # White ground but the decorative border lights up every Spectra 6
    # spot colour the panel can produce (red / yellow / blue / green /
    # black). Push to the higher 0.7 tier so all four chromatic accents
    # in the dashed perimeter and corner asterisks stay punchy — at the
    # default 0.5 the green dashes can read pale-mint against the white
    # paper rather than as confident marker ink. Black body text isn't
    # affected by saturation either way.
    "marker": 0.7,
    # White ground / black body / red accent — same chromatic pressure
    # as ``default`` / ``dispatch`` so the gentler 0.5 tier is the
    # right starting point. The saloon theme's red foxing speckles
    # are sparse enough that they read as aged-paper texture at any
    # saturation; pushing higher would risk turning the speckles into
    # vivid spots that compete with the body text. Override at runtime
    # via ``--saturation`` if real-panel calibration suggests otherwise.
    "saloon": 0.5,
    # Light limestone ground / black body / red rubrum accent — same
    # palette shape as ``default`` / ``dispatch`` / ``saloon`` so the
    # gentler 0.5 tier is the natural starting point. The Roman theme's
    # stone-grain speckles are sparse and confined to the outer margin
    # ring; pushing saturation higher would risk turning the SPQR
    # cartouche and mid-edge interpunct dots into vivid spots that
    # compete with the body inscription. Override via ``--saturation``
    # after real-panel calibration if the rubrum reads too pale.
    "roman": 0.5,
    # Yellow parchment ground + black body + red matched-phrase rubric
    # + blue Hermetic ornaments. The yellow ground places this in the
    # coloured-ground tier alongside ``comic`` (also yellow page_bg),
    # so 0.7 keeps the red rubricated accent and the blue magic-circle
    # sigils crisp against the parchment — at 0.5 the corner pentagrams
    # would dither into a muted lavender against the yellow rather than
    # reading as the sharp red ritual marks they should be.
    "alchemy": 0.7,
    # Black ground / white IM Fell English body / red TFoustScript
    # matched phrase. Same chromatic-on-dark profile as ``gothic`` and
    # ``nightvision`` — push the red accent and oversized red quote
    # marks so they don't desaturate against the panel's anchored
    # black ground.
    "grimoire": 0.7,
    # White ground / black body / red accent paired with Righteous. Same
    # chromatic-on-light profile as ``default`` / ``dispatch`` / ``saloon`` /
    # ``roman`` — the gentler 0.5 tier keeps the red rising-sun fan and
    # the stepped corner ornaments crisp without over-saturating the
    # body's black ink. Override via ``--saturation`` if real-panel
    # calibration suggests otherwise.
    "deco": 0.5,
    # White ground / blue Iceland body / green matched-phrase accent. Two
    # chromatic ink colours on a light ground — same tier as the other
    # white-ground themes. The green accent reads cleanly on white at 0.5;
    # pushing higher would risk muddying the body's blue against the
    # frost-crystal accent ornaments.
    "glacier": 0.5,
    # Black slate ground / white chalk body / yellow chalk-stick matched
    # phrase. Same chromatic-on-dark profile as ``dark`` / ``gothic`` /
    # ``nightvision`` / ``grimoire`` — push the yellow accent so it doesn't
    # desaturate to a muddy ochre against the panel's anchored black.
    "chalkboard": 0.7,
    # White sign-paper ground / black hand-printed body / red highlight
    # accent. Same chromatic-on-light profile as ``default`` / ``deco`` /
    # ``dispatch`` / ``saloon`` / ``roman`` — the gentler 0.5 tier keeps
    # the red thumbtack corner accents crisp without over-saturating the
    # body's black ink. Override via ``--saturation`` if real-panel
    # calibration suggests otherwise.
    "placard": 0.5,
    # Black ink-sky ground with a load-bearing red rising-sun disc that
    # dominates the bottom-right quadrant of the page. Same chromatic-
    # on-dark profile as ``dark`` / ``gothic`` / ``grimoire`` /
    # ``nightvision`` / ``chalkboard`` — push the red disc and accent so
    # the dramatic blood-sun reads vivid rather than half-dithering into
    # a muted brick-red against the panel's anchored black.
    "chanbara": 0.7,
    # Black computer-console ground with synthesised tangerine elbow + yellow /
    # coral / red pill buttons on the sidebar. Same chromatic-on-dark profile
    # as ``dark`` / ``gothic`` / ``grimoire`` / ``nightvision`` / ``chalkboard``
    # / ``chanbara`` — push the R+Y biased tangerine and the standalone yellow
    # so the LCARS console reads as the bright Okudagram orange rather than a
    # muddied amber against the panel's anchored black.
    "lcars": 0.7,
    # Diagnostic / status panel — white ground, black body, red accent.
    # Same chromatic-on-light profile as ``default`` / ``deco`` /
    # ``saloon`` / ``roman`` so the gentler 0.5 tier is the natural
    # starting point. The synthesised-stipple swatches are the whole
    # point of the diags frame: their perceived hues depend on adjacent-
    # pixel averaging at panel distance, so over-saturation would shift
    # the calibration target.
    "diags": 0.5,
    # Swiss International / modernist — white ground, black Inter body,
    # red accent. Same chromatic-on-light profile as ``default`` /
    # ``deco`` / ``dispatch`` / ``saloon`` / ``roman`` so the gentler
    # 0.5 tier is the natural starting point. The single 6 px red
    # square is the only chromatic ink on the page besides the matched
    # phrase; over-saturation would turn that quiet accent into a
    # competing focal point against the deliberately minimal grid.
    "swiss": 0.5,
    # Herbarium / pressed-plant specimen sheet — white ground (with
    # cream Layer-0 wash), black IM Fell body, olive-stippled matched
    # phrase. Same chromatic-on-light profile as ``default`` /
    # ``placard`` — the matched phrase synthesises olive via a Y+G
    # stipple, and the pressed-leaf graphic uses the same recipe, so
    # the 0.5 tier preserves the dried-leaf colour the period
    # specimens actually develop. Pushing higher would saturate the
    # olive into a brighter chartreuse that breaks the aged-specimen
    # register.
    "herbarium": 0.5,
    # Mucha / Art Nouveau — cream-washed white ground, body painted
    # via maroon stipple, matched phrase via cyan stipple. Both body
    # and accent are synthesised colours that depend on adjacent-
    # pixel averaging, so the 0.5 tier preserves the period palette
    # of Belle-Époque posters. Pushing higher risks shifting the
    # body's maroon into a more saturated red and the matched
    # phrase's cyan into a brighter sky-blue, breaking the warm-cool
    # contrast the theme depends on.
    "mucha": 0.5,
    # Fillmore / 1960s psychedelic poster — yellow ground with all
    # six Spectra-6 inks visible simultaneously. Same chromatic-on-
    # coloured-ground profile as ``comic`` (also yellow page_bg) —
    # the 0.7 tier keeps the green blob, blue blob, red body, and
    # blue matched phrase confidently saturated against the warm
    # yellow ground rather than half-fading into the page.
    "fillmore": 0.7,
    # Firmament / 17th-century celestial atlas — navy (B+K stipple)
    # ground with chromatic ornaments (yellow stars, sky-blue moon,
    # tangerine + cyan Saturn, lavender Milky Way). Same dark-ground
    # tier as ``dark`` / ``nightvision`` / ``gothic`` / ``chanbara``
    # so the matched-phrase cream (Y+W) and the synthesised ornament
    # tones stay punchy against the navy ground rather than fading
    # into a dim mid-tone.
    "firmament": 0.7,
    # Astrarium / astronomical-clock dashboard — cream-washed white
    # ground, black serif body, tangerine matched phrase (R+Y 5/8:3/8
    # — same recipe ``deco`` uses), with teal (G+B) and sepia (R+G)
    # ring quadrants on the dial. Same chromatic-on-light profile as
    # ``deco`` / ``dispatch`` / ``herbarium`` / ``mucha`` — the
    # gentler 0.5 tier preserves the dashboard's mid-tone
    # halftone-stipple register. Pushing higher would saturate the
    # synthesised tangerine into a brighter fluorescent orange that
    # breaks the editorial / instrument-panel reading the layout is
    # going for.
    "astrarium": 0.5,
    # Kanagawa / stylised Japanese seascape — white washi-paper ground
    # with a seigaiha textile band (indigo half-disks + white concentric
    # arcs + navy deepest-row post-pass) anchored at the bottom, a
    # cream-tinted rounded paper panel knocked out for the body text,
    # and a red rounded-rectangle hanko seal in the bottom-right corner.
    # Same chromatic-on-light profile as ``default`` / ``mucha`` /
    # ``deco`` / ``placard``; the 0.5 tier preserves the cream-panel
    # vellum register and the navy deepest-row reading — pushing higher
    # would saturate the panel's Y+W cream into a brighter lemon yellow
    # and shift the navy stipple toward solid indigo.
    "kanagawa": 0.5,
    # Marquee / 1930s movie-palace facade — black ground, yellow
    # bulb-light border, big chunky Bungee Shade time digits in white,
    # Cardo Italic quote body with red matched-phrase accent. Same
    # dark-ground tier as ``dark`` / ``lcars`` / ``firmament`` /
    # ``gothic`` / ``nightvision`` so the yellow bulb-lights, the
    # white Cardo body, and the red matched-phrase accent all stay
    # confidently chromatic against the panel's anchored black.
    "marquee": 0.7,
    # Tarot / major-arcana card — cream-washed white ground (Y+W
    # Bayer wash, same recipe as ``illuminated`` / ``herbarium`` /
    # ``mucha`` / ``astrarium``), doubled red+black rubricated border,
    # Tyrian-purple matched-phrase card name. Same chromatic-on-light
    # profile as ``illuminated`` / ``mucha`` / ``astrarium`` — the
    # gentler 0.5 tier preserves the rubricated red and the synthesised
    # purple register without over-saturating the corner pentagrams.
    "tarot": 0.5,
    # Vinyl / turntable + record label — cream-washed sleeve ground
    # (right half) plus a solid black vinyl disk (left half). The
    # sleeve is the dominant region visually, and the black disk has
    # no synthesised colour that needs a saturation boost — the red
    # label and red stylus arm are solid Spectra 6 red. Same
    # chromatic-on-light profile as ``default`` / ``deco`` /
    # ``astrarium`` so the gentler 0.5 tier is the natural starting
    # point. The matched-phrase tangerine (R+Y 5:3) on the sleeve
    # uses the same recipe ``astrarium`` does and reads correctly at
    # this saturation.
    "vinyl": 0.5,
    # Cartograph / antique cartographer's chart — cream Y+W Bayer-
    # washed white ground with sparse R+G sepia foxing, two
    # diagonal-corner R+G sepia coastlines, an R+Y tangerine compass
    # rose, a solid-black sea-serpent margin doodle, three Latin
    # place-name labels in sepia, and a doubled red+black rubricated
    # cartouche knockout around the body text. Same chromatic-on-
    # light profile as ``default`` / ``deco`` / ``astrarium`` /
    # ``herbarium`` / ``tarot`` — the gentler 0.5 tier preserves the
    # cream-foxed parchment register and keeps the synthesised
    # sepia / tangerine tones reading as period inks rather than
    # over-saturating into vivid crayon spots that would compete
    # with the body text. Pushing higher would shift the foxing
    # scatter toward distinct red+green specks instead of averaging
    # into rust-brown, breaking the aged-paper illusion the layer
    # builds.
    "cartograph": 0.5,
    # Vitrail / Gothic stained-glass cathedral window. Although the
    # literary quote sits on a clear white-glass cartouche, the dominant
    # visual mass is heavily-saturated colored glass (solid red / blue /
    # yellow / green panes plus the jewel-tone Bayer stipples and the
    # twelve-petal rose window) covering nearly the whole canvas. Like
    # ``marquee`` / ``comic`` / ``atomic`` / ``blueprint`` and the other
    # saturated / colored-ground themes, the 0.7 tier keeps those jewel
    # tones punchy at panel viewing distance instead of desaturating them
    # toward muddy mid-tones. The white cartouche has no chroma to scale,
    # so the higher tier costs nothing there.
    "vitrail": 0.7,
    # Questline / pixel RPG dialogue. Black night-sky ground with a
    # sky-blue/green pixel scene and a navy (blue+black) dialogue box; the
    # white body text and yellow matched-phrase accent need the dark-ground
    # 0.7 tier to stay crisp against the saturated blue/green field rather
    # than washing out toward mid-tones at panel viewing distance.
    "questline": 0.7,
    # Chrono / 16-bit SNES JRPG. Gradient twilight-blue sky and a translucent
    # navy→blue dialogue window dominate the canvas; the white body, yellow
    # matched-phrase accent, and the synthesised gradient tones all need the
    # dark-ground 0.7 tier to stay punchy against the saturated blue field.
    "chrono": 0.7,
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
