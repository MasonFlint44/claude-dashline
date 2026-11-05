"""Lines 1–2: session line and plan-bar line, widths, overflow (PLAN §4). Phase 2."""

from __future__ import annotations


def render(session: dict, glyphs: str = "unicode") -> list[str]:
    """Placeholder until Phase 2: the model name only."""
    model = (session.get("model") or {}).get("display_name") or "Claude"
    return [model]
