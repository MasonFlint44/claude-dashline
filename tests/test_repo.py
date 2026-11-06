"""The directory row (repo.py), against throwaway git repos."""

import contextlib
import os
import subprocess
from pathlib import Path

import pytest

from conftest import make_ctx, plain
from dashline import repo

GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_AUTHOR_DATE": "2026-11-05T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-11-05T00:00:00Z",
    "GIT_ALLOW_PROTOCOL": "file",  # no test git command can reach the network
}


@pytest.fixture(autouse=True)
def git_env(monkeypatch, isolated_home):
    # None of the developer's git settings or locations reach the test repos: a global
    # config with commit.gpgsign, or the GIT_INDEX_FILE a pre-commit hook sets.
    for key in list(os.environ):
        if (key.startswith("GIT_") and key != "GIT_EXEC_PATH") or key == "XDG_CONFIG_HOME":
            monkeypatch.delenv(key)
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    (isolated_home / ".gitconfig").write_text(
        "[init]\n\tdefaultBranch = main\n[advice]\n\tdetachedHead = false\n"
    )


def git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=check
    ).stdout.strip()


def commit(cwd, name="f.txt", text="one\n", message="c"):
    path = cwd / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", message)


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "proj"
    path.mkdir()
    git(path, "init", "-q")
    commit(path)
    return path


