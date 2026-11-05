"""A whole render: stdin + .claude.json + the usage cache → lines, and when it fetches."""

import io
import json

import pytest

from conftest import ANSI, FIXTURES, NOW, merge, read_json, stdin_data
from dashline import __main__, usage

FABLE = {"model": {"id": "claude-fable-5-1", "display_name": "Fable 5.1"}}
ULTRA_ACCOUNT = {
    "accountUuid": "11111111-1111-4111-8111-111111111111",
    "organizationUuid": "22222222-2222-4222-8222-222222222222",
    "organizationType": "claude_max",
    "planDisplayName": "Ultra",
}
ENTERPRISE_ACCOUNT = {
    "accountUuid": "33333333-3333-4333-8333-333333333333",
    "organizationUuid": "44444444-4444-4444-8444-444444444444",
    "organizationType": "claude_enterprise",
}


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(usage, "spawn", lambda env, now: calls.append(now) or True)
    return calls


def setup_home(home, oauth, usage_name=None, fetched_at=NOW - 30):
    (home / ".claude.json").write_text(json.dumps({"oauthAccount": oauth}))
    if usage_name:
        from dashline import account

        env = {"HOME": str(home)}
        path = home / ".claude" / "cache" / "statusline"
        path.mkdir(parents=True)
        body = {
            "fetched_at": fetched_at,
            "account": account.identity(env),
            "data": read_json(FIXTURES / "usage" / f"{usage_name}.json"),
        }
        (path / "usage.json").write_text(json.dumps(body))


def render(home, stdin=None, columns=120, **extra_env):
    stdin = stdin if stdin is not None else stdin_data("after-first-response")
    out = io.StringIO()
    env = {"HOME": str(home), "COLUMNS": str(columns), "NO_COLOR": "1", **extra_env}
    assert __main__.render(io.StringIO(json.dumps(stdin)), out, env=env, now=NOW) == 0
    return [ANSI.sub("", line) for line in out.getvalue().splitlines()]


def test_ultra_on_fable_from_cache(isolated_home, spawned):
    setup_home(isolated_home, ULTRA_ACCOUNT, "ultra")
    lines = render(isolated_home, merge(stdin_data("after-first-response"), FABLE))
    assert lines[1].startswith("Ultra │ 7d ")
    assert " 17%  Fable " in lines[1]
    assert lines[1].endswith(" 24%")
    assert spawned == []


