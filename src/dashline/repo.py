"""Line 3, the directory row: project, branch and git state as icons (PLAN §5, option C).

`inspect` reads the repo: a Python walk for `.git`, then `git status --porcelain=v2`
and `git diff --numstat HEAD` run side by side, plus `.git` files for an operation in
progress. `draw` turns that into segments fitted to the width. Hide what's normal: a
clean, pushed branch shows the project and branch only.

Links (OSC 8, chosen 11/4): the project opens its folder (`file://host/path`); a pushed
branch on GitHub opens its compare page against the default branch, or the branch page
when it is the default.
"""

from __future__ import annotations

import os
import re

GIT_TIMEOUT = 1.0  # seconds; a slower repo shows the project without git state
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
GAP = "  "
OPERATIONS = {
    "rebase": "rebasing",
    "merge": "merging",
    "cherry_pick": "cherry-picking",
    "revert": "reverting",
    "bisect": "bisecting",
    "am": "applying patches",
}
MIN_BRANCH = 4  # a branch name never truncates below this many characters plus `…`
# git@github.com:o/r.git, ssh://git@github.com/o/r, https://github.com/o/r.git
GITHUB = re.compile(
    r"^(?:(?:ssh|https?|git)://(?:[^@/]+@)?(?P<h1>[^/:]+)(?::\d+)?/|[^@/]+@(?P<h2>[^/:]+):)"
    r"(?P<path>[^/]+/[^/]+?)(?:\.git)?/?$"
)


class RepoState:
    """What the row shows. `git` is False outside a repo (or when git failed)."""

    def __init__(self, project_dir: str, current_dir: str | None = None):
        self.project_dir = project_dir
        self.current_dir = current_dir
        self.git = False
        self.root = None  # this worktree's top level
        self.repo_name = None  # the main worktree's folder name
        self.worktree = None  # a linked worktree's folder name
        self.branch = None
        self.oid = None
        self.tag = None
        self.upstream = None
        self.upstream_gone = False
        self.has_remote = False
        self.ahead = self.behind = 0
        self.dirty = False
        self.added = self.removed = 0
        self.untracked = False
        self.conflicts = 0
        self.operation = None  # a key of OPERATIONS
        self.progress = None  # "3/7"
        self.folder_url = None
        self.branch_url = None


# ---- finding the repo (no git process) ----


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def find_git(start: str) -> tuple | None:
    """(top level, git dir, common dir) for the repo holding `start`, or None."""
    path = os.path.abspath(start)
    while True:
        dot_git = os.path.join(path, ".git")
        if os.path.isdir(dot_git):
            git_dir = dot_git
            break
        if os.path.isfile(dot_git):
            text = (_read(dot_git) or "").strip()
            if not text.startswith("gitdir:"):
                return None
            git_dir = os.path.normpath(os.path.join(path, text[len("gitdir:") :].strip()))
            break
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    common = (_read(os.path.join(git_dir, "commondir")) or "").strip()
    common_dir = os.path.normpath(os.path.join(git_dir, common)) if common else git_dir
    return path, git_dir, common_dir


def parse_remotes(config: str) -> dict:
    """`[remote "name"] url = …` sections of a git config → {name: url}."""
    remotes, current = {}, None
    for raw in config.splitlines():
        line = raw.strip()
        if line.startswith("["):
            m = re.match(r'^\[remote\s+"(.+)"\]', line)
            current = m.group(1) if m else None
        elif current and current not in remotes:
            key, _, value = line.partition("=")
            if key.strip().lower() == "url" and value.strip():
                remotes[current] = value.strip()
    return remotes


def github_web(url: str) -> str | None:
    """A GitHub remote URL → `https://github.com/owner/repo`; None for other hosts."""
    m = GITHUB.match(url.strip())
    if not m:
        return None
    host = (m.group("h1") or m.group("h2")).lower()
    if host != "github.com" and not host.startswith("github."):
        return None
    return f"https://{host}/{m.group('path')}"


def _default_branch(common_dir: str, remote: str) -> str | None:
    """The remote's default branch, from `refs/remotes/<remote>/HEAD` (set by clone)."""
    text = (_read(os.path.join(common_dir, "refs", "remotes", remote, "HEAD")) or "").strip()
    prefix = f"ref: refs/remotes/{remote}/"
    return text[len(prefix) :] if text.startswith(prefix) else None