@pytest.fixture
def cloned(tmp_path, project):
    """`project` pushed to a bare remote and cloned as `work`, tracking origin/main."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "-q", "--bare", str(project), str(remote))
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(remote), str(work))
    return work


def row(path, columns=120, glyph_set="unicode", current=None, color=False):
    state = repo.inspect(str(path), str(current or path), os.environ)
    ctx = make_ctx(columns, glyph_set, color=color)
    segments = repo.draw(state, ctx, os.environ["HOME"])
    return segments if color else plain([segments])[0]


# ---- states from the PLAN §5 table ----


def test_not_a_repo(tmp_path, isolated_home):
    notes = isolated_home / "Documents" / "notes"
    notes.mkdir(parents=True)
    assert row(notes) == "~/Documents/notes"
    assert row(notes, glyph_set="nerd") == "\U000f0770 ~/Documents/notes"
    assert row(tmp_path, columns=1000) == str(tmp_path)


def test_clean_main(project):
    assert row(project) == "proj  ⎇ main"
    assert row(project, glyph_set="nerd") == "\U000f02a2 proj  \U000f062c main"
    assert row(project, glyph_set="ascii") == "proj  (main)"


def test_uncommitted_counts(project):
    (project / "f.txt").write_text("one\ntwo\nthree\n")
    assert row(project) == "proj  ⎇ main  ✎ +2"
    (project / "f.txt").write_text("")
    assert row(project) == "proj  ⎇ main  ✎ −1"
    (project / "f.txt").write_text("uno\ndos\n")
    git(project, "add", "f.txt")
    assert row(project) == "proj  ⎇ main  ✎ +2 −1"
    assert row(project, glyph_set="ascii") == "proj  (main)  * +2 -1"


def test_untracked(project):
    (project / "new.txt").write_text("x\n")
    assert row(project) == "proj  ⎇ main  ?"
    (project / "f.txt").write_text("one\ntwo\n")
    assert row(project) == "proj  ⎇ main  ✎ +1 ?"


def test_dirty_binary_shows_the_pencil_only(project):
    (project / "b.bin").write_bytes(b"\0\1")
    git(project, "add", "b.bin")
    assert row(project) == "proj  ⎇ main  ✎"


def test_no_commits_yet(tmp_path):
    path = tmp_path / "fresh"
    path.mkdir()
    git(path, "init", "-q")
    assert row(path) == "fresh  ⎇ main"
    (path / "a.txt").write_text("a\nb\n")
    git(path, "add", "a.txt")
    assert row(path) == "fresh  ⎇ main  ✎ +2"


def test_ahead_behind_diverged(cloned, tmp_path):
    commit(cloned, "g.txt", "x\n")
    assert row(cloned) == "work  ⎇ main  ⇡1"
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(tmp_path / "remote.git"), str(other))
    commit(other, "h.txt", "y\n")
    commit(other, "i.txt", "z\n")
    git(other, "push", "-q")
    git(cloned, "fetch", "-q")
    assert row(cloned) == "work  ⎇ main  ⇡1 ⇣2"
    segs = row(cloned, color=True)
    ctx = make_ctx(color=True)
    assert [s[1] for s in segs if s[0] in ("⇡1", "⇣2")] == [ctx.p.sgr("error")] * 2
    git(cloned, "reset", "-q", "--hard", "origin/main~1")
    assert row(cloned) == "work  ⎇ main  ⇣1"
    segs = row(cloned, color=True)
    assert [s[1] for s in segs if s[0] == "⇣1"] == [ctx.p.sgr("warning")]


def test_never_pushed_only_with_a_remote(cloned, project):
    git(cloned, "switch", "-q", "-c", "feat")
    assert row(cloned) == "work  ⎇ feat  local"
    git(project, "switch", "-q", "-c", "feat")
    assert row(project) == "proj  ⎇ feat"  # no remote at all: nothing to push to


def test_upstream_gone(cloned):
    git(cloned, "switch", "-q", "-c", "feat")
    git(cloned, "push", "-q", "-u", "origin", "feat")
    assert row(cloned) == "work  ⎇ feat"
    git(cloned, "push", "-q", "origin", "--delete", "feat")
    git(cloned, "fetch", "-q", "--prune")
    assert row(cloned) == "work  ⎇ feat  gone"
    assert row(cloned, glyph_set="nerd").endswith("\U000f14cc")


def test_detached_and_tag(project):
    commit(project, "g.txt", "x\n")
    oid = git(project, "rev-parse", "HEAD~1")
    git(project, "checkout", "-q", oid)
    assert row(project) == f"proj  #{oid[:7]}"
    assert row(project, glyph_set="ascii") == f"proj  (#{oid[:7]})"
    segs = row(project, color=True)
    assert segs[-1][1] == make_ctx(color=True).p.sgr("warning")
    git(project, "tag", "v0.1.0")
    assert row(project) == "proj  tag:v0.1.0"
    assert row(project, glyph_set="ascii") == "proj  (tag:v0.1.0)"


def test_merge_conflict(project):
    git(project, "switch", "-q", "-c", "side")
    commit(project, text="side\n")
    git(project, "switch", "-q", "main")
    commit(project, text="main\n")
    git(project, "merge", "-q", "side", check=False)
    assert row(project) == "proj  ⎇ main  merging  ✗ 1  ✎ +4"  # the conflict markers
    nerd = row(project, glyph_set="nerd")
    assert "\U000f062d merging  \U000f0026 1" in nerd


def test_rebase_shows_branch_and_progress(project):
    git(project, "switch", "-q", "-c", "feat")
    commit(project, text="feat 1\n")
    commit(project, "g.txt", "feat 2\n")
    git(project, "switch", "-q", "main")
    commit(project, text="main\n")
    git(project, "switch", "-q", "feat")
    git(project, "rebase", "-q", "main", check=False)
    assert row(project) == "proj  ⎇ feat  rebasing 1/2  ✗ 1  ✎ +4"


def test_cherry_pick_revert_bisect(project):
    git(project, "switch", "-q", "-c", "side")
    commit(project, text="side\n")
    pick = git(project, "rev-parse", "HEAD")
    git(project, "switch", "-q", "main")
    commit(project, text="main\n")
    git(project, "cherry-pick", pick, check=False)
    assert "cherry-picking  ✗ 1" in row(project)
    git(project, "cherry-pick", "--abort")
    commit(project, text="again\n")
    git(project, "revert", "--no-edit", "HEAD~1", check=False)
    assert "reverting  ✗ 1" in row(project)
    git(project, "revert", "--abort")
    git(project, "bisect", "start")
    assert "bisecting" in row(project)


def test_applying_patches(project, tmp_path):
    git(project, "switch", "-q", "-c", "side")
    commit(project, text="side\n")
    patch = git(project, "format-patch", "-1", "-o", str(tmp_path / "patches"))
    git(project, "switch", "-q", "main")
    commit(project, text="main\n")
    git(project, "am", patch, check=False)
    assert "applying patches" in row(project)


def test_linked_worktree(project, tmp_path):
    wt = tmp_path / "wt-cache"
    git(project, "worktree", "add", "-q", "-b", "feat/cache", str(wt))
    (wt / "f.txt").write_text("one\ntwo\n")
    assert row(wt) == "proj ⑂ wt-cache  ⎇ feat/cache  ✎ +1"
    assert row(wt, glyph_set="ascii") == "proj [wt-cache]  (feat/cache)  * +1"
    assert row(wt, glyph_set="nerd").startswith("\U000f02a2 proj \U000f0645 wt-cache  ")


def test_project_below_the_root(project):
    sub = project / "services" / "api"
    sub.mkdir(parents=True)
    assert row(sub) == "proj/services/api  ⎇ main"


def test_cwd_drift(project, isolated_home):
    inside = project / "tests" / "fixtures"
    inside.mkdir(parents=True)
    assert row(project, current=inside) == "proj  ↳ tests/fixtures  ⎇ main"
    assert row(project, current=inside, glyph_set="ascii") == "proj  ./tests/fixtures  (main)"
    outside = isolated_home / "scratch" / "repro"
    outside.mkdir(parents=True)
    assert row(project, current=outside) == "proj  ↳ ~/scratch/repro  ⎇ main"
    assert row(project, current=outside, glyph_set="ascii") == "proj  ~/scratch/repro  (main)"


def test_sibling_dir_is_not_inside(project):
    """`/x/proj-old` starts with `/x/proj` but is not inside it."""
    sibling = project.parent / (project.name + "-old")
    sibling.mkdir()
    # Wide enough for macOS's long temp paths: drift is the first thing a narrow row drops.
    assert row(project, columns=400, current=sibling) == f"proj  ↳ {sibling}  ⎇ main"


def test_colors(project):
    (project / "f.txt").write_text("uno\ndos\n")
    segs = row(project, color=True)
    p = make_ctx(color=True).p
    by_text = {seg[0]: seg[1] for seg in segs}
    assert by_text["proj"] == p.sgr("text")
    assert by_text["⎇ main"] == p.sgr("text")
    assert by_text["✎"] == p.sgr("warning")
    assert by_text["+2"] == p.sgr("success")
    assert by_text["−1"] == p.sgr("error")


# ---- narrow terminals ----


@pytest.fixture
def busy(cloned, tmp_path):
    """A worktree on a long branch, dirty, untracked, ahead, with cwd drift."""
    wt = tmp_path / "wt-feature"
    git(cloned, "worktree", "add", "-q", "-b", "feature/a-very-long-branch-name", str(wt))
    git(wt, "push", "-q", "-u", "origin", "HEAD")
    commit(wt, "g.txt", "x\n")
    (wt / "f.txt").write_text("one\ntwo\nthree\n")
    (wt / "new.txt").write_text("n\n")
    (wt / "src").mkdir()
    return wt


def test_narrow_drop_order(busy):
    full = row(busy, current=busy / "src")
    assert full == "work ⑂ wt-feature  ↳ src  ⎇ feature/a-very-long-branch-name  ✎ +2 ?  ⇡1"
    w = len(full) + 4  # COLUMNS includes the 4-column reserve
    assert row(busy, w - 1, current=busy / "src") == (
        "work ⑂ wt-feature  ↳ src  ⎇ feature/a-very-long-branch-name  ✎ ?  ⇡1"
    )
    assert row(busy, w - 4, current=busy / "src") == (
        "work ⑂ wt-feature  ⎇ feature/a-very-long-branch-name  ✎ ?  ⇡1"
    )
    assert row(busy, w - 20, current=busy / "src") == (
        "work ⑂ wt-feature  ⎇ feature/a-very-long-…  ✎ ?  ⇡1"
    )
    # Past the worktree name, the branch gets back the room it frees.
    assert row(busy, 30, current=busy / "src") == "work  ⎇ feature/…  ✎ ?  ⇡1"
    assert row(busy, 26, current=busy / "src") == "work  ⎇ feat…  ✎ ?  ⇡1"


@pytest.mark.parametrize("glyph_set", ["nerd", "unicode", "ascii"])
def test_row_never_exceeds_the_width(busy, glyph_set):
    for columns in range(8, 120):
        text = row(busy, columns, glyph_set, current=busy / "src")
        assert len(text) <= columns - 4, (columns, text)


def test_sync_survives_narrowing(busy):
    assert row(busy, 34, current=busy / "src").endswith("⇡1")


# ---- failure modes ----


def test_no_git_binary(project, monkeypatch):
    monkeypatch.setenv("PATH", "")
    assert row(project) == "proj"


def test_slow_git_times_out(project, monkeypatch):
    monkeypatch.setattr(repo, "GIT_TIMEOUT", 0.0)
    real_start = repo._start

    def slow(args, cwd, env):
        return real_start(["-c", "alias.slow=!sleep 2", "slow"], cwd, env)

    monkeypatch.setattr(repo, "_start", slow)
    assert row(project) == "proj"


def test_missing_project_dir(tmp_path):
    assert row(tmp_path / "gone", columns=1000) == str(tmp_path / "gone")


def test_no_project_dir_no_row():
    assert repo.draw(None, make_ctx()) == []
    assert repo.draw(repo.RepoState(""), make_ctx()) == []


def test_parse_status_rename_and_conflict_records():
    state = repo.RepoState("/p")
    text = "\0".join(
        [
            "# branch.oid abc",
            "# branch.head main",
            "# branch.upstream origin/main",
            "# branch.ab +3 -0",
            "2 R. N... 100644 100644 100644 a b R100 new name",
            "old name",
            "u UU N... 100644 100644 100644 100644 a b c both.txt",
            "? untracked file",
            "",
        ]
    )
    repo.parse_status(text, state)
    assert (state.branch, state.upstream, state.ahead, state.behind) == (
        "main",
        "origin/main",
        3,
        0,
    )
    assert (state.dirty, state.conflicts, state.untracked) == (True, 1, True)


def test_parse_numstat():
    assert repo.parse_numstat("3\t1\ta.txt\n-\t-\tb.bin\n10\t0\tc d.txt\n") == (13, 1)
    assert repo.parse_numstat("") == (0, 0)


# ---- links ----


def links(segments):
    return {seg[0]: seg[2] for seg in segments if len(seg) > 2}


@pytest.mark.parametrize(
    ("url", "web"),
    [
        (
            "git@github.com:MasonFlint44/claude-dashline.git",
            "https://github.com/MasonFlint44/claude-dashline",
        ),
        ("https://github.com/o/r.git", "https://github.com/o/r"),
        ("https://github.com/o/r", "https://github.com/o/r"),
        ("https://user@github.com/o/r/", "https://github.com/o/r"),
        ("ssh://git@github.com:22/o/r.git", "https://github.com/o/r"),
        ("git@github.example.com:o/r.git", "https://github.example.com/o/r"),
        ("https://www.github.com/o/r", "https://github.com/o/r"),
        ("git@github-work:o/r.git", "https://github.com/o/r"),  # an ~/.ssh/config alias
        ("git@github.com-work:o/r.git", "https://github.com/o/r"),
        ("ssh://git@github-work/o/r", "https://github.com/o/r"),
        ("git@acme.ghe.com:o/r.git", "https://acme.ghe.com/o/r"),
        ("https://acme.ghe.com/o/r", "https://acme.ghe.com/o/r"),
        ("git@github-x.corp.example:o/r.git", None),  # a host, not an alias
        ("git@ghe.com:o/r.git", None),
        ("git@notgithub.com:o/r.git", None),
        ("git@gitlab.com:o/r.git", None),
        ("https://github.com/o", None),
        ("/srv/git/r.git", None),
    ],
)
def test_github_web(url, web):
    assert repo.github_web(url) == web


def test_parse_remotes():
    config = (
        '[core]\n\tbare = false\n[remote "origin"]\n\turl = git@github.com:o/r.git\n'
        '\tfetch = +refs/heads/*:refs/remotes/origin/*\n[remote "up/stream"]\n'
        '\tURL = https://github.com/u/r\n[branch "main"]\n\tremote = origin\n'
    )
    assert repo.parse_remotes(config) == {
        "origin": "git@github.com:o/r.git",
        "up/stream": "https://github.com/u/r",
    }


@pytest.mark.parametrize(
    "path", ["/a b/c", "/caf\u00e9/\u4e2d", "/x#y?z%w&v=u+t", "/~user/a_b.c-d", "/semi;colon:x"]
)
def test_quote_matches_urllib(path):
    from urllib.parse import quote

    assert repo.quote(path) == quote(path)


def test_folder_url_of_odd_paths():
    host = os.uname().nodename
    assert repo.folder_url("/tmp/caf\u00e9") == f"file://{host}/tmp/caf%C3%A9"
    assert repo.folder_url("/tmp/\udcff") == f"file://{host}/tmp/%FF"  # not UTF-8 on disk
    assert repo.folder_url("/tmp/\ud800") is None  # a lone surrogate from the JSON


def test_folder_url_under_wsl():
    # Windows Terminal opens only drive paths and WSL's share (\\wsl.localhost\<distro>).
    wsl = {"WSL_DISTRO_NAME": "Ubuntu-24.04"}
    url = "file://wsl.localhost/Ubuntu-24.04/home/pat/my%20proj"
    assert repo.folder_url("/home/pat/my proj", wsl) == url
    assert repo.folder_url("/tmp/\ud800", wsl) is None
    host = os.uname().nodename
    assert repo.folder_url("/tmp/x", {"WSL_DISTRO_NAME": ""}) == f"file://{host}/tmp/x"


def test_folder_link_under_wsl(project, monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Debian")
    assert links(row(project, color=True)) == {"proj": f"file://wsl.localhost/Debian{project}"}


def test_folder_link(project, isolated_home):
    host = os.uname().nodename
    assert links(row(project, color=True)) == {"proj": f"file://{host}{project}"}
    spaced = isolated_home / "my notes"
    spaced.mkdir()
    assert links(row(spaced, color=True)) == {
        "~/my notes": f"file://{host}{isolated_home}/my%20notes"
    }


def github_origin(path):
    git(path, "remote", "set-url", "origin", "git@github.com:o/r.git")


def test_branch_links_to_github(cloned):
    """origin really is a local bare repo (tests never touch the network); only its
    URL in the config says GitHub, which is all the link reads."""
    git(cloned, "switch", "-q", "-c", "feat/cache")
    github_origin(cloned)
    assert "⎇ feat/cache" not in links(row(cloned, color=True))  # not pushed yet
    git(cloned, "remote", "set-url", "origin", str(cloned.parent / "remote.git"))
    git(cloned, "push", "-q", "-u", "origin", "feat/cache")
    github_origin(cloned)
    assert links(row(cloned, color=True))["⎇ feat/cache"] == (
        "https://github.com/o/r/compare/main...feat/cache"
    )
    git(cloned, "switch", "-q", "main")
    assert links(row(cloned, color=True))["⎇ main"] == "https://github.com/o/r/tree/main"


def test_branch_link_needs_github(cloned):
    assert "⎇ main" not in links(row(cloned, color=True))  # origin is a local path


def test_links_survive_truncation_and_render(cloned, monkeypatch):
    github_origin(cloned)
    from dashline import layout

    line = layout.to_str(repo.draw(repo.inspect(str(cloned), None, os.environ), make_ctx(12)))
    assert "\x1b]8;;https://github.com/o/r/tree/main\x1b\\" in line
    assert line.count("\x1b]8;;\x1b\\") == 2  # each link is closed


def test_inspect_never_raises(project, monkeypatch, capsys):
    def boom(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(repo, "parse_status", boom)
    assert row(project) == "proj"
    assert "RuntimeError: boom" in capsys.readouterr().err


def test_worktree_of_a_bare_repo(tmp_path, project):
    bare = tmp_path / "tool.git"
    git(tmp_path, "clone", "-q", "--bare", str(project), str(bare))
    wt = tmp_path / "wt-x"
    git(bare, "worktree", "add", "-q", str(wt), "main")
    assert row(wt) == "tool ⑂ wt-x  ⎇ main  local"  # the clone has origin, no upstream


# ---- hardening (0.1.6) ----


def test_hung_hook_is_killed_with_git(project, monkeypatch, tmp_path):
    """A hook that outlives git used to hold the pipe open and the render with it."""
    monkeypatch.setattr(repo, "GIT_TIMEOUT", 0.2)
    pidfile = tmp_path / "pid"
    real_start = repo._start

    def hung(args, cwd, env):
        alias = f"alias.hang=!echo $$ > {pidfile}; exec sleep 30"
        return real_start(["-c", alias, "hang"], cwd, env)

    monkeypatch.setattr(repo, "_start", hung)
    import time

    began = time.monotonic()
    assert row(project) == "proj"
    assert time.monotonic() - began < 1.5
    pid = int(pidfile.read_text())
    for _ in range(300):  # killed, and reaped once its parent is gone (slow under load)
        if not process_alive(pid):
            break
        time.sleep(0.01)
    else:
        if "sleep" in process_info(pid)[1]:
            with contextlib.suppress(OSError):
                os.kill(pid, 9)  # only our hook, never a reused pid
        raise AssertionError("the hook's sleep outlived the timeout")


def process_info(pid) -> tuple:
    """(state letter, command) for a process: from /proc on Linux, `ps` elsewhere.
    ("", "") once it is gone."""
    proc = Path(f"/proc/{pid}")
    if Path("/proc/self/stat").exists():
        try:
            state = proc.joinpath("stat").read_text().rsplit(") ", 1)[1][:1]
            return state, proc.joinpath("cmdline").read_bytes().decode(errors="replace")
        except (OSError, IndexError):
            return "", ""
    out = subprocess.run(
        ["ps", "-o", "stat=", "-o", "command=", "-p", str(pid)], capture_output=True, text=True
    ).stdout.strip()
    state, _, command = out.partition(" ")
    return state[:1], command


def process_alive(pid) -> bool:
    """Running, as opposed to gone or a zombie (dead, waiting to be reaped)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False  # another user's process: the pid was reused, so ours is gone
    state, _ = process_info(pid)
    return state not in ("", "Z")


