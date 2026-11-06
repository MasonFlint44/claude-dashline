"""Line 3, the directory row: project, branch and git state as icons (PLAN §5, option C).

`inspect` reads the repo: a Python walk for `.git` (from the real path, so a symlinked
project dir finds its repo), then `git status --porcelain=v2` and `git diff --numstat
HEAD` run side by side, plus `.git` files for an operation in progress. `draw` turns that
into segments fitted to the width. Hide what's normal: a clean, pushed branch shows the
project and branch only.

git runs with the repo's fsmonitor hook off and submodules' own changes ignored, in a
process group of its own: at the timeout the whole group is killed, so a hung hook or
filter can't hold the render. Every name shown goes through `text.clean`, so a folder or
branch name can't put escape codes on the terminal. Any git from 2.11 works.

Links (OSC 8, chosen 11/4): the project opens its folder (`file://host/path`); a pushed
branch on GitHub opens its compare page against the default branch, or the branch page
when it is the default.
"""

from __future__ import annotations

import os
import re

from dashline.text import clean, cols, cut

GIT_TIMEOUT = 1.0  # seconds; a slower repo shows the project without git state
KILL_WAIT = 0.05  # seconds to collect a killed git before giving up on it
GAP = "  "
# Variables git sets for hooks and editors that point a git command at another repo,
# index or object store. Claude Code started from inside one (a commit message editor,
# a hook) would pass them on. GIT_CONFIG* are kept: they are the user's own settings.
GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_QUARANTINE_PATH",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
)
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
GITHUB_HOST = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*$")
# Bytes a URL path keeps as they are; the rest are percent-encoded (as urllib's quote
# does, without importing it on every render).
URL_SAFE = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-~/")
GITHUB_PATH = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")  # owner/repo
# A config section header: [section], [section "subsection"] or the old [section.sub].
CONFIG_HEADER = re.compile(r'^\[\s*([A-Za-z0-9.-]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\]')
CONFIG_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")


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
        self.real_dir = None  # project_dir with symlinks resolved, once inspected


# ---- finding the repo (no git process) ----


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def ceiling_dirs(env) -> list:
    """GIT_CEILING_DIRECTORIES as git reads it: absolute paths only, with symlinks
    resolved except after an empty entry."""
    out, resolve = [], True
    for entry in (env.get("GIT_CEILING_DIRECTORIES") or "").split(os.pathsep):
        if not entry:
            resolve = False
        elif os.path.isabs(entry):
            out.append(os.path.realpath(entry) if resolve else os.path.normpath(entry))
    return out


def find_git(start: str, ceilings: list = ()) -> tuple | None:
    """(top level, git dir, common dir) for the repo holding `start`, or None.

    Like git, the walk up never enters a ceiling directory (it may start in one).
    """
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
        if parent == path or parent in ceilings:
            return None
        path = parent
    common = (_read(os.path.join(git_dir, "commondir")) or "").strip()
    common_dir = os.path.normpath(os.path.join(git_dir, common)) if common else git_dir
    return path, git_dir, common_dir


def _config_value(raw: str) -> tuple:
    """A config value as written → (value, continues on the next line).

    Quotes are dropped and backslash escapes undone; an unquoted `#` or `;` starts a
    comment, and a backslash at the end joins the next line.
    """
    out, quoted, i = [], False, 0
    while i < len(raw):
        c = raw[i]
        if c == "\\":
            if i + 1 == len(raw):
                return "".join(out), True
            nxt = raw[i + 1]
            out.append({"n": "\n", "t": "\t", "b": "\b"}.get(nxt, nxt))
            i += 2
            continue
        if c == '"':
            quoted = not quoted
        elif not quoted and c in "#;":
            break
        else:
            out.append(c)
        i += 1
    return "".join(out), False


def parse_config(config: str) -> list:
    """A git config file → [(section, subsection, key, value)].

    Section and key names are lowercased (git treats them so); subsections keep their
    case, except in the old `[section.sub]` form. Keys without a value are skipped.
    """
    entries = []
    section = sub = None
    lines = config.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if line.startswith("["):
            m = CONFIG_HEADER.match(line)
            if not m:
                section = sub = None
                continue
            name, quoted = m.group(1), m.group(2)
            if quoted is not None:
                section, sub = name.lower(), re.sub(r"\\(.)", r"\1", quoted)
            elif "." in name:
                head, _, rest = name.partition(".")
                section, sub = head.lower(), rest.lower()
            else:
                section, sub = name.lower(), None
            line = line[m.end() :].strip()  # a key may follow on the same line
        if section is None or not line or line[0] in "#;":
            continue
        key, eq, raw = line.partition("=")
        key = key.strip()
        if not eq or not CONFIG_KEY.match(key):
            continue
        value, more = _config_value(raw)
        while more and i < len(lines):
            rest, more = _config_value(lines[i])
            value += rest
            i += 1
        entries.append((section, sub, key.lower(), value.strip()))
    return entries


