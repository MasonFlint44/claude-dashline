"""Usage cache, lock, hold, fetch (against a local server) and plan bars (usage.py)."""

import json
import threading
from pathlib import Path

import pytest

from conftest import FIXTURES, NOW, REAL_SPAWN, Server, env_for, make_session, read_json
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


def test_unused_scoped_bar_hidden_on_another_model():
    session = make_session(rate_limits=None, **MODEL_OPUS)
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra-credits-off"), NOW)  # Fable 0%
    assert labels(plan) == ["7d"]


def test_used_scoped_bar_shown_on_another_model():
    """Subagents and other sessions spend the Fable week while you're on Opus."""
    session = make_session(rate_limits=None, **MODEL_OPUS)
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra"), NOW)  # Fable 24%
    assert [(b.label, b.percent) for b in plan] == [("7d", 17), ("Fable", 24)]


def test_scoped_bar_hides_again_after_its_reset():
    session = make_session(rate_limits=None, **MODEL_OPUS)
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra"), ULTRA_FABLE_RESET + 10)
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
    plan = usage.plan_bars(session, ULTRA, usage_fixture("ultra-credits-off"), NOW)
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
    assert labels(plan) == ["7d", "Fable", "daily burst"]


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


def test_endpoint_labels_are_cleaned():
    data = {
        "limits": [
            {"kind": "odd\x1b]8;;x", "percent": 5},
            {"kind": "weekly_scoped", "percent": 5, "scope": {"model": {"display_name": "F\na"}}},
        ]
    }
    plan = usage.plan_bars(make_session(rate_limits=None), ULTRA, data, NOW)
    assert labels(plan) == ["odd?]8;;x", "F?a"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 1e400])
def test_non_finite_numbers_hide_the_bar(bad):
    data = json.loads(
        json.dumps(
            {
                "limits": [{"kind": "weekly_all", "percent": bad}],
                "spend": {"enabled": True, "percent": bad, "used": {"amount_minor": 5}},
            }
        )
    )
    assert usage.plan_bars(make_session(rate_limits=None), ULTRA, data, NOW) == []


@pytest.mark.parametrize("exponent", [400, -400, 1e300, "2"])
def test_odd_money_exponent_is_missing(exponent):
    data = {
        "spend": {
            "enabled": True,
            "used": {"amount_minor": 500, "exponent": exponent},
            "limit": {"amount_minor": 1000, "exponent": exponent},
        }
    }
    plan = usage.plan_bars(make_session(rate_limits=None), ULTRA, data, NOW)
    assert all(b.label != "credits" or b.percent == 50 for b in plan)


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


def test_passed_stdin_window_reads_zero():
    """Claude Code resends the last window it saw; once it has reset, it's 0%, not 95%."""
    session = make_session(
        rate_limits={
            "five_hour": {"used_percentage": 95, "resets_at": NOW - 10},
            "seven_day": {"used_percentage": 99, "resets_at": NOW - 10},
        },
        **MODEL_OPUS,
    )
    data = usage_fixture("ultra")  # has a live 7d row at 17%, no 5h row
    assert summary(usage.plan_bars(session, ULTRA, data, NOW))[:2] == [
        ("5h", 0, None),
        ("7d", 17, pytest.approx(ULTRA_7D_RESET)),
    ]
    assert summary(usage.plan_bars(session, None, None, NOW)) == [("5h", 0, None), ("7d", 0, None)]


def test_passed_gateway_spend_limit_reads_zero():
    session = make_session(
        rate_limits={"spend_limit": {"used_percentage": 90, "resets_at": NOW - 1, "period": "day"}}
    )
    assert summary(usage.plan_bars(session, None, None, NOW))[-1] == ("month", 0, None)


def test_stdin_only_bars_without_an_account():
    session = make_session(
        rate_limits={"five_hour": {"used_percentage": 30, "resets_at": NOW + 600}}, **MODEL_OPUS
    )
    assert summary(usage.plan_bars(session, None, None, NOW))[0] == ("5h", 30, NOW + 600)


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


def cache_folder(home):
    path = home / ".claude" / "cache" / "statusline"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_cache(home, fetched_at=NOW - 10, who="abc", data=None, file_who=None):
    """`file_who`: whose file it goes in, when that isn't `who`."""
    body = {"fetched_at": fetched_at, "account": who, "data": data or usage_fixture("ultra")}
    name = usage.cache_name(who if file_who is None else file_who)
    (cache_folder(home) / name).write_text(json.dumps(body))


