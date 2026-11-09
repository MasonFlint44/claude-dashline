"""--install: the copy, the settings entry, and when it refuses to touch settings."""

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import NO_NETWORK, ROOT, env_for, held_once, posix_only
from dashline import __version__, host, install

NOW_REAL = time.time()  # leftover folders are judged by their real mtime
ENTRY_CMD = 'python3 -I -S "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/scripts/dashline/statusline.py"'


@pytest.fixture
def conf(isolated_home):
    path = isolated_home / ".claude"
    path.mkdir()
    return path


@pytest.fixture
def env(isolated_home):
    return env_for(isolated_home)


def settings(conf):
    return json.loads((conf / "settings.json").read_text(encoding="utf-8"))


def write_settings(conf, data):
    (conf / "settings.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def run(env, glyphs=None, replace=False, cwd=None, downgrade=False):
    out = io.StringIO()
    # The POSIX entry on every platform: what these tests check is the same there.
    # Windows' own entry has tests of its own (test_windows_*).
    code = install.run(
        glyphs,
        replace=replace,
        env=env,
        out=out,
        cwd=cwd or "/",
        downgrade=downgrade,
        windows=False,
    )
    return code, out.getvalue()


# ---- the copy ----


def test_fresh_install(conf, env):
    code, out = run(env)
    assert code == 0
    target = conf / "scripts" / "dashline"
    assert (target / "statusline.py").read_bytes() == (ROOT / "statusline.py").read_bytes()
    assert (target / "VERSION").read_text() == f"{__version__}\n"
    for src in (ROOT / "src" / "dashline").glob("*.py"):
        assert (target / "dashline" / src.name).read_bytes() == src.read_bytes()
    assert not list((target / "dashline").glob("__pycache__"))
    assert f"installed dashline {__version__} in ~/.claude/scripts/dashline" in out
    assert settings(conf)["statusLine"] == {
        "type": "command",
        "command": ENTRY_CMD,
        "refreshInterval": 60,
    }


@pytest.mark.parametrize("seed", ["empty", "junk", pytest.param("link", marks=posix_only)])
def test_first_install_into_an_empty_folder_says_installed(conf, env, tmp_path, seed):
    """The install skill asks about glyphs only after `installed`: an empty folder (or one
    with desktop junk, or a dotfiles link to an empty one) is a first install too."""
    target = conf / "scripts" / "dashline"
    target.parent.mkdir(parents=True, exist_ok=True)
    if seed == "link":
        (tmp_path / "dotfiles").mkdir()
        target.symlink_to(tmp_path / "dotfiles")
    else:
        target.mkdir()
        if seed == "junk":
            (target / ".DS_Store").write_bytes(b"")
    code, out = run(env)
    assert code == 0
    assert f"installed dashline {__version__}" in out


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
    target = conf / "scripts" / "dashline"
    (target / "dashline" / "layout.py").write_text("# edited\n")
    (target / "dashline" / "gone.py").write_text("")
    code, out = run(env)
    assert code == 0
    assert "updated dashline" in out
    assert (target / "dashline" / "layout.py").read_bytes() == (
        ROOT / "src" / "dashline" / "layout.py"
    ).read_bytes()
    assert not (target / "dashline" / "gone.py").exists()
    assert not [p for p in target.parent.iterdir() if p.name != "dashline"]


def test_update_keeps_the_users_own_files(conf, env):
    run(env)
    target = conf / "scripts" / "dashline"
    (target / "dashline" / "layout.py").write_text("# old\n")
    (target / "notes.txt").write_text("mine\n")
    (target / "wrap").mkdir()
    (target / "wrap" / "run.sh").write_text("#!/bin/sh\n")
    (target / "link").symlink_to("notes.txt")
    code, out = run(env)
    assert code == 0
    assert "updated dashline" in out
    assert (target / "notes.txt").read_text() == "mine\n"
    assert (target / "wrap" / "run.sh").read_text() == "#!/bin/sh\n"
    assert str((target / "link").readlink()) == "notes.txt"
    assert (target / "dashline" / "layout.py").read_text(encoding="utf-8") != "# old\n"
    assert not [p for p in target.parent.iterdir() if p.name != "dashline"]


def test_missing_shim_is_an_error(conf, env, monkeypatch, capsys):
    monkeypatch.setattr(install, "source_shim", lambda root: None)
    code, _ = run(env)
    assert code == 1
    assert "no statusline.py next to" in capsys.readouterr().err
    assert not (conf / "scripts").exists()
    assert not (conf / "settings.json").exists()


def test_install_run_from_the_installed_copy(conf, env, monkeypatch):
    run(env)
    target = conf / "scripts" / "dashline"
    monkeypatch.setattr(install, "source_root", lambda: str(target))
    code, out = run(env)
    assert code == 0
    assert "running from ~/.claude/scripts/dashline: nothing to copy" in out


def test_symlinked_install_dir_stays_a_link(conf, env, tmp_path):
    """Dotfiles (stow, say) link the folder into a repo: the copy goes there."""
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    elsewhere = dotfiles / "dashline"
    elsewhere.mkdir()
    (conf / "scripts").mkdir()
    link = conf / "scripts" / "dashline"
    link.symlink_to(elsewhere)
    assert run(env)[0] == 0
    assert link.is_symlink() and link.resolve() == elsewhere
    assert (elsewhere / "statusline.py").exists()
    # An update swaps the folder beside the real one and keeps the user's files.
    (elsewhere / "notes.txt").write_text("mine\n")
    (elsewhere / "dashline" / "layout.py").write_text("# edited\n")
    code, out = run(env)
    assert code == 0 and "updated dashline" in out
    assert link.is_symlink() and link.resolve() == elsewhere
    assert (elsewhere / "notes.txt").read_text() == "mine\n"
    assert sorted(p.name for p in dotfiles.iterdir()) == ["dashline"]
    assert install.folder_state(str(link)) == "ours"


def test_dangling_link_counts_as_missing(conf, env, tmp_path):
    (conf / "scripts").mkdir()
    link = conf / "scripts" / "dashline"
    link.symlink_to(tmp_path / "not-yet")
    assert install.folder_state(str(link)) == "missing"
    assert run(env)[0] == 0
    assert link.is_symlink() and (tmp_path / "not-yet" / "statusline.py").exists()


def test_link_to_a_file_is_someone_elses(conf, env, tmp_path):
    (tmp_path / "file").write_text("x")
    (conf / "scripts").mkdir()
    (conf / "scripts" / "dashline").symlink_to(tmp_path / "file")
    assert install.folder_state(str(conf / "scripts" / "dashline")) == "theirs"


def test_installed_copy_runs(conf, env):
    run(env, "ascii")
    shim = conf / "scripts" / "dashline" / "statusline.py"
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
    assert (custom / "scripts" / "dashline" / "statusline.py").exists()
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
    assert json.loads(real.read_text(encoding="utf-8"))["statusLine"]["command"] == ENTRY_CMD
    if os.name != "nt":  # no such modes there
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


def test_project_entry_that_only_names_dashline_still_gets_the_note(conf, env, tmp_path):
    """A project's entry is dashline's only if its whole command runs statusline.py."""
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    entry = {"type": "command", "command": ENTRY_CMD + " || echo x"}
    (project / ".claude" / "settings.json").write_text(json.dumps({"statusLine": entry}))
    code, out = run(env, cwd=str(project))
    assert code == 0
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
        ({"command": "python3 ~/.claude/scripts/dashline/statusline.py --glyphs nerd"}, True),
        ({"command": 'python3 "$HOME/.claude/scripts/dashline/statusline.py"'}, True),
        ({"command": r"py C:\Users\me\.claude\scripts\dashline\statusline.py"}, True),
        ({"command": "python3 ~/bin/scripts/dashline/statusline.py"}, False),
        ({"command": "python3 scripts/dashline/statusline.py"}, False),
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
    cmd = f"python3 {tmp_path}/work/scripts/dashline/statusline.py"
    assert install.is_ours({"command": cmd}, env)


def test_is_ours_needs_dashline_in_the_folder(conf, env):
    """Another statusline can live at the same path: then the entry is its, not ours."""
    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('someone else')\n")
    assert not install.is_ours({"command": ENTRY_CMD}, env)
    run(env, replace=True)
    assert install.is_ours({"command": ENTRY_CMD}, env)


# ---- someone else's folder ----


def test_someone_elses_folder_is_left_alone(conf, env):
    other = conf / "scripts" / "dashline"
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


def test_someone_elses_folder_under_dashlines_own_entry(conf, env):
    """Only the folder is someone else's: the entry isn't shown as "something else"."""
    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "other.sh").write_text("echo mine\n")
    write_settings(conf, {"statusLine": {"type": "command", "command": ENTRY_CMD}})
    code, out = run(env)
    assert code == install.NEEDS_REPLACE
    assert "holds files that aren't dashline's" in out
    assert "runs something else" not in out
    assert "runs the statusline.py in that folder" in out


