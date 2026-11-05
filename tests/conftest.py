import copy
import json
import re
from pathlib import Path

import pytest

from dashline import glyphs, layout, stdin, theme
from dashline.colors import THEMES

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ANSI = re.compile(r"\x1b\[[0-9;]*m")
# The clock for every layout test: 2026-11-05 00:00:00 UTC.
NOW = 1793836800.0


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def stdin_data(name: str) -> dict:
    return read_json(FIXTURES / "stdin" / f"{name}.json")


def merge(base: dict, overrides: dict) -> dict:
    """Deep-merge overrides into a copy of base; a None value deletes the key."""
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def make_session(name: str = "after-first-response", **overrides) -> stdin.Session:
    return stdin.Session(merge(stdin_data(name), overrides))


def make_ctx(columns=120, glyph_set="unicode", theme_name="dark", color=False, now=NOW):
    palette = theme.Palette(THEMES[theme_name], color=color)
    return layout.Ctx(glyphs.get(glyph_set), palette, columns, now)


def plain(lines) -> list:
    return [ANSI.sub("", line) if isinstance(line, str) else layout.to_str(line) for line in lines]


def lines_text(session, ctx, plan=None, plan_label=None) -> list:
    if plan is None:
        plan = layout.stdin_plan_bars(session)
    return plain(layout.lay_out(session, ctx, plan, plan_label))


@pytest.fixture
def stdin_fixture():
    def load(name: str) -> str:
        return (FIXTURES / "stdin" / f"{name}.json").read_text()

    return load