def write_hold(home, until, who="abc", file_who=None, **extra):
    name = usage.hold_name(who if file_who is None else file_who)
    (cache_folder(home) / name).write_text(json.dumps({"until": until, "account": who, **extra}))


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


def test_load_ignores_another_login_in_its_file(isolated_home):
    """The file name says whose it is, and so does its content: both must agree."""
    write_cache(isolated_home, who="someone-else", file_who="abc")
    state = usage.load(env_for(isolated_home), ULTRA, NOW)
    assert (state.data, state.fetch) == (None, True)


def test_load_ignores_the_shared_file_of_older_versions(isolated_home):
    body = {"fetched_at": NOW - 10, "account": "abc", "data": usage_fixture("ultra")}
    (cache_folder(isolated_home) / "usage.json").write_text(json.dumps(body))
    state = usage.load(env_for(isolated_home), ULTRA, NOW)
    assert (state.data, state.fetch) == (None, True)


@pytest.mark.parametrize(
    ("who", "tag"),
    [
        ("0123456789abcdef", "0123456789abcdef"),
        ("env-0123456789abcdef", "env-0123456789abcdef"),
        (None, "unknown"),
    ],
)
def test_file_names_are_the_fingerprint(who, tag):
    assert usage.cache_name(who) == f"usage-{tag}.json"
    assert usage.hold_name(who) == f"fetch-{tag}.hold"


@pytest.mark.parametrize("who", ["../../etc/x", "a/b", "me@example.com", "", "x" * 65, "é"])
def test_odd_fingerprints_are_hashed_in_file_names(who):
    name = usage.cache_name(who)
    tag = name[len("usage-") : -len(".json")]
    assert len(tag) == 16 and all(c in "0123456789abcdef" for c in tag)
    assert usage.cache_name(who) == name  # stable


def test_own_files():
    tag = "0123456789abcdef"
    names = [
        f"usage-{tag}.json",
        f"fetch-env-{tag}.hold",
        "usage-unknown.json",
        "fetch.lock",
        "fetch.lock.break",
        "usage.json",
        "fetch.hold",
        f"usage-{tag}.json.123.tmp",
        f"fetch-{tag}.hold.9.tmp",
        "plan-usage",
        "other.json",
        "usage-notes.txt",
        "usage-notes.json",  # another tool's, in a shared folder: not a tag dashline writes
        f"usage-{tag.upper()}.json",
    ]
    assert usage.own_files(names) == sorted(names[:9])


def test_load_drops_day_old_data(isolated_home):
    write_cache(isolated_home, fetched_at=NOW - usage.MAX_AGE - 1)
    assert usage.load(env_for(isolated_home), ULTRA, NOW).data is None


def test_load_slightly_future_timestamp_is_age_zero(isolated_home):
    write_cache(isolated_home, fetched_at=NOW + usage.CLOCK_SLACK)
    state = usage.load(env_for(isolated_home), ULTRA, NOW)
    assert (state.age, state.fetch) == (0, False)


def test_load_after_the_clock_was_set_back_refetches(isolated_home):
    """Data fetched an hour "from now" would otherwise stay fresh for an hour."""
    write_cache(isolated_home, fetched_at=NOW + 3600)
    state = usage.load(env_for(isolated_home), ULTRA, NOW)
    assert state.data and state.fetch
    assert (state.age, state.stale_age) == (None, None)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e400"])
def test_load_non_finite_fetch_time_is_broken(isolated_home, value):
    (cache_folder(isolated_home) / usage.cache_name("abc")).write_text(
        '{"fetched_at": ' + value + ', "account": "abc", "data": {"limits": []}}'
    )
    state = usage.load(env_for(isolated_home), ULTRA, NOW)
    assert (state.data, state.fetch) == (None, True)


@pytest.mark.parametrize("text", ["", "{", "[]", '{"fetched_at": "x", "data": {}}', "[" * 100000])
def test_load_broken_cache(isolated_home, text):
    (cache_folder(isolated_home) / usage.cache_name("abc")).write_text(text)
    state = usage.load(env_for(isolated_home), ULTRA, NOW)
    assert (state.data, state.fetch) == (None, True)