def test_replace_moves_someone_elses_folder_aside(conf, env):
    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('mine')\n")
    # Their entry runs the same path, so it looks like ours until the folder is checked.
    write_settings(conf, {"statusLine": {"type": "command", "command": f"{ENTRY_CMD} -x"}})
    code, out = run(env, replace=True)
    assert code == 0, out
    backup = conf / "scripts" / "dashline.backup"
    assert (backup / "statusline.py").read_text() == "print('mine')\n"
    assert "moved the files in ~/.claude/scripts/dashline to " in out
    assert (other / "dashline" / "__init__.py").exists()
    assert settings(conf)["statusLine"]["command"] == ENTRY_CMD  # theirs, so not kept


def test_a_second_backup_gets_a_number(conf, env):
    (conf / "scripts" / "dashline.backup").mkdir(parents=True)
    (conf / "scripts" / "dashline").mkdir()
    (conf / "scripts" / "dashline" / "x").write_text("")
    assert run(env, replace=True)[0] == 0
    assert (conf / "scripts" / "dashline.backup-2" / "x").exists()


def test_empty_folder_counts_as_missing(conf, env):
    (conf / "scripts" / "dashline").mkdir(parents=True)
    assert run(env)[0] == 0


@pytest.mark.parametrize("junk", [".DS_Store", "Thumbs.db"])
def test_file_manager_junk_doesnt_make_a_folder_someones(conf, env, junk):
    target = conf / "scripts" / "dashline"
    target.mkdir(parents=True)
    (target / junk).write_text("")
    assert install.folder_state(str(target)) == "missing"
    code, out = run(env)
    assert code == 0, out
    assert (target / "dashline" / "__init__.py").exists()
    assert not (conf / "scripts" / "dashline.backup").exists()


def test_failed_replace_puts_their_folder_back(conf, env, monkeypatch, capsys):
    import shutil

    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('mine')\n")
    their_entry = {"type": "command", "command": f"bash {other}/statusline.py"}
    write_settings(conf, {"statusLine": their_entry})

    def full(*args, **kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(shutil, "copyfile", full)
    code, out = run(env, replace=True)
    assert code == 1
    assert "No space left on device" in capsys.readouterr().err
    assert "back to ~/.claude/scripts/dashline" in out
    assert (other / "statusline.py").read_text() == "print('mine')\n"
    assert sorted(p.name for p in other.parent.iterdir()) == ["dashline"]
    assert settings(conf)["statusLine"] == their_entry


def test_replace_whose_settings_write_fails_puts_their_folder_back(conf, env, monkeypatch, capsys):
    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('mine')\n")
    write_settings(conf, {"statusLine": {"type": "command", "command": "echo theirs"}})

    def fail(path, data):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(install, "write_settings", fail)
    code, _ = run(env, replace=True)
    assert code == 1
    assert "couldn't write" in capsys.readouterr().err
    assert (other / "statusline.py").read_text() == "print('mine')\n"
    assert not (other / "dashline").exists()
    assert sorted(p.name for p in other.parent.iterdir()) == ["dashline"]


def test_failed_set_aside_changes_nothing(conf, env, monkeypatch, capsys):
    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('mine')\n")
    write_settings(conf, {"statusLine": {"type": "command", "command": "echo theirs"}})
    real_rename = os.rename

    def rename(src, dst):
        if str(dst).endswith(".backup"):
            raise OSError(13, "Permission denied")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", rename)
    code, _ = run(env, replace=True)
    assert code == 1
    assert "couldn't move" in capsys.readouterr().err
    assert sorted(p.name for p in other.iterdir()) == ["statusline.py"]
    assert settings(conf)["statusLine"]["command"] == "echo theirs"


# ---- a command the user edited ----

EDITED = '/opt/py312/bin/python3 -I -S "$HOME/.claude/scripts/dashline/statusline.py"'


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


def test_unknown_glyphs_in_the_command_are_kept(conf, env):
    """A typo like `--glyphs Nerd` meant a set: a plain install keeps it and says so,
    for the glyph step to ask which (PLAN §9: never a reset to unicode)."""
    mine = f"{ENTRY_CMD} --glyphs Nerd"
    write_settings(conf, {"statusLine": {"type": "command", "command": mine}})
    code, out = run(env)
    assert code == 0, out
    assert settings(conf)["statusLine"]["command"] == mine
    assert "now runs it with --glyphs Nerd" in out
    assert "note: --glyphs Nerd isn't a glyph set (nerd, unicode or ascii)" in out
    # Asked for a set, it's replaced.
    code, out = run(env, "nerd")
    assert code == 0, out
    assert settings(conf)["statusLine"]["command"] == f"{ENTRY_CMD} --glyphs nerd"
    assert "isn't a glyph set" not in out


@pytest.mark.parametrize(
    ("cmd", "glyphs", "expected"),
    [
        (ENTRY_CMD, "nerd", f"{ENTRY_CMD} --glyphs nerd"),
        (f"{ENTRY_CMD} --glyphs nerd", "unicode", ENTRY_CMD),
        (f"{ENTRY_CMD} --glyphs=nerd", "ascii", f"{ENTRY_CMD} --glyphs ascii"),
        (f"{ENTRY_CMD} --glyphs 'nerd' --glyphs x", "ascii", f"{ENTRY_CMD} --glyphs ascii"),
        # The flag goes after the script, ahead of anything the command does next.
        (
            f"{ENTRY_CMD} 2>/dev/null || echo off",
            "ascii",
            f"{ENTRY_CMD} --glyphs ascii 2>/dev/null || echo off",
        ),
        (
            f"{ENTRY_CMD} --glyphs nerd 2>/dev/null || echo off",
            "unicode",
            f"{ENTRY_CMD} 2>/dev/null || echo off",
        ),
        (
            f"{ENTRY_CMD} --glyphs nerd 2>/dev/null",
            "ascii",
            f"{ENTRY_CMD} --glyphs ascii 2>/dev/null",
        ),
        # A --glyphs after the command ends belongs to something else: it stays.
        (
            f"{ENTRY_CMD} || echo off --glyphs nerd",
            "ascii",
            f"{ENTRY_CMD} --glyphs ascii || echo off --glyphs nerd",
        ),
        (
            "python3 $HOME/.claude/scripts/dashline/statusline.py;true",
            "nerd",
            "python3 $HOME/.claude/scripts/dashline/statusline.py --glyphs nerd;true",
        ),
        (
            "python3 '/home/my me/.claude/scripts/dashline/statusline.py' | cat",
            "nerd",
            "python3 '/home/my me/.claude/scripts/dashline/statusline.py' --glyphs nerd | cat",
        ),
        (
            r"py C:\Users\me\.claude\scripts\dashline\statusline.py -x",
            "nerd",
            r"py C:\Users\me\.claude\scripts\dashline\statusline.py --glyphs nerd -x",
        ),
    ],
)
def test_with_glyphs(cmd, glyphs, expected):
    assert install.with_glyphs(cmd, glyphs) == expected


def test_glyphs_change_keeps_a_shell_tail_working(conf, env):
    write_settings(conf, {"statusLine": {"type": "command", "command": f"{EDITED} || echo off"}})
    code, out = run(env, "ascii")
    assert code == 0
    assert settings(conf)["statusLine"]["command"] == f"{EDITED} --glyphs ascii || echo off"
    assert "now runs it with ascii glyphs" in out


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
        # The path as the rest of install's messages give it.
        assert "dashline: ~/.claude/settings.json is read-only" in capsys.readouterr().err
        assert (conf / "settings.json").read_text() == before
        assert not (conf / "scripts").exists()  # checked before copying
    finally:
        (conf / "settings.json").chmod(0o644)


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="POSIX permissions")
def test_read_only_settings_folder_is_refused_before_copying(conf, env, capsys):
    write_settings(conf, {"theme": "dark"})
    conf.chmod(0o555)
    try:
        code, _ = run(env)
        assert code == 1
        assert "can't write in" in capsys.readouterr().err
        assert not (conf / "scripts").exists()  # checked before copying
    finally:
        conf.chmod(0o755)
    assert settings(conf) == {"theme": "dark"}