def test_kill_survives_a_pipe_held_open(monkeypatch):
    """When something outside the group holds the pipe, give up instead of waiting."""
    import subprocess
    import time

    proc = subprocess.Popen(
        ["sh", "-c", "sleep 30"], stdout=subprocess.PIPE, start_new_session=True
    )
    monkeypatch.setattr(repo, "_kill", lambda p: None)  # pretend the kill missed
    began = time.monotonic()
    assert repo._finish(proc, time.monotonic()) is None
    assert time.monotonic() - began < 1
    proc.kill()
    proc.wait()


def test_names_cannot_inject_escapes():
    state = repo.RepoState("/x/pro\x1b[31mj\nnext", "/elsewhere/\x1b]8;;evil\x07")
    state.root = "/x/root"
    state.repo_name = "re\x1bpo"
    state.worktree = "wt\n2"
    state.branch = "feat\u202eevil"
    text = plain([repo.draw(state, make_ctx(200))])[0]
    assert "\x1b" not in text and "\n" not in text and "\u202e" not in text
    assert text.startswith("re?po ⑂ wt?2  ↳ /elsewhere/?]8;;evil?  ⎇ feat?evil")
    folder = repo.RepoState("/x/a\x1bb")
    assert plain([repo.draw(folder, make_ctx())]) == ["/x/a?b"]
    tagged = repo.RepoState("/x")
    tagged.root, tagged.repo_name, tagged.tag = "/x", "x", "v1\x1b"
    assert plain([repo.draw(tagged, make_ctx())]) == ["x  tag:v1?"]


