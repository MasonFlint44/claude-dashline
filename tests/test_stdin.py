import pytest

from conftest import make_session
from dashline import stdin


def test_startup_capture():
    s = make_session("startup")
    assert (s.model, s.effort, s.fast, s.cost) == ("Opus 5.5", "medium", False, 0.0)
    assert s.context_percent is None  # null until the first response
    assert s.cache is None
    assert s.windows == {}
    assert s.project_dir == "/home/user/project"


def test_after_first_response_capture():
    s = make_session()
    assert s.model == "Sonnet 5.5"
    assert s.context_percent == 4
    assert s.cache.observed and s.cache.warm
    assert s.cache.ttl == "1h"
    assert s.cache.recache_tokens == 42281
    assert s.cache.miss_cause is None
    assert set(s.windows) == {"seven_day"}
    assert s.windows["seven_day"].percent == 17


def test_miss_cause_is_the_first_cause():
    s = make_session(prompt_cache={"last_miss_cause": {"causes": ["tools_changed", "x"]}})
    assert s.cache.miss_cause == "tools_changed"


@pytest.mark.parametrize(
    "data",
    [
        {"model": "Opus"},
        {"model": {"display_name": 5}},
        {"cost": {"total_cost_usd": "1.0"}},
        {"cost": {"total_cost_usd": True}},
        {"fast_mode": "yes"},
        {"rate_limits": {"five_hour": {"used_percentage": None}}},
        {"rate_limits": []},
        {"prompt_cache": "warm"},
        {"prompt_cache": {"last_miss_cause": {"causes": [3]}}},
    ],
)
def test_wrong_types_read_as_missing(data):
    s = stdin.Session(data)
    assert s.model is None or isinstance(s.model, str)
    assert s.cost is None
    assert s.fast is False
    assert s.windows == {}
    assert s.cache is None or s.cache.miss_cause is None


def test_model_falls_back_to_id():
    assert stdin.Session({"model": {"id": "claude-x"}}).model == "claude-x"


@pytest.mark.parametrize(
    ("text", "epoch"),
    [
        ("2026-11-06T07:00:00+00:00", 1793948400.0),
        ("2026-11-06T07:00:00Z", 1793948400.0),
        ("2026-11-06T07:00:00", 1793948400.0),
        ("2026-11-06T07:00:00.281290+00:00", 1793948400.28129),
        ("2026-11-06T07:00:00.123456789Z", 1793948400.123456789),
        ("2026-11-06T09:30:00+02:30", 1793948400.0),
        ("2026-11-06T02:00:00-0500", 1793948400.0),
        ("2026-11-06 07:00:00Z", 1793948400.0),
    ],
)
def test_iso_time(text, epoch):
    assert stdin.iso_time(text) == pytest.approx(epoch)


@pytest.mark.parametrize(
    "value", [None, 1793948400, "", "tomorrow", "2026-13-01T00:00:00Z", "2026-11-06"]
)
def test_iso_time_rejects(value):
    assert stdin.iso_time(value) is None


def test_gateway_spend_limit():
    s = stdin.Session(
        {
            "rate_limits": {
                "spend_limit": {"used_percentage": 40, "resets_at": 1793948400, "period": "month"}
            }
        }
    )
    assert (s.spend_limit.percent, s.spend_limit.resets_at, s.spend_limit.period) == (
        40,
        1793948400,
        "month",
    )
    assert (
        stdin.Session({"rate_limits": {"spend_limit": {"used_percentage": "x"}}}).spend_limit
        is None
    )
    assert stdin.Session({}).spend_limit is None


def test_model_id_lowercased():
    assert stdin.Session({"model": {"id": "Claude-Fable-5-1"}}).model_id == "claude-fable-5-1"
    assert stdin.Session({}).model_id == ""