def test_new_settings_folder_is_checked_where_it_will_be_made(isolated_home, tmp_path):
    custom = tmp_path / "a" / "b"
    code, _ = run({"HOME": str(isolated_home), "CLAUDE_CONFIG_DIR": str(custom), **NO_NETWORK})
    assert code == 0
    assert "statusLine" in settings(custom)


@posix_only
def test_settings_temp_file_is_private_until_written(conf, env, monkeypatch):
    write_settings(conf, {"env": {"SECRET": "x"}})
    (conf / "settings.json").chmod(0o600)
    modes = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *args, **kw):
        if ".dashline-" in str(path):
            modes.append((flags & os.O_EXCL, mode))
        return real_open(path, flags, mode, *args, **kw)

    monkeypatch.setattr(os, "open", spy)
    assert run(env)[0] == 0
    assert modes == [(os.O_EXCL, 0o600)]
    assert (conf / "settings.json").stat().st_mode & 0o777 == 0o600


@posix_only
def test_settings_keep_a_wider_mode(conf, env):
    write_settings(conf, {"theme": "dark"})
    (conf / "settings.json").chmod(0o640)
    assert run(env)[0] == 0
    assert (conf / "settings.json").stat().st_mode & 0o777 == 0o640


def test_a_stale_settings_temp_file_is_replaced(conf, env):
    write_settings(conf, {"theme": "dark"})
    (conf / f"settings.json.dashline-{os.getpid()}.tmp").write_text("old")
    assert run(env)[0] == 0
    assert sorted(p.name for p in conf.iterdir()) == ["scripts", "settings.json"]


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
    assert install.run(None, env=env, out=out, windows=False) == 0
    assert "sets its own statusLine" in out.getvalue()


# ---- the folder swap ----


def test_failed_swap_puts_the_old_copy_back(conf, env, monkeypatch, capsys):
    run(env)
    target = conf / "scripts" / "dashline"
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
    assert sorted(p.name for p in target.parent.iterdir()) == ["dashline"]


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
    for name in (f"dashline.new-{dead}", f"dashline.old-{dead}", f"dashline.new-{alive}"):
        (scripts / name / "dashline").mkdir(parents=True)
    (scripts / "dashline.notes").mkdir()
    assert run(env)[0] == 0
    assert sorted(p.name for p in scripts.iterdir()) == [
        "dashline",
        f"dashline.new-{alive}",
        "dashline.notes",
    ]


def test_leftovers_where_pids_cant_be_checked(conf, monkeypatch):
    monkeypatch.setattr(install, "_alive", lambda pid: None)
    scripts = conf / "scripts"
    (scripts / "dashline.old-11").mkdir(parents=True)
    (scripts / "dashline.old-12").mkdir()
    os.utime(scripts / "dashline.old-11", (NOW_REAL - 7200, NOW_REAL - 7200))
    # Recent but already in the past: made just now, it would be "from the future".
    os.utime(scripts / "dashline.old-12", (NOW_REAL - 10, NOW_REAL - 10))
    assert install.clean_leftovers(str(scripts), NOW_REAL) == (["dashline.old-11"], [])
    assert (scripts / "dashline.old-12").exists()


def test_leftover_that_vanishes_mid_scan(conf, monkeypatch):
    monkeypatch.setattr(install, "_alive", lambda pid: None)
    scripts = conf / "scripts"
    scripts.mkdir()
    monkeypatch.setattr(os, "listdir", lambda path: ["dashline.old-11"])  # gone already
    assert install.clean_leftovers(str(scripts), NOW_REAL) == ([], [])


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
    target = conf / "scripts" / "dashline"
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
    target = conf / "scripts" / "dashline"
    (target / "VERSION").write_text("99.0.0\n")
    code, _ = run(env, downgrade=True)
    assert code == 0
    assert (target / "VERSION").read_text() == f"{__version__}\n"


@pytest.mark.parametrize("version", ["0.0.1", "garbage", None])
def test_older_or_unknown_installed_copy_just_updates(conf, env, version):
    run(env)
    target = conf / "scripts" / "dashline"
    if version is None:
        (target / "VERSION").unlink()
    else:
        (target / "VERSION").write_text(version + "\n")
    code, _ = run(env)
    assert code == 0
    assert (target / "VERSION").read_text() == f"{__version__}\n"


# ---- a command whose dashline arguments can't be told apart ----

LOGIN_SHELL = "bash -lc 'python3 ~/.claude/scripts/dashline/statusline.py{flag}'"
GUARDED = (
    "[ -f ~/.claude/scripts/dashline/statusline.py ] && "
    "python3 ~/.claude/scripts/dashline/statusline.py"
)


@pytest.mark.parametrize(
    "cmd",
    [
        LOGIN_SHELL.format(flag=" --glyphs nerd"),
        LOGIN_SHELL.format(flag=""),
        "python3 $(echo ~/.claude/scripts/dashline/statusline.py)",
        "sh ~/.claude/scripts/dashline/statusline.py",
        "python3 -c 'x' ~/.claude/scripts/dashline/statusline.py",
        "python3 ~/.claude/scripts/dashline/statusline.py.bak",
    ],
)
def test_with_glyphs_refuses_what_it_cant_follow(cmd):
    assert install.with_glyphs(cmd, "ascii") is None


@pytest.mark.parametrize(
    ("flag", "edit"),
    [
        (" --glyphs nerd", "change `--glyphs nerd` to `--glyphs ascii`"),
        ("", "add `--glyphs ascii` right after statusline.py, where dashline reads it"),
    ],
)
def test_glyphs_change_refused_in_a_login_shell(conf, env, capsys, flag, edit):
    cmd = LOGIN_SHELL.format(flag=flag)
    write_settings(conf, {"statusLine": {"type": "command", "command": cmd}})
    before = (conf / "settings.json").read_bytes()
    code, out = run(env, "ascii")
    err = capsys.readouterr().err
    assert code == 1
    assert "can't change --glyphs in this statusLine command automatically" in err
    assert f"  {cmd}\n" in err
    assert f"edit ~/.claude/settings.json yourself: {edit}. Nothing was changed." in err
    assert (conf / "settings.json").read_bytes() == before
    assert not (conf / "scripts").exists()  # checked before anything was copied
    assert out == ""


def test_update_leaves_a_login_shell_command_alone(conf, env):
    cmd = LOGIN_SHELL.format(flag=" --glyphs nerd")
    write_settings(conf, {"statusLine": {"type": "command", "command": cmd}})
    code, out = run(env)
    assert code == 0
    assert settings(conf)["statusLine"]["command"] == cmd
    assert "with nerd glyphs" in out
    code, _ = run(env, "nerd")  # the set it already uses: nothing to change
    assert code == 0


def test_unknown_glyphs_in_a_login_shell_are_left_alone(conf, env):
    cmd = LOGIN_SHELL.format(flag=" --glyphs fancy")
    write_settings(conf, {"statusLine": {"type": "command", "command": cmd}})
    assert run(env)[0] == 0
    assert settings(conf)["statusLine"]["command"] == cmd


def test_guarded_command_gets_the_flag_after_the_script(conf, env):
    write_settings(conf, {"statusLine": {"type": "command", "command": GUARDED}})
    assert run(env, "ascii")[0] == 0
    cmd = settings(conf)["statusLine"]["command"]
    assert cmd == f"{GUARDED} --glyphs ascii"
    assert install.glyphs_of({"command": cmd}) == "ascii"