def parse_remotes(config) -> dict:
    """`[remote "name"] url = …` sections of a git config → {name: first url}.

    `config` is the file's text or `parse_config`'s entries.
    """
    entries = parse_config(config) if isinstance(config, str) else config
    remotes = {}
    for section, sub, key, value in entries:
        if section == "remote" and sub and key == "url" and value and sub not in remotes:
            remotes[sub] = value
    return remotes


def _env_bool(value: str | None) -> bool:
    """A git boolean from the environment: unset, empty, 0, false, no and off are false."""
    value = (value or "").strip().lower()
    if value.lstrip("-").isascii() and value.lstrip("-").isdigit():
        return int(value) != 0
    return value not in ("", "false", "no", "off")


def config_files(env) -> list:
    """The config files git reads before a repo's own: system, then global.

    `[include]` and `[includeIf]` aren't followed: only the link reads these, for
    `url.<base>.insteadOf` shorthands like `gh:owner/repo`.
    """
    paths = []
    if not _env_bool(env.get("GIT_CONFIG_NOSYSTEM")):
        paths.append(env.get("GIT_CONFIG_SYSTEM") or "/etc/gitconfig")
    if env.get("GIT_CONFIG_GLOBAL"):
        paths.append(env["GIT_CONFIG_GLOBAL"])
    else:
        home = env.get("HOME") or ""
        xdg = env.get("XDG_CONFIG_HOME") or (os.path.join(home, ".config") if home else "")
        if xdg:
            paths.append(os.path.join(xdg, "git", "config"))
        if home:
            paths.append(os.path.join(home, ".gitconfig"))
    return paths


def url_rewrites(entries: list) -> list:
    """`[url "<base>"] insteadOf = <prefix>` entries → [(prefix, base)]."""
    return [
        (value, sub)
        for section, sub, key, value in entries
        if section == "url" and sub and key == "insteadof" and value
    ]


def rewrite_url(url: str, rewrites: list) -> str:
    """`url` as git expands it: the longest matching insteadOf prefix becomes its base."""
    best = max((r for r in rewrites if url.startswith(r[0])), key=lambda r: len(r[0]), default=None)
    return best[1] + url[len(best[0]) :] if best else url


def _reftable(common_dir: str) -> bool:
    """Whether the repo keeps its refs in the reftable format (git 2.45+), not files."""
    return os.path.isdir(os.path.join(common_dir, "reftable"))


def _ref_exists(common_dir: str, ref: str, git=None) -> bool:
    """Whether `refs/…` exists, loose or packed.

    Under reftable the files can't say, so `git` (args → output, or None) is asked;
    without an answer the ref is assumed to exist.
    """
    if _reftable(common_dir):
        out = git(["for-each-ref", "--format=%(refname)", ref]) if git else None
        return out is None or ref in out.splitlines()
    if os.path.exists(os.path.join(common_dir, *ref.split("/"))):
        return True
    packed = _read(os.path.join(common_dir, "packed-refs")) or ""
    return any(line.endswith(" " + ref) for line in packed.splitlines())


def configured_upstream(entries: list, branch: str, common_dir: str, git=None) -> tuple:
    """(upstream, gone) for a branch from its `[branch]` config, as git status names it.

    For when status can't say: HEAD is detached while the branch is being rebased.
    git: as for `_ref_exists`.
    """
    remote = merge = None
    for section, sub, key, value in entries:
        if section == "branch" and sub == branch:
            if key == "remote":
                remote = value  # the last value wins, as in git
            elif key == "merge":
                merge = value
    if not remote or not merge or not merge.startswith("refs/heads/"):
        return None, False
    name = merge[len("refs/heads/") :]
    if remote == ".":
        return name, not _ref_exists(common_dir, merge, git)
    ref = f"refs/remotes/{remote}/{name}"
    return f"{remote}/{name}", not _ref_exists(common_dir, ref, git)


def github_host(host: str) -> str | None:
    """The web host for a GitHub remote's host, or None when it isn't GitHub.

    github.com itself, also as `www.github.com` or an SSH alias from ~/.ssh/config like
    `github-work` or `github.com-work` (the usual way to use two accounts); GitHub
    Enterprise Server at `github.<domain>`; Enterprise Cloud at `<name>.ghe.com`.
    """
    if not GITHUB_HOST.match(host):
        return None  # not a name GitHub allows, so not a page to link to
    if host in ("github.com", "www.github.com") or host.startswith("github.com-"):
        return "github.com"
    if host.startswith("github-") and "." not in host:
        return "github.com"
    if host.startswith("github.") or host.endswith(".ghe.com"):
        return host
    return None


