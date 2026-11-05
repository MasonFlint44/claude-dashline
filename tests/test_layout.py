import pytest

from conftest import NOW, lines_text, make_ctx, make_session
from dashline import layout
from dashline.layout import Bar

BUSY = {
    "prompt_cache": {"expires_at": NOW + 3000},
    "context_window": {"used_percentage": 41},
    "rate_limits": {
        "five_hour": {"used_percentage": 22, "resets_at": NOW + 3600},
        "seven_day": {"used_percentage": 74, "resets_at": NOW + 2 * 86400 + 4 * 3600},
    },
    "fast_mode": True,
    "effort": {"level": "xhigh"},
    "cost": {"total_cost_usd": 11.8},
    "agent": {"name": "code-reviewer"},
}
FOUR = [Bar("5h", 22), Bar("7d", 48), Bar("Fable", 24), Bar("credits", 12)]


def cells(line: str, label: str) -> int:
    """Width of the bar after `label` in a plain line."""
    rest = line.split(label + " ", 1)[1]
    return len(rest) - len(rest.lstrip("▆▁#-"))


# ---- golden lines ----


def test_after_first_response_golden():
    assert lines_text(make_session(), make_ctx(120)) == [
        "Sonnet 5.5 · high · $0.09 │ context ▆▆" + "▁" * 46 + " 4%",
        "7d ▆▆▆▆" + "▁" * 20 + " 17%",
    ]


def test_startup_has_no_bars():
    assert lines_text(make_session("startup"), make_ctx(120)) == ["Opus 5.5 · medium · $0.00"]


def test_busy_golden_120():
    assert lines_text(make_session(**BUSY), make_ctx(120)) == [
        "Sonnet 5.5 · xhigh ↯ · @code-reviewer · $11.80 │ context " + "▆" * 20 + "▁" * 28 + " 41%",
        "5h ▆▆▆▆▆" + "▁" * 19 + " 22%  7d " + "▆" * 18 + "▁" * 6 + " 74% (2d4h)",
    ]


def test_ascii_golden():
    s = make_session(prompt_cache={"warm": False, "last_miss_cause": {"causes": ["tools_changed"]}})
    line = lines_text(s, make_ctx(120, "ascii"))[0]
    assert len(line) == 116
    assert line == (
        "Sonnet 5.5 / high / $0.09 | context ##"
        + "-" * 36
        + " 4% cache cold (tools changed) recache 42k"
    )


# ---- widths ----


@pytest.mark.parametrize("columns", range(10, 201, 3))
@pytest.mark.parametrize("plan_label", [None, "Ultra"])
def test_lines_never_exceed_the_width(columns, plan_label):
    for plan in (None, FOUR, []):
        for glyph_set in ("nerd", "unicode", "ascii"):
            lines = lines_text(make_session(**BUSY), make_ctx(columns, glyph_set), plan, plan_label)
            assert all(len(line) <= columns - layout.RESERVE for line in lines), lines
            assert len(lines) <= 2


def test_plan_bars_share_a_width_and_context_is_double():
    first, second = lines_text(make_session(**BUSY), make_ctx(120), FOUR, "Ultra")
    widths = {cells(second, label) for label in ("5h", "7d", "Fable", "credits")}
    assert widths == {16}
    assert cells(first, "context") == 32


def test_widths_cap_at_24_and_48():
    first, second = lines_text(make_session(**BUSY), make_ctx(200))
    assert cells(second, "5h") == 24
    assert cells(first, "context") == 48


def test_context_alone_takes_up_to_48():
    s = make_session(rate_limits=None)
    assert cells(lines_text(s, make_ctx(200), [])[0], "context") == 48
    assert (
        cells(lines_text(s, make_ctx(70), [])[0], "context") == 66 - 25 - 3 - 11
    )  # text, separator, label and percent


def test_credits_moves_up_only_when_needed():
    at_90 = lines_text(make_session(**BUSY), make_ctx(90), FOUR, "Ultra")
    assert "credits" in at_90[1]
    at_80 = lines_text(make_session(**{**BUSY, "agent": None}), make_ctx(80), FOUR, "Ultra")
    assert "credits" in at_80[0]
    assert "credits" not in at_80[1]
    assert cells(at_80[0], "credits") == cells(at_80[1], "5h")  # keeps the plan width


def test_agent_drops_before_bars_shrink_to_text():
    lines = lines_text(make_session(**BUSY), make_ctx(70))
    assert "@code-reviewer" not in lines[0]
    assert "▆" in lines[0]


def test_text_only_when_nothing_fits_at_8():
    assert lines_text(make_session(**BUSY), make_ctx(50)) == [
        "Sonnet 5.5 · xhigh ↯ · $11.80 │ context 41%",
        "5h 22%  7d 74% (2d4h)",
    ]


