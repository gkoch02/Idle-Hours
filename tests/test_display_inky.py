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
