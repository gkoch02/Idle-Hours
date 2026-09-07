"""The quiet-hours sleep frame: the bundled sleep quote, and ``--quiet-theme``.

Cross-cutting by nature — the feature spans ``render_quote`` (the frame),
``runtime_theme`` (the theme resolution), ``runtime_quiet`` (the dispatch),
and ``runtime_actions`` (the button paths) — so it gets its own module rather
than being scattered across four, in the same spirit as
``test_bake_equivalence.py``.

The load-bearing fence here is
``TestSleepFrameContent::test_dark_theme_frame_reproduces_the_bundled_png``:
``assets/goodnight.png`` was hand-produced long before this code existed, and
the themed renderer reproduces it to the pixel. That is what makes the default
flip from the static PNG to ``--quiet-image auto`` safe — a ``dark``-theme
appliance sees no change at all.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from unittest.mock import patch

import pytest
from PIL import Image, ImageChops

from idle_hours import render_quote as rq
from idle_hours import run_clock
from idle_hours.runtime_quiet import enter_quiet, exit_quiet, render_quiet_frame
from idle_hours.runtime_state import RuntimeState
from idle_hours.runtime_theme import QUIET_THEME_INHERIT, resolve_quiet_theme
from idle_hours.theme_names import theme_cycle

BUNDLED_GOODNIGHT = rq.BASE_DIR / "assets" / "goodnight.png"


def _quiet_args(tmp_path, **overrides) -> argparse.Namespace:
    defaults = dict(
        render_script="render_quote.py",
        output=str(tmp_path / "current.png"),
        width=800, height=480, display_script=None,
        mode="debug", theme="default",
        auto_day_theme="default", auto_night_theme="dark",
        history_path="", history_days=7, telemetry_path="",
        state_path="", quiet_start="22:00", quiet_end="06:00",
        quiet_off=False, quiet_image="auto", quiet_theme=QUIET_THEME_INHERIT,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _diff_pixels(a: Image.Image, b: Image.Image) -> int:
    return sum(ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L").histogram()[1:])


class TestSleepFrameContent:
    def test_row_carries_the_quote_and_its_attribution(self):
        assert rq.SLEEP_QUOTE_ROW["display_quote"] == "To sleep, perchance to dream."
        assert rq.SLEEP_QUOTE_ROW["author"] == "William Shakespeare"
        assert rq.SLEEP_QUOTE_ROW["title"] == "Hamlet"

    def test_row_has_no_corpus_identity(self):
        """The sleep row must never be confusable with a real corpus row.

        Anything keying on ``(source_id, line_number)`` — the anti-repeat
        ledger, ``ban_quote_keys``, the pin — would otherwise be able to match
        it. It never reaches the picker, so it carries no such pair.
        """
        assert "source_id" not in rq.SLEEP_QUOTE_ROW
        assert "line_number" not in rq.SLEEP_QUOTE_ROW

    def test_dark_theme_frame_reproduces_the_bundled_png(self):
        """The themed renderer reproduces ``assets/goodnight.png`` exactly.

        The bundled PNG is a frozen ``dark``-theme render of this very row, so
        an appliance on the dark theme sees a byte-identical frame whether it
        copies the PNG or renders it. That equivalence is what lets
        ``--quiet-image`` default to ``auto`` without changing what anyone's
        panel shows tonight.
        """
        rendered = rq.render_sleep_frame("22:00", 800, 480, theme="dark")
        bundled = Image.open(BUNDLED_GOODNIGHT)
        assert rendered.size == bundled.size
        assert _diff_pixels(rendered, bundled) == 0

    def test_matched_phrase_takes_the_theme_accent(self):
        """"sleep" is painted in the accent colour, not merely bolded.

        ``matched_text`` here is not a time phrase, so this also pins that
        ``resolve_display_match``'s literal-search-first branch is what the
        sleep row relies on — a regression that made it time-phrase-only would
        silently drop the accent and nothing else would notice.
        """
        assert rq.resolve_display_match(
            rq.SLEEP_QUOTE_ROW["display_quote"], rq.SLEEP_QUOTE_ROW["matched_text"],
        ) == "sleep"
        accent = rq.THEMES["dark"]["accent"]
        frame = rq.render_sleep_frame("22:00", 800, 480, theme="dark")
        assert accent in {c for _n, c in frame.convert("RGB").getcolors(maxcolors=1 << 20)}

    def test_no_debug_footer_even_though_the_loop_runs_in_debug_mode(self):
        """A sleep frame is always production-mode.

        ``run_clock`` defaults to ``--mode debug``, and the goodnight branch
        does not thread ``args.mode`` through, so this pins that a debug
        appliance still gets a clean sleep frame.
        """
        debug = rq.render("22:00", dict(rq.SLEEP_QUOTE_ROW), 800, 480, mode="debug", theme="dark")
        sleep = rq.render_sleep_frame("22:00", 800, 480, theme="dark")
        assert _diff_pixels(debug, sleep) > 0

    @pytest.mark.parametrize("theme", sorted(rq.THEMES))
    def test_renders_in_every_registered_theme(self, theme):
        """Every theme must survive the synthetic row.

        The row has no ``source_id`` / ``line_number`` / ``quality_score`` /
        ``fuzzy_bucket``, so a theme reaching for a corpus field the picker
        always supplies would raise here rather than at 22:00 on the panel.
        """
        frame = rq.render_sleep_frame("22:00", 800, 480, theme=theme)
        assert frame.size == (800, 480)
        inks = {c for _n, c in frame.convert("RGB").getcolors(maxcolors=1 << 20)}
        assert inks <= set(rq.SPECTRA6.values())

    def test_the_shared_row_is_never_mutated_by_a_render(self):
        """``SLEEP_QUOTE_ROW`` is module-level and reaches 60+ theme painters.

        Every other row ``render`` sees is freshly built by the picker, so this
        is the one shared-mutable call site — and ``contact_sheet`` /
        ``/api/preview`` / ``--once`` each render many frames per process.
        """
        import copy
        before = copy.deepcopy(rq.SLEEP_QUOTE_ROW)
        for theme in ("dark", "cardcatalog", "lieder", "izakaya", "betweenus"):
            rq.render_sleep_frame("22:00", 800, 480, theme=theme)
        assert rq.SLEEP_QUOTE_ROW == before

    def test_falls_back_to_the_wall_clock_without_a_time(self):
        assert rq.render_sleep_frame(None, 800, 480, theme="dark").size == (800, 480)


class TestGoodnightCli:
    """``render_quote.py --mode goodnight`` — sleep quote by default."""

    def _run(self, tmp_path, *extra):
        out = tmp_path / "frame.png"
        subprocess.run(
            [sys.executable, "-m", "idle_hours.render_quote", "--mode", "goodnight",
             "--theme", "dark", "--time", "22:00", "--output", str(out), *extra],
            check=True, capture_output=True,
        )
        return Image.open(out)

    def test_default_renders_the_sleep_quote(self, tmp_path):
        assert _diff_pixels(self._run(tmp_path), Image.open(BUNDLED_GOODNIGHT)) == 0

    def test_message_flag_still_renders_a_static_headline(self, tmp_path):
        """Back-compat: ``--message`` remains the headline path.

        It is now opt-in rather than the default, because a headline carries
        no attribution line and no accent phrase.
        """
        framed = self._run(tmp_path, "--message", "Good night.")
        expected = rq.render_static_message("Good night.", 800, 480, theme="dark")
        assert _diff_pixels(framed, expected) == 0

    def test_time_is_optional(self, tmp_path):
        out = tmp_path / "frame.png"
        subprocess.run(
            [sys.executable, "-m", "idle_hours.render_quote", "--mode", "goodnight",
             "--theme", "dark", "--output", str(out)],
            check=True, capture_output=True,
        )
        assert Image.open(out).size == (800, 480)


class TestQuietThemeResolution:
    def test_inherit_is_the_default_and_matches_the_clock(self, tmp_path):
        """The default must be a no-op against the pre-flag behaviour."""
        args = _quiet_args(tmp_path, theme="scholar")
        state = RuntimeState("scholar")
        assert resolve_quiet_theme(args, state, "22:00") == "scholar"

    def test_fixed_theme_overrides_the_clock_theme(self, tmp_path):
        args = _quiet_args(tmp_path, theme="scholar", quiet_theme="nightvision")
        state = RuntimeState("scholar")
        assert resolve_quiet_theme(args, state, "22:00") == "nightvision"

    def test_auto_uses_the_configured_night_theme(self, tmp_path):
        args = _quiet_args(tmp_path, quiet_theme="auto", auto_night_theme="grimdark")
        state = RuntimeState("default")
        assert resolve_quiet_theme(args, state, "22:00") == "grimdark"

    def test_manual_override_beats_the_quiet_theme(self, tmp_path):
        """Decision 1: button B wins everywhere, quiet hours included."""
        args = _quiet_args(tmp_path, quiet_theme="nightvision")
        state = RuntimeState("default")
        state.manual_theme = "comic"
        assert resolve_quiet_theme(args, state, "22:00") == "comic"

    def test_missing_attr_falls_back_to_inherit(self, tmp_path):
        """A Namespace predating the flag must behave as ``inherit``."""
        args = _quiet_args(tmp_path, theme="saloon")
        del args.quiet_theme
        assert resolve_quiet_theme(args, RuntimeState("saloon"), "22:00") == "saloon"


class TestQuietThemeRandom:
    def test_pick_is_held_for_the_whole_window(self, tmp_path):
        """Rerolls per quiet window, not per resolve.

        ``--theme random`` rerolls when the displayed quote changes; the sleep
        frame's quote never changes, so the window is the only meaningful unit.
        """
        args = _quiet_args(tmp_path, quiet_theme="random")
        state = RuntimeState("default")
        first = resolve_quiet_theme(args, state, "22:00")
        assert state.quiet_theme == first
        for _ in range(20):
            assert resolve_quiet_theme(args, state, "23:30") == first

    def test_exit_quiet_clears_the_pick_so_the_next_night_rerolls(self, tmp_path):
        args = _quiet_args(tmp_path, quiet_theme="random")
        state = RuntimeState("default")
        resolve_quiet_theme(args, state, "22:00")
        assert state.quiet_theme is not None
        exit_quiet(state)
        assert state.quiet_theme is None

    def test_pick_is_a_registered_non_diags_theme(self, tmp_path):
        """``diags`` renders swatches instead of a quote — never a sleep frame."""
        args = _quiet_args(tmp_path, quiet_theme="random")
        for _ in range(60):
            state = RuntimeState("default")
            picked = resolve_quiet_theme(args, state, "22:00")
            assert picked in rq.THEMES
            assert picked != "diags"

    def test_a_fixed_quiet_theme_ignores_a_stale_held_pick(self, tmp_path):
        """Changing ``--quiet-theme`` away from ``random`` must take effect."""
        args = _quiet_args(tmp_path, quiet_theme="marker")
        state = RuntimeState("default")
        state.quiet_theme = "comic"
        assert resolve_quiet_theme(args, state, "22:00") == "marker"


class TestQuietThemeCli:
    def test_cli_choices_match_theme_order(self):
        """Mirror of ``--theme``'s sync fence.

        A theme added to ``THEME_ORDER`` without updating ``--quiet-theme``
        would be rejected at systemd startup rather than here.
        """
        for name in [*rq.THEME_ORDER, "auto", "random", QUIET_THEME_INHERIT]:
            with patch("sys.argv", ["run_clock.py", "--quiet-theme", name, "--once"]):
                try:
                    ns = run_clock.parse_args()
                except SystemExit:
                    raise AssertionError(f"--quiet-theme {name} was rejected by argparse")
                assert ns.quiet_theme == name

    def test_default_is_inherit(self):
        with patch("sys.argv", ["run_clock.py", "--once"]):
            assert run_clock.parse_args().quiet_theme == QUIET_THEME_INHERIT

    def test_quiet_image_defaults_to_the_themed_render(self):
        with patch("sys.argv", ["run_clock.py", "--once"]):
            assert run_clock.parse_args().quiet_image == "auto"


class TestQuietFrameDispatch:
    """``render_quiet_frame`` is the one definition of "put the panel to sleep"."""

    def test_auto_renders_in_the_quiet_theme(self, tmp_path):
        args = _quiet_args(tmp_path, theme="scholar", quiet_theme="nightvision")
        state = RuntimeState("scholar")
        with patch("idle_hours.run_clock.render_now") as mock_render, \
             patch("idle_hours.run_clock._display_quiet_image") as mock_copy:
            render_quiet_frame(args, state, "22:00")
        assert mock_copy.called is False
        mode, theme = mock_render.call_args.args[5], mock_render.call_args.args[6]
        assert (mode, theme) == ("goodnight", "nightvision")

    def test_static_path_ignores_the_quiet_theme(self, tmp_path):
        """A supplied PNG is a fixed image — theming it is not possible."""
        png = tmp_path / "custom.png"
        png.write_bytes(b"\x89PNG")
        args = _quiet_args(tmp_path, quiet_image=str(png), quiet_theme="nightvision")
        with patch("idle_hours.run_clock.render_now") as mock_render, \
             patch("idle_hours.run_clock._display_quiet_image") as mock_copy:
            render_quiet_frame(args, RuntimeState("default"), "22:00")
        assert mock_copy.called and mock_render.called is False

    def test_empty_renders_the_quiet_start_quote_in_the_quiet_theme(self, tmp_path):
        args = _quiet_args(tmp_path, quiet_image="", quiet_theme="marker")
        with patch("idle_hours.run_clock.render_now") as mock_render:
            render_quiet_frame(args, RuntimeState("default"), "23:17")
        call = mock_render.call_args
        assert call.args[6] == "marker"
        # Scheduled entry renders --quiet-start, the last-quote-of-the-night contract.
        assert call.kwargs["time_str"] == "22:00"

    def test_manual_entry_renders_the_current_time(self, tmp_path):
        args = _quiet_args(tmp_path, quiet_image="")
        with patch("idle_hours.run_clock.render_now") as mock_render:
            render_quiet_frame(args, RuntimeState("default"), "14:03", manual_only=True)
        assert mock_render.call_args.kwargs["time_str"] == "14:03"

    def test_enter_quiet_holds_the_render_lock(self, tmp_path):
        """Callers already inside ``_button_render_gate`` must call
        ``render_quiet_frame`` directly — ``render_lock`` is not reentrant."""
        args = _quiet_args(tmp_path)
        state = RuntimeState("default")
        held = []
        with patch("idle_hours.run_clock.render_now",
                   side_effect=lambda *a, **k: held.append(state.render_lock.locked())), \
             patch("idle_hours.run_clock.append_telemetry"):
            enter_quiet(args, state, "22:00")
        assert held == [True]


class TestAutoSentinelReachesEveryQuietPath:
    """Regression: only ``enter_quiet`` understood ``--quiet-image auto``.

    ``action_quiet`` (button D short-press) and the button-D long-press
    shutdown preamble both called ``_display_quiet_image`` directly, so on a
    themed install they tried to copy a file literally named ``auto`` and
    raised ``FileNotFoundError``. An opt-in footgun while the default was a
    real path; the default's problem once ``--quiet-image`` defaults to
    ``auto``.
    """

    def test_button_d_short_press_renders_rather_than_copying(self, tmp_path):
        args = _quiet_args(tmp_path, state_path=str(tmp_path / "state.json"))
        state = RuntimeState("default")
        state.manual_quiet = False
        with patch("idle_hours.run_clock.render_now") as mock_render, \
             patch("idle_hours.run_clock.current_time_str", return_value="14:03"), \
             patch("idle_hours.run_clock.append_telemetry"):
            result = run_clock.action_quiet(args, state, label="button D")
        assert result["ok"] is True and state.manual_quiet is True
        assert mock_render.call_args.args[5] == "goodnight"

    def test_shutdown_preamble_leaves_the_panel_alone_when_quiet_image_is_empty(self, tmp_path):
        """The ``if args.quiet_image`` guard is preserved for shutdown only.

        With ``--quiet-image ""`` the quiet-hours contract is "render the
        corpus quote" — worth a 10–20 s Spectra 6 refresh at the start of a
        night, but not in the seconds before poweroff, where the panel already
        shows a quote and the refresh is pure cost. ``action_quiet`` has no
        such guard: a manual toggle should match the scheduled rising edge.
        """
        args = _quiet_args(
            tmp_path, quiet_image="", state_path=str(tmp_path / "state.json"),
            shutdown_command="true", buttons_off=False,
        )
        state = RuntimeState("default")
        with patch("idle_hours.run_clock.render_now") as mock_render, \
             patch("idle_hours.run_clock.current_time_str", return_value="22:00"), \
             patch("idle_hours.run_clock.append_telemetry"), \
             patch("idle_hours.run_clock.subprocess.run"):
            _short, hold = run_clock._build_button_handlers(args, state)
            hold["D"]()
        assert mock_render.called is False

    def test_manual_quiet_toggle_still_renders_when_quiet_image_is_empty(self, tmp_path):
        """...whereas the button-D short press does render, matching the
        scheduled edge's last-quote-of-the-night contract."""
        args = _quiet_args(
            tmp_path, quiet_image="", state_path=str(tmp_path / "state.json"),
        )
        state = RuntimeState("default")
        with patch("idle_hours.run_clock.render_now") as mock_render, \
             patch("idle_hours.run_clock.current_time_str", return_value="14:03"), \
             patch("idle_hours.run_clock.append_telemetry"):
            run_clock.action_quiet(args, state, label="button D")
        assert mock_render.called
        assert mock_render.call_args.kwargs["time_str"] == "14:03"

    def test_shutdown_preamble_renders_rather_than_copying(self, tmp_path):
        args = _quiet_args(
            tmp_path, state_path=str(tmp_path / "state.json"),
            shutdown_command="true", buttons_off=False,
        )
        state = RuntimeState("default")
        with patch("idle_hours.run_clock.render_now") as mock_render, \
             patch("idle_hours.run_clock.current_time_str", return_value="22:00"), \
             patch("idle_hours.run_clock.append_telemetry"), \
             patch("idle_hours.run_clock.subprocess.run"):
            _short, hold = run_clock._build_button_handlers(args, state)
            hold["D"]()
        assert mock_render.call_args.args[5] == "goodnight"