def test_extremely_narrow_drops_countdowns_then_cuts():
    assert lines_text(make_session(**BUSY), make_ctx(40)) == [
        "Sonnet 5.5 · xhigh ↯ · $11.80 │ con…",
        "5h 22%  7d 74%",
    ]


def test_plan_label_moves_to_line_1_without_plan_bars():
    lines = lines_text(make_session(rate_limits=None), make_ctx(120), [], "API")
    assert len(lines) == 1
    assert lines[0].startswith("Sonnet 5.5 · high · API · $0.09 │ context")


def test_plan_label_heads_line_2():
    assert lines_text(make_session(), make_ctx(120), None, "Ultra")[1].startswith("Ultra │ 7d ")


def test_missing_columns_uses_default():
    s = make_session(**BUSY)
    assert layout.render(s, make_ctx().g, make_ctx().p, None, NOW) == layout.render(
        s, make_ctx().g, make_ctx().p, 80, NOW
    )


# ---- line 1 pieces ----


@pytest.mark.parametrize(
    ("overrides", "start"),
    [
        ({"fast_mode": True}, "Sonnet 5.5 · high ↯ · $0.09"),
        ({"fast_mode": True, "effort": None}, "Sonnet 5.5 ↯ · $0.09"),
        ({"effort": {"level": "max"}}, "Sonnet 5.5 · max · $0.09"),
        ({"cost": None}, "Sonnet 5.5 · high │ context"),
    ],
)
def test_session_items(overrides, start):
    assert lines_text(make_session(**overrides), make_ctx(120))[0].startswith(start)


@pytest.mark.parametrize(
    ("cache", "tail"),
    [
        ({"expires_at": NOW + 3000}, " 4%"),  # warm, an hour cache, 50 min left
        ({"expires_at": NOW + 400}, " 4% ⧗ 7m"),  # within 10 min of expiry
        ({"ttl": "5m", "expires_at": NOW + 200}, " 4%"),
        ({"ttl": "5m", "expires_at": NOW + 50}, " 4% ⧗ 50s"),  # within 1 min on a 5m cache
        ({"expires_at": NOW - 5}, " 4% cache cold ↻42k"),  # expired before the CLI noticed
        (
            {"warm": False, "last_miss_cause": {"causes": ["ttl_expired_1h"]}},
            " 4% cache cold (idle) ↻42k",
        ),
        ({"warm": False, "last_miss_cause": {"causes": ["unknown"]}}, " 4% cache cold ↻42k"),
        (
            {"warm": False, "last_miss_cause": {"causes": ["new_cause"]}},
            " 4% cache cold (new cause) ↻42k",
        ),
        ({"warm": False, "recache_tokens_if_cold": 0}, " 4% cache cold"),
        ({"warm": False, "caching_observed": False}, " 4%"),  # provider reports no caching
    ],
)
def test_cache_state(cache, tail):
    assert lines_text(make_session(prompt_cache=cache), make_ctx(120))[0].endswith(tail)


def test_cache_text_shrinks_to_its_glyph_when_narrow():
    s = make_session(prompt_cache={"warm": False, "last_miss_cause": {"causes": ["tools_changed"]}})
    assert lines_text(s, make_ctx(120, "nerd"))[0].endswith(
        "\U000f0717 cold (tools changed) \U000f045042k"
    )
    assert lines_text(s, make_ctx(60, "nerd"))[0].endswith("4% \U000f0717 cold")


def test_countdown_only_from_70_percent():
    s = make_session(rate_limits={"seven_day": {"used_percentage": 69, "resets_at": NOW + 600}})
    assert lines_text(s, make_ctx(120))[1].endswith(" 69%")
    s = make_session(rate_limits={"seven_day": {"used_percentage": 70, "resets_at": NOW + 600}})
    assert lines_text(s, make_ctx(120))[1].endswith(" 70% (10m)")


# ---- color ----


def test_colors_come_from_the_theme():
    lines = layout.lay_out(
        make_session(effort={"level": "max"}, fast_mode=True), make_ctx(120, color=True), []
    )
    styles = dict((text, sgr) for text, sgr in lines[0])
    assert styles["Sonnet 5.5"] == "1;38;2;255;255;255"  # text, bold
    assert styles["max"] == "1;38;2;255;107;128"  # error, bold
    assert styles["↯"] == "38;2;255;120;20"  # fastMode
    assert styles[" · "] == "38;2;153;153;153"  # inactive
    assert styles["▁" * 46] == "38;2;80;80;80"  # subtle
    assert styles["▆▆"] == "38;2;78;186;101"  # 4%: success


def test_no_color_has_no_escapes():
    out = layout.render(make_session(**BUSY), make_ctx().g, make_ctx().p, 120, NOW)
    assert all("\x1b" not in line for line in out)
