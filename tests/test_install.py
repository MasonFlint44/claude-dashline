"""--install: the copy, the settings entry, and when it refuses to touch settings."""

import io
import json
import subprocess
import sys

import pytest

from conftest import ROOT
from dashline import __version__, install

ENTRY_CMD = 'python3 -I -S "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/scripts/statusline/statusline.py"'


@pytest.fixture
def conf(isolated_home):
    path = isolated_home / ".claude"
    path.mkdir()
    return path


@pytest.fixture
def env(isolated_home):
    return {"HOME": str(isolated_home)}


def settings(conf):
    return json.loads((conf / "settings.json").read_text())


def write_settings(conf, data):
    (conf / "settings.json").write_text(json.dumps(data, indent=2) + "\n")


def run(env, glyphs=None, replace=False, cwd=None):
    out = io.StringIO()
    code = install.run(glyphs, replace=replace, env=env, out=out, cwd=cwd or "/")
    return code, out.getvalue()


# ---- the copy ----


def test_fresh_install(conf, env):
    code, out = run(env)
    assert code == 0
    target = conf / "scripts" / "statusline"
    assert (target / "statusline.py").read_bytes() == (ROOT / "statusline.py").read_bytes()
    assert (target / "VERSION").read_text() == f"{__version__}\n"
    for src in (ROOT / "src" / "dashline").glob("*.py"):
        assert (target / "dashline" / src.name).read_bytes() == src.read_bytes()
    assert not list((target / "dashline").glob("__pycache__"))
    assert f"installed dashline {__version__} in ~/.claude/scripts/statusline" in out
    assert settings(conf)["statusLine"] == {
        "type": "command",
        "command": ENTRY_CMD,
        "refreshInterval": 60,
    }


def test_second_run_changes_nothing(conf, env):
    run(env, "nerd")
    before = (conf / "settings.json").stat().st_mtime_ns
    code, out = run(env)
    assert code == 0
    assert "already has dashline" in out
    assert "already runs it with nerd glyphs" in out
    assert (conf / "settings.json").stat().st_mtime_ns == before


def test_stale_copy_is_replaced_whole(conf, env):
    run(env)
    target = conf / "scripts" / "statusline"
    (target / "dashline" / "layout.py").write_text("# edited\n")
    (target / "dashline" / "gone.py").write_text("")
    code, out = run(env)
    assert code == 0
    assert "updated dashline" in out
    assert (target / "dashline" / "layout.py").read_bytes() == (
        ROOT / "src" / "dashline" / "layout.py"
    ).read_bytes()
    assert not (target / "dashline" / "gone.py").exists()
    assert not [p for p in target.parent.iterdir() if p.name != "statusline"]


