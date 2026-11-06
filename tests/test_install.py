"""--install: the copy, the settings entry, and when it refuses to touch settings."""

import io
import json
import os
import subprocess
import sys
import time

import pytest

from conftest import NO_NETWORK, ROOT
from dashline import __version__, install

NOW_REAL = time.time()  # leftover folders are judged by their real mtime
ENTRY_CMD = 'python3 -I -S "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/scripts/statusline/statusline.py"'


@pytest.fixture
def conf(isolated_home):
    path = isolated_home / ".claude"
    path.mkdir()
    return path


@pytest.fixture
def env(isolated_home):
    return {"HOME": str(isolated_home), **NO_NETWORK}


def settings(conf):
    return json.loads((conf / "settings.json").read_text())


def write_settings(conf, data):
    (conf / "settings.json").write_text(json.dumps(data, indent=2) + "\n")


def run(env, glyphs=None, replace=False, cwd=None, downgrade=False):
    out = io.StringIO()
    code = install.run(
        glyphs, replace=replace, env=env, out=out, cwd=cwd or "/", downgrade=downgrade
    )
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
    code, _ = run({"HOME": str(isolated_home), "CLAUDE_CONFIG_DIR": str(custom), **NO_NETWORK})
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
    assert "Nothing was changed" in out
    # An install that stops to ask copies nothing either.
    assert not (conf / "scripts").exists()

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


def test_settings_that_arent_utf8(conf, env, capsys):
    (conf / "settings.json").write_bytes(b'{"theme": "\xff"}')
    assert run(env)[0] == 1
    assert "isn't UTF-8 text" in capsys.readouterr().err


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
        ({"command": 'python3 "$HOME/.claude/scripts/statusline/statusline.py"'}, True),
        ({"command": r"py C:\Users\me\.claude\scripts\statusline\statusline.py"}, True),
        ({"command": "python3 ~/bin/scripts/statusline/statusline.py"}, False),
        ({"command": "python3 scripts/statusline/statusline.py"}, False),
        ({"command": "bash ~/.claude/statusline.sh"}, False),
        ({"command": None}, False),
        ("python3 statusline.py", False),
        (None, False),
    ],
)
def test_is_ours(entry, ours, env):
    assert install.is_ours(entry, env) is ours


def test_is_ours_with_a_config_dir(isolated_home, tmp_path):
    env = {"HOME": str(isolated_home), "CLAUDE_CONFIG_DIR": str(tmp_path / "work")}
    cmd = f"python3 {tmp_path}/work/scripts/statusline/statusline.py"
    assert install.is_ours({"command": cmd}, env)


def test_is_ours_needs_dashline_in_the_folder(conf, env):
    """Another statusline can live at the same path: then the entry is its, not ours."""
    other = conf / "scripts" / "statusline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('someone else')\n")
    assert not install.is_ours({"command": ENTRY_CMD}, env)
    run(env, replace=True)
    assert install.is_ours({"command": ENTRY_CMD}, env)


# ---- someone else's folder ----


def test_someone_elses_folder_is_left_alone(conf, env):
    other = conf / "scripts" / "statusline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('mine')\n")
    their_entry = {"type": "command", "command": f"bash {other}/statusline.py"}
    write_settings(conf, {"statusLine": their_entry})
    code, out = run(env)
    assert code == install.NEEDS_REPLACE
    assert "holds files that aren't dashline's" in out
    assert "Nothing was changed" in out
    assert (other / "statusline.py").read_text() == "print('mine')\n"
    assert settings(conf)["statusLine"] == their_entry


def test_replace_moves_someone_elses_folder_aside(conf, env):
    other = conf / "scripts" / "statusline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('mine')\n")
    # Their entry runs the same path, so it looks like ours until the folder is checked.
    write_settings(conf, {"statusLine": {"type": "command", "command": f"{ENTRY_CMD} -x"}})
    code, out = run(env, replace=True)
    assert code == 0, out
    backup = conf / "scripts" / "statusline.backup"
    assert (backup / "statusline.py").read_text() == "print('mine')\n"
    assert "moved the files in ~/.claude/scripts/statusline to " in out
    assert (other / "dashline" / "__init__.py").exists()
    assert settings(conf)["statusLine"]["command"] == ENTRY_CMD  # theirs, so not kept


