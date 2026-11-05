"""Usage cache, lock, hold, fetch (against a local server) and plan bars (usage.py)."""

import json
import threading
from pathlib import Path

import pytest

from conftest import FIXTURES, NOW, REAL_SPAWN, env_for, make_session, read_json
from dashline import account, usage
from dashline.account import Account

MODEL_FABLE = {"model": {"id": "claude-fable-5-1", "display_name": "Fable 5.1"}}
MODEL_OPUS = {"model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"}}
ULTRA = Account("subscription", "Ultra", org_type="claude_max", fingerprint="abc")
ENTERPRISE = Account("subscription", "Enterprise", org_type="claude_enterprise", fingerprint="e")


def usage_fixture(name):
    return read_json(FIXTURES / "usage" / f"{name}.json")


def summary(plan):
    """[(label, percent, resets_at)] for readable asserts."""
    return [(b.label, b.percent, b.resets_at) for b in plan]


def labels(plan):
    return [b.label for b in plan]


# ---- plan bars from the captures ----

# 2026-11-06T07:00:00.281290Z and .281413Z
ULTRA_7D_RESET = 1793948400.28129
ULTRA_FABLE_RESET = 1793948400.281413


def test_ultra_on_fable():
    session = make_session(rate_limits=None, **MODEL_FABLE)
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra"), NOW)
    assert summary(plan) == [
        ("7d", 17, pytest.approx(ULTRA_7D_RESET)),
        ("Fable", 24, pytest.approx(ULTRA_FABLE_RESET)),
    ]


def test_scoped_bar_hidden_on_another_model():
    session = make_session(rate_limits=None, **MODEL_OPUS)
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra"), NOW)
    assert labels(plan) == ["7d"]


def test_scoped_bar_shown_at_zero():
    session = make_session(rate_limits=None, **MODEL_FABLE)
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra-credits-off"), NOW)
    assert [(b.label, b.percent) for b in plan] == [("7d", 3), ("Fable", 0)]


def test_scope_matches_model_id_alone():
    session = make_session(rate_limits=None, model={"id": "claude-fable-5-1"})
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra"), NOW)
    assert labels(plan) == ["7d", "Fable"]


def test_scope_needs_a_word_boundary_in_the_name():
    session = make_session(rate_limits=None, model={"id": "x", "display_name": "Fabled 1"})
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra"), NOW)
    assert labels(plan) == ["7d"]


def test_enterprise_month_bar_at_zero():
    session = make_session(rate_limits=None)
    plan = usage.plan_bars(session, ENTERPRISE, usage_fixture("enterprise"), NOW)
    assert summary(plan) == [("month", 0, None)]


def test_credits_only_once_used():
    data = usage_fixture("ultra")
    session = make_session(rate_limits=None, **MODEL_OPUS)
    assert "credits" not in labels(usage.plan_bars(session, ULTRA, data, NOW))
    data["spend"]["used"]["amount_minor"] = 5000
    data["spend"]["percent"] = 25
    plan = usage.plan_bars(session, ULTRA, data, NOW)
    assert summary(plan)[-1] == ("credits", 25, None)


def test_credits_percent_from_amounts():
    data = usage_fixture("ultra")
    data["spend"]["used"]["amount_minor"] = 5000
    data["spend"]["percent"] = None
    plan = usage.plan_bars(make_session(rate_limits=None), ULTRA, data, NOW)
    assert plan[-1].percent == 25


def test_credits_off_or_unlimited_hidden():
    data = usage_fixture("ultra-credits-off")
    data["spend"]["used"]["amount_minor"] = 5000
    assert "credits" not in labels(usage.plan_bars(make_session(), ULTRA, data, NOW))
    data = usage_fixture("ultra")
    data["spend"]["used"]["amount_minor"] = 5000
    data["spend"]["limit"] = None
    data["spend"]["percent"] = None
    assert "credits" not in labels(usage.plan_bars(make_session(), ULTRA, data, NOW))


