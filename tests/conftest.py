import copy
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from dashline import glyphs, layout, stdin, theme, usage
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
    if plan is None:
        plan = layout.stdin_plan_bars(session)
    return plain(layout.lay_out(session, ctx, plan, plan_label))


@pytest.fixture
def stdin_fixture():
    def load(name: str) -> str:
        return (FIXTURES / "stdin" / f"{name}.json").read_text()

    return load


TOKEN_VARS = (
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """No test sees the real ~/.claude, a real login, or starts a real fetch."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for var in TOKEN_VARS:
        monkeypatch.delenv(var, raising=False)
    # Belt and braces for subprocesses: a stray HTTPS request goes to a dead port.
    for var in ("HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    for var in ("NO_PROXY", "no_proxy", "TERM_PROGRAM", "NO_COLOR", "COLORFGBG"):
        monkeypatch.delenv(var, raising=False)

    def no_spawn(env, now):
        raise AssertionError("a test tried to start a real fetch")

    monkeypatch.setattr(usage, "spawn", no_spawn)
    return home


def env_for(home):
    return {"HOME": str(home)}


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