def test_a_second_backup_gets_a_number(conf, env):
    (conf / "scripts" / "statusline.backup").mkdir(parents=True)
    (conf / "scripts" / "statusline").mkdir()
    (conf / "scripts" / "statusline" / "x").write_text("")
    assert run(env, replace=True)[0] == 0
    assert (conf / "scripts" / "statusline.backup-2" / "x").exists()


def test_empty_folder_counts_as_missing(conf, env):
    (conf / "scripts" / "statusline").mkdir(parents=True)
    assert run(env)[0] == 0


# ---- a command the user edited ----

EDITED = '/opt/py312/bin/python3 -I -S "$HOME/.claude/scripts/statusline/statusline.py"'


def test_hand_edited_command_is_kept(conf, env):
    entry = {"type": "command", "command": f"{EDITED} --glyphs nerd", "refreshInterval": 60}
    write_settings(conf, {"statusLine": entry})
    code, out = run(env)
    assert code == 0
    assert settings(conf)["statusLine"] == entry
    assert "already runs it with nerd glyphs" in out


def test_hand_edited_command_only_changes_its_glyphs(conf, env):
    write_settings(conf, {"statusLine": {"type": "command", "command": f"{EDITED} --glyphs nerd"}})
    run(env, "ascii")
    assert settings(conf)["statusLine"]["command"] == f"{EDITED} --glyphs ascii"
    run(env, "unicode")
    assert settings(conf)["statusLine"]["command"] == EDITED
    run(env, "nerd")
    assert settings(conf)["statusLine"]["command"] == f"{EDITED} --glyphs nerd"


def test_unknown_glyphs_in_the_command_are_dropped(conf, env):
    write_settings(
        conf, {"statusLine": {"type": "command", "command": f"{ENTRY_CMD} --glyphs fancy"}}
    )
    code, out = run(env)
    assert code == 0
    assert settings(conf)["statusLine"]["command"] == ENTRY_CMD
    assert "now runs it with unicode glyphs" in out


@pytest.mark.parametrize(
    ("cmd", "glyphs", "expected"),
    [
        (ENTRY_CMD, "nerd", f"{ENTRY_CMD} --glyphs nerd"),
        (f"{ENTRY_CMD} --glyphs nerd", "unicode", ENTRY_CMD),
        (f"{ENTRY_CMD} --glyphs=nerd", "ascii", f"{ENTRY_CMD} --glyphs ascii"),
        (f"{ENTRY_CMD} --glyphs 'nerd' --glyphs x", "ascii", f"{ENTRY_CMD} --glyphs ascii"),
    ],
)
def test_with_glyphs(cmd, glyphs, expected):
    assert install.with_glyphs(cmd, glyphs) == expected


# ---- settings.json edge cases ----


def test_settings_with_a_bom(conf, env):
    (conf / "settings.json").write_bytes(b"\xef\xbb\xbf" + b'{"theme": "light"}\n')
    code, _ = run(env)
    assert code == 0
    raw = (conf / "settings.json").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # kept, as the editor that added it wants
    data = json.loads(raw.decode("utf-8-sig"))
    assert data["theme"] == "light"
    assert data["statusLine"]["command"] == ENTRY_CMD


def test_read_only_settings_are_refused(conf, env, capsys):
    write_settings(conf, {"theme": "dark"})
    (conf / "settings.json").chmod(0o444)
    try:
        before = (conf / "settings.json").read_text()
        code, _ = run(env)
        assert code == 1
        assert "read-only" in capsys.readouterr().err
        assert (conf / "settings.json").read_text() == before
        assert not (conf / "scripts").exists()  # checked before copying
    finally:
        (conf / "settings.json").chmod(0o644)


def test_read_only_settings_that_need_no_change_are_fine(conf, env):
    run(env)
    (conf / "settings.json").chmod(0o444)
    try:
        assert run(env)[0] == 0
    finally:
        (conf / "settings.json").chmod(0o644)


