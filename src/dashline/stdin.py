"""Claude Code's statusline JSON → a Session.

Every field is optional: keys come and go between CLI versions, and `rate_limits` /
`prompt_cache` only appear after the first API response (PLAN §1, Phase 0 results).
A field of the wrong type reads as missing, never as an error.
"""

from __future__ import annotations

import json


def parse(text: str) -> dict:
    """Parse stdin text. Bad or empty input gives an empty dict, never an exception."""
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _dig(data, *keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _str(value) -> str | None:
    return value if isinstance(value, str) and value else None


class Window:
    """One stdin rate-limit window (`five_hour`, `seven_day`)."""

    def __init__(self, percent: float, resets_at: float | None):
        self.percent = percent
        self.resets_at = resets_at


class Cache:
    """`prompt_cache`: whether the prompt cache is warm and when it expires."""

    def __init__(self, data: dict):
        self.observed = data.get("caching_observed") is True
        self.warm = data.get("warm") is True
        self.ttl = _str(data.get("ttl"))
        self.expires_at = _num(data.get("expires_at"))
        self.recache_tokens = _num(data.get("recache_tokens_if_cold"))
        causes = _dig(data, "last_miss_cause", "causes")
        self.miss_cause = causes[0] if isinstance(causes, list) and causes else None
        if not isinstance(self.miss_cause, str):
            self.miss_cause = None


class Session:
    def __init__(self, data: dict):
        self.model = _str(_dig(data, "model", "display_name")) or _str(_dig(data, "model", "id"))
        self.effort = _str(_dig(data, "effort", "level"))
        self.fast = data.get("fast_mode") is True
        self.agent = _str(_dig(data, "agent", "name"))
        self.cost = _num(_dig(data, "cost", "total_cost_usd"))
        self.context_percent = _num(_dig(data, "context_window", "used_percentage"))
        self.project_dir = _str(_dig(data, "workspace", "project_dir")) or _str(data.get("cwd"))
        self.current_dir = _str(_dig(data, "workspace", "current_dir")) or _str(data.get("cwd"))
        cache = data.get("prompt_cache")
        self.cache = Cache(cache) if isinstance(cache, dict) else None
        self.windows = {}
        for key in ("five_hour", "seven_day"):
            window = _dig(data, "rate_limits", key)
            percent = _num(_dig(window, "used_percentage"))
            if percent is not None:
                self.windows[key] = Window(percent, _num(_dig(window, "resets_at")))


def load(text: str) -> Session:
    return Session(parse(text))
