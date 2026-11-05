"""Claude Code's statusline JSON → a plain dict-backed view.

Every field is optional: keys come and go between CLI versions, and `rate_limits` /
`prompt_cache` only appear after the first API response (PLAN §1, Phase 0 results).
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