@pytest.mark.parametrize("glyphs", ["ascii", "unicode"])
def test_rewritten_commands_still_parse_in_sh(glyphs):
    for cmd in (
        f"{EDITED} --glyphs nerd 2>/dev/null || echo off --glyphs x",
        GUARDED,
        f"FOO=1 exec {EDITED} --glyphs=nerd; true",
    ):
        changed = install.with_glyphs(cmd, glyphs)
        assert changed is not None
        assert "echo off --glyphs x" in changed or "echo off" not in cmd
        assert subprocess.run(["sh", "-n", "-c", changed], env=NO_NETWORK).returncode == 0


def test_a_tail_flag_isnt_dashlines():
    cmd = f"{ENTRY_CMD} || echo off --glyphs nerd"
    assert install.glyphs_of({"command": cmd}) == "unicode"
    assert install.flag_value(cmd) is None


# ---- settings that can't be written back as they were ----


def test_settings_with_a_lone_surrogate_escape(conf, env):
    (conf / "settings.json").write_text('{"note": "\\ud83d", "name": "café"}\n', encoding="utf-8")
    code, _ = run(env)
    assert code == 0
    data = settings(conf)
    assert data["note"] == "\ud83d" and data["name"] == "café"
    assert data["statusLine"]["command"] == ENTRY_CMD


def test_replace_with_a_lone_surrogate_escape(conf, env):
    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('mine')\n")
    (conf / "settings.json").write_text(
        '{"note": "\\ud83d", "statusLine": {"type": "command", "command": "echo theirs"}}\n'
    )
    code, _ = run(env, replace=True)
    assert code == 0
    assert settings(conf)["statusLine"]["command"] == ENTRY_CMD
    assert (conf / "scripts" / "dashline.backup" / "statusline.py").exists()


def test_settings_that_cant_be_serialized_change_nothing(conf, env, monkeypatch, capsys):
    write_settings(conf, {"theme": "dark"})

    def deep(*args, **kw):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(install.json, "dumps", deep)
    code, _ = run(env)
    assert code == 1
    assert "can't be written back" in capsys.readouterr().err
    assert not (conf / "scripts").exists()


def test_deeply_nested_settings_are_refused(conf, env, monkeypatch, capsys):
    write_settings(conf, {"theme": "dark"})

    def deep(*args, **kw):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(install.json, "loads", deep)
    code, _ = run(env)
    assert code == 1
    assert "isn't readable JSON (nested too deeply)" in capsys.readouterr().err
    assert not (conf / "scripts").exists()


def test_ctrl_c_during_replace_puts_their_folder_back(conf, env, monkeypatch):
    import shutil

    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('mine')\n")
    write_settings(conf, {"statusLine": {"type": "command", "command": "echo theirs"}})

    def interrupted(*args, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(shutil, "copyfile", interrupted)
    with pytest.raises(KeyboardInterrupt):
        install.run(None, replace=True, env=env, out=io.StringIO(), cwd="/", windows=False)
    assert (other / "statusline.py").read_text() == "print('mine')\n"
    assert sorted(p.name for p in other.parent.iterdir()) == ["dashline"]
    assert settings(conf)["statusLine"]["command"] == "echo theirs"


def test_put_back_that_fails_says_so(conf, env, monkeypatch, capsys):
    import shutil

    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('mine')\n")
    write_settings(conf, {"statusLine": {"type": "command", "command": "echo theirs"}})
    real_rename = os.rename

    def rename(src, dst):
        if str(src).endswith(".backup"):
            raise OSError(16, "Device or resource busy")
        real_rename(src, dst)

    def full(*args, **kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "rename", rename)
    monkeypatch.setattr(shutil, "copyfile", full)
    code, out = run(env, replace=True)
    assert code == 1
    assert "move it yourself" in out
    assert (conf / "scripts" / "dashline.backup" / "statusline.py").exists()


def test_failed_settings_write_leaves_no_temp_file(conf, env, monkeypatch, capsys):
    write_settings(conf, {"theme": "dark"})

    def broken(src, dst):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(os, "replace", broken)
    code, _ = run(env)
    assert code == 1
    assert "couldn't write" in capsys.readouterr().err
    assert sorted(p.name for p in conf.iterdir()) == ["scripts", "settings.json"]
    assert settings(conf) == {"theme": "dark"}


# ---- the user's files across an update ----


def stale_install(env, conf):
    run(env)
    target = conf / "scripts" / "dashline"
    (target / "dashline" / "layout.py").write_text("# old\n")
    return target


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="POSIX permissions")
def test_unreadable_extra_is_moved_not_copied(conf, env):
    target = stale_install(env, conf)
    secret = target / "secret.txt"
    secret.write_text("mine\n")
    secret.chmod(0)
    try:
        code, out = run(env)
        assert code == 0 and "updated dashline" in out
        assert secret.exists() and secret.stat().st_mode & 0o777 == 0
    finally:
        secret.chmod(0o600)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs FIFOs")
def test_a_fifo_extra_is_moved(conf, env):
    import stat

    target = stale_install(env, conf)
    os.mkfifo(target / "pipe")
    code, _ = run(env)
    assert code == 0
    assert stat.S_ISFIFO((target / "pipe").lstat().st_mode)


def test_a_big_extra_folder_is_moved_not_copied(conf, env):
    target = stale_install(env, conf)
    venv = target / ".venv"
    (venv / "lib").mkdir(parents=True)
    (venv / "lib" / "big.bin").write_bytes(b"x" * 100_000)
    inodes = (venv.stat().st_ino, (venv / "lib" / "big.bin").stat().st_ino)
    assert run(env)[0] == 0
    assert (venv.stat().st_ino, (venv / "lib" / "big.bin").stat().st_ino) == inodes


def test_an_extra_that_wont_move_is_kept_aside(conf, env, monkeypatch):
    target = stale_install(env, conf)
    (target / "stuck.txt").write_text("mine\n")
    (target / "notes.txt").write_text("also mine\n")
    real_rename = os.rename

    def rename(src, dst):
        if str(src).endswith("stuck.txt"):
            raise OSError(13, "Permission denied")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", rename)
    code, out = run(env)
    assert code == 0
    kept = conf / "scripts" / "dashline.kept"
    assert (
        "note: couldn't move stuck.txt into the new copy (Permission denied); "
        "it's in ~/.claude/scripts/dashline.kept" in out
    )
    assert sorted(p.name for p in kept.iterdir()) == ["stuck.txt"]
    assert (target / "notes.txt").read_text() == "also mine\n"
    assert (target / "dashline" / "layout.py").read_text(encoding="utf-8") != "# old\n"


def test_failed_swap_moves_the_users_files_back(conf, env, monkeypatch, capsys):
    target = stale_install(env, conf)
    (target / "notes.txt").write_text("mine\n")
    real_rename = os.rename

    def rename(src, dst):
        if ".new-" in str(src) and str(dst) == str(target):
            raise OSError(28, "No space left on device")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", rename)
    code, _ = run(env)
    assert code == 1
    assert (target / "notes.txt").read_text() == "mine\n"
    assert (target / "dashline" / "layout.py").read_text() == "# old\n"
    assert sorted(p.name for p in target.parent.iterdir()) == ["dashline"]


def test_ctrl_c_before_the_swap_moves_the_users_files_back(conf, env, monkeypatch):
    target = stale_install(env, conf)
    (target / "notes.txt").write_text("mine\n")
    real_rename = os.rename

    def rename(src, dst):
        if ".old-" in str(dst):
            raise KeyboardInterrupt
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", rename)
    with pytest.raises(KeyboardInterrupt):
        install.run(None, env=env, out=io.StringIO(), cwd="/", windows=False)
    assert (target / "notes.txt").read_text() == "mine\n"
    assert sorted(p.name for p in target.parent.iterdir()) == ["dashline"]