def test_folder_with_control_characters(tmp_path):
    path = tmp_path / "a\x1bb\nc"
    path.mkdir()
    git(path, "init", "-q")
    assert row(path) == "a?b?c  ⎇ main"


def test_links_never_carry_control_characters():
    ctx = make_ctx()
    assert repo._link(ctx.seg("x"), "https://github.com/o/r\x1b\\") == ctx.seg("x")
    assert repo._link(ctx.seg("x"), "file://hôst/x") == ctx.seg("x")
    assert repo._link(ctx.seg("x"), "https://github.com/o/r") == (
        *ctx.seg("x"),
        "https://github.com/o/r",
    )


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:o/r\x1b]8;;https://evil\x1b\\.git",
        "https://github.com/o/r q",
        "https://github.com/o\x07/r",
        "git@github.co\x1bm:o/r.git",
    ],
)
def test_github_web_rejects_odd_names(url):
    assert repo.github_web(url) is None


def test_parse_config_syntax():
    config = (
        "# a comment\n"
        '[Remote "origin"]\n'
        '\tURL = "git@github.com:o/r.git" ; inline comment\n'
        "\turl = git@github.com:o/second.git\n"
        '[remote "fork"] url = https://github.com/f/r # same line as the header\n'
        "[remote.Old]\n"
        "\turl = https://github.com/old/\\\n"
        "r.git\n"
        '[remote "quoted \\"name\\""]\n'
        "\turl = https://github.com/q/r\n"
        '[remote "empty"]\n'
        "\turl\n"
        '[branch "feat"]\n\tremote = origin\n\tmerge = refs/heads/feat\n'
    )
    assert repo.parse_remotes(config) == {
        "origin": "git@github.com:o/r.git",
        "fork": "https://github.com/f/r",
        "old": "https://github.com/old/r.git",
        'quoted "name"': "https://github.com/q/r",
    }
    entries = repo.parse_config(config)
    assert ("branch", "feat", "merge", "refs/heads/feat") in entries


