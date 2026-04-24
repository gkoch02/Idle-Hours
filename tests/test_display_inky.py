"""Tests for display_inky.py — retry wrapper around the Inky hardware push.

The underlying ``_push_to_panel`` function requires a physical Pimoroni Inky
display, so these tests exercise only the retry/error behavior of ``main`` with
``_push_to_panel`` mocked out.
"""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

# display_inky imports Pillow at module scope, so skip cleanly if unavailable.
pytest.importorskip("PIL")

import display_inky  # noqa: E402


@pytest.fixture
def fake_image(tmp_path):
    img = tmp_path / "frame.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")  # non-empty; _push_to_panel is mocked so content unused
    return img


def _argv(image_path):
    return ["display_inky.py", str(image_path)]


@pytest.fixture(autouse=True)
def stub_inky_import(monkeypatch):
    """Make ``from inky.auto import auto`` succeed so the import-guard in main() passes."""
    fake_inky = type(sys)("inky")
    fake_auto_mod = type(sys)("inky.auto")
    fake_auto_mod.auto = lambda **kwargs: None  # unused; _push_to_panel is mocked
    monkeypatch.setitem(sys.modules, "inky", fake_inky)
    monkeypatch.setitem(sys.modules, "inky.auto", fake_auto_mod)


class TestRetry:
    def test_success_on_first_attempt_no_retry(self, fake_image):
        with patch("display_inky._push_to_panel", return_value=(800, 480)) as push, \
             patch("sys.argv", _argv(fake_image)), \
             patch("time.sleep") as sleep:
            rc = display_inky.main()
        assert rc == 0
        assert push.call_count == 1
        assert sleep.call_count == 0

    def test_transient_failure_then_success(self, fake_image, capsys):
        side = [IOError("panel disconnected"), (800, 480)]
        with patch("display_inky._push_to_panel", side_effect=side) as push, \
             patch("sys.argv", _argv(fake_image)), \
             patch("time.sleep") as sleep:
            rc = display_inky.main()
        assert rc == 0
        assert push.call_count == 2
        assert sleep.call_count == 1
        assert "retrying" in capsys.readouterr().err

    def test_all_attempts_fail_raises(self, fake_image, capsys):
        with patch("display_inky._push_to_panel", side_effect=IOError("boom")) as push, \
             patch("sys.argv", _argv(fake_image)), \
             patch("time.sleep"):
            with pytest.raises(SystemExit) as exc_info:
                display_inky.main()
        assert push.call_count == display_inky.MAX_ATTEMPTS
        assert "failed after" in str(exc_info.value)

    def test_missing_image_exits_without_push(self, tmp_path):
        missing = tmp_path / "does-not-exist.png"
        with patch("display_inky._push_to_panel") as push, \
             patch("sys.argv", _argv(missing)):
            with pytest.raises(SystemExit) as exc_info:
                display_inky.main()
        assert push.call_count == 0
        assert "not found" in str(exc_info.value)