def test_session_limit_is_5h_and_first():
    data = usage_fixture("ultra")
    data["limits"].append(
        {"kind": "session", "percent": 40, "resets_at": "2026-11-05T03:00:00Z", "scope": None}
    )
    plan = usage.plan_bars(make_session(rate_limits=None, **MODEL_FABLE), ULTRA, data, NOW)
    assert labels(plan) == ["5h", "7d", "Fable"]
    assert plan[0].resets_at == NOW + 3 * 3600


def test_unknown_kind_shown_by_name():
    data = usage_fixture("ultra")
    data["limits"].append({"kind": "daily_burst", "percent": 12, "resets_at": None})
    plan = usage.plan_bars(make_session(rate_limits=None, **MODEL_OPUS), ULTRA, data, NOW)
    assert labels(plan) == ["7d", "daily burst"]


@pytest.mark.parametrize(
    "row",
    [
        "not a row",
        {"kind": "weekly_all"},
        {"kind": "weekly_all", "percent": "17"},
        {"kind": None, "percent": 3},
        {"kind": "weekly_scoped", "percent": 3, "scope": None},
    ],
)
def test_odd_rows_are_skipped(row):
    data = {"limits": [row]}
    assert usage.plan_bars(make_session(rate_limits=None), ULTRA, data, NOW) == []


@pytest.mark.parametrize("data", [None, {}, {"limits": "x", "spend": []}, {"spend": {"x": 1}}])
def test_odd_shapes_fall_back_to_stdin(data):
    plan = usage.plan_bars(make_session(), ULTRA, data, NOW)
    assert summary(plan) == [("7d", 17, 1793948400)]


def test_rolled_over_window_reads_zero():
    data = usage_fixture("ultra")
    later = ULTRA_7D_RESET + 10
    plan = usage.plan_bars(make_session(rate_limits=None, **MODEL_OPUS), ULTRA, data, later)
    assert summary(plan) == [("7d", 0, None)]


# ---- merging with stdin ----


def test_stdin_higher_percent_wins_same_window():
    session = make_session(
        rate_limits={"seven_day": {"used_percentage": 21, "resets_at": 1793948400}}, **MODEL_OPUS
    )
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra"), NOW)
    assert (plan[0].label, plan[0].percent) == ("7d", 21)


def test_cache_higher_percent_wins_same_window():
    session = make_session(
        rate_limits={"seven_day": {"used_percentage": 9, "resets_at": 1793948400}}, **MODEL_OPUS
    )
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra"), NOW)
    assert plan[0].percent == 17


def test_newer_window_wins():
    """stdin already sees the next week: its 2% beats the cache's 17% of the old one."""
    next_week = ULTRA_7D_RESET + 7 * 86400
    session = make_session(
        rate_limits={"seven_day": {"used_percentage": 2, "resets_at": next_week}}, **MODEL_OPUS
    )
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra"), NOW)
    assert (plan[0].percent, plan[0].resets_at) == (2, next_week)


def test_stdin_window_missing_from_endpoint_kept():
    session = make_session(
        rate_limits={
            "five_hour": {"used_percentage": 30, "resets_at": NOW + 600},
            "seven_day": {"used_percentage": 17, "resets_at": 1793948400},
        },
        **MODEL_FABLE,
    )
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra"), NOW)
    assert labels(plan) == ["5h", "7d", "Fable"]


# ---- full windows ----


def full_week(data):
    data["limits"][0]["percent"] = 100
    return data


def test_full_window_is_just_full():
    """At 100% a window is a full bar, credits or not: no blocked state to work out."""
    for fixture in ("ultra", "ultra-credits-off"):
        data = full_week(usage_fixture(fixture))
        plan = usage.plan_bars(make_session(rate_limits=None, **MODEL_OPUS), ULTRA, data, NOW)
        assert (plan[0].label, plan[0].percent) == ("7d", 100)


def test_credits_past_100_keep_counting():
    data = usage_fixture("ultra")
    data["spend"].update(percent=130)
    data["spend"]["used"]["amount_minor"] = 26000
    plan = usage.plan_bars(make_session(rate_limits=None, **MODEL_OPUS), ULTRA, data, NOW)
    assert (plan[-1].label, plan[-1].percent) == ("credits", 130)


