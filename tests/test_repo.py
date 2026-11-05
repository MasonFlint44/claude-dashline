"""The directory row (repo.py), against throwaway git repos."""

import os
import subprocess

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
    assert row(tmp_path) == str(tmp_path)


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
    assert row(project, current=sibling) == f"proj  ↳ {sibling}  ⎇ main"


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
    assert row(busy, 30, current=busy / "src") == "work  ⎇ feat…  ✎ ?  ⇡1"


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
    assert row(tmp_path / "gone") == str(tmp_path / "gone")


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
