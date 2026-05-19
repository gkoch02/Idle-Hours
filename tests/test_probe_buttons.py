"""Tests for probe_buttons.py — standalone GPIO diagnostic script.

``gpiozero`` is not available in CI, so we stub it in ``sys.modules`` and
replace ``signal.pause`` with a KeyboardInterrupt so ``main()`` doesn't hang.
"""
from __future__ import annotations

import signal
import sys
import types

import pytest

from idle_hours import probe_buttons


class FakeButton:
    """Captures constructor args and simulates a press."""

    instances: list["FakeButton"] = []

    def __init__(self, pin, *, pull_up=True, bounce_time=None):
        self.pin = pin
        self.pull_up = pull_up
        self.bounce_time = bounce_time
        self.when_pressed = None
        self.when_released = None
        FakeButton.instances.append(self)


@pytest.fixture
def stub_gpiozero(monkeypatch):
    FakeButton.instances = []
    fake_module = types.ModuleType("gpiozero")
    fake_module.Button = FakeButton
    monkeypatch.setitem(sys.modules, "gpiozero", fake_module)
    return fake_module


@pytest.fixture
def stub_signal_pause(monkeypatch):
    def raise_interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(signal, "pause", raise_interrupt)


class TestDefaults:
    def test_default_pins_covers_inky_impression(self):
        assert 5 in probe_buttons.DEFAULT_PINS
        assert 6 in probe_buttons.DEFAULT_PINS
        assert 16 in probe_buttons.DEFAULT_PINS
        assert 24 in probe_buttons.DEFAULT_PINS


class TestLog:
    def test_log_prints_iso_timestamp(self, capsys):
        probe_buttons._log("hello")
        captured = capsys.readouterr().out
        assert "hello" in captured
        # ISO-ish "[YYYY-MM-DDTHH:MM:SS]" prefix
        assert captured.startswith("[")
        assert "T" in captured.split("]")[0]


class TestMain:
    def test_returns_1_when_gpiozero_missing(self, monkeypatch, capsys):
        # A None entry in sys.modules is CPython's cached-ImportError sentinel:
        # the next `from gpiozero import Button` raises ModuleNotFoundError without
        # hitting the import machinery, so we don't need gpiozero uninstalled.
        monkeypatch.setitem(sys.modules, "gpiozero", None)
        rc = probe_buttons.main([])
        assert rc == 1
        err = capsys.readouterr().err
        assert "gpiozero not available" in err

    def test_attaches_default_pins(self, stub_gpiozero, stub_signal_pause):
        rc = probe_buttons.main([])
        assert rc == 0
        pins = sorted(b.pin for b in FakeButton.instances)
        assert pins == sorted(probe_buttons.DEFAULT_PINS)
        for btn in FakeButton.instances:
            assert btn.pull_up is True
            assert btn.bounce_time == 0.05
            assert callable(btn.when_pressed)
            assert callable(btn.when_released)

    def test_custom_pins_and_bounce(self, stub_gpiozero, stub_signal_pause):
        rc = probe_buttons.main(["--pins", "7", "8", "--bounce", "0.2"])
        assert rc == 0
        pins = sorted(b.pin for b in FakeButton.instances)
        assert pins == [7, 8]
        assert all(b.bounce_time == 0.2 for b in FakeButton.instances)

    def test_pull_down_flag(self, stub_gpiozero, stub_signal_pause):
        probe_buttons.main(["--pull-down", "--pins", "5"])
        assert FakeButton.instances[0].pull_up is False

    def test_returns_1_when_no_pins_attach(self, monkeypatch, capsys):
        fake_module = types.ModuleType("gpiozero")

        def exploding_button(pin, *, pull_up=True, bounce_time=None):
            raise RuntimeError(f"GPIO {pin} busy")

        fake_module.Button = exploding_button
        monkeypatch.setitem(sys.modules, "gpiozero", fake_module)

        rc = probe_buttons.main(["--pins", "5"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "attach FAILED" in captured.out
        assert "No pins attached" in captured.err

    def test_partial_failure_still_continues(self, monkeypatch, stub_signal_pause, capsys):
        attached: list[FakeButton] = []
        fake_module = types.ModuleType("gpiozero")

        def maybe_fail(pin, *, pull_up=True, bounce_time=None):
            if pin == 5:
                raise RuntimeError("pin 5 is busy")
            btn = FakeButton(pin, pull_up=pull_up, bounce_time=bounce_time)
            attached.append(btn)
            return btn

        fake_module.Button = maybe_fail
        monkeypatch.setitem(sys.modules, "gpiozero", fake_module)

        rc = probe_buttons.main(["--pins", "5", "6"])
        assert rc == 0
        assert [b.pin for b in attached] == [6]
        captured = capsys.readouterr().out
        assert "attach FAILED" in captured
        assert "listening on GPIO 6" in captured

    def test_press_callback_logs_pin(self, stub_gpiozero, stub_signal_pause, capsys):
        probe_buttons.main(["--pins", "7"])
        btn = FakeButton.instances[0]
        btn.when_pressed()
        btn.when_released()
        out = capsys.readouterr().out
        assert "GPIO 7: PRESSED" in out
        assert "GPIO 7: released" in out