def folder_url(path: str) -> str:
    from urllib.parse import quote

    host = os.uname().nodename if hasattr(os, "uname") else ""
    path = path.replace(os.sep, "/")
    if not path.startswith("/"):
        path = "/" + path  # C:/x on Windows
    return f"file://{host}{quote(path)}"


def branch_url(state: RepoState, remotes: dict, common_dir: str) -> str | None:
    """Compare page for a pushed branch on GitHub; the branch page for the default."""
    from urllib.parse import quote

    if not state.branch or not state.upstream or state.upstream_gone:
        return None
    remote = max((r for r in remotes if state.upstream.startswith(r + "/")), key=len, default=None)
    web = github_web(remotes[remote]) if remote else None
    if not web:
        return None
    branch = state.upstream[len(remote) + 1 :]
    default = _default_branch(common_dir, remote)
    if default is None or default == branch:
        return f"{web}/tree/{quote(branch)}"
    return f"{web}/compare/{quote(default)}...{quote(branch)}"


def operation(git_dir: str) -> tuple:
    """(operation, progress) from the files git leaves while one runs."""

    def exists(*parts):
        return os.path.exists(os.path.join(git_dir, *parts))

    def number(*parts):
        text = (_read(os.path.join(git_dir, *parts)) or "").strip()
        return text if text.isdigit() else None

    def progress(done, total):
        return f"{done}/{total}" if done and total else None

    if exists("rebase-merge"):
        return "rebase", progress(number("rebase-merge", "msgnum"), number("rebase-merge", "end"))
    if exists("rebase-apply"):
        step = progress(number("rebase-apply", "next"), number("rebase-apply", "last"))
        return ("am" if exists("rebase-apply", "applying") else "rebase"), step
    if exists("MERGE_HEAD"):
        return "merge", None
    if exists("CHERRY_PICK_HEAD"):
        return "cherry_pick", None
    if exists("REVERT_HEAD"):
        return "revert", None
    if exists("BISECT_LOG"):
        return "bisect", None
    return None, None


def _rebase_branch(git_dir: str) -> str | None:
    """The branch being rebased (HEAD is detached while a rebase runs)."""
    for sub in ("rebase-merge", "rebase-apply"):
        head = (_read(os.path.join(git_dir, sub, "head-name")) or "").strip()
        if head.startswith("refs/heads/"):
            return head[len("refs/heads/") :]
    return None


# ---- git ----


def _git_env(env) -> dict:
    out = dict(env)
    out.update(GIT_OPTIONAL_LOCKS="0", LC_ALL="C", GIT_TERMINAL_PROMPT="0")
    out.pop("GIT_DIR", None)
    out.pop("GIT_WORK_TREE", None)
    return out


