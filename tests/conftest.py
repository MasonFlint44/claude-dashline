import copy
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from dashline import account, doctor, glyphs, layout, stdin, theme, usage
from dashline.colors import THEMES

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ANSI = re.compile(r"\x1b\[[0-9;]*m|\x1b\]8;;[^\x1b]*\x1b\\")
# The clock for every layout test: 2026-11-05 00:00:00 UTC.
NOW = 1793836800.0
# The real usage.spawn, for the one test that checks it (with Popen faked).
REAL_SPAWN = usage.spawn


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def stdin_data(name: str) -> dict:
    return read_json(FIXTURES / "stdin" / f"{name}.json")


def merge(base: dict, overrides: dict) -> dict:
    """Deep-merge overrides into a copy of base; a None value deletes the key."""
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def make_session(name: str = "after-first-response", **overrides) -> stdin.Session:
    return stdin.Session(merge(stdin_data(name), overrides))


def make_ctx(columns=120, glyph_set="unicode", theme_name="dark", color=False, now=NOW):
    palette = theme.Palette(THEMES[theme_name], color=color)
    return layout.Ctx(glyphs.get(glyph_set), palette, columns, now)


def plain(lines) -> list:
    return [ANSI.sub("", line if isinstance(line, str) else layout.to_str(line)) for line in lines]


def lines_text(session, ctx, plan=None, plan_label=None) -> list:
    if plan is None:  # stdin's windows alone, through the real path
        plan = usage.plan_bars(session, None, None, NOW)
    return plain(layout.lay_out(session, ctx, plan, plan_label))


@pytest.fixture
def stdin_fixture():
    def load(name: str) -> str:
        return (FIXTURES / "stdin" / f"{name}.json").read_text()

    return load


# Everything that picks the login or the provider; the providers come from account.py,
# so a new one is cleared here too.
TOKEN_VARS = (
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    *(var for var, _ in account.PROVIDERS),
)
# The developer's shell, which a test must not inherit: other proxies (the local
# stand-in server is plain http, so HTTP_PROXY would route it away), the terminal, and
# Claude Code's own session variables when the suite runs inside Claude Code.
SHELL_VARS = (
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
    "TERM_PROGRAM",
    "NO_COLOR",
    "COLORFGBG",
    "COLUMNS",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_CODE_GIT_BASH_PATH",
    "WSL_DISTRO_NAME",
    # The developer's own config: a test's git and theme must not depend on it.
    "XDG_CONFIG_HOME",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
)


# Where a stray HTTPS request from a subprocess goes: a port nothing listens on.
DEAD_PROXY = "http://127.0.0.1:9"
NO_NETWORK = {"HTTPS_PROXY": DEAD_PROXY, "https_proxy": DEAD_PROXY}


def _runs_python(args) -> bool:
    """Whether a subprocess runs Python or a shell, either of which can run dashline."""
    if isinstance(args, (str, bytes, os.PathLike)):
        args = [args]
    words = [os.fsdecode(a) for a in args]
    if not words:
        return False
    program = Path(words[0]).name.lower()
    program = program[:-4] if program.endswith(".exe") else program  # Windows: bash.exe
    return (
        words[0] == sys.executable
        or program.startswith("python")
        or program in ("sh", "bash", "zsh", "dash", "py", "powershell", "pwsh")
        # A shell command names the script inside: `py -3 -I -S "C:/…/statusline.py"`.
        or any("statusline.py" in w for w in words)
    )