class TestThemeSaturation:
    def test_default_theme_uses_default_saturation(self):
        assert display_inky.resolve_saturation("default", None) == display_inky.THEME_SATURATION["default"]

    def test_dark_theme_uses_higher_saturation(self):
        assert display_inky.resolve_saturation("dark", None) == display_inky.THEME_SATURATION["dark"]
        assert display_inky.THEME_SATURATION["dark"] > display_inky.THEME_SATURATION["default"]

    def test_explicit_override_wins_over_theme(self):
        assert display_inky.resolve_saturation("dark", 0.25) == 0.25

    def test_unknown_theme_falls_back_to_default(self):
        assert display_inky.resolve_saturation("nope", None) == display_inky.THEME_SATURATION["default"]

    @pytest.mark.parametrize("theme", ["scholar", "newsprint", "nightvision"])
    def test_new_themes_have_saturation_entries(self, theme):
        """Every theme registered in ``render_quote.THEMES`` must have a
        ``THEME_SATURATION`` entry. Without this the resolve call silently
        falls back to the default saturation, which can make a dark-background
        theme (``nightvision``) look muddier than intended."""
        import render_quote as rq
        assert theme in rq.THEMES
        assert theme in display_inky.THEME_SATURATION

    def test_every_render_theme_has_saturation(self):
        """Belt-and-braces: the dynamic list of registered render themes must
        exactly equal the saturation table's keys. Prevents a new theme from
        silently inheriting the default saturation just because someone added
        a THEMES entry without touching display_inky."""
        import render_quote as rq
        assert set(rq.THEMES.keys()) == set(display_inky.THEME_SATURATION.keys())

    def test_main_passes_theme_saturation_to_panel(self, fake_image):
        captured: list[float] = []

        def capture(image_path, saturation):
            captured.append(saturation)
            return (800, 480)

        argv = ["display_inky.py", str(fake_image), "--theme", "dark"]
        with patch("display_inky._push_to_panel", side_effect=capture), \
             patch("sys.argv", argv), \
             patch("time.sleep"):
            display_inky.main()
        assert captured == [display_inky.THEME_SATURATION["dark"]]

    def test_explicit_saturation_overrides_theme(self, fake_image):
        captured: list[float] = []

        def capture(image_path, saturation):
            captured.append(saturation)
            return (800, 480)

        argv = ["display_inky.py", str(fake_image), "--theme", "dark", "--saturation", "0.1"]
        with patch("display_inky._push_to_panel", side_effect=capture), \
             patch("sys.argv", argv), \
             patch("time.sleep"):
            display_inky.main()
        assert captured == [0.1]


class TestInkyImportGuard:
    def test_unimportable_inky_exits_with_guidance(self, fake_image, monkeypatch):
        # main() tries ``from inky.auto import auto`` up-front so an operator
        # gets a useful error at startup rather than inside the retry loop.
        # Replace the fake-inky module with one that raises on attribute access
        # (simulating a missing library on the host).
        broken = type(sys)("inky.auto")

        def _raise(*_a, **_kw):
            raise ImportError("No module named 'inky'")

        # The import statement resolves `inky.auto.auto` at ``from`` time — this
        # mirrors what happens when the parent package isn't installed.
        monkeypatch.setitem(sys.modules, "inky.auto", broken)
        # Drop ``auto`` so ``from inky.auto import auto`` fails with ImportError.
        # (We can't use __getattr__ reliably across Python versions; a missing
        # attribute on a module object raises ImportError at ``from`` time.)

        with patch("sys.argv", _argv(fake_image)), \
             patch("display_inky._push_to_panel") as push:
            with pytest.raises(SystemExit) as exc_info:
                display_inky.main()
        msg = str(exc_info.value)
        assert "Pimoroni Inky library" in msg
        assert push.call_count == 0


class TestCliArgParsing:
    def test_parse_args_defaults(self, fake_image):
        with patch("sys.argv", ["display_inky.py", str(fake_image)]):
            args = display_inky.parse_args()
        assert args.image == str(fake_image)
        assert args.saturation is None
        assert args.theme == "default"

    def test_parse_args_rejects_unknown_theme(self, fake_image):
        with patch("sys.argv", ["display_inky.py", str(fake_image), "--theme", "purple"]):
            with pytest.raises(SystemExit):
                display_inky.parse_args()

    def test_backoff_schedule_shape(self):
        # The retry loop expects exactly MAX_ATTEMPTS-1 backoff values so the
        # final attempt doesn't sleep before giving up.
        assert len(display_inky.RETRY_BACKOFF_SECONDS) == display_inky.MAX_ATTEMPTS - 1
        assert all(s > 0 for s in display_inky.RETRY_BACKOFF_SECONDS)
        assert display_inky.RETRY_BACKOFF_SECONDS == tuple(sorted(display_inky.RETRY_BACKOFF_SECONDS))