def test_enterprise_month_bar(isolated_home, spawned):
    setup_home(isolated_home, ENTERPRISE_ACCOUNT, "enterprise")
    stdin = merge(stdin_data("after-first-response"), {"rate_limits": None})
    lines = render(isolated_home, stdin)
    assert lines[1] == "Enterprise │ month " + "▁" * ((116 - 13 - 9) // 3) + " 0%"


def test_no_cache_yet_uses_stdin_and_fetches(isolated_home, spawned):
    setup_home(isolated_home, ULTRA_ACCOUNT)
    lines = render(isolated_home)
    assert lines[1] == "Ultra │ 7d " + "▆" * 6 + "▁" * 27 + " 17%"  # (116 - 8 - 7) // 3
    assert spawned == [NOW]


def test_old_cache_fetches_and_tags_stale(isolated_home, spawned):
    setup_home(isolated_home, ULTRA_ACCOUNT, "ultra", fetched_at=NOW - 12 * 60)
    lines = render(isolated_home)
    assert lines[1].endswith(" ·12m")
    assert spawned == [NOW]


def test_held_fetch_does_not_spawn(isolated_home, spawned):
    from dashline import account

    setup_home(isolated_home, ULTRA_ACCOUNT)
    path = isolated_home / ".claude" / "cache" / "statusline"
    path.mkdir(parents=True)
    who = account.identity({"HOME": str(isolated_home)})
    (path / "fetch.hold").write_text(json.dumps({"until": NOW + 60, "account": who}))
    render(isolated_home)
    assert spawned == []


def test_api_key_session(isolated_home, spawned):
    stdin = merge(stdin_data("after-first-response"), {"rate_limits": None})
    lines = render(isolated_home, stdin)
    assert lines[1:] == ["/home/user/project"]  # no plan line, just the folder row
    assert " · API · $0.09 │ context " in lines[0]
    assert spawned == []


def test_bedrock_session(isolated_home, spawned):
    setup_home(isolated_home, ULTRA_ACCOUNT, "ultra")
    stdin = merge(stdin_data("after-first-response"), {"rate_limits": None})
    lines = render(isolated_home, stdin, CLAUDE_CODE_USE_BEDROCK="1")
    assert " · Bedrock · $0.09 │ " in lines[0]
    assert lines[1:] == ["/home/user/project"]
    assert spawned == []


def test_gateway_spend_bar(isolated_home, spawned):
    stdin = merge(
        stdin_data("after-first-response"),
        {"rate_limits": {"seven_day": None, "spend_limit": {"used_percentage": 40}}},
    )
    lines = render(isolated_home, stdin)
    assert lines[1].startswith("Gateway │ month ▆▆▆▆▆▆▆▆▆▆")
    assert spawned == []


def test_full_week_line(isolated_home, spawned):
    setup_home(isolated_home, ULTRA_ACCOUNT, "ultra-credits-off")
    stdin = merge(
        stdin_data("after-first-response"),
        {"rate_limits": {"seven_day": {"used_percentage": 100, "resets_at": 1794229200}}},
    )
    lines = render(isolated_home, stdin)
    # 116 - "Ultra │ " (8) - "7d" " 100% (4d13h)" (16) = 92 free: a third is 30.
    assert lines[1] == "Ultra │ 7d " + "▆" * 30 + " 100% (4d13h)"


def test_fetch_error_still_prints_first(isolated_home, monkeypatch):
    """The spawn runs after the output; if it fails, the lines are already out."""
    setup_home(isolated_home, ULTRA_ACCOUNT)

    def broken(env, now):
        raise OSError("no fork")

    monkeypatch.setattr(usage, "spawn", broken)
    assert render(isolated_home)[1].startswith("Ultra │ 7d")


def test_render_stays_fast(isolated_home, spawned):
    """Budget 40 ms with a warm cache; in-process here, so far less."""
    import time

    setup_home(isolated_home, ULTRA_ACCOUNT, "ultra")
    # A real folder: the fixture's /home/user/project is an automount lookup on macOS.
    project = isolated_home / "project"
    project.mkdir()
    where = {"current_dir": str(project), "project_dir": str(project)}
    stdin = merge(stdin_data("after-first-response"), {"workspace": where, "cwd": str(project)})
    render(isolated_home, stdin)
    start = time.perf_counter()
    for _ in range(20):
        render(isolated_home, stdin)
    assert (time.perf_counter() - start) / 20 < 0.02


def test_no_color_render_has_no_color_codes(isolated_home, spawned):
    setup_home(isolated_home, ULTRA_ACCOUNT, "ultra")
    out = io.StringIO()
    env = {"HOME": str(isolated_home), "COLUMNS": "120", "NO_COLOR": "1"}
    stdin = io.StringIO(json.dumps(stdin_data("after-first-response")))
    __main__.render(stdin, out, env=env, now=NOW)
    assert "Ultra" in out.getvalue()
    assert "\x1b[" not in out.getvalue()


@pytest.mark.parametrize(("value", "colored"), [("1", False), ("", True)])
def test_empty_no_color_still_colors(isolated_home, spawned, value, colored):
    """no-color.org: only a non-empty NO_COLOR turns color off."""
    out = io.StringIO()
    env = {"HOME": str(isolated_home), "COLUMNS": "120", "NO_COLOR": value}
    __main__.render(io.StringIO(json.dumps(stdin_data("startup"))), out, env=env, now=NOW)
    assert ("\x1b[" in out.getvalue()) == colored