def test_hold_blocks_fetch_until_it_ends(isolated_home):
    write_hold(isolated_home, until=NOW + 60)
    assert usage.load(env_for(isolated_home), ULTRA, NOW).fetch is False
    assert usage.load(env_for(isolated_home), ULTRA, NOW + 61).fetch is True


def test_hold_for_another_login_is_ignored(isolated_home):
    write_hold(isolated_home, until=NOW + 60, who="other")
    assert usage.load(env_for(isolated_home), ULTRA, NOW).fetch is True
    write_hold(isolated_home, until=NOW + 60, who="other", file_who="abc")
    assert usage.load(env_for(isolated_home), ULTRA, NOW).fetch is True


def test_hold_written_after_now_is_ignored(isolated_home):
    """The clock was set back: a 60 s hold written "later" must not last an hour."""
    write_hold(isolated_home, until=NOW + 3660, at=NOW + 3600)
    assert usage.load(env_for(isolated_home), ULTRA, NOW).fetch is True


def test_hold_longer_than_any_dashline_writes_is_ignored(isolated_home):
    write_hold(isolated_home, until=NOW + usage.RETRY_MAX + 3600)
    assert usage.load(env_for(isolated_home), ULTRA, NOW).fetch is True
    write_hold(isolated_home, until=NOW + usage.RETRY_MAX)
    assert usage.load(env_for(isolated_home), ULTRA, NOW).fetch is False


@pytest.mark.parametrize("until", ["soon", None, float("nan")])
def test_odd_hold_is_no_hold(isolated_home, until):
    write_hold(isolated_home, until=until)
    assert usage.hold(env_for(isolated_home), "abc", NOW) is None


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


def lock_race(env, now, n=8):
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(usage.take_lock(env, now))) for _ in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return [r for r in results if r]


def test_lock_race_one_winner(isolated_home):
    """On the real clock: a lock still being written is judged by its mtime, and a fake
    `now` hours before that would make it look like one from the future."""
    import time

    for _ in range(30):
        env = env_for(isolated_home)
        assert len(lock_race(env, time.time())) == 1
        usage._remove(usage._path(env, "fetch.lock"))


def test_stale_lock_race_one_winner(isolated_home):
    """Several renders find the same dead child's lock: only one may break it and fetch.

    On the real clock, since a lock being written is judged by its mtime."""
    import time

    env = env_for(isolated_home)
    for _ in range(30):
        now = time.time()
        assert usage.take_lock(env, now - usage.LOCK_STALE)
        assert len(lock_race(env, now)) == 1
        usage._remove(usage._path(env, "fetch.lock"))
    assert sorted(p.name for p in Path(usage.cache_dir(env)).iterdir()) == []


def test_breaking_a_stale_lock_leaves_a_newer_one(isolated_home):
    """Another render broke the stale lock first and took a new one (maybe on the same
    inode): that one stays."""
    env = env_for(isolated_home)
    path = usage._path(env, "fetch.lock")
    usage.take_lock(env, NOW)
    stale = usage._lock_id(path)[0]
    Path(path).unlink()
    live = usage.take_lock(env, NOW + usage.LOCK_STALE)  # the other render's lock
    usage._break_lock(path, stale, NOW + usage.LOCK_STALE)
    assert json.loads(Path(path).read_text())["nonce"] == live
    assert sorted(p.name for p in Path(path).parent.iterdir()) == ["fetch.lock"]


def test_breaker_that_died_doesnt_block_forever(isolated_home):
    import os

    env = env_for(isolated_home)
    usage.take_lock(env, NOW)
    guard = Path(usage._path(env, "fetch.lock.break"))
    guard.write_text("")
    os.utime(guard, (NOW + 30, NOW + 30))
    assert not usage.take_lock(env, NOW + usage.LOCK_STALE)  # a breaker is at work
    assert usage.take_lock(env, NOW + 30 + usage.LOCK_STALE)  # it died: guard and lock go
    assert not guard.exists()


def test_lock_from_after_now_is_stale(isolated_home):
    """The clock was set back an hour: the lock must not block fetches for that hour."""
    env = env_for(isolated_home)
    assert usage.take_lock(env, NOW + 3600)
    assert usage.take_lock(env, NOW)


