"""Concurrency / lock-ordering stress tests.

The main loop, button handlers, and the curator web server all live in the
same process and share three locks on ``RuntimeState``:

* ``render_lock``   — whoever holds this is painting to the panel
* ``ledger_lock``   — serialises ``append_history`` / ``remove_last_history_entry``
* ``lock``          — protects scalar state fields (``manual_theme`` etc.)

These tests don't try to exhaustively verify correctness under every
interleaving (impossible in Python without model checking). They lock in the
observable guarantees the code comments promise:

* ``_button_render_gate`` drops presses during in-flight renders rather than
  queuing — so a burst of taps during a slow Spectra 6 refresh does NOT
  execute N handlers N ticks later.
* ``append_history`` under ``ledger_lock`` produces well-formed JSONL even
  under concurrent writers.
* ``remove_last_history_entry`` is atomic — a concurrent reader never sees
  a torn ledger.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pick_quote
import run_clock


def _args(tmp_path: Path, **overrides) -> argparse.Namespace:
    defaults = dict(
        render_script="render_quote.py",
        output=str(tmp_path / "current.png"),
        width=800,
        height=480,
        display_script=None,
        mode="debug",
        theme="default",
        history_path=str(tmp_path / "history.jsonl"),
        history_days=7,
        telemetry_path="",
        state_path=str(tmp_path / "state.json"),
        quiet_image="",
        shutdown_command="",
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestRenderGateDropsConcurrentPresses:
    def test_second_press_is_dropped_while_first_holds_lock(self, tmp_path, capsys):
        """A second button press that arrives while a render is in flight is
        dropped (returns without running its body), NOT queued. This is the
        "first press wins" contract documented in run_clock."""
        state = run_clock.RuntimeState("default")
        first_entered = threading.Event()
        release_first = threading.Event()
        observed = []

        def slow_first():
            with run_clock._button_render_gate(state, "test", "first") as acquired:
                observed.append(("first", acquired))
                first_entered.set()
                release_first.wait(timeout=2)

        def immediate_second():
            with run_clock._button_render_gate(state, "test", "second") as acquired:
                observed.append(("second", acquired))

        t1 = threading.Thread(target=slow_first)
        t1.start()
        first_entered.wait(timeout=2)
        t2 = threading.Thread(target=immediate_second)
        t2.start()
        t2.join(timeout=2)
        release_first.set()
        t1.join(timeout=2)

        assert ("first", True) in observed
        assert ("second", False) in observed, "second press should have been dropped, not queued"


class TestConcurrentLedgerAppend:
    def test_concurrent_appends_produce_well_formed_jsonl(self, tmp_path):
        """N threads each appending M entries concurrently should produce
        exactly N*M valid JSON lines — no interleaved writes, no dropped
        entries. ``append_history`` opens the file with ``mode="a"`` (O_APPEND)
        and writes one short JSON line per call; on POSIX, writes smaller than
        ``PIPE_BUF`` (4096 on Linux) to an O_APPEND file are atomic, so threads
        calling ``append_history`` concurrently — with NO external lock — must
        still produce line-atomic output.
        """
        path = tmp_path / "history.jsonl"
        n_threads = 8
        n_per_thread = 25

        def worker(tid: int):
            for i in range(n_per_thread):
                # Intentionally no lock — we're verifying kernel-level atomicity,
                # not application-level serialisation.
                pick_quote.append_history(str(path), f"src-{tid}", i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert path.exists()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == n_threads * n_per_thread
        parsed = [json.loads(line) for line in lines]  # must not raise
        keys = {(e["source_id"], e["line_number"]) for e in parsed}
        assert len(keys) == n_threads * n_per_thread, "some appends were lost or collided"

    def test_unskip_rewrite_is_atomic_under_concurrent_reader(self, tmp_path):
        """``remove_last_history_entry`` rewrites the ledger atomically
        (via ``atomic_io.atomic_write_text``). A reader running concurrently
        with the rewrite sees either the pre-rewrite or the post-rewrite
        content — never a torn/empty ledger."""
        path = tmp_path / "history.jsonl"
        for i in range(50):
            pick_quote.append_history(str(path), "src-X", i)

        stop = threading.Event()
        errors: list[str] = []
        reader_counts: list[int] = []

        def reader():
            while not stop.is_set():
                try:
                    content = path.read_text(encoding="utf-8")
                    lines = [line for line in content.splitlines() if line.strip()]
                    for line in lines:
                        json.loads(line)  # every line must be valid JSON
                    reader_counts.append(len(lines))
                except json.JSONDecodeError as exc:
                    errors.append(f"torn ledger: {exc}")
                except FileNotFoundError:
                    errors.append("ledger disappeared")

        t = threading.Thread(target=reader)
        t.start()
        try:
            for i in range(10):
                pick_quote.remove_last_history_entry(str(path), "src-X", 49 - i)
                time.sleep(0.001)
        finally:
            stop.set()
            t.join(timeout=2)

        assert not errors, f"reader saw corruption: {errors[:3]}"
        assert reader_counts, "reader never ran"


class TestRenderGateFairness:
    def test_many_bursty_presses_resolve_to_at_most_in_flight_count(self, tmp_path):
        """When 20 handlers fire concurrently while one slow renderer holds the
        lock, only the first should get ``acquired=True``; the rest must see
        ``False`` and drop immediately."""
        state = run_clock.RuntimeState("default")
        running = threading.Event()
        release = threading.Event()
        acquired_count = 0
        dropped_count = 0
        count_lock = threading.Lock()

        def slow_holder():
            with run_clock._button_render_gate(state, "test", "holder") as acquired:
                assert acquired
                running.set()
                release.wait(timeout=5)

        def taps():
            nonlocal acquired_count, dropped_count
            with run_clock._button_render_gate(state, "test", "tap") as acquired:
                with count_lock:
                    if acquired:
                        acquired_count += 1
                    else:
                        dropped_count += 1

        holder = threading.Thread(target=slow_holder)
        holder.start()
        running.wait(timeout=2)

        tappers = [threading.Thread(target=taps) for _ in range(20)]
        for t in tappers:
            t.start()
        for t in tappers:
            t.join(timeout=2)

        release.set()
        holder.join(timeout=2)

        # Every one of the 20 tappers arrived while the holder had the lock.
        assert acquired_count == 0
        assert dropped_count == 20


class TestActionBusyBehavior:
    """The busy/drop contract is genuinely concurrent: a second caller must
    observe the render_lock held by someone else and bail out."""

    def test_action_theme_is_dropped_when_render_in_flight(self, tmp_path):
        """If another thread is rendering, action_theme must return
        ``{"ok": False, "error": "busy"}`` without touching state."""
        args = _args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_effective_theme = "default"

        # Hold the render lock so the gate rejects.
        with state.render_lock:
            result = run_clock.action_theme(args, state, label="test")
        assert result == {"ok": False, "error": "busy"}
        assert state.manual_theme is None, "theme must NOT have been mutated while busy"

    def test_parallel_theme_toggles_with_one_blocked_by_lock(self, tmp_path):
        """Launch two concurrent action_theme calls; the one that arrives
        while render_lock is held must drop, the other must succeed. This is
        the actual multi-thread property run_clock's HTTP + GPIO paths rely on."""
        args = _args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_effective_theme = "default"

        holder_in = threading.Event()
        holder_release = threading.Event()
        results: list[dict] = []

        def holder():
            with state.render_lock:
                holder_in.set()
                holder_release.wait(timeout=2)

        def tap():
            results.append(run_clock.action_theme(args, state, label="tap"))

        h = threading.Thread(target=holder)
        h.start()
        holder_in.wait(timeout=2)
        t = threading.Thread(target=tap)
        t.start()
        t.join(timeout=2)
        holder_release.set()
        h.join(timeout=2)

        assert results == [{"ok": False, "error": "busy"}]
        assert state.manual_theme is None


class TestActionThemeToggleArithmetic:
    """Not a concurrency test — locks in the cycle arithmetic so a
    regression in ``_next_theme`` (wrong modulus, off-by-one) surfaces
    immediately. Covers the full-loop wrap: N presses from the head of
    THEME_ORDER revisit the head exactly."""

    def test_n_sequential_presses_return_to_head_of_cycle(self, tmp_path):
        import render_quote as rq
        args = _args(tmp_path)
        state = run_clock.RuntimeState("default")
        state.last_effective_theme = rq.THEME_ORDER[0]

        with patch("run_clock.render_now"), \
             patch("run_clock.current_time_str", return_value="10:00"), \
             patch("run_clock.current_bucket", return_value="h10_exact"):
            for _ in range(len(rq.THEME_ORDER)):
                result = run_clock.action_theme(args, state, label="test")
                assert result["ok"] is True

        # After exactly len(THEME_ORDER) presses the cycle completes one loop
        # and lands back where it started.
        assert state.manual_theme == rq.THEME_ORDER[0]
