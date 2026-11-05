import json

import pytest

from dashline import theme
from dashline.colors import THEMES, TOKENS


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake HOME with a config dir, a project dir, and no managed settings."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(theme, "managed_settings_path", lambda: None)
    (tmp_path / ".claude").mkdir()
    (tmp_path / "proj" / ".claude").mkdir(parents=True)
    return tmp_path


def write(path, data):
    path.write_text(json.dumps(data))


def test_default_is_dark(home):
    assert theme.theme_setting(str(home / "proj"), {}) == "dark"


def test_user_settings(home):
    write(home / ".claude" / "settings.json", {"theme": "light"})
    assert theme.theme_setting(str(home / "proj"), {}) == "light"


def test_project_beats_user_and_local_beats_project(home):
    write(home / ".claude" / "settings.json", {"theme": "light"})
    write(home / "proj" / ".claude" / "settings.json", {"theme": "dark-ansi"})
    assert theme.theme_setting(str(home / "proj"), {}) == "dark-ansi"
    write(home / "proj" / ".claude" / "settings.local.json", {"theme": "light-ansi"})
    assert theme.theme_setting(str(home / "proj"), {}) == "light-ansi"


def test_managed_settings_win(home, monkeypatch):
    managed = home / "managed.json"
    write(managed, {"theme": "dark-daltonized"})
    monkeypatch.setattr(theme, "managed_settings_path", lambda: str(managed))
    write(home / "proj" / ".claude" / "settings.local.json", {"theme": "light"})
    assert theme.theme_setting(str(home / "proj"), {}) == "dark-daltonized"


def test_legacy_global_config(home):
    write(home / ".claude.json", {"theme": "light"})
    assert theme.theme_setting(None, {}) == "light"
    write(home / ".claude" / "settings.json", {"theme": "dark-ansi"})
    assert theme.theme_setting(None, {}) == "dark-ansi"


def test_claude_config_dir(home, tmp_path):
    conf = tmp_path / "alt"
    conf.mkdir()
    write(conf / "settings.json", {"theme": "light-ansi"})
    assert theme.theme_setting(None, {"CLAUDE_CONFIG_DIR": str(conf)}) == "light-ansi"


def test_broken_settings_are_skipped(home):
    (home / ".claude" / "settings.json").write_text("{not json")
    write(home / "proj" / ".claude" / "settings.json", ["theme"])
    assert theme.theme_setting(str(home / "proj"), {}) == "dark"


@pytest.mark.parametrize(
    ("colorfgbg", "expected"),
    [
        (None, "dark"),
        ("15;0", "dark"),
        ("0;15", "light"),
        ("0;default;8", "dark"),
        ("0;7", "light"),
        ("x", "dark"),
    ],
)
def test_auto(colorfgbg, expected):
    env = {"COLORFGBG": colorfgbg} if colorfgbg else {}
    assert theme.resolve("auto", env) == THEMES[expected]


def test_custom_theme(home):
    (home / ".claude" / "themes").mkdir()
    write(
        home / ".claude" / "themes" / "mine.json",
        {
            "name": "Mine",
            "base": "light",
            "overrides": {
                "success": "rgb(1,2,3)",
                "warning": "#ff8800",
                "error": "ansi:magenta",
                "subtle": "not a color",
                "nonsense": "rgb(9,9,9)",
            },
        },
    )
    tokens = theme.resolve("custom:mine", {})
    assert tokens["success"] == "rgb(1,2,3)"
    assert tokens["warning"] == "#ff8800"
    assert tokens["error"] == "ansi:magenta"
    assert tokens["subtle"] == THEMES["light"]["subtle"]
    assert "nonsense" not in tokens


def test_missing_custom_theme_and_unknown_name_fall_back_to_dark(home):
    assert theme.resolve("custom:gone", {}) == THEMES["dark"]
    assert theme.resolve("solarized", {}) == THEMES["dark"]


@pytest.mark.parametrize(
    ("value", "parsed"),
    [
        ("rgb(78,186,101)", (78, 186, 101)),
        ("rgb( 1, 2, 3 )", (1, 2, 3)),
        ("rgb(256,0,0)", None),
        ("#FFC107", (255, 193, 7)),
        ("#fff", (255, 255, 255)),
        ("ansi:green", "32"),
        ("ansi:redBright", "91"),
        ("ansi:purple", None),
        (None, None),
    ],
)
def test_parse_color(value, parsed):
    assert theme.parse_color(value) == parsed


def test_every_builtin_token_parses():
    for tokens in THEMES.values():
        assert all(theme.parse_color(tokens[t]) is not None for t in TOKENS)


def test_palette_sgr():
    p = theme.Palette(THEMES["dark"])
    assert p.sgr("success") == "38;2;78;186;101"
    assert p.sgr("error", bold=True) == "1;38;2;255;107;128"
    assert theme.Palette(THEMES["dark-ansi"]).sgr("warning") == "93"
    assert theme.Palette(THEMES["dark"], color=False).sgr("success", bold=True) == ""


def test_no_color(home):
    assert theme.load(None, {"NO_COLOR": "1"}).color is False
    assert theme.load(None, {}).color is True
