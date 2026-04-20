"""Inky Impression button listener.

The Inky Impression has four capacitive buttons wired to GPIO 5 / 6 / 16 / 24
(labelled A / B / C / D on the panel). This module attaches a debounced press
handler to each so ``run_clock.py`` can react to user input without polling.

The hardware import (``gpiozero``) happens inside :func:`start_listener` so this
module is import-safe on dev machines and the test suite can stub it out.
"""
from __future__ import annotations

from typing import Callable, Mapping

BUTTON_GPIO: dict[str, int] = {
    "A": 5,
    "B": 6,
    "C": 16,
    "D": 24,
}

DEBOUNCE_SECONDS = 0.3


def start_listener(
    handlers: Mapping[str, Callable[[], None]],
    *,
    bounce_time: float = DEBOUNCE_SECONDS,
) -> list:
    """Attach ``handlers[label]`` to each Inky button press.

    ``handlers`` keys must be subset of ``BUTTON_GPIO`` (``"A"``/``"B"``/``"C"``/``"D"``);
    unknown labels raise ``ValueError``. Returns the list of created button objects so
    the caller can keep them alive for the lifetime of the process — ``gpiozero``
    drops handlers when the ``Button`` is garbage-collected.
    """
    unknown = set(handlers) - set(BUTTON_GPIO)
    if unknown:
        raise ValueError(f"Unknown button label(s): {sorted(unknown)}; expected subset of {sorted(BUTTON_GPIO)}")

    from gpiozero import Button  # local import so this module is safe on non-Pi hosts

    buttons = []
    for label, callback in handlers.items():
        button = Button(BUTTON_GPIO[label], pull_up=True, bounce_time=bounce_time)
        button.when_pressed = callback
        buttons.append(button)
    return buttons