def test_symlinked_install_dir_is_replaced(conf, env, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (conf / "scripts").mkdir()
    (conf / "scripts" / "statusline").symlink_to(elsewhere)
    assert run(env)[0] == 0
    target = conf / "scripts" / "statusline"
    assert not target.is_symlink()
    assert (target / "statusline.py").exists()
    assert elsewhere.exists()  # the link's target is left alone


def test_installed_copy_runs(conf, env):
    run(env, "ascii")
    shim = conf / "scripts" / "statusline" / "statusline.py"
    r = subprocess.run(
        [sys.executable, "-I", "-S", str(shim), "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd="/",
    )
    assert r.stdout == f"dashline {__version__}\n"


def test_config_dir(isolated_home, tmp_path):
    custom = tmp_path / "work-claude"
    code, _ = run({"HOME": str(isolated_home), "CLAUDE_CONFIG_DIR": str(custom)})
    assert code == 0
    assert (custom / "scripts" / "statusline" / "statusline.py").exists()
    assert "statusLine" in settings(custom)
    assert not (isolated_home / ".claude").exists()


# ---- the settings entry ----


def test_keeps_other_settings_and_order(conf, env):
    write_settings(conf, {"theme": "light", "model": "opus", "permissions": {"allow": []}})
    run(env, "nerd")
    data = settings(conf)
    assert list(data) == ["theme", "model", "permissions", "statusLine"]
    assert data["statusLine"]["command"] == f"{ENTRY_CMD} --glyphs nerd"


def test_keeps_glyphs_and_own_fields(conf, env):
    entry = {
        "type": "command",
        "command": f"{ENTRY_CMD} --glyphs nerd",
        "padding": 1,
        "refreshInterval": 30,
    }
    write_settings(conf, {"statusLine": entry})
    code, out = run(env)
    assert code == 0
    assert settings(conf)["statusLine"] == entry
    assert "already runs it with nerd glyphs, refreshing every 30 s" in out


def test_switches_glyphs(conf, env):
    run(env, "nerd")
    code, out = run(env, "unicode")
    assert code == 0
    assert settings(conf)["statusLine"]["command"] == ENTRY_CMD
    assert "now runs it with unicode glyphs" in out


def test_someone_elses_statusline_needs_replace(conf, env):
    theirs = {"type": "command", "command": "bash ~/my-status.sh", "padding": 0}
    write_settings(conf, {"statusLine": theirs})
    before = (conf / "settings.json").read_text()
    code, out = run(env, "nerd")
    assert code == install.NEEDS_REPLACE
    assert "bash ~/my-status.sh" in out
    assert "--replace" in out
    assert (conf / "settings.json").read_text() == before
    # The copy still happened, so --replace only has to change settings.
    assert (conf / "scripts" / "statusline" / "statusline.py").exists()

    code, out = run(env, "nerd", replace=True)
    assert code == 0
    assert settings(conf)["statusLine"] == {
        "type": "command",
        "command": f"{ENTRY_CMD} --glyphs nerd",
        "refreshInterval": 60,
    }


def test_symlinked_settings_stay_a_link(conf, env, tmp_path):
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text('{"theme": "dark"}\n')
    real.chmod(0o640)
    (conf / "settings.json").symlink_to(real)
    assert run(env)[0] == 0
    assert (conf / "settings.json").is_symlink()
    assert json.loads(real.read_text())["statusLine"]["command"] == ENTRY_CMD
    assert real.stat().st_mode & 0o777 == 0o640
    assert [p.name for p in real.parent.iterdir()] == ["settings.json"]


@pytest.mark.parametrize("text", ["{not json", "[1, 2]"])
def test_bad_settings_are_left_alone(conf, env, text, capsys):
    (conf / "settings.json").write_text(text)
    code, _ = run(env)
    assert code == 1
    assert (conf / "settings.json").read_text() == text
    assert "fix it and run again" in capsys.readouterr().err


def test_empty_settings_file(conf, env):
    (conf / "settings.json").write_text("")
    assert run(env)[0] == 0
    assert settings(conf)["statusLine"]["command"] == ENTRY_CMD


def test_project_statusline_wins_note(conf, env, tmp_path):
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"statusLine": {"type": "command", "command": "echo hi"}})
    )
    code, out = run(env, cwd=str(project))
    assert code == 0
    assert "note:" in out
    assert "sets its own statusLine" in out


# ---- helpers ----


@pytest.mark.parametrize(
    ("command", "glyphs"),
    [
        (ENTRY_CMD, "unicode"),
        (f"{ENTRY_CMD} --glyphs nerd", "nerd"),
        (f"{ENTRY_CMD} --glyphs=ascii", "ascii"),
        (f"{ENTRY_CMD} --glyphs 'nerd'", "nerd"),
    ],
)
def test_glyphs_of(command, glyphs):
    assert install.glyphs_of({"command": command}) == glyphs


@pytest.mark.parametrize(
    ("entry", "ours"),
    [
        ({"command": ENTRY_CMD}, True),
        ({"command": "python3 ~/.claude/scripts/statusline/statusline.py --glyphs nerd"}, True),
        ({"command": r"py C:\Users\me\.claude\scripts\statusline\statusline.py"}, True),
        ({"command": "bash ~/.claude/statusline.sh"}, False),
        ({"command": None}, False),
        ("python3 statusline.py", False),
        (None, False),
    ],
)
def test_is_ours(entry, ours):
    assert install.is_ours(entry) is ours


def test_home_short():
    env = {"HOME": "/home/me"}
    assert install.home_short("/home/me/.claude", env) == "~/.claude"
    assert install.home_short("/home/meg/x", env) == "/home/meg/x"
    assert install.home_short("/etc", env) == "/etc"


def test_no_temp_files_left(conf, env):
    write_settings(conf, {"theme": "dark"})
    run(env)
    assert sorted(p.name for p in conf.iterdir()) == ["scripts", "settings.json"]
