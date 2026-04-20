"""Tests for the Inky button listener.

The hardware (``gpiozero``) is not present in CI, so these tests stub the
``gpiozero.Button`` import and verify that ``start_listener`` wires each label
to the correct GPIO pin and dispatches the registered callback when ``Button``
fires its ``when_pressed`` event.
"""
from __future__ import annotations

import sys
import types

import pytest

import inky_buttons


class FakeButton:
    """Minimal stand-in for ``gpiozero.Button`` capturing constructor args."""

    instances: list["FakeButton"] = []

    def __init__(self, pin, *, pull_up=True, bounce_time=None):
        self.pin = pin
        self.pull_up = pull_up
        self.bounce_time = bounce_time
        self.when_pressed = None
        FakeButton.instances.append(self)


@pytest.fixture(autouse=True)
def stub_gpiozero(monkeypatch):
    FakeButton.instances = []
    fake_module = types.ModuleType("gpiozero")
    fake_module.Button = FakeButton
    monkeypatch.setitem(sys.modules, "gpiozero", fake_module)


class TestStartListener:
    def test_attaches_handler_to_each_label(self):
        called: list[str] = []
        handlers = {label: (lambda label=label: called.append(label)) for label in ("A", "B", "C", "D")}
        buttons = inky_buttons.start_listener(handlers)
        assert len(buttons) == 4
        # Wire-up: each button should be on its declared GPIO pin.
        pins = {b.pin for b in buttons}
        assert pins == set(inky_buttons.BUTTON_GPIO.values())

        # Simulate each press and verify dispatch.
        for button in buttons:
            button.when_pressed()
        assert sorted(called) == ["A", "B", "C", "D"]

    def test_partial_handler_set_only_wires_those_pins(self):
        called: list[str] = []
        handlers = {"A": lambda: called.append("A"), "C": lambda: called.append("C")}
        buttons = inky_buttons.start_listener(handlers)
        assert len(buttons) == 2
        assert {b.pin for b in buttons} == {inky_buttons.BUTTON_GPIO["A"], inky_buttons.BUTTON_GPIO["C"]}

    def test_unknown_label_raises(self):
        with pytest.raises(ValueError) as exc_info:
            inky_buttons.start_listener({"E": lambda: None})
        assert "Unknown button" in str(exc_info.value)

    def test_debounce_default_passed_through(self):
        inky_buttons.start_listener({"A": lambda: None})
        assert FakeButton.instances[0].bounce_time == inky_buttons.DEBOUNCE_SECONDS

    def test_debounce_override(self):
        inky_buttons.start_listener({"A": lambda: None}, bounce_time=1.5)
        assert FakeButton.instances[0].bounce_time == 1.5
