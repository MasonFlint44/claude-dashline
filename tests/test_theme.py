import json
import os

import pytest

from dashline import host, theme
from dashline.colors import THEMES, TOKENS


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake HOME with a config dir, a project dir, and no managed settings."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # home on Windows
    monkeypatch.setattr(theme, "managed_settings_path", lambda: None)
    (tmp_path / ".claude").mkdir()
    (tmp_path / "proj" / ".claude").mkdir(parents=True)
    return tmp_path


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


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
        # Digits to str.isdigit() that int() refuses, or too many for it: not a crash.
        ("15;\u00b2", "dark"),
        ("15;" + "1" * 5000, "dark"),
        ("15;\u0661", "dark"),  # an Arabic-Indic one
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


@pytest.mark.parametrize("slug", ["../outside", "..\\outside", "/abs/x", "C:x", ".hidden", ""])
def test_custom_theme_name_stays_in_the_themes_folder(home, slug):
    """`custom:<slug>` names a file in themes/: never a path out of it."""
    (home / ".claude" / "themes").mkdir()
    write(home / ".claude" / "outside.json", {"base": "light"})
    write(home / ".claude" / "themes" / "x.json", {"base": "light"})
    (home / ".claude" / "themes" / ".hidden.json").write_text('{"base": "light"}')
    assert theme.resolve(f"custom:{slug}", {}) == THEMES["dark"]


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


@pytest.mark.parametrize("base", [["dark"], {"x": 1}, 7, None, "nope"])
def test_custom_theme_with_an_odd_base_falls_back_to_dark(home, base):
    (home / ".claude" / "themes").mkdir()
    write(home / ".claude" / "themes" / "odd.json", {"base": base, "overrides": []})
    assert theme.resolve("custom:odd", {}) == THEMES["dark"]


def test_config_dir_follows_the_env_home(tmp_path):
    env = {"HOME": str(tmp_path / "elsewhere")}
    assert theme.config_dir(env) == str(tmp_path / "elsewhere" / ".claude")
    rooted = os.path.abspath("/cfg")  # noqa: PTH100 (Windows gives it the current drive)
    assert theme.config_dir({**env, "CLAUDE_CONFIG_DIR": "/cfg"}) == rooted


def test_absolute_by_windows_rules(monkeypatch):
    """On Windows a path needs its drive or server: `/cfg` is made absolute (`D:\\cfg`,
    as Node's path.resolve), on every Python (3.13 changed ntpath.isabs for it), so
    Git Bash can't read it under its own root. A drive-relative `C:cfg` isn't absolute."""
    monkeypatch.setattr(host, "WINDOWS", True)
    for path in ("C:\\cfg", "c:/cfg", "\\\\srv\\share", "//srv/share/x"):
        assert theme.is_absolute(path), path
    for path in ("/cfg", "\\cfg", "cfg", ".cc", "C:cfg", ""):
        assert not theme.is_absolute(path), path


def test_settings_with_a_bom(home):
    path = home / ".claude" / "settings.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"theme": "light"}')
    assert theme.theme_setting(None, {}) == "light"


def test_a_project_dir_with_a_nul_is_skipped(home):
    write(home / ".claude" / "settings.json", {"theme": "light"})
    assert theme.theme_setting(str(home) + "/\x00", {}) == "light"


def test_deeply_nested_settings_are_skipped(home):
    """Before Python 3.14 the json parser recurses, so nesting this deep raises
    RecursionError, which isn't a ValueError."""
    deep = "[" * 100000 + "]" * 100000
    (home / ".claude" / "settings.json").write_text(deep)
    (home / ".claude.json").write_text(deep)
    write(home / "proj" / ".claude" / "settings.json", {"theme": "light"})
    assert theme.theme_setting(str(home / "proj"), {}) == "light"
    (home / "proj" / ".claude" / "settings.json").write_text(deep)
    assert theme.theme_setting(str(home / "proj"), {}) == "dark"


def test_home_on_windows_is_userprofile_first(monkeypatch):
    """As for Claude Code (Node's os.homedir): Git Bash sets a HOME of its own."""
    env = {"HOME": "/c/Users/pat", "USERPROFILE": "C:\\Users\\pat"}
    monkeypatch.setattr(host, "WINDOWS", True)
    assert theme.home_dir(env) == "C:\\Users\\pat"
    assert theme.home_dir({"HOME": "/c/Users/pat"}) == "/c/Users/pat"
    monkeypatch.setattr(host, "WINDOWS", False)
    assert theme.home_dir(env) == "/c/Users/pat"