class TestThemeChangeWhileAsleep:
    """Decision 1 + the bug it exposed.

    ``_render_unlocked`` has no quiet awareness, so a button-B press during
    the blackout painted a corpus quote onto a sleeping panel — and since the
    main loop only calls ``enter_quiet`` on the rising edge, nothing put the
    sleep frame back until the following night.
    """

    def _state(self):
        state = RuntimeState("default")
        state.last_effective_theme = "default"
        return state

    def test_press_during_quiet_repaints_the_sleep_frame(self, tmp_path):
        args = _quiet_args(tmp_path, state_path=str(tmp_path / "state.json"))
        state = self._state()
        with patch("idle_hours.run_clock.render_now") as mock_render, \
             patch("idle_hours.run_clock._render_unlocked") as mock_quote, \
             patch("idle_hours.run_clock.current_time_str", return_value="23:30"), \
             patch("idle_hours.run_clock.append_telemetry"):
            result = run_clock.action_theme(args, state, label="button B", target="comic")
        assert result["ok"] is True
        assert mock_quote.called is False, "painted a corpus quote onto a sleeping panel"
        mode, theme = mock_render.call_args.args[5], mock_render.call_args.args[6]
        assert (mode, theme) == ("goodnight", "comic")

    def test_press_outside_quiet_still_repaints_a_quote(self, tmp_path):
        args = _quiet_args(tmp_path, state_path=str(tmp_path / "state.json"))
        state = self._state()
        with patch("idle_hours.run_clock._render_unlocked") as mock_quote, \
             patch("idle_hours.run_clock.current_time_str", return_value="14:00"), \
             patch("idle_hours.run_clock.append_telemetry"):
            assert run_clock.action_theme(args, state, label="button B", target="comic")["ok"]
        assert mock_quote.called

    def test_manual_quiet_counts_as_asleep(self, tmp_path):
        """Quiet from a button-D toggle, outside the scheduled window."""
        args = _quiet_args(tmp_path, state_path=str(tmp_path / "state.json"))
        state = self._state()
        state.manual_quiet = True
        with patch("idle_hours.run_clock.render_now") as mock_render, \
             patch("idle_hours.run_clock._render_unlocked") as mock_quote, \
             patch("idle_hours.run_clock.current_time_str", return_value="14:00"), \
             patch("idle_hours.run_clock.append_telemetry"):
            run_clock.action_theme(args, state, label="button B", target="comic")
        assert mock_quote.called is False
        assert mock_render.call_args.args[5] == "goodnight"