def test_users_files_that_cant_go_back_are_kept(conf, env, monkeypatch, capsys):
    target = stale_install(env, conf)
    (target / "notes.txt").write_text("mine\n")
    real_rename = os.rename

    def rename(src, dst):
        if ".new-" in str(src) and str(dst) == str(target):
            raise OSError(28, "No space left on device")
        if ".new-" in str(src) and str(src).endswith("notes.txt"):
            raise OSError(5, "Input/output error")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", rename)
    assert run(env)[0] == 1
    kept = conf / "scripts" / "dashline.kept"
    assert (kept / "notes.txt").read_text() == "mine\n"


# ---- the Windows entry ----


def test_windows_command_names_the_copy_in_forward_slashes(env, isolated_home):
    cmd = install.windows_command({"HOME": "C:\\Users\\Pat Lee"}, "py -3")
    assert cmd == 'py -3 -I -S "C:/Users/Pat Lee/.claude/scripts/dashline/statusline.py"'


def test_windows_python_takes_the_first_that_runs_3_9(monkeypatch):
    found = {"py": None, "python": "C:/py/python.exe", "python3": "C:/apps/python3.exe"}
    ran = []

    def run(argv, **kwargs):
        ran.append(argv)
        ok = argv[0] == "C:/apps/python3.exe"  # python.exe here is too old
        return subprocess.CompletedProcess(argv, 0, "True\n" if ok else "False\n", "")

    assert install.windows_python(found.get, run) == "python3"
    assert ran[0][:4] == ["C:/py/python.exe", "-I", "-S", "-c"]

    def store_stub(argv, **kwargs):  # the Store's python3.exe with no Python installed
        return subprocess.CompletedProcess(argv, 9009, "", "")

    assert install.windows_python(found.get, store_stub) is None

    def broken(argv, **kwargs):
        raise OSError("not a program")

    assert install.windows_python(found.get, broken) is None
    py = {"py": "C:/Windows/py.exe"}
    seen = []

    def launcher(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "True\n", "")

    assert install.windows_python(py.get, launcher) == "py -3"
    assert seen[0][:2] == ["C:/Windows/py.exe", "-3"]


def test_windows_install_writes_a_command_both_shells_run(conf, env):
    out = io.StringIO()
    code = install.run("nerd", env=env, out=out, cwd="/", windows=True, python=pythons("python"))
    assert code == 0, out.getvalue()
    cmd = settings(conf)["statusLine"]["command"]
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    assert cmd == f'python -I -S "{target}" --glyphs nerd'
    assert install.is_ours(settings(conf)["statusLine"], env)
    # An update keeps it while its Python runs, and changing the glyph set edits only
    # the flag.
    assert win(env, "ascii")[0] == 0
    assert settings(conf)["statusLine"]["command"] == f'python -I -S "{target}" --glyphs ascii'


def test_windows_install_without_python_changes_nothing(conf, env, capsys):
    code = install.run(None, env=env, out=io.StringIO(), cwd="/", windows=True, python=pythons())
    assert code == 1
    assert "no Python 3.9 or newer runs as py -3, python or python3" in capsys.readouterr().err
    assert not (conf / "settings.json").exists()
    assert not (conf / "scripts").exists()


def pythons(*working):
    """A stand-in for install.windows_python where `working` are the names that run."""

    def find(names=install.WINDOWS_PYTHONS):
        return next((name for name in names if name in working), None)

    return find


def win(env, glyphs=None, replace=False, python=None):
    """install.run as on Windows, with `python` finding the Pythons that run (python)."""
    python = python or pythons("python")
    out = io.StringIO()
    code = install.run(
        glyphs, replace=replace, env=env, out=out, cwd="/", windows=True, python=python
    )
    return code, out.getvalue()


def no_python(names=None):
    raise AssertionError("no Python is looked for here")


def test_windows_install_rewrites_the_old_bash_only_command(conf, env):
    """The command an older dashline wrote is Bash only: PowerShell can't run it. On
    Windows install rewrites it, with its glyph set and the rest of the entry kept."""
    write_settings(
        conf,
        {"statusLine": {"type": "command", "command": f"{ENTRY_CMD} --glyphs nerd", "padding": 1}},
    )
    code, out = win(env)
    assert code == 0, out
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    assert settings(conf)["statusLine"] == {
        "type": "command",
        "command": f'python -I -S "{target}" --glyphs nerd',
        "padding": 1,
        "refreshInterval": 60,
    }
    assert "PowerShell can't run it" in out
    # Asked for another set at the same time: the new command has that one.
    write_settings(conf, {"statusLine": {"type": "command", "command": ENTRY_CMD}})
    assert win(env, "ascii")[0] == 0
    assert settings(conf)["statusLine"]["command"] == f'python -I -S "{target}" --glyphs ascii'
    # Off Windows the same entry is the standard one, and stays.
    write_settings(conf, {"statusLine": {"type": "command", "command": ENTRY_CMD}})
    assert run(env)[0] == 0
    assert settings(conf)["statusLine"]["command"] == ENTRY_CMD


@pytest.mark.parametrize(
    ("cmd", "old"),
    [
        (ENTRY_CMD, True),
        (f"{ENTRY_CMD} --glyphs nerd", True),
        # Which Python runs it is what a Windows user had to change: still the old one.
        (ENTRY_CMD.replace("python3", "python", 1), True),
        (ENTRY_CMD.replace("python3", "py -3.13", 1), True),
        (ENTRY_CMD.replace("python3", "py -3", 1), True),
        (ENTRY_CMD.replace("python3", '"C:/Program Files/Python313/python.exe"', 1), True),
        (ENTRY_CMD.replace("python3", "C:\\Python39\\python.exe", 1), True),
        (f'{ENTRY_CMD} --glyphs "nerd"', True),  # quoted by hand
        (f"{ENTRY_CMD} --glyphs='ascii'", True),
        # Anything else is an edit of the user's own.
        (ENTRY_CMD.replace("python3", "python -X utf8", 1), False),
        (ENTRY_CMD.replace("python3", "env python3", 1), False),
        (ENTRY_CMD.replace("python3", "bash", 1), False),
        (f"{ENTRY_CMD} 2>/dev/null", False),
        (ENTRY_CMD.replace("$HOME/.claude", "$HOME/dots/claude"), False),
        ('py -3 -I -S "C:/Users/pat/.claude/scripts/dashline/statusline.py"', False),
    ],
)
def test_old_form(cmd, old):
    assert install.old_form({"type": "command", "command": cmd}) is old


def test_windows_install_keeps_a_command_edited_by_hand(conf, env):
    """Only the old command (any Python) is rewritten: other edits are kept as written,
    unless --replace says to use dashline's own."""
    mine = f"{ENTRY_CMD} 2>/dev/null"
    write_settings(conf, {"statusLine": {"type": "command", "command": mine}})
    code, out = win(env)
    assert code == 0, out
    assert settings(conf)["statusLine"]["command"] == mine
    code, out = win(env, replace=True, python=pythons("py -3"))
    assert code == 0, out
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    assert settings(conf)["statusLine"]["command"] == f'py -3 -I -S "{target}"'
    assert "used shell variables" in out


def test_windows_edited_command_is_kept_unless_replace(conf, env):
    """A full path to Python is the user's edit: kept, even when that Python is gone
    (doctor says so), until --replace writes dashline's own command."""
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    mine = f'"C:/Py/python.exe" -I -S "{target}" --glyphs nerd'
    write_settings(conf, {"statusLine": {"type": "command", "command": mine}})
    code, out = win(env, python=no_python)
    assert code == 0, out
    assert settings(conf)["statusLine"]["command"] == mine
    code, out = win(env, replace=True)
    assert code == 0, out
    assert settings(conf)["statusLine"]["command"] == f'python -I -S "{target}" --glyphs nerd'
    assert "note: --replace wrote dashline's own command in place of the edited one" in out


def test_windows_install_rewrites_an_old_command_with_another_python(conf, env):
    old = ENTRY_CMD.replace("python3", "python", 1) + " --glyphs nerd"
    write_settings(conf, {"statusLine": {"type": "command", "command": old}})
    code, out = win(env, python=pythons("py -3"))
    assert code == 0, out
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    assert settings(conf)["statusLine"]["command"] == f'py -3 -I -S "{target}" --glyphs nerd'