def test_enterprise_cap_full():
    data = usage_fixture("enterprise")
    data["spend"]["percent"] = 100
    plan = usage.plan_bars(make_session(rate_limits=None), ENTERPRISE, data, NOW)
    assert summary(plan) == [("month", 100, None)]


# ---- gateway spend limit ----


def test_gateway_spend_limit_bar():
    session = make_session(
        rate_limits={
            "seven_day": None,
            "spend_limit": {"used_percentage": 40, "resets_at": NOW + 86400},
        }
    )
    plan = usage.plan_bars(session, Account("api", "Gateway"), None, NOW)
    assert summary(plan) == [("month", 40, NOW + 86400)]


@pytest.mark.parametrize(
    ("period", "label"), [("weekly", "week"), ("month", "month"), ("x", "month")]
)
def test_gateway_period_label(period, label):
    session = make_session(
        rate_limits={"seven_day": None, "spend_limit": {"used_percentage": 1, "period": period}}
    )
    assert labels(usage.plan_bars(session, Account("api", "Gateway"), None, NOW)) == [label]


# ---- the cache as a render reads it ----


def write_cache(home, fetched_at=NOW - 10, who="abc", data=None):
    path = home / ".claude" / "cache" / "statusline"
    path.mkdir(parents=True, exist_ok=True)
    body = {"fetched_at": fetched_at, "account": who, "data": data or usage_fixture("ultra")}
    (path / "usage.json").write_text(json.dumps(body))


def write_hold(home, until, who="abc", **extra):
    path = home / ".claude" / "cache" / "statusline"
    path.mkdir(parents=True, exist_ok=True)
    (path / "fetch.hold").write_text(json.dumps({"until": until, "account": who, **extra}))


def test_load_api_reads_nothing(isolated_home):
    write_cache(isolated_home)
    state = usage.load(env_for(isolated_home), Account("api", "API"), NOW)
    assert (state.data, state.fetch) == (None, False)


def test_load_no_cache_wants_fetch(isolated_home):
    state = usage.load(env_for(isolated_home), ULTRA, NOW)
    assert (state.data, state.fetch, state.stale_age) == (None, True, None)


def test_load_fresh_cache(isolated_home):
    write_cache(isolated_home)
    state = usage.load(env_for(isolated_home), ULTRA, NOW)
    assert state.data["limits"]
    assert (state.age, state.fetch, state.stale_age) == (10, False, None)


def test_load_old_cache_refetches_then_tags(isolated_home):
    write_cache(isolated_home, fetched_at=NOW - usage.FRESH)
    state = usage.load(env_for(isolated_home), ULTRA, NOW)
    assert state.fetch and state.data and state.stale_age is None
    write_cache(isolated_home, fetched_at=NOW - usage.STALE - 1)
    assert usage.load(env_for(isolated_home), ULTRA, NOW).stale_age == usage.STALE + 1


def test_load_ignores_another_login(isolated_home):
    write_cache(isolated_home, who="someone-else")
    state = usage.load(env_for(isolated_home), ULTRA, NOW)
    assert (state.data, state.fetch) == (None, True)


def test_load_drops_day_old_data(isolated_home):
    write_cache(isolated_home, fetched_at=NOW - usage.MAX_AGE - 1)
    assert usage.load(env_for(isolated_home), ULTRA, NOW).data is None


def test_load_future_timestamp_is_age_zero(isolated_home):
    write_cache(isolated_home, fetched_at=NOW + 100)
    assert usage.load(env_for(isolated_home), ULTRA, NOW).age == 0


@pytest.mark.parametrize("text", ["", "{", "[]", '{"fetched_at": "x", "data": {}}'])
def test_load_broken_cache(isolated_home, text):
    path = isolated_home / ".claude" / "cache" / "statusline"
    path.mkdir(parents=True)
    (path / "usage.json").write_text(text)
    state = usage.load(env_for(isolated_home), ULTRA, NOW)
    assert (state.data, state.fetch) == (None, True)


