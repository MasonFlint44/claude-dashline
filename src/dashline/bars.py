"""Bar cells, ramp color and reset countdown (PLAN §4, bar style).

A bar is one solid color: flat `success` up to 40%, a blend to pure `warning` at 70%,
a blend to `error` at 90%, flat `error` above. Themes with named ANSI colors can't
blend, so they step to the nearest anchor instead.
"""

from __future__ import annotations

import math

GREEN_UNTIL = 40.0
GOLD_AT = 70.0
CORAL_FROM = 90.0
COUNTDOWN_FROM = 70.0  # the gold anchor: color and countdown change together


def round_half_up(x: float) -> int:
    """Round .5 up, so bars and percents step evenly (Python's round() goes to even)."""
    return math.floor(x + 0.5)


def _lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ramp(percent: float, palette) -> tuple | str:
    """The fill color for a percent: an (r, g, b) blend, or a token name for ANSI themes."""
    green, gold, coral = (palette.rgb(t) for t in ("success", "warning", "error"))
    if not (green and gold and coral):
        if percent < (GREEN_UNTIL + GOLD_AT) / 2:
            return "success"
        return "warning" if percent < (GOLD_AT + CORAL_FROM) / 2 else "error"
    if percent <= GREEN_UNTIL:
        return green
    if percent < GOLD_AT:
        return _lerp(green, gold, (percent - GREEN_UNTIL) / (GOLD_AT - GREEN_UNTIL))
    if percent < CORAL_FROM:
        return _lerp(gold, coral, (percent - GOLD_AT) / (CORAL_FROM - GOLD_AT))
    return coral


def filled(percent: float, width: int) -> int:
    """Whole filled cells: nearest cell, at least 1 above 0%, all of them only at 100%."""
    if percent <= 0 or width <= 0:
        return 0
    if percent >= 100:
        return width
    return min(width - 1, max(1, round_half_up(percent / 100 * width)))


def percent_text(percent: float) -> str:
    """`41%`. Rounds, but never shows 100% before the limit is actually reached."""
    shown = round_half_up(percent)
    if percent < 100:
        shown = min(shown, 99)
    return f"{max(shown, 0)}%"


def duration(seconds: float) -> str:
    """Countdown text: `2d4h`, `1h40m`, `40m`, `45s`."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes = -(-seconds // 60)  # round up: "1m" until it's really gone
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours}h" if hours else f"{days}d"


def tokens(count: float) -> str:
    """`950`, `38k`, `1.2M`."""
    count = int(count)
    if count < 1000:
        return str(count)
    if round(count / 1000) < 1000:
        return f"{round(count / 1000)}k"
    return f"{count / 1_000_000:.1f}M"