def test_project_dir_from_claude(conf, env, tmp_path):
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"statusLine": {"type": "command", "command": "echo hi"}})
    )
    out = io.StringIO()
    env = dict(env, CLAUDE_PROJECT_DIR=str(project))
    assert install.run(None, env=env, out=out) == 0
    assert "sets its own statusLine" in out.getvalue()


# ---- the folder swap ----


def test_failed_swap_puts_the_old_copy_back(conf, env, monkeypatch, capsys):
    run(env)
    target = conf / "scripts" / "statusline"
    (target / "dashline" / "layout.py").write_text("# old\n")
    real_rename = os.rename

    def rename(src, dst):
        if ".new-" in str(src):
            raise OSError(28, "No space left on device")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", rename)
    code, _ = run(env)
    assert code == 1
    assert "No space left on device" in capsys.readouterr().err
    assert (target / "dashline" / "layout.py").read_text() == "# old\n"
    assert sorted(p.name for p in target.parent.iterdir()) == ["statusline"]


def dead_pid():
    pid = 4_000_000
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return pid
        except OSError:
            pass
        pid += 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX process check")
def test_leftovers_of_dead_installs_are_removed(conf, env):
    scripts = conf / "scripts"
    dead, alive = dead_pid(), os.getppid()
    for name in (f"statusline.new-{dead}", f"statusline.old-{dead}", f"statusline.new-{alive}"):
        (scripts / name / "dashline").mkdir(parents=True)
    (scripts / "statusline.notes").mkdir()
    assert run(env)[0] == 0
    assert sorted(p.name for p in scripts.iterdir()) == [
        "statusline",
        f"statusline.new-{alive}",
        "statusline.notes",
    ]


def test_leftovers_where_pids_cant_be_checked(conf, monkeypatch):
    monkeypatch.setattr(install, "_alive", lambda pid: None)
    scripts = conf / "scripts"
    (scripts / "statusline.old-11").mkdir(parents=True)
    (scripts / "statusline.old-12").mkdir()
    os.utime(scripts / "statusline.old-11", (NOW_REAL - 7200, NOW_REAL - 7200))
    removed = install.clean_leftovers(str(scripts), NOW_REAL)
    assert removed == ["statusline.old-11"]
    assert (scripts / "statusline.old-12").exists()


def test_home_short():
    env = {"HOME": "/home/me"}
    assert install.home_short("/home/me/.claude", env) == "~/.claude"
    assert install.home_short("/home/meg/x", env) == "/home/meg/x"
    assert install.home_short("/etc", env) == "/etc"


def test_no_temp_files_left(conf, env):
    write_settings(conf, {"theme": "dark"})
    run(env)
    assert sorted(p.name for p in conf.iterdir()) == ["scripts", "settings.json"]


# ---- a newer installed copy ----


def test_newer_installed_copy_asks_first(conf, env):
    run(env, "nerd")
    target = conf / "scripts" / "statusline"
    (target / "VERSION").write_text("99.0.0\n")
    (target / "dashline" / "layout.py").write_text("# newer\n")
    before = settings(conf)
    code, out = run(env)
    assert code == install.NEEDS_DOWNGRADE
    assert "dashline 99.0.0, newer than this copy" in out
    assert "--downgrade" in out and "Nothing was changed." in out
    assert (target / "VERSION").read_text() == "99.0.0\n"
    assert (target / "dashline" / "layout.py").read_text() == "# newer\n"
    assert settings(conf) == before


def test_downgrade_installs_this_copy(conf, env):
    run(env)
    target = conf / "scripts" / "statusline"
    (target / "VERSION").write_text("99.0.0\n")
    code, _ = run(env, downgrade=True)
    assert code == 0
    assert (target / "VERSION").read_text() == f"{__version__}\n"


@pytest.mark.parametrize("version", ["0.0.1", "garbage", None])
def test_older_or_unknown_installed_copy_just_updates(conf, env, version):
    run(env)
    target = conf / "scripts" / "statusline"
    if version is None:
        (target / "VERSION").unlink()
    else:
        (target / "VERSION").write_text(version + "\n")
    code, _ = run(env)
    assert code == 0
    assert (target / "VERSION").read_text() == f"{__version__}\n"
