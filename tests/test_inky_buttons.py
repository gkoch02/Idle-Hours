"""Tests for the Inky button listener.

The hardware (``gpiozero``) is not present in CI, so these tests stub the
``gpiozero.Button`` import and verify that ``start_listener`` wires each label
to the correct GPIO pin and dispatches the registered callback when ``Button``
fires its ``when_pressed`` / ``when_held`` / ``when_released`` events.
"""
from __future__ import annotations

import sys
import types

import pytest

import inky_buttons


class FakeButton:
    """Minimal stand-in for ``gpiozero.Button`` capturing constructor args."""

    instances: list["FakeButton"] = []

    def __init__(self, pin, *, pull_up=True, bounce_time=None, hold_time=None):
        self.pin = pin
        self.pull_up = pull_up
        self.bounce_time = bounce_time
        self.hold_time = hold_time
        self.when_pressed = None
        self.when_held = None
        self.when_released = None
        FakeButton.instances.append(self)


@pytest.fixture(autouse=True)
def stub_gpiozero(monkeypatch):
    FakeButton.instances = []
    fake_module = types.ModuleType("gpiozero")
    fake_module.Button = FakeButton
    monkeypatch.setitem(sys.modules, "gpiozero", fake_module)


def _button_for_label(buttons, label):
    pin = inky_buttons.BUTTON_GPIO[label]
    for obj in buttons:
        if isinstance(obj, FakeButton) and obj.pin == pin:
            return obj
    raise AssertionError(f"no FakeButton for label {label}")


class TestStartListener:
    def test_attaches_handler_to_each_label(self):
        called: list[str] = []
        handlers = {label: (lambda label=label: called.append(label)) for label in ("A", "B", "C", "D")}
        buttons = inky_buttons.start_listener(handlers)
        # Only FakeButton objects are expected when there are no hold handlers.
        fake_buttons = [b for b in buttons if isinstance(b, FakeButton)]
        assert len(fake_buttons) == 4
        pins = {b.pin for b in fake_buttons}
        assert pins == set(inky_buttons.BUTTON_GPIO.values())

        for button in fake_buttons:
            button.when_pressed()
        assert sorted(called) == ["A", "B", "C", "D"]

    def test_partial_handler_set_only_wires_those_pins(self):
        called: list[str] = []
        handlers = {"A": lambda: called.append("A"), "C": lambda: called.append("C")}
        buttons = inky_buttons.start_listener(handlers)
        fake_buttons = [b for b in buttons if isinstance(b, FakeButton)]
        assert len(fake_buttons) == 2
        assert {b.pin for b in fake_buttons} == {inky_buttons.BUTTON_GPIO["A"], inky_buttons.BUTTON_GPIO["C"]}

    def test_unknown_label_raises(self):
        with pytest.raises(ValueError) as exc_info:
            inky_buttons.start_listener({"E": lambda: None})
        assert "Unknown button" in str(exc_info.value)

    def test_unknown_label_in_hold_handlers_raises(self):
        with pytest.raises(ValueError) as exc_info:
            inky_buttons.start_listener({}, hold_handlers={"Z": lambda: None})
        assert "Unknown button" in str(exc_info.value)

    def test_debounce_default_passed_through(self):
        inky_buttons.start_listener({"A": lambda: None})
        assert FakeButton.instances[0].bounce_time == inky_buttons.DEBOUNCE_SECONDS

    def test_debounce_override(self):
        inky_buttons.start_listener({"A": lambda: None}, bounce_time=1.5)
        assert FakeButton.instances[0].bounce_time == 1.5

    def test_hold_time_default_passed_through(self):
        inky_buttons.start_listener({"A": lambda: None}, hold_handlers={"A": lambda: None})
        assert FakeButton.instances[0].hold_time == inky_buttons.DEFAULT_HOLD_SECONDS

    def test_hold_time_override(self):
        inky_buttons.start_listener(
            {"A": lambda: None}, hold_handlers={"A": lambda: None}, hold_time=5.0,
        )
        assert FakeButton.instances[0].hold_time == 5.0


class TestHoldDispatch:
    def test_short_press_fires_short_only(self):
        short_calls: list[str] = []
        long_calls: list[str] = []
        buttons = inky_buttons.start_listener(
            {"A": lambda: short_calls.append("A")},
            hold_handlers={"A": lambda: long_calls.append("A")},
        )
        button = _button_for_label(buttons, "A")
        # Simulate a quick tap: press then release without hold firing.
        button.when_pressed()
        button.when_released()
        assert short_calls == ["A"]
        assert long_calls == []

    def test_long_press_fires_long_only(self):
        short_calls: list[str] = []
        long_calls: list[str] = []
        buttons = inky_buttons.start_listener(
            {"A": lambda: short_calls.append("A")},
            hold_handlers={"A": lambda: long_calls.append("A")},
        )
        button = _button_for_label(buttons, "A")
        # Press, hold fires before release; when released the short action
        # MUST NOT fire because the button was held long enough.
        button.when_pressed()
        button.when_held()
        button.when_released()
        assert short_calls == []
        assert long_calls == ["A"]

    def test_hold_handler_without_short_handler(self):
        long_calls: list[str] = []
        buttons = inky_buttons.start_listener(
            {},  # no short actions
            hold_handlers={"D": lambda: long_calls.append("D")},
        )
        button = _button_for_label(buttons, "D")
        button.when_pressed()
        button.when_held()
        button.when_released()  # should not crash with no short handler
        assert long_calls == ["D"]

    def test_short_handler_without_hold_handler_uses_when_pressed(self):
        short_calls: list[str] = []
        buttons = inky_buttons.start_listener(
            {"B": lambda: short_calls.append("B")},
        )
        button = _button_for_label(buttons, "B")
        # When there's no hold handler, the short action fires on press (not release)
        # — same snappy behavior we had before long-press support.
        assert button.when_pressed is not None
        assert button.when_held is None
        assert button.when_released is None
        button.when_pressed()
        assert short_calls == ["B"]


class TestPressLogger:
    """``press_logger`` fires on every hardware press regardless of short/long dispatch."""

    def test_press_logger_fires_for_simple_button(self):
        seen: list[tuple[str, int]] = []
        buttons = inky_buttons.start_listener(
            {"B": lambda: None},
            press_logger=lambda label, pin: seen.append((label, pin)),
        )
        _button_for_label(buttons, "B").when_pressed()
        assert seen == [("B", inky_buttons.BUTTON_GPIO["B"])]

    def test_press_logger_fires_for_hold_enabled_button(self):
        seen: list[tuple[str, int]] = []
        buttons = inky_buttons.start_listener(
            {"A": lambda: None},
            hold_handlers={"A": lambda: None},
            press_logger=lambda label, pin: seen.append((label, pin)),
        )
        _button_for_label(buttons, "A").when_pressed()
        assert seen == [("A", inky_buttons.BUTTON_GPIO["A"])]

    def test_press_logger_exception_does_not_suppress_handler(self):
        """A broken press_logger must not prevent the real handler from running."""
        fired: list[str] = []

        def boom(label, pin):
            raise RuntimeError("logger blew up")

        buttons = inky_buttons.start_listener(
            {"C": lambda: fired.append("C")},
            press_logger=boom,
        )
        _button_for_label(buttons, "C").when_pressed()
        assert fired == ["C"]