def test_windows_newer_copy_stops_before_looking_for_python(conf, env):
    """Exit 4 (a newer copy) comes first: no Python is looked for, nor missed."""
    write_settings(conf, {"statusLine": {"type": "command", "command": ENTRY_CMD}})
    assert run(env)[0] == 0
    (conf / "scripts" / "dashline" / "VERSION").write_text("99.0.0\n")
    assert win(env, python=no_python)[0] == install.NEEDS_DOWNGRADE


def test_windows_install_without_python_keeps_the_old_command(conf, env, capsys):
    write_settings(conf, {"statusLine": {"type": "command", "command": ENTRY_CMD}})
    before = (conf / "settings.json").read_text()
    assert win(env, python=pythons())[0] == 1
    assert "no Python 3.9 or newer" in capsys.readouterr().err
    assert (conf / "settings.json").read_text() == before


def test_windows_replace_writes_the_windows_command(conf, env):
    write_settings(conf, {"statusLine": {"type": "command", "command": "bash ~/my-status.sh"}})
    assert win(env, python=no_python)[0] == install.NEEDS_REPLACE  # asks first, no Python
    code, out = win(env, "nerd", replace=True)
    assert code == 0, out
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    assert settings(conf)["statusLine"]["command"] == f'python -I -S "{target}" --glyphs nerd'


def test_windows_replace_of_their_folder_writes_the_windows_command(conf, env):
    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('mine')\n")
    write_settings(conf, {"statusLine": {"type": "command", "command": f"{ENTRY_CMD} -x"}})
    assert win(env, python=no_python)[0] == install.NEEDS_REPLACE
    assert not (conf / "settings.json").read_text().count("python -I")
    write_settings(conf, {})
    assert win(env, python=no_python)[0] == install.NEEDS_REPLACE  # a new entry, but asks
    code, out = win(env, replace=True)
    assert code == 0, out
    assert settings(conf)["statusLine"]["command"].startswith('python -I -S "')


def test_windows_install_refuses_a_path_both_shells_expand(conf, isolated_home, capsys):
    env = env_for(isolated_home, CLAUDE_CONFIG_DIR=str(isolated_home / "c$fg"))
    assert win(env)[0] == 1
    assert "has a $ or `" in capsys.readouterr().err
    assert not (isolated_home / "c$fg").exists()


def test_windows_entry_is_ours_whatever_the_case(conf, isolated_home, monkeypatch):
    """C:\\Cfg and c:\\cfg are one folder on Windows."""
    env = env_for(isolated_home, CLAUDE_CONFIG_DIR="C:\\Cfg")
    entry = {"type": "command", "command": 'py -3 -I -S "c:/cfg/scripts/dashline/statusline.py"'}
    monkeypatch.setattr(host, "WINDOWS", False)
    assert not install.runs_install_dir(entry, env)
    monkeypatch.setattr(host, "WINDOWS", True)
    assert install.runs_install_dir(entry, env)


def test_windows_python_gives_up_on_a_hung_probe():
    def hangs(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    assert install.windows_python({"python": "C:/py/python.exe"}.get, hangs) is None


def test_settings_keep_lf_line_endings(conf, env):
    assert run(env)[0] == 0
    assert b"\r\n" not in (conf / "settings.json").read_bytes()
    assert (conf / "scripts" / "dashline" / "VERSION").read_bytes() == f"{__version__}\n".encode()


def test_settings_write_waits_for_a_file_held_open_on_windows(conf, env, monkeypatch):
    """Claude Code or an antivirus scan can hold settings.json open for a moment."""
    calls = held_once(monkeypatch, "replace", lambda src, dst: dst.endswith("settings.json"))
    assert run(env)[0] == 0
    assert len(calls) == 2
    assert settings(conf)["statusLine"]["command"] == ENTRY_CMD


@pytest.mark.parametrize("held", ["the old copy", "the new copy"])
def test_folder_swap_waits_for_a_held_folder_on_windows(conf, env, monkeypatch, held):
    """A scan of the new copy, or a render importing the old one, holds its folder for
    a moment: the swap tries again."""
    assert run(env)[0] == 0  # an old copy to swap out
    (conf / "scripts" / "dashline" / "VERSION").write_text("0.0.1\n")
    old = held == "the old copy"
    calls = held_once(
        monkeypatch,
        "rename",
        lambda src, dst: (".old-" in dst) if old else (".new-" in src),
    )
    code, out = run(env)
    assert code == 0, out
    assert len(calls) == 2
    assert (conf / "scripts" / "dashline" / "VERSION").read_text() == f"{__version__}\n"


def test_folder_check_on_windows_makes_a_file(tmp_path, monkeypatch):
    """os.access ignores a folder's permissions on Windows: a file is made instead."""
    monkeypatch.setattr(host, "WINDOWS", True)
    folder = tmp_path / "folder"
    folder.mkdir()
    assert host.can_write_in(str(folder))
    assert list(folder.iterdir()) == []
    assert not host.can_write_in(str(folder / "missing"))


def test_messages_spell_out_the_path_when_git_bash_has_another_home(monkeypatch, tmp_path):
    """On a domain Git Bash's HOME can be H:\\, so `~/.claude` pasted there is wrong."""
    profile = str(tmp_path / "pat")
    path = str(tmp_path / "pat" / ".claude" / "settings.json")
    monkeypatch.setattr(host, "WINDOWS", True)
    assert install.home_short(path, {"USERPROFILE": profile}) == "~/.claude/settings.json"
    same = {"USERPROFILE": profile, "HOME": profile + os.sep}
    assert install.home_short(path, same) == "~/.claude/settings.json"
    other = {"USERPROFILE": profile, "HOME": str(tmp_path / "H")}
    assert install.home_short(path, other) == Path(path).as_posix()


# ---- found in the third review ----


def test_replace_waits_for_a_held_folder_on_windows(conf, env, monkeypatch):
    """Moving another tool's folder aside tries again while a file in it is open."""
    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('mine')\n")
    write_settings(conf, {"statusLine": {"type": "command", "command": "echo theirs"}})
    calls = held_once(monkeypatch, "rename", lambda src, dst: str(dst).endswith(".backup"))
    code, out = run(env, replace=True)
    assert code == 0, out
    assert len(calls) == 2
    backup = conf / "scripts" / "dashline.backup"
    assert (backup / "statusline.py").read_text() == "print('mine')\n"


def test_failed_replace_put_back_waits_for_a_held_folder_on_windows(conf, env, monkeypatch):
    """After a failed --replace, the other tool's folder goes back even if it's held."""
    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "statusline.py").write_text("print('mine')\n")
    write_settings(conf, {"statusLine": {"type": "command", "command": "echo theirs"}})
    monkeypatch.setattr(install, "copy", lambda env: (_ for _ in ()).throw(OSError(28, "full")))
    calls = held_once(monkeypatch, "rename", lambda src, dst: str(src).endswith(".backup"))
    code, out = run(env, replace=True)
    assert code == 1
    assert len(calls) == 2
    assert "moved the files in ~/.claude/scripts/dashline.backup back" in out
    assert (other / "statusline.py").read_text() == "print('mine')\n"


def test_a_folder_that_cant_be_kept_is_a_note_not_a_failure(conf, env, monkeypatch):
    """The new copy is in place when the old folder, holding a file of the user's that
    wouldn't move, can't be renamed dashline.kept: the install still succeeds, the
    note says where the file is, and the next install keeps it."""
    target = stale_install(env, conf)
    (target / "stuck.txt").write_text("mine\n")
    real_rename = os.rename

    def rename(src, dst):
        if str(src).endswith("stuck.txt") or str(dst).endswith("dashline.kept"):
            raise OSError(13, "Permission denied")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", rename)
    code, out = run(env)
    assert code == 0, out
    assert f"updated dashline {__version__}" in out
    assert f"it's in ~/.claude/scripts/dashline.old-{os.getpid()}" in out
    assert settings(conf)["statusLine"]["command"] == ENTRY_CMD
    monkeypatch.setattr(os, "rename", real_rename)
    monkeypatch.setattr(install, "_alive", lambda pid: False)
    monkeypatch.setattr(os, "getpid", lambda: 1)  # the next install is another process
    (target / "VERSION").write_text("0.0.1\n")
    assert run(env)[0] == 0
    kept = conf / "scripts" / "dashline.kept"
    assert sorted(p.name for p in kept.iterdir()) == ["stuck.txt"]
    assert not list((conf / "scripts").glob("dashline.old-*"))