@pytest.fixture(autouse=True)
def no_network_in_subprocesses(monkeypatch):
    """A subprocess that could run the statusline must get the dead proxy.

    The statusline starts a real usage fetch when its cache is stale. In-process that's
    caught by the fake spawn below, but a subprocess given its own env (as doctor's
    `command` check does) would reach api.anthropic.com unless that env carries
    NO_NETWORK. This fails the test that forgets it, even when the code under test
    catches the error (doctor turns a broken check into a finding).
    """
    real_init = subprocess.Popen.__init__
    leaks = []

    def guarded(self, args, *rest, **kwargs):
        env = kwargs.get("env")
        if env is not None and os.name == "nt":  # names there ignore case: one HTTPS_PROXY
            env = {k.upper(): v for k, v in env.items()}
        safe = env is None or all(env.get(var.upper()) == DEAD_PROXY for var in NO_NETWORK)
        if not safe and _runs_python(args):
            leaks.append(args)
            raise AssertionError(
                f"a subprocess ({args!r}) got an env without the dead HTTPS_PROXY: "
                "add conftest.NO_NETWORK to it"
            )
        real_init(self, args, *rest, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "__init__", guarded)
    yield
    assert not leaks, f"subprocesses without conftest.NO_NETWORK in their env: {leaks}"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """No test sees the real ~/.claude, a real login, real managed settings, or starts a
    real fetch."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # home on Windows (theme.home_dir)
    for var in TOKEN_VARS:
        monkeypatch.delenv(var, raising=False)
    # Belt and braces for subprocesses: a stray HTTPS request goes to a dead port.
    for var in NO_NETWORK:
        monkeypatch.setenv(var, DEAD_PROXY)
    # Managed settings would win over everything a test writes.
    monkeypatch.setattr(theme, "MANAGED_SETTINGS", str(tmp_path / "managed-settings.json"))
    for var in SHELL_VARS:
        monkeypatch.delenv(var, raising=False)

    def no_spawn(env, now):
        raise AssertionError("a test tried to start a real fetch")

    monkeypatch.setattr(usage, "spawn", no_spawn)
    # A busy runner (a shared Windows one most of all) can take seconds to start a shell:
    # doctor's `command` check calls that slow, which these tests don't measure
    # (test_command_slow* set their own).
    monkeypatch.setattr(doctor, "SLOW_MS", 60_000)
    monkeypatch.setattr(doctor, "SLOW_MS_WINDOWS", 60_000)
    return home


@pytest.fixture(autouse=True)
def no_real_keychain(request, monkeypatch):
    """No test reads the developer's login Keychain on a Mac: `security` answers "not
    found" (exit 44). A test that fakes subprocess.run itself replaces this; one marked
    `real_keychain` gets the real subprocess.run.
    """
    if request.node.get_closest_marker("real_keychain"):
        return
    real_run = subprocess.run

    def guarded(args, *rest, **kwargs):
        words = [args] if isinstance(args, (str, bytes, os.PathLike)) else list(args)
        if words and Path(os.fsdecode(words[0])).name == "security":
            text = kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding")
            empty = "" if text else b""
            return subprocess.CompletedProcess(args, 44, empty, empty)
        return real_run(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded)


# What a Windows program needs from the environment to start at all (Python wants
# SYSTEMROOT for sockets and randomness) and to find others.
WINDOWS_ESSENTIALS = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP")


def held_once(monkeypatch, name, when=lambda *args: True):
    """As on Windows, where a file another process has open can't be moved or removed:
    `os.<name>` raises PermissionError the first time `when(*args)` holds, then works.
    Turns on host.WINDOWS (no sleeping between tries); returns the matching calls."""
    from dashline import host

    real, calls = getattr(os, name), []

    def busy(*args, **kwargs):
        if when(*args):
            calls.append(args)
            if len(calls) == 1:
                raise PermissionError(13, "in use")
        return real(*args, **kwargs)

    monkeypatch.setattr(os, name, busy)
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return calls


posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX behavior (file modes, signals)")
windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows behavior (paths, home)")


def env_for(home, **more):
    """An env with HOME and the dead proxy (plus, on Windows, what programs need)."""
    env = {"HOME": str(home), **NO_NETWORK, **more}
    if os.name == "nt":
        env.update({k: os.environ[k] for k in WINDOWS_ESSENTIALS if k in os.environ})
    return env


# ---- a local stand-in for the usage endpoint ----


class Server:
    """A local stand-in for the usage endpoint: replies come from a queue."""

    def __init__(self):
        self.replies = []
        self.requests = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                server.requests.append((self.path, self.headers))
                status, body, headers = server.replies.pop(0)
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body.encode() if isinstance(body, str) else body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        ).start()

    def reply(self, status, body="", **headers):
        self.replies.append((status, body, headers))


@pytest.fixture
def server():
    s = Server()
    yield s
    s.httpd.shutdown()
    s.httpd.server_close()


@pytest.fixture
def logged_in(isolated_home):
    """A Linux-style login: .claude.json account plus a credentials file."""
    (isolated_home / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"accountUuid": "a", "organizationUuid": "o"}})
    )
    conf = isolated_home / ".claude"
    conf.mkdir()
    creds = {"claudeAiOauth": {"accessToken": "tok-123", "expiresAt": (NOW + 86400) * 1000}}
    (conf / ".credentials.json").write_text(json.dumps(creds))
    return env_for(isolated_home)