def test_release_only_removes_its_own_lock(isolated_home):
    env = env_for(isolated_home)
    old = usage.take_lock(env, NOW)
    new = usage.take_lock(env, NOW + usage.LOCK_STALE)  # old's child took too long
    usage.release(env, old)
    assert json.loads(Path(usage._path(env, "fetch.lock")).read_text())["nonce"] == new
    usage.release(env, new)
    assert not Path(usage._path(env, "fetch.lock")).exists()


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
    nonce = json.loads(Path(usage._path(env, "fetch.lock")).read_text())["nonce"]
    assert seen["argv"][-1] == nonce
    assert seen["kwargs"]["stdout"] is subprocess.DEVNULL
    assert seen["kwargs"]["start_new_session"] is True
    assert not REAL_SPAWN(env, NOW + 1)  # the lock is held until the child ends


def test_child_releases_the_lock_and_holds_on_a_surprise(isolated_home, monkeypatch):
    """A failure refresh didn't foresee still backs off: no refetch on every render."""
    import os
    import time

    monkeypatch.setattr(usage, "refresh", lambda env, now: 1 / 0)
    monkeypatch.setattr(os, "environ", env_for(isolated_home))
    env = env_for(isolated_home)
    nonce = usage.take_lock(env, time.time())
    usage.child(nonce)
    assert not Path(usage._path(env, "fetch.lock")).exists()
    held = usage.hold(env, None)
    assert held["reason"] == "fetch failed (ZeroDivisionError)"
    acct = Account("subscription", fingerprint=None)
    assert usage.load(env, acct, time.time()).fetch is False


def fresh_credentials(env):
    """A token valid on the real clock, for code that reads time.time()."""
    import time

    creds = {"claudeAiOauth": {"accessToken": "tok-123", "expiresAt": (time.time() + 86400) * 1000}}
    (Path(env["HOME"]) / ".claude" / ".credentials.json").write_text(json.dumps(creds))


def test_child_fetches_and_writes_the_cache(server, logged_in, monkeypatch):
    """child() as the spawned process runs it, against the local server."""
    import os
    import time

    monkeypatch.setattr(usage, "API_URL", server.url)
    monkeypatch.setattr(os, "environ", logged_in)
    fresh_credentials(logged_in)
    server.reply(200, json.dumps(usage_fixture("ultra")))
    nonce = usage.take_lock(logged_in, time.time())
    usage.child(nonce)
    assert cache_files(logged_in)["cache"]["data"] == usage_fixture("ultra")
    assert not Path(usage._path(logged_in, "fetch.lock")).exists()


@pytest.mark.parametrize("what", ["fresh cache", "hold"])
def test_child_skips_when_another_child_got_there_first(server, logged_in, monkeypatch, what):
    """Two renders read a stale cache; the first child fetches and releases the lock
    before the second render takes it. The second child must not fetch again."""
    import os
    import time

    monkeypatch.setattr(usage, "API_URL", server.url)
    monkeypatch.setattr(os, "environ", logged_in)
    fresh_credentials(logged_in)
    now, who = time.time(), account.identity(logged_in)
    if what == "fresh cache":
        write_cache(logged_in_home(logged_in), fetched_at=now - 5, who=who)
    else:
        write_hold(logged_in_home(logged_in), until=now + 600, who=who)
    nonce = usage.take_lock(logged_in, now)
    usage.child(nonce)
    assert server.requests == []
    assert not Path(usage._path(logged_in, "fetch.lock")).exists()


def test_spawn_releases_the_lock_when_the_child_cant_start(isolated_home, monkeypatch):
    import subprocess

    def broken(*args, **kwargs):
        raise OSError("no python")

    monkeypatch.setattr(subprocess, "Popen", broken)
    env = env_for(isolated_home)
    assert REAL_SPAWN(env, NOW) is False
    assert not Path(usage._path(env, "fetch.lock")).exists()


