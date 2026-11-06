"""Which Claude Code theme is active, and its tokens as terminal color codes (PLAN §4a).

The statusline JSON carries no theme, so this follows the CLI's own lookup: the `theme`
key in the settings files (managed, then project-local, project, user), then the legacy
`theme` in ~/.claude.json, then `dark`. `auto` uses COLORFGBG (the CLI also asks the
terminal, which a statusline can't). `custom:<slug>` reads themes/<slug>.json.
"""

from __future__ import annotations

import json
import os
import re
import sys

from dashline.colors import THEMES, TOKENS

ANSI_NAMES = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
RGB = re.compile(r"^rgb\(\s?(\d{1,3}),\s?(\d{1,3}),\s?(\d{1,3})\s?\)$")
HEX = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def home_dir(env) -> str:
    """HOME from `env`, so a caller's env decides where ~ is, not the process's."""
    return env.get("HOME") or os.path.expanduser("~")


def config_dir(env) -> str:
    return env.get("CLAUDE_CONFIG_DIR") or os.path.join(home_dir(env), ".claude")


# Where the CLI reads managed settings, by platform. Tests point MANAGED_SETTINGS elsewhere.
MANAGED_DIRS = {
    "darwin": "/Library/Application Support/ClaudeCode",
    "win32": "C:\\Program Files\\ClaudeCode",
}
MANAGED_SETTINGS = os.path.join(
    MANAGED_DIRS.get(sys.platform, "/etc/claude-code"), "managed-settings.json"
)


def managed_settings_path() -> str | None:
    return MANAGED_SETTINGS


def _read_json(path: str | None) -> dict:
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8-sig") as f:  # -sig: a BOM some editors add
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def settings_files(project_dir: str | None, env) -> list:
    """The settings files a value can come from, the one that wins first.

    Managed, project-local, project, user. (Flags like --settings can't be seen from here.)
    """
    user = os.path.join(config_dir(env), "settings.json")
    candidates = []
    managed = managed_settings_path()
    if managed:
        candidates.append(managed)
    if project_dir:
        project = os.path.join(project_dir, ".claude", "settings.json")
        candidates.append(os.path.join(project_dir, ".claude", "settings.local.json"))
        # The CLI skips project settings that are the user settings file (project dir = ~).
        if os.path.realpath(project) != os.path.realpath(user):
            candidates.append(project)
    candidates.append(user)
    return candidates


def theme_setting(project_dir: str | None, env) -> str:
    """The raw `theme` value the CLI would use, e.g. "dark", "auto" or "custom:slug"."""
    for path in settings_files(project_dir, env):
        value = _read_json(path).get("theme")
        if isinstance(value, str) and value:
            return value
    legacy_dir = env.get("CLAUDE_CONFIG_DIR") or home_dir(env)
    legacy = _read_json(os.path.join(legacy_dir, ".claude.json")).get("theme")
    if isinstance(legacy, str) and legacy and legacy != "dark":
        return legacy
    return "dark"


def auto_theme(env) -> str:
    """`auto` without a terminal to ask: COLORFGBG's background index, else dark."""
    last = (env.get("COLORFGBG") or "").split(";")[-1]
    if last.isdigit() and int(last) <= 15:
        return "dark" if int(last) <= 6 or int(last) == 8 else "light"
    return "dark"


def resolve(setting: str, env) -> dict:
    """Token → color string (CLI notation) for a theme setting."""
    if setting == "auto":
        return dict(THEMES[auto_theme(env)])
    if setting in THEMES:
        return dict(THEMES[setting])
    if setting.startswith("custom:"):
        slug = setting[len("custom:") :]
        custom = _read_json(os.path.join(config_dir(env), "themes", f"{slug}.json"))
        base = custom.get("base")
        tokens = dict(THEMES[base if isinstance(base, str) and base in THEMES else "dark"])
        overrides = custom.get("overrides")
        if isinstance(overrides, dict):
            for token, value in overrides.items():
                if token in TOKENS and parse_color(value) is not None:
                    tokens[token] = value
        return tokens
    return dict(THEMES["dark"])


def parse_color(value) -> tuple | str | None:
    """`rgb(r,g,b)` / `#rrggbb` → (r, g, b); `ansi:name` → SGR code string; else None."""
    if not isinstance(value, str):
        return None
    m = RGB.match(value)
    if m:
        rgb = tuple(int(x) for x in m.groups())
        return rgb if all(c <= 255 for c in rgb) else None
    m = HEX.match(value)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    if value.startswith("ansi:"):
        name = value[5:]
        bright = name.endswith("Bright")
        base = name[: -len("Bright")] if bright else name
        if base in ANSI_NAMES:
            return str((90 if bright else 30) + ANSI_NAMES.index(base))
    return None


class Palette:
    """Theme tokens as SGR parameters. With color off every lookup is empty."""

    def __init__(self, tokens: dict, color: bool = True):
        self.color = color
        self.colors = {t: parse_color(tokens.get(t)) for t in TOKENS}

    def rgb(self, token: str) -> tuple | None:
        value = self.colors.get(token)
        return value if isinstance(value, tuple) else None

    def sgr(self, token: str | tuple | None, bold: bool = False) -> str:
        if not self.color:
            return ""
        value = self.colors.get(token) if isinstance(token, str) else token
        if isinstance(value, tuple):
            code = "38;2;{};{};{}".format(*value)
        elif isinstance(value, str):
            code = value
        else:
            code = ""
        if bold:
            code = f"1;{code}" if code else "1"
        return code


def load(project_dir: str | None, env) -> Palette:
    color = not env.get("NO_COLOR")
    return Palette(resolve(theme_setting(project_dir, env), env), color=color)