def test_hold_blocks_fetch_until_it_ends(isolated_home):
    write_hold(isolated_home, until=NOW + 60)
    assert usage.load(env_for(isolated_home), ULTRA, NOW).fetch is False
    assert usage.load(env_for(isolated_home), ULTRA, NOW + 61).fetch is True


def test_hold_for_another_login_is_ignored(isolated_home):
    write_hold(isolated_home, until=NOW + 60, who="other")
    assert usage.load(env_for(isolated_home), ULTRA, NOW).fetch is True


def test_config_dir_cache_path(tmp_path):
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "conf")}
    assert usage.cache_dir(env) == str(tmp_path / "conf" / "cache" / "statusline")


# ---- the lock ----


def test_lock_is_exclusive(isolated_home):
    env = env_for(isolated_home)
    assert usage.take_lock(env, NOW)
    assert not usage.take_lock(env, NOW + 1)
    assert usage.take_lock(env, NOW + usage.LOCK_STALE)  # its child died


def test_lock_without_content_uses_mtime(isolated_home):
    import time

    env = env_for(isolated_home)
    path = isolated_home / ".claude" / "cache" / "statusline"
    path.mkdir(parents=True)
    (path / "fetch.lock").write_text("")
    now = time.time()
    assert not usage.take_lock(env, now)
    assert usage.take_lock(env, now + usage.LOCK_STALE + 5)


def test_lock_race_one_winner(isolated_home):
    env = env_for(isolated_home)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(usage.take_lock(env, NOW))) for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1


def test_spawn_starts_a_detached_child_without_the_token(isolated_home, monkeypatch):
    import subprocess

    seen = {}

    class FakePopen:
        def __init__(self, argv, **kwargs):
            seen["argv"], seen["kwargs"] = argv, kwargs

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    env = env_for(isolated_home)
    env["CLAUDE_CODE_OAUTH_TOKEN"] = "secret-token"
    assert REAL_SPAWN(env, NOW)
    assert not any("secret-token" in a for a in seen["argv"])
    assert seen["argv"][1:4] == ["-I", "-S", "-c"]
    assert seen["kwargs"]["stdout"] is subprocess.DEVNULL
    assert seen["kwargs"]["start_new_session"] is True
    assert not REAL_SPAWN(env, NOW + 1)  # the lock is held until the child ends


def test_child_releases_the_lock(isolated_home, monkeypatch):
    monkeypatch.setattr(usage, "refresh", lambda env, now: 1 / 0)
    env = env_for(isolated_home)
    assert usage.take_lock(env, NOW)
    usage.child()
    assert usage.take_lock(env, NOW + 1)


# ---- fetching against a local server ----


def cache_files(env):
    path = usage.cache_dir(env)
    return {name: read_json_path(f"{path}/{name}") for name in ("usage.json", "fetch.hold")}


def read_json_path(path):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else None


def test_fetch_ok_writes_cache(server, logged_in):
    server.reply(200, json.dumps(usage_fixture("ultra")))
    assert usage.refresh(logged_in, NOW, server.url, "linux") == "ok"
    path, headers = server.requests[0]
    assert path == "/api/oauth/usage"
    assert headers["Authorization"] == "Bearer tok-123"
    assert headers["anthropic-beta"] == "oauth-2025-04-20"
    assert headers["User-Agent"].startswith("dashline/")
    files = cache_files(logged_in)
    assert files["usage.json"]["fetched_at"] == NOW
    assert files["usage.json"]["account"] == account.identity(logged_in)
    assert files["usage.json"]["data"] == usage_fixture("ultra")
    assert files["fetch.hold"] is None


def test_token_never_written(server, logged_in):
    server.reply(500)
    usage.refresh(logged_in, NOW, server.url, "linux")
    server.reply(200, "{}")
    usage.refresh(logged_in, NOW + 999, server.url, "linux")
    for path in Path(usage.cache_dir(logged_in)).iterdir():
        assert "tok-123" not in path.read_text()