def github_web(url: str) -> str | None:
    """A GitHub remote URL → `https://github.com/owner/repo`; None for other hosts."""
    m = GITHUB.match(url.strip())
    if not m:
        return None
    host = github_host((m.group("h1") or m.group("h2")).lower())
    if not host or not GITHUB_PATH.match(m.group("path")):
        return None
    return f"https://{host}/{m.group('path')}"


def _default_branch(common_dir: str, remote: str, git=None) -> str | None:
    """The remote's default branch, from `refs/remotes/<remote>/HEAD` (set by clone).

    Under reftable that ref isn't a file, so `git` (args → output, or None) is asked.
    """
    prefix = f"refs/remotes/{remote}/"
    if _reftable(common_dir):
        text = ((git(["symbolic-ref", "-q", prefix + "HEAD"]) if git else None) or "").strip()
    else:
        text = (_read(os.path.join(common_dir, *prefix.split("/"), "HEAD")) or "").strip()
        text = text[len("ref: ") :] if text.startswith("ref: ") else ""
    return (text[len(prefix) :] or None) if text.startswith(prefix) else None


def quote(text: str) -> str:
    """`text` percent-encoded as UTF-8 for a URL path; `/` is kept.

    Raises UnicodeEncodeError for a lone surrogate (only bytes from a file name that
    isn't UTF-8 encode).
    """
    raw = text.encode("utf-8", "surrogateescape")
    return "".join(chr(b) if b in URL_SAFE else f"%{b:02X}" for b in raw)


def folder_url(path: str) -> str | None:
    """`file://host/path` for the folder, or None when the path can't be encoded."""
    host = os.uname().nodename if hasattr(os, "uname") else ""
    path = path.replace(os.sep, "/")
    if not path.startswith("/"):
        path = "/" + path  # C:/x on Windows
    try:
        return f"file://{host}{quote(path)}"
    except UnicodeEncodeError:
        return None


def branch_url(
    state: RepoState, remotes: dict, common_dir: str, rewrites: list = (), git=None
) -> str | None:
    """Compare page for a pushed branch on GitHub; the branch page for the default.

    rewrites: url_rewrites from every config file, so `gh:owner/repo` links too.
    git: as for `_default_branch`.
    """
    if not state.branch or not state.upstream or state.upstream_gone:
        return None
    remote = max((r for r in remotes if state.upstream.startswith(r + "/")), key=len, default=None)
    web = github_web(rewrite_url(remotes[remote], list(rewrites))) if remote else None
    if not web:
        return None
    branch = state.upstream[len(remote) + 1 :]
    default = _default_branch(common_dir, remote, git)
    try:
        if default is None or default == branch:
            return f"{web}/tree/{quote(branch)}"
        return f"{web}/compare/{quote(default)}...{quote(branch)}"
    except UnicodeEncodeError:
        return None


def operation(git_dir: str) -> tuple:
    """(operation, progress) from the files git leaves while one runs."""

    def exists(*parts):
        return os.path.exists(os.path.join(git_dir, *parts))

    def number(*parts):
        text = (_read(os.path.join(git_dir, *parts)) or "").strip()
        return text if text.isascii() and text.isdigit() else None

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
    # A cherry-pick or revert of several commits, stopped between them: the first
    # line of the todo list is the step it stopped at.
    todo = (_read(os.path.join(git_dir, "sequencer", "todo")) or "").split(None, 1)
    if todo and todo[0] in ("pick", "p"):
        return "cherry_pick", None
    if todo and todo[0] in ("revert", "r"):
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
    out = {k: v for k, v in env.items() if k not in GIT_LOCATION_VARS}
    out.update(GIT_OPTIONAL_LOCKS="0", LC_ALL="C", GIT_TERMINAL_PROMPT="0")
    return out


def _start(args: list, cwd: str, env: dict):
    import subprocess

    return subprocess.Popen(
        # No fsmonitor: its hook is a program the repo's config names, run on each status.
        # Empty means off on every git: a hook path before 2.36, a boolean since. No
        # --no-optional-locks: git before 2.15 refuses it, and GIT_OPTIONAL_LOCKS=0
        # does the same where it exists.
        ["git", "-c", "core.fsmonitor=", *args],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # its own process group, so a timeout kills hooks too
    )