def _start(args: list, cwd: str, env: dict):
    import subprocess

    return subprocess.Popen(
        ["git", "--no-optional-locks", *args],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def _finish(proc, deadline: float) -> str | None:
    import subprocess
    import time

    try:
        out, _ = proc.communicate(timeout=max(0.01, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return None
    return out.decode("utf-8", "replace") if proc.returncode == 0 else None


def parse_status(text: str, state: RepoState) -> None:
    """`git status --porcelain=v2 --branch -z` → branch, upstream, ahead/behind, files."""
    fields = text.split("\0")
    i = 0
    while i < len(fields):
        field = fields[i]
        i += 1
        if field.startswith("# branch.oid "):
            oid = field[len("# branch.oid ") :]
            state.oid = None if oid == "(initial)" else oid
        elif field.startswith("# branch.head "):
            head = field[len("# branch.head ") :]
            state.branch = None if head == "(detached)" else head
        elif field.startswith("# branch.upstream "):
            state.upstream = field[len("# branch.upstream ") :]
        elif field.startswith("# branch.ab "):
            parts = field.split()
            if len(parts) == 4:
                state.ahead, state.behind = abs(int(parts[2])), abs(int(parts[3]))
        elif field.startswith(("1 ", "2 ")):
            state.dirty = True
            if field.startswith("2 "):
                i += 1  # a rename carries its original path as the next field
        elif field.startswith("u "):
            state.dirty = True
            state.conflicts += 1
        elif field.startswith("? "):
            state.untracked = True


def parse_numstat(text: str) -> tuple:
    """`git diff --numstat` → (added, removed); binary files count as nothing."""
    added = removed = 0
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            added += int(parts[0])
            removed += int(parts[1])
    return added, removed


def inspect(project_dir: str, current_dir: str | None, env) -> RepoState:
    """Read the project's repo. Never raises; any trouble means fewer details."""
    state = RepoState(project_dir, current_dir)
    try:
        _inspect(state, env)
    except Exception:
        import sys
        import traceback

        traceback.print_exc(file=sys.stderr)
    return state


def _repo_name(common_dir: str, root: str) -> str:
    """The main checkout's folder name, or a bare repo's name without `.git`."""
    base = os.path.basename(common_dir)
    if base == ".git":
        return os.path.basename(os.path.dirname(common_dir))
    if base.endswith(".git") and len(base) > 4:
        return base[:-4]
    return base or os.path.basename(root)


def _inspect(state: RepoState, env) -> None:
    import time

    project_dir = state.project_dir
    if not os.path.isdir(project_dir):
        return
    state.folder_url = folder_url(os.path.abspath(project_dir))
    found = find_git(project_dir)
    if not found:
        return
    root, git_dir, common_dir = found
    state.root = root
    if os.path.normpath(git_dir) != os.path.normpath(common_dir):
        state.worktree = os.path.basename(root)
        state.repo_name = _repo_name(common_dir, root)
    else:
        state.repo_name = os.path.basename(root)
    remotes = parse_remotes(_read(os.path.join(common_dir, "config")) or "")
    state.has_remote = bool(remotes)
    state.operation, state.progress = operation(git_dir)

    genv = _git_env(env)
    deadline = time.monotonic() + GIT_TIMEOUT
    try:
        status = _start(["status", "--porcelain=v2", "--branch", "-z"], root, genv)
        # Run beside status; on a clean tree it is cheap and its answer is unused.
        numstat = _start(
            ["diff", "--numstat", "--no-ext-diff", "--no-textconv", "HEAD"], root, genv
        )
    except OSError:
        return  # no git
    status_text = _finish(status, deadline)
    numstat_text = _finish(numstat, deadline)
    if status_text is None:
        return
    state.git = True
    parse_status(status_text, state)
    if state.upstream and "# branch.ab " not in status_text:
        state.upstream_gone = True
    if state.dirty:
        if numstat_text is None and state.oid is None:
            # No commits yet: compare the index with the empty tree.
            proc = _start(["diff", "--numstat", "--cached", EMPTY_TREE], root, genv)
            numstat_text = _finish(proc, deadline)
        if numstat_text is not None:
            state.added, state.removed = parse_numstat(numstat_text)
    state.branch_url = branch_url(state, remotes, common_dir)
    if state.branch is None and state.operation == "rebase":
        state.branch = _rebase_branch(git_dir)
    if state.branch is None and state.oid:
        tag = _finish(_start(["describe", "--tags", "--exact-match", "HEAD"], root, genv), deadline)
        state.tag = tag.strip() if tag and tag.strip() else None
    return


# ---- drawing ----


def collapse_home(path: str, home: str | None) -> str:
    if home and (path == home or path.startswith(home.rstrip(os.sep) + os.sep)):
        return "~" + path[len(home.rstrip(os.sep)) :]
    return path


def _drift(state: RepoState, ctx, home: str | None) -> list:
    """Where Claude's shell is, when it isn't the project dir."""
    cur, proj = state.current_dir, state.project_dir
    if not cur or os.path.normpath(cur) == os.path.normpath(proj):
        return []
    rel = os.path.relpath(cur, proj) if cur.startswith(proj.rstrip(os.sep) + os.sep) else None
    text = (ctx.g["drift_inside"] + rel) if rel else collapse_home(cur, home)
    return [ctx.seg(ctx.g["drift"] + text, "inactive")]


def _link(seg: tuple, url: str | None) -> tuple:
    return (*seg, url) if url else seg


def _project(state: RepoState, ctx, home: str | None, worktree: bool) -> list:
    link = state.folder_url
    if not state.root:
        text = ctx.g["folder"] + collapse_home(state.project_dir, home)
        return [_link(ctx.seg(text, "text"), link)]
    out = [_link(ctx.seg(ctx.g["project"] + state.repo_name, "text"), link)]
    proj = os.path.normpath(state.project_dir)
    if proj != os.path.normpath(state.root) and proj.startswith(state.root):
        sub = proj[len(state.root) :].replace(os.sep, "/")
        out.append(_link(ctx.seg(sub, "inactive"), link))
    if worktree and state.worktree:
        out += [
            ctx.seg(ctx.g["worktree"], "inactive"),
            ctx.seg(state.worktree, "text"),
            ctx.seg(ctx.g["worktree_end"], "inactive"),
        ]
    return out


def _ref(state: RepoState, ctx, branch_room: int | None) -> list:
    end = ctx.g["ref_end"]
    if state.branch:
        name = state.branch
        if branch_room is not None and len(name) > branch_room:
            keep = max(MIN_BRANCH, branch_room - len(ctx.g["ellipsis"]))
            name = name[:keep] + ctx.g["ellipsis"]
        return [_link(ctx.seg(ctx.g["branch"] + name + end, "text"), state.branch_url)]
    if state.tag:
        return [ctx.seg(ctx.g["tag"] + state.tag + end, "warning")]
    if state.oid:
        return [ctx.seg(ctx.g["detached"] + state.oid[:7] + end, "warning")]
    return []


def _changes(state: RepoState, ctx, counts: bool) -> list:
    """`✎ +120 −45 ?`: uncommitted lines, then the untracked marker."""
    out = []
    if state.dirty:
        out.append(ctx.seg(ctx.g["uncommitted"], "warning"))
        if counts and state.added:
            out += [(" ", ""), ctx.seg(f"+{state.added}", "success")]
        if counts and state.removed:
            out += [(" ", ""), ctx.seg(f"{ctx.g['minus']}{state.removed}", "error")]
    if state.untracked:
        if out:
            out.append((" ", ""))
        out.append(ctx.seg(ctx.g["untracked"], "warning"))
    return out


def _sync(state: RepoState, ctx) -> list:
    if not state.git or not (state.branch or state.operation == "rebase"):
        return []
    if state.upstream_gone:
        return [ctx.seg(ctx.g["upstream_gone"], "inactive")]
    if not state.upstream:
        return [ctx.seg(ctx.g["never_pushed"], "warning")] if state.has_remote else []
    token = "error" if state.ahead and state.behind else "warning"
    out = []
    if state.ahead:
        out.append(ctx.seg(f"{ctx.g['ahead']}{state.ahead}", token))
    if state.behind:
        if out:
            out.append((" ", ""))
        out.append(ctx.seg(f"{ctx.g['behind']}{state.behind}", token))
    return out


def _alerts(state: RepoState, ctx) -> list:
    out = []
    if state.operation:
        text = OPERATIONS[state.operation]
        if state.progress:
            text += f" {state.progress}"
        out.append([ctx.seg(ctx.g[f"op_{state.operation}"] + text, "error")])
    if state.conflicts:
        out.append([ctx.seg(f"{ctx.g['conflicts']}{state.conflicts}", "error")])
    return out


def draw(state: RepoState | None, ctx, home: str | None = None) -> list:
    """The row as segments, within ctx.width.

    Narrow terminals give up, in order: line counts (the pencil stays), the cwd drift,
    branch length (down to a few characters and `…`), the worktree name; then the row
    is cut short. Operations, conflicts and sync never drop.
    """
    from dashline.layout import truncate, width

    if state is None or not state.project_dir:
        return []

    def build(counts=True, drift=True, branch_room=None, worktree=True):
        groups = [_project(state, ctx, home, worktree)]
        if drift:
            groups.append(_drift(state, ctx, home))
        groups.append(_ref(state, ctx, branch_room))
        groups += _alerts(state, ctx)
        groups.append(_changes(state, ctx, counts))
        groups.append(_sync(state, ctx))
        line = []
        for group in (g for g in groups if g):
            if line:
                line.append((GAP, ""))
            line += group
        return line

    steps = [{}, {"counts": False}, {"counts": False, "drift": False}]
    for kwargs in steps:
        line = build(**kwargs)
        if width(line) <= ctx.width:
            return line
    if state.branch:
        room = len(state.branch) - (width(line) - ctx.width)
        line = build(counts=False, drift=False, branch_room=max(room, MIN_BRANCH))
        if width(line) <= ctx.width:
            return line
    line = build(counts=False, drift=False, branch_room=MIN_BRANCH, worktree=False)
    return truncate(line, ctx.width, ctx.g["ellipsis"], ctx.p.sgr("inactive"))
