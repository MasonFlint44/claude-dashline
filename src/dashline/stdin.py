"""Claude Code's statusline JSON → a Session.

Every field is optional: keys come and go between CLI versions, and `rate_limits` /
`prompt_cache` only appear after the first API response (PLAN §1, Phase 0 results).
A field of the wrong type, a number that isn't finite, a negative cost or token count,
or a path with a NUL in it reads as missing, never as an error. Names that get displayed
(model, effort, agent) have control characters replaced (text.clean), so a name can't
split a line or start an escape sequence.
"""

from __future__ import annotations

import json
import math
import re

from dashline.text import clean

# ISO 8601 with any fraction length and Z or an offset; 3.9's fromisoformat takes neither.
ISO = re.compile(r"^(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?$")


def parse(text: str) -> dict:
    """Parse stdin text. Bad or empty input gives an empty dict, never an exception."""
    try:
        data = json.loads(text) if text.strip() else {}
    except (ValueError, RecursionError):  # RecursionError: nesting thousands deep
        return {}
    return data if isinstance(data, dict) else {}


def _dig(data, *keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _num(value) -> float | None:
    """A finite number, or None. NaN, ±Infinity and ints too big for a float are None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def _count(value) -> float | None:
    """A finite number that isn't negative (a cost, a token count), or None."""
    value = _num(value)
    return value if value is not None and value >= 0 else None


def _str(value) -> str | None:
    return value if isinstance(value, str) and value else None


def _path(value) -> str | None:
    """A path, or None. One with a NUL in it can't name a file, and os.path calls on it
    raise."""
    value = _str(value)
    return value if value is not None and "\x00" not in value else None


def iso_time(value) -> float | None:
    """`2026-11-06T07:00:00.281290+00:00` → epoch seconds; None if it isn't one."""
    if not isinstance(value, str):
        return None
    m = ISO.match(value.strip())
    if not m:
        return None
    from datetime import datetime, timezone

    base, fraction, zone = m.groups()
    try:
        when = datetime.fromisoformat(base.replace(" ", "T"))
    except ValueError:
        return None
    if zone and zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        digits = zone[1:].replace(":", "")
        offset = sign * (int(digits[:2]) * 3600 + int(digits[2:]) * 60)
    else:
        offset = 0  # no zone: the endpoints only send UTC
    seconds = when.replace(tzinfo=timezone.utc).timestamp() - offset
    return seconds + (float(f"0.{fraction}") if fraction else 0.0)


class Window:
    """One stdin rate-limit window (`five_hour`, `seven_day`, gateway `spend_limit`)."""

    def __init__(self, percent: float, resets_at: float | None, period: str | None = None):
        self.percent = percent
        self.resets_at = resets_at
        self.period = period


class Cache:
    """`prompt_cache`: whether the prompt cache is warm and when it expires."""

    def __init__(self, data: dict):
        self.observed = data.get("caching_observed") is True
        self.warm = data.get("warm") is True
        self.ttl = _str(data.get("ttl"))
        self.expires_at = _num(data.get("expires_at"))
        self.recache_tokens = _count(data.get("recache_tokens_if_cold"))
        causes = _dig(data, "last_miss_cause", "causes")
        cause = causes[0] if isinstance(causes, list) and causes else None
        self.miss_cause = clean(cause) if isinstance(cause, str) else None


class Session:
    def __init__(self, data: dict):
        model = _str(_dig(data, "model", "display_name")) or _str(_dig(data, "model", "id"))
        self.model = clean(model) if model else None
        self.model_id = (_str(_dig(data, "model", "id")) or "").lower()
        effort = _str(_dig(data, "effort", "level"))
        self.effort = clean(effort) if effort else None
        self.fast = data.get("fast_mode") is True
        agent = _str(_dig(data, "agent", "name"))
        self.agent = clean(agent) if agent else None
        self.cost = _count(_dig(data, "cost", "total_cost_usd"))
        self.context_percent = _num(_dig(data, "context_window", "used_percentage"))
        cwd = _path(data.get("cwd"))
        self.project_dir = _path(_dig(data, "workspace", "project_dir")) or cwd
        self.current_dir = _path(_dig(data, "workspace", "current_dir")) or cwd
        cache = data.get("prompt_cache")
        self.cache = Cache(cache) if isinstance(cache, dict) else None
        self.windows = {}
        for key in ("five_hour", "seven_day"):
            window = _dig(data, "rate_limits", key)
            percent = _num(_dig(window, "used_percentage"))
            if percent is not None:
                self.windows[key] = Window(percent, _num(_dig(window, "resets_at")))
        # Only behind an LLM gateway with a spend limit.
        spend = _dig(data, "rate_limits", "spend_limit")
        percent = _num(_dig(spend, "used_percentage"))
        self.spend_limit = None
        if percent is not None:
            resets_at = _num(_dig(spend, "resets_at"))
            self.spend_limit = Window(percent, resets_at, _str(_dig(spend, "period")))


def load(text: str) -> Session:
    return Session(parse(text))