def test_rebase_of_a_pushed_branch_is_not_local(cloned):
    git(cloned, "switch", "-q", "-c", "feat")
    commit(cloned, text="feat\n")
    git(cloned, "push", "-q", "-u", "origin", "feat")
    git(cloned, "switch", "-q", "main")
    commit(cloned, text="main\n")
    git(cloned, "switch", "-q", "feat")
    git(cloned, "rebase", "-q", "main", check=False)
    assert row(cloned) == "work  ⎇ feat  rebasing 1/1  ✗ 1  ✎ +4"
    github_origin(cloned)
    assert links(row(cloned, color=True))["⎇ feat"] == (
        "https://github.com/o/r/compare/main...feat"
    )
    git(cloned, "update-ref", "-d", "refs/remotes/origin/feat")
    assert row(cloned).endswith("✎ +4  gone")


def test_rebase_of_a_local_branch_is_still_local(cloned):
    git(cloned, "switch", "-q", "-c", "feat")
    commit(cloned, text="feat\n")
    git(cloned, "switch", "-q", "main")
    commit(cloned, text="main\n")
    git(cloned, "switch", "-q", "feat")
    git(cloned, "rebase", "-q", "main", check=False)
    assert row(cloned).endswith("✎ +4  local")


def test_configured_upstream_packed_and_local(tmp_path):
    common = tmp_path / "git"
    (common / "refs" / "heads").mkdir(parents=True)
    (common / "packed-refs").write_text("# pack-refs\nabc refs/remotes/up/feat\n")
    entries = repo.parse_config(
        '[branch "feat"]\n remote = up\n merge = refs/heads/feat\n'
        '[branch "loc"]\n remote = .\n merge = refs/heads/main\n'
        '[branch "odd"]\n remote = up\n merge = feat\n'
    )
    assert repo.configured_upstream(entries, "feat", str(common)) == ("up/feat", False)
    assert repo.configured_upstream(entries, "loc", str(common)) == ("main", True)
    (common / "refs" / "heads" / "main").write_text("abc\n")
    assert repo.configured_upstream(entries, "loc", str(common)) == ("main", False)
    assert repo.configured_upstream(entries, "odd", str(common)) == (None, False)
    assert repo.configured_upstream(entries, "none", str(common)) == (None, False)


def test_git_location_variables_are_ignored(project, tmp_path):
    env = dict(os.environ)
    env.update(
        GIT_INDEX_FILE=str(tmp_path / "other-index"),
        GIT_DIR=str(tmp_path / "nowhere"),
        GIT_OBJECT_DIRECTORY=str(tmp_path / "objects"),
        GIT_COMMON_DIR=str(tmp_path / "common"),
    )
    state = repo.inspect(str(project), str(project), env)
    assert plain([repo.draw(state, make_ctx())]) == ["proj  ⎇ main"]


def test_symlink_into_a_repo(project, tmp_path):
    sub = project / "services" / "api"
    sub.mkdir(parents=True)
    link = tmp_path / "api-link"
    link.symlink_to(sub)
    assert row(link) == "proj/services/api  ⎇ main"


def test_symlinked_project_has_no_false_drift(project, tmp_path):
    link = tmp_path / "proj-link"
    link.symlink_to(project)
    assert row(link, current=project) == "proj  ⎇ main"
    (project / "src").mkdir()
    assert row(link, current=project / "src") == "proj  ↳ src  ⎇ main"
    assert row(project, current=link) == "proj  ⎇ main"


def test_fsmonitor_hook_never_runs(project, tmp_path):
    marker = tmp_path / "ran"
    hook = tmp_path / "hook.sh"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    git(project, "config", "core.fsmonitor", str(hook))
    git(project, "status", check=False)
    assert marker.exists()  # git would run it
    marker.unlink()
    assert row(project) == "proj  ⎇ main"
    assert not marker.exists()