def _kill(proc) -> None:
    """Kill git and everything it started (hooks, filters, an alias's shell)."""
    import contextlib
    import signal

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (AttributeError, OSError):  # no process groups here, or git already gone
        with contextlib.suppress(OSError):
            proc.kill()


def _finish(proc, deadline: float) -> str | None:
    import subprocess
    import time

    try:
        out, _ = proc.communicate(timeout=max(0.01, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        _kill(proc)
        try:
            proc.communicate(timeout=KILL_WAIT)
        except subprocess.TimeoutExpired:
            # Something left the group and still holds the pipe: don't wait for it.
            proc.stdout.close()
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
            parts = [p.lstrip("+-") for p in field.split()[2:]]
            if len(parts) == 2 and all(p.isascii() and p.isdigit() for p in parts):
                state.ahead, state.behind = int(parts[0]), int(parts[1])
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
    # git itself works from the resolved path: a symlink into a repo is still in it.
    state.real_dir = os.path.realpath(project_dir)
    found = find_git(state.real_dir, ceiling_dirs(env))
    if not found:
        return
    root, git_dir, common_dir = found
    state.root = root
    if os.path.normpath(git_dir) != os.path.normpath(common_dir):
        state.worktree = os.path.basename(root)
        state.repo_name = _repo_name(common_dir, root)
    else:
        state.repo_name = os.path.basename(root)
    config = parse_config(_read(os.path.join(common_dir, "config")) or "")
    remotes = parse_remotes(config)
    state.has_remote = bool(remotes)
    state.operation, state.progress = operation(git_dir)

    genv = _git_env(env)
    deadline = time.monotonic() + GIT_TIMEOUT
    # A submodule's own edits and untracked files are its business, and slow to find.
    subs = "--ignore-submodules=dirty"
    diff = ["diff", "--numstat", "--no-ext-diff", "--no-textconv", subs]
    try:
        status = _start(["status", "--porcelain=v2", "--branch", "-z", subs], root, genv)
        # Run beside status; on a clean tree it is cheap and its answer is unused.
        numstat = _start([*diff, "HEAD"], root, genv)
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

    def run_git(args):
        """One more git command within the deadline: its output, or None."""
        if time.monotonic() >= deadline:
            return None
        try:
            return _finish(_start(args, root, genv), deadline)
        except OSError:
            return None

    if state.dirty:
        if numstat_text is None and state.oid is None and time.monotonic() < deadline:
            # No commits yet: `--cached` alone compares the index with the empty tree,
            # whatever the repo's hash.
            numstat_text = _finish(_start([*diff, "--cached"], root, genv), deadline)
        if numstat_text is not None:
            state.added, state.removed = parse_numstat(numstat_text)
    if state.branch is None and state.operation == "rebase":
        # HEAD is detached while a rebase runs: take the branch, and its upstream,
        # from the rebase state and the config.
        state.branch = _rebase_branch(git_dir)
        if state.branch:
            state.upstream, state.upstream_gone = configured_upstream(
                config, state.branch, common_dir, run_git
            )
    if state.branch and state.upstream and not state.upstream_gone:
        # insteadOf shorthands usually live in the global config, so read it only here.
        rewrites = []
        for path in config_files(env):
            rewrites += url_rewrites(parse_config(_read(path) or ""))
        rewrites += url_rewrites(config)
        state.branch_url = branch_url(state, remotes, common_dir, rewrites, run_git)
    if state.branch is None and state.oid and time.monotonic() < deadline:
        tag = _finish(_start(["describe", "--tags", "--exact-match", "HEAD"], root, genv), deadline)
        state.tag = tag.strip() if tag and tag.strip() else None
    return


# ---- drawing ----


def collapse_home(path: str, home: str | None) -> str:
    """`/home/me/x` → `~/x`. A home of `/` (or none) collapses nothing."""
    home = (home or "").rstrip(os.sep)
    if home and (path == home or path.startswith(home + os.sep)):
        return "~" + path[len(home) :]
    return path


def _inside(path: str, parent: str) -> str | None:
    """`path` relative to `parent` when it is strictly inside it, else None."""
    prefix = parent if parent.endswith(os.sep) else parent + os.sep
    return os.path.relpath(path, parent) if path.startswith(prefix) else None


def _drift(state: RepoState, ctx, home: str | None) -> list:
    """Where Claude's shell is, when it isn't the project dir."""
    cur, proj = state.current_dir, state.project_dir
    if not cur:
        return []
    # Compare real paths: a shell in the symlink's target hasn't moved.
    real_cur = os.path.realpath(cur)
    real_proj = state.real_dir or os.path.realpath(proj)
    if real_cur == real_proj:
        return []
    rel = _inside(real_cur, real_proj)
    text = (ctx.g["drift_inside"] + rel) if rel else collapse_home(cur, home)
    return [ctx.seg(ctx.g["drift"] + clean(text), "inactive")]


def _link(seg: tuple, url: str | None) -> tuple:
    # Only printable ASCII reaches the OSC 8 escape; anything else means no link.
    if url and all("!" <= c <= "~" for c in url):
        return (*seg, url)
    return seg


def _subpath(state: RepoState) -> str:
    """The project dir below the repo's top level, as `/services/api`; "" at the top."""
    rel = _inside(state.real_dir or os.path.normpath(state.project_dir), state.root)
    return "/" + rel.replace(os.sep, "/") if rel else ""


def _project(state: RepoState, ctx, home: str | None, worktree: bool, sub: str) -> list:
    """sub: "full" shows the whole subpath, "last" only its last folder, "" none."""
    link = state.folder_url
    if not state.root:
        text = ctx.g["folder"] + clean(collapse_home(state.project_dir, home))
        return [_link(ctx.seg(text, "text"), link)]
    out = [_link(ctx.seg(ctx.g["project"] + clean(state.repo_name), "text"), link)]
    path = _subpath(state) if sub else ""
    if path and sub == "last" and path.count("/") > 1:
        path = "/" + ctx.g["ellipsis"] + path[path.rindex("/") :]
    if path:
        out.append(_link(ctx.seg(clean(path), "inactive"), link))
    if worktree and state.worktree:
        out += [
            ctx.seg(ctx.g["worktree"], "inactive"),
            ctx.seg(clean(state.worktree), "text"),
            ctx.seg(ctx.g["worktree_end"], "inactive"),
        ]
    return out


def _ref_name(state: RepoState) -> str | None:
    """The branch or tag, which may be shortened; None for a commit or nothing."""
    name = state.branch or state.tag
    return clean(name) if name else None


def _ref(state: RepoState, ctx, ref_room: int | None) -> list:
    end = ctx.g["ref_end"]
    name = _ref_name(state)
    if name and ref_room is not None and cols(name) > ref_room:
        keep = max(MIN_BRANCH, ref_room - cols(ctx.g["ellipsis"]))
        name = cut(name, keep) + ctx.g["ellipsis"]
    if state.branch:
        return [_link(ctx.seg(ctx.g["branch"] + name + end, "text"), state.branch_url)]
    if state.tag:
        return [ctx.seg(ctx.g["tag"] + name + end, "warning")]
    if state.oid:
        return [ctx.seg(ctx.g["detached"] + clean(state.oid[:7]) + end, "warning")]
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
    # A detached HEAD has nothing to push, mid-rebase too. A branch being rebased is
    # known by now, from the rebase state.
    if not state.git or not state.branch:
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
    then the branch or tag shortens (down to a few characters and `…`). Past that the
    worktree name goes, the subpath keeps only its last folder and then goes, each step
    giving the branch the room it frees. Then the row is cut short. Operations,
    conflicts and sync never drop.
    """
    from dashline.layout import truncate, width

    if state is None or not state.project_dir:
        return []

    def build(counts=True, drift=True, worktree=True, sub="full", ref_room=None):
        groups = [_project(state, ctx, home, worktree, sub)]
        if drift:
            groups.append(_drift(state, ctx, home))
        groups.append(_ref(state, ctx, ref_room))
        groups += _alerts(state, ctx)
        groups.append(_changes(state, ctx, counts))
        groups.append(_sync(state, ctx))
        line = []
        for group in (g for g in groups if g):
            if line:
                line.append((GAP, ""))
            line += group
        return line

    name = _ref_name(state)
    shortest = MIN_BRANCH + cols(ctx.g["ellipsis"])
    quiet = {"counts": False, "drift": False}
    # (what to leave out, whether the branch or tag may shorten to fit)
    steps = [
        ({}, False),
        ({"counts": False}, False),
        (quiet, True),
        ({**quiet, "worktree": False}, True),
        ({**quiet, "worktree": False, "sub": "last"}, True),
        ({**quiet, "worktree": False, "sub": ""}, True),
    ]
    for kwargs, shorten in steps:
        line = build(**kwargs)
        over = width(line) - ctx.width
        if over <= 0:
            return line
        if shorten and name and cols(name) - over >= shortest:
            return build(**kwargs, ref_room=cols(name) - over)
    line = build(**steps[-1][0], ref_room=shortest)
    return truncate(line, ctx.width, ctx.g["ellipsis"], ctx.p.sgr("inactive"))
