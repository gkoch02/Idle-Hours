"""Canonical fuzzy-bucket primitives shared by the mining, selection, and runtime scripts.

LitClock divides each of 12 hours into 12 minute-state buckets (144 total), named
``h{HOUR}_{STATE}``. The miner, ``pick_quote``, ``run_clock``, and the substring
repair tool must all agree on the state names and rounding rule, so this module
is the single source of truth. Prior to extraction, four independent copies drifted
apart (see git history for the substring-repair bug that motivated this module).

Rounding rule: ``rounded = ((minute + 2) // 5) * 5``; 60 wraps to 0 (and the next hour).
"""
from __future__ import annotations

BUCKET_ORDER: list[str] = [
    "exact",
    "five_past",
    "ten_past",
    "quarter_past",
    "twenty_past",
    "twenty_five_past",
    "half_past",
    "twenty_five_to",
    "twenty_to",
    "quarter_to",
    "ten_to",
    "five_to",
]

DEFAULT_BUCKET_MINUTES: dict[str, int] = {
    "exact": 0,
    "five_past": 5,
    "ten_past": 10,
    "quarter_past": 15,
    "twenty_past": 20,
    "twenty_five_past": 25,
    "half_past": 30,
    "twenty_five_to": 35,
    "twenty_to": 40,
    "quarter_to": 45,
    "ten_to": 50,
    "five_to": 55,
}

_STATE_BY_ROUNDED: dict[int, str] = {m: name for name, m in DEFAULT_BUCKET_MINUTES.items()}


def minute_bucket(minute: int) -> str:
    """Return the state name for a 0–59 minute-of-hour value."""
    if not 0 <= minute <= 59:
        raise ValueError(f"Unexpected minute: {minute}")
    rounded = ((minute + 2) // 5) * 5
    if rounded == 60:
        rounded = 0
    return _STATE_BY_ROUNDED[rounded]


def bucket_for_time(time_str: str) -> str:
    """Return the full ``h{1..12}_{state}`` bucket for an ``HH:MM`` 24-hour time."""
    hour24, minute = (int(part) for part in time_str.split(":", 1))
    rounded_minute = ((minute + 2) // 5) * 5
    if rounded_minute == 60:
        rounded_minute = 0
        hour24 = (hour24 + 1) % 24
    hour12 = hour24 % 12 or 12
    return f"h{hour12}_{_STATE_BY_ROUNDED[rounded_minute]}"


def neighbor_buckets(bucket: str) -> list[str]:
    """Return ``bucket`` plus its siblings in alternating outward-distance order.

    Used by ``pick_quote`` when no candidate in the exact bucket qualifies.
    """
    hour_part, state = bucket.split("_", 1)
    idx = BUCKET_ORDER.index(state)
    neighbors = [bucket]
    for distance in range(1, len(BUCKET_ORDER)):
        if idx - distance >= 0:
            neighbors.append(f"{hour_part}_{BUCKET_ORDER[idx - distance]}")
        if idx + distance < len(BUCKET_ORDER):
            neighbors.append(f"{hour_part}_{BUCKET_ORDER[idx + distance]}")
    return neighbors
