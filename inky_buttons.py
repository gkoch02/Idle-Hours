"""Inky Impression button listener.

The Inky Impression has four capacitive buttons wired to GPIO 5 / 6 / 16 / 24
(labelled A / B / C / D on the panel). This module attaches a debounced press
handler to each so ``run_clock.py`` can react to user input without polling.

The hardware import (``gpiozero``) happens inside :func:`start_listener` so this
module is import-safe on dev machines and the test suite can stub it out.

Short-press vs long-press: when a button has both a short and a hold handler,
the short callback fires on *release* only if the button was not held long
enough to trigger the hold callback. This avoids firing both on a long press.
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
DEFAULT_HOLD_SECONDS = 2.0


class _HoldDispatcher:
    """Route a button's press/hold/release events to short- and long-press callbacks.

    gpiozero fires ``when_pressed`` on every press. ``when_held`` fires after
    ``hold_time`` seconds while the button is still held; it also sets the
    ``Button.is_held`` attribute. We route through this dispatcher so the short
    callback only fires on release when the button was NOT held, preventing a
    long press from triggering both the short and long actions.
    """

    def __init__(
        self,
        short: Callable[[], None] | None,
        long_: Callable[[], None] | None,
    ) -> None:
        self._short = short
        self._long = long_
        self._held = False

    def on_press(self) -> None:
        self._held = False

    def on_hold(self) -> None:
        self._held = True
        if self._long is not None:
            self._long()

    def on_release(self) -> None:
        if not self._held and self._short is not None:
            self._short()


def buttons_alive(handles: list | None) -> bool:
    """Return True if every ``gpiozero.Button`` in ``handles`` is still claiming its pin.

    ``gpiozero.Button`` sets ``.closed = True`` when its pin factory releases
    the GPIO (explicit ``close()``, garbage collection, or a fatal error in
    the background thread that talks to the pin). If any listener-managed
    button reports closed we treat the whole listener as dead and let the
    main loop log loudly — silently-broken buttons are worse than no buttons,
    because the user doesn't know why presses stopped doing anything.

    ``None``/empty means the listener was never started (``--buttons-off``
    or a gpiozero import failure). We report alive in that case so the
    main loop doesn't log a spurious warning.
    """
    if not handles:
        return True
    for obj in handles:
        closed = getattr(obj, "closed", None)
        if closed is True:
            return False
    return True


def start_listener(
    handlers: Mapping[str, Callable[[], None]],
    *,
    hold_handlers: Mapping[str, Callable[[], None]] | None = None,
    hold_time: float = DEFAULT_HOLD_SECONDS,
    bounce_time: float = DEBOUNCE_SECONDS,
    press_logger: Callable[[str, int], None] | None = None,
) -> list:
    """Attach ``handlers[label]`` (short press) and optional ``hold_handlers[label]``
    (long press, ``hold_time`` seconds) to each Inky button.

    Keys in either mapping must be a subset of ``BUTTON_GPIO``
    (``"A"``/``"B"``/``"C"``/``"D"``); unknown labels raise ``ValueError``. A label
    may appear in ``hold_handlers`` without appearing in ``handlers`` if you only
    want a long-press action. Returns the list of created button objects (plus
    dispatcher refs) so the caller can keep them alive for the lifetime of the
    process — ``gpiozero`` drops handlers when the ``Button`` is
    garbage-collected.

    ``press_logger``, if provided, is called as ``press_logger(label, gpio_pin)``
    on every hardware press — runs before the short/long dispatch and can't be
    suppressed by handler exceptions. Use it to verify that a physical button
    is actually wired to the expected GPIO pin before blaming the handler.
    """
    hold_handlers = dict(hold_handlers or {})
    labels = set(handlers) | set(hold_handlers)
    unknown = labels - set(BUTTON_GPIO)
    if unknown:
        raise ValueError(
            f"Unknown button label(s): {sorted(unknown)}; expected subset of {sorted(BUTTON_GPIO)}"
        )

    from gpiozero import Button  # local import so this module is safe on non-Pi hosts

    keepalive: list = []
    for label in sorted(labels):
        short = handlers.get(label)
        long_ = hold_handlers.get(label)
        pin = BUTTON_GPIO[label]
        button = Button(
            pin,
            pull_up=True,
            bounce_time=bounce_time,
            hold_time=hold_time,
        )

        def _make_press_cb(lbl: str, p: int, dispatch: Callable[[], None] | None):
            def _cb() -> None:
                if press_logger is not None:
                    try:
                        press_logger(lbl, p)
                    except Exception:
                        pass
                if dispatch is not None:
                    dispatch()
            return _cb

        if long_ is None:
            # No hold handler: keep the simple press-fires-immediately path so
            # single-action buttons stay snappy.
            button.when_pressed = _make_press_cb(label, pin, short)
        else:
            dispatcher = _HoldDispatcher(short, long_)
            button.when_pressed = _make_press_cb(label, pin, dispatcher.on_press)
            button.when_held = dispatcher.on_hold
            button.when_released = dispatcher.on_release
            keepalive.append(dispatcher)
        keepalive.append(button)
    return keepalive