def test_leftover_with_the_users_files_is_kept(conf, monkeypatch):
    """An install stopped while moving the user's files: they're kept, dashline's not."""
    monkeypatch.setattr(install, "_alive", lambda pid: False)
    scripts = conf / "scripts"
    old = scripts / "dashline.old-11"
    (old / "dashline").mkdir(parents=True)
    (old / "VERSION").write_text("0.1.0\n")
    (old / "notes.txt").write_text("mine\n")
    kept = scripts / "dashline.kept"
    removed = install.clean_leftovers(str(scripts), NOW_REAL)
    assert removed == (["dashline.old-11"], [str(kept)])
    assert sorted(p.name for p in kept.iterdir()) == ["notes.txt"]


def test_windows_replace_with_glyphs_rebuilds_a_wrapped_command(conf, env):
    """--replace rewrites a dashline command with variables on Windows, so --glyphs at
    the same time goes into the new command instead of failing on the old one."""
    wrapped = f"bash -lc '{ENTRY_CMD}'"
    write_settings(conf, {"statusLine": {"type": "command", "command": wrapped}})
    code, out = win(env, "nerd", replace=True)
    assert code == 0, out
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    assert settings(conf)["statusLine"]["command"] == f'python -I -S "{target}" --glyphs nerd'
    assert "used shell variables" in out
    # Without --replace it's the user's edit: the glyph change is refused, as before.
    write_settings(conf, {"statusLine": {"type": "command", "command": wrapped}})
    assert win(env, "nerd")[0] == 1


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="POSIX permissions")
def test_windows_checks_settings_are_writable_before_looking_for_python(conf, env, capsys):
    """Looking for Python can take seconds (and open the Store): not for nothing."""
    write_settings(conf, {"theme": "dark"})
    (conf / "settings.json").chmod(0o444)
    try:
        code, _ = win(env, python=no_python)
        assert code == 1
        assert "read-only" in capsys.readouterr().err
    finally:
        (conf / "settings.json").chmod(0o644)


def test_windows_refuses_a_backtick_in_the_install_path(isolated_home, capsys):
    conf = isolated_home / "cl`aude"
    conf.mkdir()
    env = env_for(isolated_home, CLAUDE_CONFIG_DIR=str(conf))
    code, _ = win(env)
    assert code == 1
    assert "has a $ or `" in capsys.readouterr().err
    assert not (conf / "scripts").exists()


@posix_only
def test_link_into_a_missing_folder_is_refused(conf, env, tmp_path, capsys):
    (conf / "scripts").mkdir()
    (conf / "scripts" / "dashline").symlink_to(tmp_path / "gone" / "dashline")
    code, _ = run(env)
    assert code == 1
    assert "whose folder doesn't exist" in capsys.readouterr().err


def test_settings_that_are_a_folder_are_refused(conf, env, capsys):
    (conf / "settings.json").mkdir()
    code, _ = run(env)
    assert code == 1
    assert "can't read" in capsys.readouterr().err
    assert not (conf / "scripts").exists()


@pytest.mark.parametrize(
    "entry",
    ["python3 x.py", ["a"], 3, {"type": "command"}, {"type": "command", "command": None}],
)
def test_statusline_of_another_shape_is_someone_elses(conf, env, entry):
    write_settings(conf, {"statusLine": entry})
    code, out = run(env)
    assert code == install.NEEDS_REPLACE
    assert "runs something else" in out
    assert settings(conf)["statusLine"] == entry
    assert run(env, replace=True)[0] == 0
    assert settings(conf)["statusLine"]["command"] == ENTRY_CMD


def test_null_statusline_counts_as_none(conf, env):
    write_settings(conf, {"statusLine": None})
    assert run(env)[0] == 0
    assert settings(conf)["statusLine"]["command"] == ENTRY_CMD


# ---- found in the fourth review ----


def test_settings_changed_while_installing_are_kept(conf, env, monkeypatch):
    """Claude Code (or the user) writes settings.json while install copies: the entry
    goes into what's there then, not over it."""
    write_settings(conf, {"model": "opus"})
    real_copy = install.copy

    def copy_while_someone_writes(env):
        result = real_copy(env)
        write_settings(conf, {"model": "sonnet", "permissions": {"allow": ["Bash(ls)"]}})
        return result

    monkeypatch.setattr(install, "copy", copy_while_someone_writes)
    code, out = run(env)
    assert code == 0, out
    data = settings(conf)
    assert data["model"] == "sonnet"
    assert data["permissions"] == {"allow": ["Bash(ls)"]}
    assert data["statusLine"]["command"] == ENTRY_CMD


def test_statusline_changed_while_installing_is_left_alone(conf, env, monkeypatch, capsys):
    real_copy = install.copy

    def copy_while_someone_writes(env):
        result = real_copy(env)
        write_settings(conf, {"statusLine": {"type": "command", "command": "echo mine"}})
        return result

    monkeypatch.setattr(install, "copy", copy_while_someone_writes)
    code, _ = run(env)
    assert code == 1
    assert "statusLine changed while installing" in capsys.readouterr().err
    assert settings(conf)["statusLine"]["command"] == "echo mine"


def test_an_earlier_install_with_this_pid_keeps_the_users_files(conf, env):
    """An install killed while moving the user's files left them in .new-PID; a later
    install that gets the same pid keeps them instead of clearing the folder."""
    stale_install(env, conf)
    new = conf / "scripts" / f"dashline.new-{os.getpid()}"
    (new / "dashline").mkdir(parents=True)
    (new / "notes.txt").write_text("mine\n")
    code, out = run(env)
    assert code == 0, out
    kept = conf / "scripts" / "dashline.kept"
    assert (kept / "notes.txt").read_text() == "mine\n"
    assert "note: files from an interrupted install are in ~/.claude/scripts/dashline.kept" in out
    assert not new.exists()


def test_leftover_with_the_users_files_gets_a_note(conf, env, monkeypatch):
    run(env)
    monkeypatch.setattr(install, "_alive", lambda pid: False)
    old = conf / "scripts" / "dashline.old-11"
    (old / "dashline").mkdir(parents=True)
    (old / "notes.txt").write_text("mine\n")
    code, out = run(env)  # nothing to update: the note comes all the same
    assert code == 0, out
    assert "already has dashline" in out
    assert "note: files from an interrupted install are in ~/.claude/scripts/dashline.kept" in out


@posix_only
def test_leftovers_beside_a_linked_folder_are_cleaned(conf, env, isolated_home, monkeypatch):
    """scripts/dashline links to a folder of another name: its leftovers have that
    name."""
    dots = isolated_home / "dots"
    dots.mkdir()
    (conf / "scripts").mkdir()
    (conf / "scripts" / "dashline").symlink_to(dots / "sl", target_is_directory=True)
    (dots / "sl").mkdir()
    monkeypatch.setattr(install, "_alive", lambda pid: False)
    for name in ("sl.new-4242", "sl.old-4243"):
        (dots / name / "dashline").mkdir(parents=True)
    assert run(env)[0] == 0
    assert sorted(p.name for p in dots.iterdir()) == ["sl"]


def test_a_linked_leftover_is_unlinked_not_emptied(conf, tmp_path, monkeypatch):
    monkeypatch.setattr(install, "_alive", lambda pid: False)
    scripts = conf / "scripts"
    scripts.mkdir()
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "dashline").mkdir(parents=True)
    (elsewhere / "notes.txt").write_text("mine\n")
    (scripts / "dashline.old-11").symlink_to(elsewhere, target_is_directory=True)
    assert install.clean_leftovers(str(scripts), NOW_REAL) == (["dashline.old-11"], [])
    assert (elsewhere / "dashline").is_dir()
    assert (elsewhere / "notes.txt").exists()