def test_spawned_child_runs_and_backs_off(logged_in):
    """The real detached process: no network here (the proxy is a dead port), so it
    writes a hold and releases the lock. The token comes from the environment, so on a
    Mac the child never asks the real Keychain (a monkeypatch can't reach it)."""
    import os
    import time

    env = dict(logged_in, HTTPS_PROXY="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9")
    env["CLAUDE_CODE_OAUTH_TOKEN"] = "tok-env"
    env["PATH"] = os.environ.get("PATH", "")
    assert REAL_SPAWN(env, time.time())
    lock = Path(usage._path(env, "fetch.lock"))
    deadline = time.time() + 20
    while lock.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert not lock.exists()
    held = usage.hold(env, account.identity(env))
    assert held["reason"] == "no answer (network)"
    assert cache_files(env)["cache"] is None


# ---- fetching against a local server ----


def cache_files(env, who=...):
    """{"cache": ..., "hold": ...} of the login `who` (by default, the one `env` is in)."""
    who = account.identity(env) if who is ... else who
    path = usage.cache_dir(env)
    return {
        "cache": read_json_path(f"{path}/{usage.cache_name(who)}"),
        "hold": read_json_path(f"{path}/{usage.hold_name(who)}"),
    }


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
    assert files["cache"]["fetched_at"] == NOW
    assert files["cache"]["account"] == account.identity(logged_in)
    assert files["cache"]["data"] == usage_fixture("ultra")
    assert files["hold"] is None


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
    assert cache_files(logged_in)["hold"] is None
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
    held = cache_files(logged_in)["hold"]
    assert held["until"] == NOW + wait
    assert held["server"] is False
    assert reason == held["reason"]
    assert words in reason
    assert cache_files(logged_in)["cache"] is None


@pytest.mark.parametrize(
    ("status", "header", "wait", "server_set"),
    [
        (403, "7200", 7200, True),  # longer than the fixed hour: the server's wins
        (401, "60", 300, False),  # shorter than the fixed wait: ours wins
        (404, "9" * 50, 86400, True),  # capped at a day, still the server's
    ],
)
def test_fixed_holds_honor_a_longer_retry_after(
    server, logged_in, status, header, wait, server_set
):
    server.reply(status, "{}", **{"Retry-After": header})
    usage.refresh(logged_in, NOW, server.url, "linux")
    held = cache_files(logged_in)["hold"]
    assert held["until"] == NOW + wait
    assert held["server"] is server_set


def test_backoff_doubles_and_caps(server, logged_in):
    waits = []
    now = NOW
    for _ in range(7):
        server.reply(503)
        usage.refresh(logged_in, now, server.url, "linux")
        held = cache_files(logged_in)["hold"]
        waits.append(held["until"] - now)
        now = held["until"]
    assert waits == [60, 120, 240, 480, 960, 1800, 1800]
    assert held["reason"] == "HTTP 503"


def test_rate_limited_honors_retry_after(server, logged_in):
    server.reply(429, "", **{"Retry-After": "900"})
    usage.refresh(logged_in, NOW, server.url, "linux")
    held = cache_files(logged_in)["hold"]
    assert held["until"] == NOW + 900
    assert held["server"] is True  # doctor won't fetch through it unless asked


def test_short_retry_after_is_our_backoff(server, logged_in):
    server.reply(429, "", **{"Retry-After": "5"})
    usage.refresh(logged_in, NOW, server.url, "linux")
    held = cache_files(logged_in)["hold"]
    assert (held["until"], held["server"]) == (NOW + 60, False)


def test_two_logins_keep_their_own_cache_and_hold(server, logged_in):
    """One session on CLAUDE_CODE_OAUTH_TOKEN, another on the stored login: neither
    undoes the other's numbers or the wait the server asked of it."""
    other = dict(logged_in, CLAUDE_CODE_OAUTH_TOKEN="tok-other")
    assert account.identity(other) != account.identity(logged_in)

    server.reply(429, "", **{"Retry-After": "3600"})
    usage.refresh(other, NOW, server.url, "linux")
    server.reply(200, json.dumps(usage_fixture("ultra")))
    assert usage.refresh(logged_in, NOW + 1, server.url, "linux") == "ok"
    server.reply(403, "{}")
    usage.refresh(logged_in, NOW + 200, server.url, "linux")
    server.reply(200, json.dumps(usage_fixture("ultra-credits-off")))
    usage.refresh(logged_in, NOW + 400, server.url, "linux")

    assert server.requests[0][1]["Authorization"] == "Bearer tok-other"
    mine, theirs = cache_files(logged_in), cache_files(other)
    assert mine["cache"]["data"] == usage_fixture("ultra-credits-off")
    assert mine["hold"] is None  # its success removed its own hold
    assert theirs["cache"] is None
    assert theirs["hold"]["until"] == NOW + 3600  # and left this one alone
    acct = account.load(other, make_session())
    assert usage.load(other, acct, NOW + 500).fetch is False


