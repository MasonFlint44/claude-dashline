"""host: where Windows differs, and what the render may read."""

import os

import pytest

from conftest import posix_only
from dashline import host, repo, theme


def test_program_off_windows_is_the_name(monkeypatch):
    monkeypatch.setattr(host, "WINDOWS", False)
    assert host.program("git") == "git"


def test_program_on_windows_never_comes_from_the_current_folder(tmp_path, monkeypatch):
    """Windows looks in the current folder (the project) before PATH: a cloned repo's
    own git.exe would run on every render. Only PATH's absolute folders count."""
    monkeypatch.setattr(host, "WINDOWS", True)
    project, tools = tmp_path / "proj", tmp_path / "tools"
    project.mkdir()
    tools.mkdir()
    (project / "git.exe").write_text("")
    monkeypatch.chdir(project)
    env = {
        "PATH": os.pathsep.join([".", "", str(tools)]),
        "PATHEXT": ".com;.exe",
    }  # lower: this runs on case-sensitive disks too
    with pytest.raises(FileNotFoundError):
        host.program("git", env)
    assert host.which("git", env) is None
    (tools / "git.exe").write_text("")
    env["PATH"] += os.pathsep  # a new PATH: not the cached answer
    assert host.program("git", env) == str(tools / "git.exe")
    # Names in any case, as os.environ has them on Windows.
    assert host.which("git", {"Path": str(tools), "PATHEXT": ".exe"}) == str(tools / "git.exe")


def test_git_runs_by_its_full_path_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "WINDOWS", True)
    started = []

    class Popen:
        def __init__(self, argv, **kwargs):
            started.append(argv)

    monkeypatch.setattr("subprocess.Popen", Popen)
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "git.exe").write_text("")
    repo._start(["status"], str(tmp_path), {"PATH": str(tools), "PATHEXT": ".exe"})
    assert started[0][0] == str(tools / "git.exe")
    with pytest.raises(FileNotFoundError):  # the render shows the folder alone
        repo._start(["status"], str(tmp_path), {"PATH": str(tmp_path / "none")})


@posix_only
@pytest.mark.parametrize("kind", ["fifo", "device", "big"])
def test_render_reads_no_pipe_device_or_huge_file(tmp_path, monkeypatch, kind):
    """A repo's .claude/settings.json can be a link to anything: a pipe would block the
    render forever, /dev/zero would never end."""
    path = tmp_path / "settings.json"
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "device":
        path.symlink_to("/dev/zero")
    else:
        monkeypatch.setattr(theme, "MAX_JSON", 10)
        monkeypatch.setattr(repo, "MAX_GIT_FILE", 10)
        path.write_text('{"theme": "light", "x": 1}')
    assert theme._read_json(str(path)) == {}
    assert repo._read(str(path)) is None


def test_plain_file(tmp_path):
    small = tmp_path / "a"
    small.write_text("{}")
    assert host.plain_file(str(small), 10)
    assert not host.plain_file(str(small), 1)
    assert not host.plain_file(str(tmp_path), 10)  # a folder
    assert not host.plain_file(str(tmp_path / "gone"), 10)
    assert not host.plain_file("a\x00b", 10)