def test_submodule_edits_are_its_own(project, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    git(lib, "init", "-q")
    commit(lib, "l.txt", "l\n")
    git(project, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(lib), "lib")
    git(project, "commit", "-q", "-m", "add lib")
    (project / "lib" / "l.txt").write_text("edited\n")
    (project / "lib" / "new.txt").write_text("n\n")
    assert row(project) == "proj  ⎇ main"
    commit(project / "lib", "l.txt", "moved on\n")  # a new commit is a change here
    assert row(project) == "proj  ⎇ main  ✎ +1 −1"


def test_no_commits_yet_in_a_sha256_repo(tmp_path):
    path = tmp_path / "fresh"
    path.mkdir()
    git(path, "init", "-q", "--object-format=sha256")
    (path / "a.txt").write_text("a\nb\n")
    git(path, "add", "a.txt")
    assert row(path) == "fresh  ⎇ main  ✎ +2"


@pytest.mark.parametrize(
    ("path", "home", "shown"),
    [
        ("/home/me/x", "/home/me", "~/x"),
        ("/home/me/x", "/home/me/", "~/x"),
        ("/home/me", "/home/me/", "~"),
        ("/home/meow", "/home/me", "/home/meow"),
        ("/etc/x", "/", "/etc/x"),
        ("/etc/x", "", "/etc/x"),
        ("/etc/x", None, "/etc/x"),
    ],
)
def test_collapse_home(path, home, shown):
    assert repo.collapse_home(path, home) == shown


def test_interrupted_pick_sequence(project):
    git(project, "switch", "-q", "-c", "side")
    commit(project, text="side\n")
    commit(project, "g.txt", "g\n")
    git(project, "switch", "-q", "main")
    commit(project, text="main\n")
    git(project, "cherry-pick", "side~1", "side", check=False)
    git(project, "checkout", "--theirs", "f.txt")
    git(project, "add", "f.txt")
    git(project, "commit", "-q", "--no-edit")  # resolved, but the sequence waits
    assert not (project / ".git" / "CHERRY_PICK_HEAD").exists()
    assert row(project) == "proj  ⎇ main  cherry-picking"
    git(project, "cherry-pick", "--quit")
    assert row(project) == "proj  ⎇ main"


def test_interrupted_revert_sequence(project):
    commit(project, text="two\n")
    commit(project, text="three\n")
    git(project, "revert", "--no-edit", "HEAD~1", "HEAD", check=False)  # stops at once
    (project / "f.txt").write_text("one\n")
    git(project, "add", "f.txt")
    git(project, "commit", "-q", "--no-edit")
    assert not (project / ".git" / "REVERT_HEAD").exists()
    assert row(project) == "proj  ⎇ main  reverting"


def test_long_subpath_gives_way(project):
    sub = project / "services" / "billing-and-invoicing" / "api"
    sub.mkdir(parents=True)
    git(project, "switch", "-q", "-c", "feature/long-branch-name")
    full = row(sub)
    assert full == "proj/services/billing-and-invoicing/api  ⎇ feature/long-branch-name"
    # The branch shortens first; when it can't, the subpath keeps its last folder, and
    # the branch gets the room that frees. Then the subpath goes.
    assert row(sub, 46) == "proj/…/api  ⎇ feature/long-branch-name"
    assert row(sub, 29) == "proj/…/api  ⎇ feature/lo…"
    assert row(sub, 23) == "proj/…/api  ⎇ feat…"
    assert row(sub, 22) == "proj  ⎇ feature/l…"
    assert row(sub, 17) == "proj  ⎇ feat…"


def test_long_tag_shortens(project):
    commit(project, "g.txt", "x\n")
    git(project, "checkout", "-q", "--detach")
    git(project, "tag", "release-2026-11-05-candidate")
    assert row(project, 32) == "proj  tag:release-2026-11-0…"


def test_tag_lookup_is_skipped_after_the_timeout(project, monkeypatch):
    """Once git has used up its time, the tag lookup isn't started."""
    git(project, "checkout", "-q", "--detach")
    calls = []
    real_start = repo._start

    def counting(args, cwd, env):
        calls.append(args[0])
        return real_start(args, cwd, env)

    monkeypatch.setattr(repo, "_start", counting)
    import time

    real_monotonic = time.monotonic

    def clock():
        # After status and numstat start, jump past the deadline.
        return real_monotonic() + (10 if len(calls) >= 2 else 0)

    monkeypatch.setattr(time, "monotonic", clock)
    row(project)
    assert "describe" not in calls


def test_wide_branch_names_shorten_by_columns(project):
    from dashline.text import cols

    git(project, "checkout", "-q", "-b", "功能/很长的分支名称用于测试")
    for columns in (60, 40, 30, 24):
        line = row(project, columns)
        assert cols(line) <= columns - 4, (columns, line)
    assert "…" in row(project, 30)


# ---- insteadOf shorthands ----


@pytest.mark.parametrize(
    ("url", "expanded"),
    [
        ("gh:o/r", "https://github.com/o/r"),
        ("gh:o/r.git", "https://github.com/o/r.git"),
        ("ghs:o/r", "git@github.com:o/r"),  # the longest matching prefix wins
        ("https://example.com/x", "https://example.com/x"),
    ],
)
def test_rewrite_url(url, expanded):
    rules = [("gh:", "https://github.com/"), ("ghs:", "git@github.com:"), ("g", "nope:")]
    assert repo.rewrite_url(url, rules) == expanded


def test_url_rewrites_from_config():
    entries = repo.parse_config(
        '[url "https://github.com/"]\n\tinsteadOf = gh:\n\tpushInsteadOf = ghp:\n'
        '[URL "git@github.com:"]\n\tInsteadOf = ghs:\n'
    )
    assert repo.url_rewrites(entries) == [
        ("gh:", "https://github.com/"),
        ("ghs:", "git@github.com:"),
    ]


def test_config_files(tmp_path):
    home = str(tmp_path)
    assert repo.config_files({"HOME": home}) == [
        "/etc/gitconfig",
        f"{home}/.config/git/config",
        f"{home}/.gitconfig",
    ]
    assert repo.config_files(
        {"HOME": home, "GIT_CONFIG_NOSYSTEM": "1", "XDG_CONFIG_HOME": "/x"}
    ) == ["/x/git/config", f"{home}/.gitconfig"]
    assert repo.config_files({"GIT_CONFIG_GLOBAL": "/g", "GIT_CONFIG_SYSTEM": "/s"}) == [
        "/s",
        "/g",
    ]


@pytest.mark.parametrize("where", ["global", "repo"])
def test_shorthand_remote_links_to_github(cloned, isolated_home, where):
    rule = '[url "git@github.com:"]\n\tinsteadOf = gh:\n'
    if where == "global":
        with (isolated_home / ".gitconfig").open("a") as f:
            f.write(rule)
    else:
        with (cloned / ".git" / "config").open("a") as f:
            f.write(rule)
    # Git itself must not see the shorthand while the test pushes to the local remote.
    git(cloned, "remote", "set-url", "origin", "gh:o/r")
    assert links(row(cloned, color=True))["⎇ main"] == "https://github.com/o/r/tree/main"


# ---- 0.1.7 ----


def test_rebase_of_a_detached_head_is_not_local(cloned):
    """No branch, nothing to push: a remote alone doesn't make the commit `local`."""
    commit(cloned, text="main\n")
    git(cloned, "switch", "-q", "--detach", "HEAD~1")
    commit(cloned, text="detached\n")
    git(cloned, "rebase", "-q", "main", check=False)
    shown = row(cloned)
    assert "rebasing 1/1" in shown
    assert shown.endswith("✎ +4")


def git_version() -> tuple:
    out = git(".", "--version").split()[2]
    return tuple(int(p) for p in out.split(".")[:2] if p.isdigit())


needs_reftable = pytest.mark.skipif(git_version() < (2, 45), reason="reftable needs git 2.45")


@pytest.fixture
def reftable(tmp_path, project):
    """Like `cloned`, with the clone's refs in the reftable format."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "-q", "--bare", str(project), str(remote))
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", "--ref-format=reftable", str(remote), str(work))
    assert (work / ".git" / "reftable").is_dir()
    return work


@needs_reftable
def test_reftable_branch_links_to_compare(reftable):
    git(reftable, "switch", "-q", "-c", "feat")
    git(reftable, "push", "-q", "-u", "origin", "feat")
    github_origin(reftable)
    assert links(row(reftable, color=True))["⎇ feat"] == (
        "https://github.com/o/r/compare/main...feat"
    )


@needs_reftable
def test_reftable_rebase_sees_a_gone_upstream(reftable):
    git(reftable, "switch", "-q", "-c", "feat")
    commit(reftable, text="feat\n")
    git(reftable, "push", "-q", "-u", "origin", "feat")
    git(reftable, "switch", "-q", "main")
    commit(reftable, text="main\n")
    git(reftable, "switch", "-q", "feat")
    git(reftable, "rebase", "-q", "main", check=False)
    assert row(reftable) == "work  ⎇ feat  rebasing 1/1  ✗ 1  ✎ +4"
    git(reftable, "update-ref", "-d", "refs/remotes/origin/feat")
    assert row(reftable).endswith("✎ +4  gone")


def test_ref_checks_under_reftable_without_git(tmp_path):
    common = tmp_path / "git"
    (common / "reftable").mkdir(parents=True)
    # No answer from git: assume the ref is there, and no default branch.
    assert repo._ref_exists(str(common), "refs/remotes/o/x")
    assert repo._ref_exists(str(common), "refs/remotes/o/x", lambda args: None)
    assert not repo._ref_exists(str(common), "refs/remotes/o/x", lambda args: "refs/x/y\n")
    assert repo._default_branch(str(common), "o") is None
    head = "refs/remotes/o/trunk\n"
    assert repo._default_branch(str(common), "o", lambda args: head) == "trunk"


def test_ceiling_directories_stop_the_walk(project, monkeypatch, tmp_path):
    sub = project / "sub"
    sub.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", f"relative/dir{os.pathsep}{project}")
    assert row(sub, columns=1000) == str(sub)  # the repo is above the ceiling
    assert row(project) == "proj  ⎇ main"  # a walk may start in a ceiling


def test_ceiling_dirs_resolve_symlinks_until_an_empty_entry(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    value = os.pathsep.join(["rel", str(link), "", str(link) + "/"])
    assert repo.ceiling_dirs({"GIT_CEILING_DIRECTORIES": value}) == [
        os.path.realpath(real),
        str(link),
    ]
    assert repo.ceiling_dirs({}) == []


@pytest.mark.parametrize("value", ["1", "true", "Yes", "on", "2"])
def test_config_nosystem_set(value):
    assert "/etc/gitconfig" not in repo.config_files({"GIT_CONFIG_NOSYSTEM": value})


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_config_nosystem_unset(value):
    assert "/etc/gitconfig" in repo.config_files({"GIT_CONFIG_NOSYSTEM": value})


def test_parse_config_escapes_and_bad_headers():
    config = (
        '[core]\n\tx = "a\\tb\\n\\"c\\\\" d\\\n'
        "e ; comment\n"
        '[remote "origin"]\n\turl = a\n'
        "[bad header\n\turl = b\n"
        '[remote "next"]\n\turl = c\n'
    )
    entries = repo.parse_config(config)
    assert ("core", None, "x", 'a\tb\n"c\\ de') in entries
    assert repo.parse_remotes(entries) == {"origin": "a", "next": "c"}


def test_kill_falls_back_without_process_groups(monkeypatch):
    killed = []

    class Proc:
        pid = 12345

        def kill(self):
            killed.append(True)
            raise ProcessLookupError  # already gone: not an error

    def no_group(pid, sig):
        raise PermissionError

    monkeypatch.setattr(os, "killpg", no_group)
    repo._kill(Proc())
    monkeypatch.delattr(os, "killpg")  # Windows has none
    repo._kill(Proc())
    assert killed == [True, True]


def test_parse_status_ignores_a_malformed_ahead_behind():
    state = repo.RepoState("/p")
    repo.parse_status("# branch.ab +x -1\0# branch.ab +1\0", state)
    assert (state.ahead, state.behind) == (0, 0)
    repo.parse_status("# branch.ab +3 -2\0", state)
    assert (state.ahead, state.behind) == (3, 2)


def test_repo_name_fallbacks():
    assert repo._repo_name("/srv/x/.git", "/w/a") == "x"
    assert repo._repo_name("/srv/tool.git", "/w/a") == "tool"
    assert repo._repo_name("/srv/tool", "/w/a") == "tool"  # a bare repo without .git
    assert repo._repo_name("/srv/tool/", "/w/a") == "a"


# ---- hosts, discovery and old git (third review) ----


@pytest.mark.parametrize(
    ("url", "web"),
    [
        # scp form without a user (`User git` in ~/.ssh/config)
        ("github-work:o/r.git", "https://github.com/o/r"),
        ("github.com:o/r.git", "https://github.com/o/r"),
        # SSH over port 443, and other aliases under github.com
        ("ssh://git@ssh.github.com:443/o/r.git", "https://github.com/o/r"),
        ("git@ssh.github.com:o/r.git", "https://github.com/o/r"),
        ("git@work.github.com:o/r.git", "https://github.com/o/r"),
        # an alias has no dot after its dash: this is some other host
        ("git@github.com-mirror.corp.example:o/r.git", None),
        # a wiki clone has no branch pages
        ("git@github.com:o/r.wiki.git", None),
        ("https://github.com/o/r.wiki", None),
        # gists and other paths that aren't owner/repo
        ("https://gist.github.com/abc123.git", None),
        # not scp form: a Windows path, a relative path, other URL schemes
        ("C:/src/o/r", None),
        ("c:o/r", None),
        ("./github.com:o/r", None),
        ("file:///srv/o/r.git", None),
    ],
)
def test_github_web_hosts(url, web):
    assert repo.github_web(url) == web


def test_an_empty_dot_git_is_passed_over(project):
    """A half-deleted clone's empty `.git` isn't a repo; git keeps walking up."""
    inner = project / "inner"
    (inner / ".git").mkdir(parents=True)
    found = repo.find_git(str(inner))
    assert found and os.path.realpath(found[0]) == os.path.realpath(project)
    head_only = project / "head-only" / ".git"
    head_only.mkdir(parents=True)
    (head_only / "HEAD").write_text("ref: refs/heads/main\n")
    found = repo.find_git(str(head_only.parent))
    assert found and os.path.realpath(found[0]) == os.path.realpath(project)


def test_a_dot_git_file_to_nowhere_ends_the_search(project):
    """git stops with "not a git repository" there; so does the row."""
    sub = project / "sub"
    sub.mkdir()
    (sub / ".git").write_text("gitdir: /nonexistent/x\n")
    assert repo.find_git(str(sub)) is None


@pytest.fixture
def mounted(project, monkeypatch):
    """`project` on a filesystem of its own, as if `sub` were mounted under it."""
    real_stat = os.stat
    top = os.path.realpath(project)

    def stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if isinstance(path, (str, os.PathLike)) and os.path.realpath(path) == top:
            fields = list(result[:10])
            fields[2] += 1  # st_dev
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(os, "stat", stat)
    sub = project / "sub"
    sub.mkdir()
    return sub


def test_the_search_stops_at_a_mount_point(mounted, project, monkeypatch):
    assert repo.find_git(str(mounted)) is None
    found = repo.find_git(str(mounted), across_filesystems=True)
    assert found and os.path.realpath(found[0]) == os.path.realpath(project)
    assert row(mounted, columns=1000) == str(mounted)
    monkeypatch.setenv("GIT_DISCOVERY_ACROSS_FILESYSTEM", "true")
    assert row(mounted).startswith("proj")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("", False),
        (" 0 ", False),
        ("false", False),
        ("No", False),
        ("off", False),
        ("0x0", False),
        ("00", False),
        ("-0", False),
        ("0k", False),
        ("1", True),
        ("2", True),
        ("true", True),
        ("yes", True),
        ("on", True),
        ("0x10", True),
        ("010", True),
        ("+1", True),
        ("1k", True),
        # git stops with "bad boolean" on these; they read as set, and never raise
        ("--1", True),
        ("1_0", True),
        ("0x", True),
        ("08", True),
        ("junk", True),
        ("\u0661", True),  # a non-ASCII digit
    ],
)
def test_env_bool(value, expected):
    assert repo._env_bool(value) is expected


def test_odd_git_config_nosystem_is_quiet(cloned, monkeypatch, capsys):
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "--1")
    assert row(cloned).startswith("work")
    assert "Traceback" not in capsys.readouterr().err


def test_git_before_2_15_shows_the_folder_alone(project, monkeypatch, tmp_path):
    """Old git refuses --no-optional-locks (exit 129) and so never locks the index."""
    import shutil

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "git"
    fake.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do\n'
        '  [ "$a" = --no-optional-locks ] && { echo "unknown option" >&2; exit 129; }\n'
        "done\n"
        f'exec "{shutil.which("git")}" "$@"\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert row(project) == "proj"


def test_run_git_within_the_deadline(project, monkeypatch):
    import time

    env = dict(os.environ)
    later = time.monotonic() + 5
    assert repo._run_git(["rev-parse", "--abbrev-ref", "HEAD"], str(project), env, later)
    assert repo._run_git(["status"], str(project), env, time.monotonic() - 1) is None

    def no_git(*args):
        raise OSError("no git")

    monkeypatch.setattr(repo, "_start", no_git)
    assert repo._run_git(["status"], str(project), env, later) is None


def test_branch_url_of_a_name_that_cannot_be_encoded(tmp_path):
    state = repo.RepoState(str(tmp_path))
    state.branch = "x"
    remotes = {"origin": "git@github.com:o/r.git"}
    state.upstream = "origin/feat"
    assert repo.branch_url(state, remotes, str(tmp_path)) == "https://github.com/o/r/tree/feat"
    state.upstream = "origin/\ud800"  # a lone surrogate from a broken name
    assert repo.branch_url(state, remotes, str(tmp_path)) is None