@pytest.mark.parametrize(
    ("cmd", "bash_only"),
    [
        ("python -I -S ~/.claude/scripts/dashline/statusline.py", True),
        ('python -I -S "C:/x/statusline.py" --out=~/x', True),
        ("python -I -S $HOME/.claude/scripts/dashline/statusline.py", True),
        ('python -I -S "C:/Users/pat/.claude/scripts/dashline/statusline.py"', False),
        ('python -I -S "C:/x~/statusline.py"', False),
    ],
)
def test_uses_variables(cmd, bash_only):
    assert install.uses_variables({"command": cmd}) is bash_only


def test_windows_replace_rewrites_a_tilde_path(conf, env):
    """PowerShell passes `~` to Python as it is: Bash only, like a $-variable."""
    mine = "python -I -S ~/.claude/scripts/dashline/statusline.py"
    write_settings(conf, {"statusLine": {"type": "command", "command": mine}})
    assert win(env, python=no_python)[0] == 0
    assert settings(conf)["statusLine"]["command"] == mine  # the user's edit
    code, out = win(env, replace=True)
    assert code == 0, out
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    assert settings(conf)["statusLine"]["command"] == f'python -I -S "{target}"'
    assert "used shell variables or ~" in out


def test_windows_form(env, conf):
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    form = install.windows_form
    assert form({"command": f'py -3 -I -S "{target}"'}, env) == "py -3"
    assert form({"command": f'python3 -I -S "{target}" --glyphs nerd'}, env) == "python3"
    assert form({"command": f'PYTHON -I -S "{target.upper()}"'}, env) == "python"
    assert form({"command": f'py -3 -I -S "{target}" 2>NUL'}, env) is None
    assert form({"command": f'"C:/Py/python.exe" -I -S "{target}"'}, env) is None
    assert form({"command": ENTRY_CMD}, env) is None
    assert form({"command": 3}, env) is None


def test_windows_command_whose_python_is_gone_is_rewritten(conf, env):
    """py is gone (a switch to the Store's Python, say): a plain install writes the
    command again with a Python that runs, glyph set kept."""
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    assert win(env, "nerd", python=pythons("py -3"))[0] == 0
    assert settings(conf)["statusLine"]["command"] == f'py -3 -I -S "{target}" --glyphs nerd'
    probed = []

    def only_python(names=install.WINDOWS_PYTHONS):
        probed.append(names)
        return pythons("python")(names)

    code, out = win(env, python=only_python)
    assert code == 0, out
    assert settings(conf)["statusLine"]["command"] == f'python -I -S "{target}" --glyphs nerd'
    assert "note: the statusLine command's Python (py -3) doesn't run here any more" in out
    assert probed[0] == ("py -3",)  # its own Python first
    # While it runs, only that one is asked, and the command stays.
    probed.clear()
    code, out = win(env, python=only_python)
    assert code == 0, out
    assert probed == [("python",)]
    assert "note:" not in out


def test_windows_command_whose_python_is_gone_with_none_left(conf, env, capsys):
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    write_settings(conf, {"statusLine": {"type": "command", "command": f'py -3 -I -S "{target}"'}})
    before = (conf / "settings.json").read_text()
    assert win(env, python=pythons())[0] == 1
    assert "no Python 3.9 or newer runs as py -3, python or python3" in capsys.readouterr().err
    assert (conf / "settings.json").read_text() == before


def test_windows_rewrite_keeps_an_unknown_glyph_set(conf, env):
    """The glyph step asks about `--glyphs Nerd`: a rewrite keeps it for that."""
    write_settings(
        conf, {"statusLine": {"type": "command", "command": f"{ENTRY_CMD} --glyphs Nerd"}}
    )
    code, out = win(env)
    assert code == 0, out
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    assert settings(conf)["statusLine"]["command"] == f'python -I -S "{target}" --glyphs Nerd'
    assert "--glyphs Nerd isn't a glyph set" in out


def test_windows_rewrite_drops_a_glyph_value_that_isnt_a_word(conf, env):
    """A value the command quoted (`'a;b'`) would be shell text unquoted."""
    write_settings(
        conf, {"statusLine": {"type": "command", "command": f"{ENTRY_CMD} --glyphs 'a;b'"}}
    )
    code, out = win(env, replace=True)
    assert code == 0, out
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    assert settings(conf)["statusLine"]["command"] == f'python -I -S "{target}"'


def test_windows_python_prefers_the_launcher(monkeypatch):
    """py -3 first (python.org's launcher, on PATH by default), then python."""
    found = {"py": "C:/Windows/py.exe", "python": "C:/py/python.exe"}

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "True\n", "")

    assert install.windows_python(found.get, run) == "py -3"
    assert install.WINDOWS_PYTHONS == ("py -3", "python", "python3")


# ---- found in the fifth review ----


def test_odd_leftover_names_dont_stop_an_install(conf, env, monkeypatch):
    """A number too long to be a pid is someone else's folder; one no process can have
    is no install's."""
    scripts = conf / "scripts"
    scripts.mkdir()
    (scripts / f"dashline.old-{'9' * 200}").mkdir()
    (scripts / "dashline.old-9999999999").mkdir()
    code, out = run(env)
    assert code == 0, out
    names = sorted(p.name for p in scripts.iterdir())
    assert f"dashline.old-{'9' * 200}" in names
    if os.name != "nt":  # there pids can't be asked: the folder's age decides
        assert "dashline.old-9999999999" not in names


def test_a_leftover_that_is_a_file_is_removed(conf, env, monkeypatch):
    monkeypatch.setattr(install, "_alive", lambda pid: False)
    scripts = conf / "scripts"
    scripts.mkdir()
    (scripts / "dashline.new-11").write_text("x")
    (scripts / f"dashline.new-{os.getpid()}").write_text("x")  # this install's pid
    code, out = run(env)
    assert code == 0, out
    assert sorted(p.name for p in scripts.iterdir()) == ["dashline"]


@posix_only
def test_install_from_a_deleted_folder(conf, env, tmp_path, monkeypatch):
    """The folder it was run from is gone: the install still succeeds, quietly."""
    gone = tmp_path / "gone"
    gone.mkdir()
    monkeypatch.chdir(gone)
    gone.rmdir()
    out = io.StringIO()
    assert install.run(None, env=env, out=out, windows=False) == 0, out.getvalue()


def test_replace_over_another_tools_folder_with_a_version_file(conf, env):
    """Its VERSION isn't dashline's: --replace backs the folder up, no exit 4."""
    other = conf / "scripts" / "dashline"
    other.mkdir(parents=True)
    (other / "VERSION").write_text("99.0\n")
    (other / "run.sh").write_text("echo theirs\n")
    code, out = run(env, replace=True)
    assert code == 0, out
    assert (conf / "scripts" / "dashline.backup" / "run.sh").exists()


def test_a_dead_python_is_asked_once(conf, env):
    target = (conf / "scripts" / "dashline" / "statusline.py").as_posix()
    write_settings(conf, {"statusLine": {"type": "command", "command": f'py -3 -I -S "{target}"'}})
    asked = []

    def find(names=install.WINDOWS_PYTHONS):
        asked.append(names)
        return pythons("python")(names)

    assert win(env, python=find)[0] == 0
    assert asked == [("py -3",), ("python", "python3")]


def test_as_installed(env):
    """The command install writes, with any --glyphs; an edited one isn't."""
    entry = {"command": install.command("nerd")}
    assert install.as_installed(entry, env, windows=False)
    assert not install.as_installed({"command": install.COMMAND + " --bogus"}, env, False)
    assert not install.as_installed({"command": None}, env, False)
    windows = install.windows_command(env, "py -3")
    assert install.as_installed({"command": windows + " --glyphs ascii"}, env, windows=True)
    assert not install.as_installed({"command": "C:/Python/python.exe" + windows[5:]}, env, True)


def test_pid_zero_is_never_alive():
    """os.kill(0, 0) asks about the caller's own process group: a `dashline.old-0`
    would look alive forever."""
    assert install._alive(0) is False