def test_fetch_ok_clears_hold_and_render_sees_it(server, logged_in):
    write_hold(logged_in_home(logged_in), until=NOW - 1, who=account.identity(logged_in))
    server.reply(200, json.dumps(usage_fixture("ultra")))
    usage.refresh(logged_in, NOW, server.url, "linux")
    assert cache_files(logged_in)["fetch.hold"] is None
    acct = account.load(logged_in, make_session())
    state = usage.load(logged_in, acct, NOW + 5)
    assert state.data == usage_fixture("ultra")
    assert state.fetch is False


def logged_in_home(env):
    return Path(env["HOME"])


@pytest.mark.parametrize(
    ("status", "wait", "words"),
    [(401, 300, "401"), (403, 3600, "403"), (404, 6 * 3600, "404")],
)
def test_fixed_holds(server, logged_in, status, wait, words):
    server.reply(status, "{}")
    reason = usage.refresh(logged_in, NOW, server.url, "linux")
    held = cache_files(logged_in)["fetch.hold"]
    assert held["until"] == NOW + wait
    assert reason == held["reason"]
    assert words in reason
    assert cache_files(logged_in)["usage.json"] is None


def test_backoff_doubles_and_caps(server, logged_in):
    waits = []
    now = NOW
    for _ in range(7):
        server.reply(503)
        usage.refresh(logged_in, now, server.url, "linux")
        held = cache_files(logged_in)["fetch.hold"]
        waits.append(held["until"] - now)
        now = held["until"]
    assert waits == [60, 120, 240, 480, 960, 1800, 1800]
    assert held["reason"] == "HTTP 503"


def test_rate_limited_honors_retry_after(server, logged_in):
    server.reply(429, "", **{"Retry-After": "900"})
    usage.refresh(logged_in, NOW, server.url, "linux")
    assert cache_files(logged_in)["fetch.hold"]["until"] == NOW + 900


@pytest.mark.parametrize("body", ["not json", "[1]", ""])
def test_unreadable_answer_backs_off(server, logged_in, body):
    server.reply(200, body)
    assert usage.refresh(logged_in, NOW, server.url, "linux") == "unreadable answer"
    assert cache_files(logged_in)["fetch.hold"]["until"] == NOW + 60
    assert cache_files(logged_in)["usage.json"] is None


def test_network_failure_backs_off(logged_in):
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nothing listens here now
    reason = usage.refresh(logged_in, NOW, f"http://127.0.0.1:{port}", "linux")
    assert reason == "no answer (network)"
    assert cache_files(logged_in)["fetch.hold"]["until"] == NOW + 60


def test_failure_keeps_old_cache(server, logged_in):
    server.reply(200, json.dumps(usage_fixture("ultra")))
    usage.refresh(logged_in, NOW, server.url, "linux")
    server.reply(500)
    usage.refresh(logged_in, NOW + 200, server.url, "linux")
    assert cache_files(logged_in)["usage.json"]["fetched_at"] == NOW


def test_no_login_holds_without_calling(server, isolated_home):
    env = env_for(isolated_home)
    reason = usage.refresh(env, NOW, server.url, "linux")
    assert reason == "no Claude login found"
    assert cache_files(env)["fetch.hold"]["until"] == NOW + 600
    assert server.requests == []


def test_expired_token_holds_without_calling(server, logged_in):
    creds = {"claudeAiOauth": {"accessToken": "old", "expiresAt": NOW * 1000}}
    (logged_in_home(logged_in) / ".claude" / ".credentials.json").write_text(json.dumps(creds))
    reason = usage.refresh(logged_in, NOW, server.url, "linux")
    assert reason.startswith("token expired")
    assert cache_files(logged_in)["fetch.hold"]["until"] == NOW + 300
    assert server.requests == []


def test_cache_files_are_private(server, logged_in):
    import stat

    server.reply(200, "{}")
    usage.refresh(logged_in, NOW, server.url, "linux")
    path = Path(usage.cache_dir(logged_in))
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert stat.S_IMODE((path / "usage.json").stat().st_mode) == 0o600
    assert [p.name for p in path.iterdir() if p.suffix == ".tmp"] == []