def test_success_removes_the_shared_files_of_older_versions(server, logged_in):
    folder = Path(usage.cache_dir(logged_in))
    folder.mkdir(parents=True)
    (folder / "usage.json").write_text("{}")
    (folder / "fetch.hold").write_text("{}")
    (folder / "plan-usage").write_text("{}")  # another tool's
    server.reply(200, "{}")
    usage.refresh(logged_in, NOW, server.url, "linux")
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["plan-usage", usage.cache_name(account.identity(logged_in))]


def test_old_files_of_unused_logins_are_removed(server, logged_in):
    import os

    folder = Path(usage.cache_dir(logged_in))
    folder.mkdir(parents=True)
    gone, recent = "a" * 16, "b" * 16
    old, held = folder / f"usage-{gone}.json", folder / f"fetch-{recent}.hold"
    other = folder / "usage-notes.json"  # not a name dashline writes: never removed
    for path in (old, held, other, folder / f"fetch-env-{gone}.hold"):
        path.write_text("{}")
    long_ago = NOW - usage.MAX_AGE - usage.CLOCK_SLACK - 10
    for path in (old, other, folder / f"fetch-env-{gone}.hold"):
        os.utime(path, (long_ago, long_ago))
    os.utime(held, (NOW - 3600, NOW - 3600))
    server.reply(503)
    usage.refresh(logged_in, NOW, server.url, "linux")
    names = sorted(p.name for p in folder.iterdir())
    expected = [held.name, other.name, usage.hold_name(account.identity(logged_in))]
    assert names == sorted(expected)


def test_deadline_bounds_a_trickling_answer():
    """A server sending a byte at a time never trips the per-read timeout."""
    import contextlib
    import socket
    import threading
    import time

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    stop = threading.Event()

    def trickle():
        conn, _ = listener.accept()
        with conn:
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
            while not stop.is_set():
                with contextlib.suppress(OSError):
                    conn.sendall(b" ")
                time.sleep(0.05)

    threading.Thread(target=trickle, daemon=True).start()
    url = f"http://127.0.0.1:{listener.getsockname()[1]}/"
    start = time.monotonic()
    try:
        assert usage.get(url, "tok", timeout=2, now=NOW, deadline=0.5) == (0, None, None)
        assert time.monotonic() - start < 2
    finally:
        stop.set()
        listener.close()


def test_deeply_nested_answer_is_unreadable(server, logged_in):
    server.reply(200, "[" * 200000)
    assert usage.refresh(logged_in, NOW, server.url, "linux") == "unreadable answer"


@pytest.mark.parametrize(
    ("status", "header", "wait"),
    [
        (429, "7200", 7200),  # past the 30 min backoff cap: still honored
        (429, "9" * 5000, 86400),  # nonsense: capped at a day
        (503, "600", 600),
        (429, "soon", 60),  # unreadable: normal backoff
        (429, "²", 60),
    ],
)
def test_retry_after_seconds(server, logged_in, status, header, wait):
    server.reply(status, "", **{"Retry-After": header})
    usage.refresh(logged_in, NOW, server.url, "linux")
    assert cache_files(logged_in)["hold"]["until"] == NOW + wait


def test_retry_after_http_date(server, logged_in):
    from email.utils import formatdate

    server.reply(429, "", **{"Retry-After": formatdate(NOW + 5400, usegmt=True)})
    usage.refresh(logged_in, NOW, server.url, "linux")
    assert cache_files(logged_in)["hold"]["until"] == NOW + 5400


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        ("120", 120),
        (" 0 ", 0),
        ("Thu, 05 Nov 2026 01:00:00 GMT", 3600),
        ("Wed, 04 Nov 2026 23:00:00 GMT", 0),  # already past
        ("", None),
        (None, None),
        ("-5", None),
        ("Thu, 99 Nov 2026 01:00:00 GMT", None),
    ],
)
def test_retry_after_parsing(value, seconds):
    assert usage.retry_after(value, NOW) == seconds