class TestThemeCurrentIsWhatIsDisplayed:
    """``action_theme`` must reason about the theme actually on the panel.

    While asleep that is NOT ``state.last_effective_theme``: quiet frames go
    through ``render_quiet_frame`` → ``render_now`` rather than
    ``_render_unlocked``, so they deliberately never reach
    ``commit_render_result`` and the field still holds the pre-sleep *clock*
    theme. Deriving ``current`` from it got both consumers wrong — a Codex
    review finding on the PR that added ``--quiet-theme``, reproduced here
    before it was fixed.
    """

    def _args(self, tmp_path):
        return _quiet_args(
            tmp_path, theme="scholar", quiet_theme="nightvision",
            state_path=str(tmp_path / "state.json"),
        )

    def _state(self, manual_theme=None):
        state = RuntimeState("scholar")
        state.last_effective_theme = "scholar"   # the pre-sleep clock frame
        state.manual_theme = manual_theme
        return state

    def _apply(self, tmp_path, target, time_str, *, manual_theme=None):
        """Returns (result, theme painted onto a SLEEP frame, quote repainted?)."""
        state = self._state(manual_theme)
        with patch("idle_hours.run_clock.render_now") as sleep_render, \
             patch("idle_hours.run_clock._render_unlocked") as quote_render, \
             patch("idle_hours.run_clock.current_time_str", return_value=time_str), \
             patch("idle_hours.run_clock.append_telemetry"), \
             patch("idle_hours.run_clock.save_runtime_state"):
            result = run_clock.action_theme(self._args(tmp_path), state, label="t", target=target)
        painted = sleep_render.call_args.args[6] if sleep_render.called else None
        return result, painted, quote_render.called

    def test_applying_the_clock_theme_while_asleep_is_not_a_noop(self, tmp_path):
        """The bug: ``scholar`` matched the stale field and was dropped.

        The operator saw ``nightvision`` on the panel, asked for ``scholar``,
        and got a 200 carrying ``noop: True`` with no repaint.
        """
        result, painted, _quote = self._apply(tmp_path, "scholar", "23:30")
        assert not result.get("noop"), "apply of the clock theme was dropped while asleep"
        assert result["previous"] == "nightvision", "reported the stale clock theme as current"
        assert painted == "scholar"

    def test_cycle_advances_from_the_displayed_theme_while_asleep(self, tmp_path):
        """The other half: B advanced from ``scholar``, skipping the visible one."""
        result, painted, _quote = self._apply(tmp_path, None, "23:30")
        order = list(rq.THEME_ORDER)
        expected = order[(order.index("nightvision") + 1) % len(order)]
        assert result["previous"] == "nightvision"
        assert result["theme"] == expected
        assert painted == expected

    def test_applying_the_displayed_quiet_theme_is_still_a_noop(self, tmp_path):
        """The guard must keep working, just against the right value —
        re-applying what is already up should not burn a Spectra 6 refresh."""
        result, painted, quote = self._apply(tmp_path, "nightvision", "23:30")
        assert result.get("noop") is True
        assert painted is None and quote is False

    def test_awake_behaviour_is_unchanged(self, tmp_path):
        """Outside quiet hours ``last_effective_theme`` is still the source."""
        noop, _painted, _quote = self._apply(tmp_path, "scholar", "14:00")
        cycled, _p2, quote = self._apply(tmp_path, None, "14:00")
        assert noop.get("noop") is True
        assert cycled["previous"] == "scholar"
        assert quote is True, "awake presses must still paint a quote"

    def test_a_manual_override_is_what_is_displayed_while_asleep(self, tmp_path):
        """``resolve_quiet_theme`` puts ``manual_theme`` first, so a second
        press cycles from the operator's own pick, not from ``--quiet-theme``."""
        result, _painted, _quote = self._apply(tmp_path, None, "23:30", manual_theme="comic")
        assert result["previous"] == "comic"


class TestQuietThemeIsRegistered:
    def test_every_cycle_theme_is_accepted_as_a_quiet_theme(self, tmp_path):
        """Anything button B can reach must also be nameable as a quiet theme."""
        state = RuntimeState("default")
        for name in theme_cycle():
            args = _quiet_args(tmp_path, quiet_theme=name)
            assert resolve_quiet_theme(args, state, "22:00") == name