def test_retry_after_date_without_a_zone_is_utc():
    """`-0000` means "zone unknown": parsedate_to_datetime gives a naive time."""
    assert usage.retry_after("Thu, 05 Nov 2026 01:00:00 -0000", NOW) == 3600


def test_retry_after_date_parser_giving_none(monkeypatch):
    import email.utils

    monkeypatch.setattr(email.utils, "parsedate_to_datetime", lambda value: None)
    assert usage.retry_after("Thu, 05 Nov 2026 01:00:00 GMT", NOW) is None


def test_cut_off_answer_backs_off(server, logged_in):
    """A connection that ends mid-answer raises IncompleteRead, not an OSError."""
    server.reply(200, "a\r\n{}", **{"Transfer-Encoding": "chunked"})
    assert usage.refresh(logged_in, NOW, server.url, "linux") == "no answer (network)"
    assert cache_files(logged_in)["hold"]["until"] == NOW + 60


def test_redirect_is_refused_and_keeps_the_token(server, logged_in):
    other = Server()
    try:
        server.reply(302, "", Location=other.url + "/steal")
        other.reply(200, "{}")
        reason = usage.refresh(logged_in, NOW, server.url, "linux")
        assert reason == "redirect refused (HTTP 302)"
        assert other.requests == []
        assert cache_files(logged_in)["hold"]["until"] == NOW + 60
    finally:
        other.httpd.shutdown()
        other.httpd.server_close()


def test_oversized_answer_is_unreadable(server, logged_in):
    server.reply(200, '{"x": "' + "a" * usage.MAX_BODY + '"}')
    assert usage.refresh(logged_in, NOW, server.url, "linux") == "unreadable answer"


def test_huge_failure_count_is_clamped(server, logged_in):
    who = account.identity(logged_in)
    write_hold(logged_in_home(logged_in), until=NOW - 1, who=who, failures=1e300)
    server.reply(503)
    usage.refresh(logged_in, NOW, server.url, "linux")
    assert cache_files(logged_in)["hold"]["until"] == NOW + usage.BACKOFF_MAX


@pytest.mark.parametrize("body", ["not json", "[1]", ""])
def test_unreadable_answer_backs_off(server, logged_in, body):
    server.reply(200, body)
    assert usage.refresh(logged_in, NOW, server.url, "linux") == "unreadable answer"
    assert cache_files(logged_in)["hold"]["until"] == NOW + 60
    assert cache_files(logged_in)["cache"] is None


def test_network_failure_backs_off(logged_in):
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nothing listens here now
    reason = usage.refresh(logged_in, NOW, f"http://127.0.0.1:{port}", "linux")
    assert reason == "no answer (network)"
    assert cache_files(logged_in)["hold"]["until"] == NOW + 60


def test_failure_keeps_old_cache(server, logged_in):
    server.reply(200, json.dumps(usage_fixture("ultra")))
    usage.refresh(logged_in, NOW, server.url, "linux")
    server.reply(500)
    usage.refresh(logged_in, NOW + 200, server.url, "linux")
    assert cache_files(logged_in)["cache"]["fetched_at"] == NOW


def test_no_login_holds_without_calling(server, isolated_home):
    env = env_for(isolated_home)
    reason = usage.refresh(env, NOW, server.url, "linux")
    assert reason == "no Claude login found"
    assert cache_files(env)["hold"]["until"] == NOW + 600
    assert server.requests == []


def test_expired_token_holds_without_calling(server, logged_in):
    creds = {"claudeAiOauth": {"accessToken": "old", "expiresAt": NOW * 1000}}
    (logged_in_home(logged_in) / ".claude" / ".credentials.json").write_text(json.dumps(creds))
    reason = usage.refresh(logged_in, NOW, server.url, "linux")
    assert reason.startswith("token expired")
    assert cache_files(logged_in)["hold"]["until"] == NOW + 300
    assert server.requests == []


def test_cache_files_are_private(server, logged_in):
    import stat

    server.reply(200, "{}")
    usage.refresh(logged_in, NOW, server.url, "linux")
    path = Path(usage.cache_dir(logged_in))
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    name = usage.cache_name(account.identity(logged_in))
    assert stat.S_IMODE((path / name).stat().st_mode) == 0o600
    assert [p.name for p in path.iterdir() if p.suffix == ".tmp"] == []
