import pytest

from conftest import NOW, lines_text, make_ctx, make_session, plain
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
        # Line 2: 116 usable - "7d" " 17%" (7) = 109 free; one bar gets a third, 36.
        # Context matches it; line 1 has 77 left.
        "Sonnet 5.5 · high · $0.09 │ context ▆" + "▁" * 35 + " 4%",
        "7d " + "▆" * 6 + "▁" * 30 + " 17%",
    ]


def test_startup_has_no_bars():
    assert lines_text(make_session("startup"), make_ctx(120)) == ["Opus 5.5 · medium · $0.00"]


def test_busy_golden_120():
    assert lines_text(make_session(**BUSY), make_ctx(120)) == [
        # Line 2: 116 - 7 - 14 - 2 (gap) = 93 free, a third each = 31; context matches.
        "Sonnet 5.5 · xhigh ↯ · @code-reviewer · $11.80 │ context " + "▆" * 13 + "▁" * 18 + " 41%",
        "5h " + "▆" * 7 + "▁" * 24 + " 22%  7d " + "▆" * 23 + "▁" * 8 + " 74% (2d4h)",
    ]


def test_ascii_golden():
    s = make_session(prompt_cache={"warm": False, "last_miss_cause": {"causes": ["tools_changed"]}})
    line = lines_text(s, make_ctx(120, "ascii"))[0]
    # Context matches line 2's 7d bar: (116 - 7) // 3 = 36 (line 1 has room for 38).
    assert line == (
        "Sonnet 5.5 / high / $0.09 | context #"
        + "-" * 35
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


def test_plan_bars_and_context_share_a_width():
    first, second = lines_text(make_session(**BUSY), make_ctx(120), FOUR, "Ultra")
    widths = {cells(second, label) for label in ("5h", "7d", "Fable", "credits")}
    assert widths == {16}
    assert cells(first, "context") == 16


def test_widths_scale_with_the_row():
    first, second = lines_text(make_session(**BUSY), make_ctx(200))
    third = (196 - 7 - 14 - 2) // 3  # usable, the two bars' text, the gap
    assert cells(second, "5h") == cells(second, "7d") == third == 57
    assert cells(first, "context") == third


def test_three_bars_fill_line_2():
    plan = [Bar("5h", 30), Bar("7d", 50), Bar("Fable", 20)]
    for columns in (90, 120, 160, 200):
        second = lines_text(make_session(), make_ctx(columns), plan, "Ultra")[1]
        assert columns - 4 - 2 <= len(second) <= columns - 4  # within the rounding


def test_two_bars_take_a_third_each():
    plan = [Bar("5h", 30), Bar("7d", 50)]
    second = lines_text(make_session(), make_ctx(120), plan, "Pro")[1]
    free = 116 - len("Pro │ ") - 7 - 7 - 2
    assert cells(second, "5h") == cells(second, "7d") == free // 3


def test_four_bars_share_the_row():
    plan = [Bar("5h", 30), Bar("7d", 50), Bar("Fable", 20), Bar("credits", 40)]
    second = lines_text(make_session(), make_ctx(160), plan, "Ultra")[1]
    free = 156 - 8 - (7 + 7 + 10 + 12) - 6
    assert {cells(second, b.label) for b in plan} == {free // 4}


def test_context_alone_sizes_as_if_line_2_existed():
    s = make_session(rate_limits=None)
    assert cells(lines_text(s, make_ctx(200), [])[0], "context") == 196 // 3
    assert cells(lines_text(s, make_ctx(70), [])[0], "context") == 66 // 3
    # Line 1's room still limits it: text, separator, label and percent.
    assert cells(lines_text(s, make_ctx(52), [])[0], "context") == 48 - 25 - 3 - 11


def test_bars_never_leave_line_2():
    no_agent = make_session(**{**BUSY, "agent": None})
    for columns in range(30, 201):
        first, *rest = lines_text(no_agent, make_ctx(columns), FOUR, "Ultra")
        assert not any(label in first for label in ("5h", "7d", "Fable", "credits"))
        assert rest and rest[0].startswith("Ultra │ 5h ")


def test_trailing_bar_turns_into_text_first():
    no_agent = make_session(**{**BUSY, "agent": None})
    at_86 = lines_text(no_agent, make_ctx(86), FOUR, "Ultra")[1]
    # 82 - 8 (plan name) - 36 (labels and percents) - 6 (gaps) = 32 free: 8 each.
    assert {cells(at_86, b.label) for b in FOUR} == {8}
    at_85 = lines_text(no_agent, make_ctx(85), FOUR, "Ultra")[1]
    # Credits as text frees its cells and a column; three bars get a third of 32.
    assert at_85.endswith("  credits 12%")
    assert {cells(at_85, b.label) for b in FOUR[:3]} == {10}


def test_context_keeps_the_smallest_bar_beside_text_plan_bars():
    first, second = lines_text(make_session(**{**BUSY, "agent": None}), make_ctx(70), FOUR, "Ultra")
    assert second == "Ultra │ 5h 22%  7d 48%  Fable 24%  credits 12%"
    assert cells(first, "context") == 8


def test_agent_drops_before_bars_shrink_to_text():
    lines = lines_text(make_session(**BUSY), make_ctx(70))
    assert "@code-reviewer" not in lines[0]
    assert "▆" in lines[0]


def test_each_line_turns_bars_into_text_on_its_own():
    assert lines_text(make_session(**BUSY), make_ctx(50)) == [
        # Line 1 has 2 columns left for cells: the context bar is text.
        "Sonnet 5.5 · xhigh ↯ · $11.80 │ context 41%",
        # Line 2: 46 - 2 (gap) - 7 - 13 (7d as text) = 24 free, a third is 8.
        "5h ▆▆▁▁▁▁▁▁ 22%  7d 74% (2d4h)",
    ]
    assert lines_text(make_session(**BUSY), make_ctx(48)) == [
        "Sonnet 5.5 · xhigh ↯ · $11.80 │ context 41%",
        "5h 22%  7d 74% (2d4h)",
    ]


def test_extremely_narrow_drops_countdowns_then_cuts():
    assert lines_text(make_session(**BUSY), make_ctx(40)) == [
        "Sonnet 5.5 · xhigh ↯ · $11.80 │ con…",
        "5h 22%  7d 74% (2d4h)",
    ]
    assert lines_text(make_session(**BUSY), make_ctx(24))[1] == "5h 22%  7d 74%"
    assert lines_text(make_session(**BUSY), make_ctx(17))[1] == "5h 22%  7d 7…"


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
    assert styles["▁" * 36] == "38;2;80;80;80"  # subtle: context alone gets 116 // 3 = 38
    assert styles["▆▆"] == "38;2;78;186;101"  # 4%: success


def test_no_color_has_no_escapes():
    out = layout.render(make_session(**BUSY), make_ctx().g, make_ctx().p, 120, NOW)
    assert all("\x1b" not in line for line in out)


# ---- full bars and stale data (Phase 3) ----


def test_full_bar_at_100():
    plan = [Bar("5h", 100, NOW + 72 * 60), Bar("7d", 71, NOW + 2 * 86400)]
    second = lines_text(make_session(), make_ctx(120), plan, "Pro")[1]
    n = cells(second, "5h")
    assert second.startswith("Pro │ 5h " + "▆" * n + " 100% (1h12m)  7d ")


def test_hitting_100_fills_the_bar():
    def line(percent):
        plan = [Bar("5h", percent, NOW + 3600), Bar("7d", 50, NOW + 86400)]
        return lines_text(make_session(), make_ctx(120), plan, "Pro")[1]

    before, after = line(99), line(100)
    assert "▁" in before.split("7d")[0]
    assert "▁" not in after.split("7d")[0]
    assert " 100% (1h)  7d " in after
    # "100%" is one column wider than "99%"; here the shared width absorbs it.
    assert cells(before, "5h") == cells(after, "5h") == 29


def test_full_cap_without_reset_time():
    second = lines_text(make_session(), make_ctx(120), [Bar("month", 100)], "Enterprise")[1]
    assert second == "Enterprise │ month " + "▆" * ((116 - 13 - 11) // 3) + " 100%"


def test_full_bar_is_coral():
    ctx = make_ctx(120, color=True)
    lines = layout.lay_out(make_session(), ctx, [Bar("7d", 100, NOW + 60)])
    fill = next(seg for seg in lines[1] if seg[0].startswith("▆"))
    assert fill[1] == ctx.p.sgr("error")


def test_stale_tag_after_line_2():
    plan = [Bar("7d", 17)]
    lines = lines_text(make_session(), make_ctx(120), plan, "Ultra")
    stale = plain(layout.lay_out(make_session(), make_ctx(120), plan, "Ultra", stale=12 * 60))
    assert stale[1].endswith(" 17% ·12m")
    # The tag takes its 5 columns from the bar's free space: 101 // 3 → 96 // 3.
    assert (cells(lines[1], "7d"), cells(stale[1], "7d")) == (33, 32)
    ascii_line = plain(
        layout.lay_out(make_session(), make_ctx(120, "ascii"), plan, "Ultra", stale=3700)
    )[1]
    assert ascii_line.endswith("17% ~1h2m")


def test_stale_tag_needs_line_2():
    lines = plain(layout.lay_out(make_session(), make_ctx(120), [], "API", stale=900))
    assert len(lines) == 1
    assert "·15m" not in lines[0]


@pytest.mark.parametrize("columns", range(10, 161, 3))
def test_full_and_stale_never_exceed_the_width(columns):
    plan = [Bar("5h", 100, NOW + 3000), Bar("7d", 95, NOW + 86400), Bar("Fable", 24)]
    lines = plain(layout.lay_out(make_session(**BUSY), make_ctx(columns), plan, "Ultra", 900))
    assert all(len(line) <= columns - layout.RESERVE for line in lines)


# ---- long model names ----

ARN = "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/a1b2c3d4e5f6"


def test_long_model_name_is_cut_before_cost_or_context():
    s = make_session(model={"id": ARN, "display_name": ARN}, **BUSY)
    first = lines_text(s, make_ctx(100))[0]
    assert len(first) <= 96
    assert first.startswith("arn:aws:bedrock:")
    assert "… · xhigh ↯ · $11.80 │ context ▆" in first  # the bar is kept at 8 or more
    assert cells(first, "context") >= layout.CONTEXT_MIN
    assert "code-reviewer" not in first  # the agent went first


def test_long_model_name_keeps_sixteen_columns_then_the_bar_turns_into_text():
    s = make_session(model={"id": ARN, "display_name": ARN}, **BUSY)
    first = lines_text(s, make_ctx(53))[0]
    assert first == "arn:aws:bedrock… · xhigh ↯ · $11.80 │ context 41%"


def test_short_model_names_are_never_cut():
    for columns in range(20, 90):
        first = lines_text(make_session(**BUSY), make_ctx(columns))[0]
        assert "Sonnet 5.5 · " in first or first.startswith("Sonnet 5.5"), (columns, first)


# ---- wide characters ----


@pytest.mark.parametrize("columns", [120, 80, 60, 45, 30])
def test_wide_model_and_agent_names_fit(columns):
    from dashline.text import cols

    s = make_session(model={"id": "x", "display_name": "模型名称很长的模型名称"}, **BUSY)
    s.agent = "代码审查员"
    for line in lines_text(s, make_ctx(columns)):
        assert cols(line) <= columns - 4, line


def test_wide_model_name_is_cut_by_columns():
    from dashline.text import cols

    s = make_session(model={"id": "x", "display_name": "模型" * 20}, **BUSY)
    first = lines_text(s, make_ctx(70))[0]
    assert first.split(" · ")[0].endswith("…")
    assert cols(first) <= 66
    assert "$11.80 │ context ▆" in first


# ---- the context bar never narrows as the terminal widens ----


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "prompt_cache": {
                "caching_observed": True,
                "warm": False,
                "recache_tokens_if_cold": 38000,
                "last_miss_cause": {"causes": ["tools_changed"]},
            }
        },
        BUSY,
    ],
)
def test_context_bar_never_narrows_as_the_terminal_widens(overrides):
    s = make_session(**overrides)
    # Two plan bars: their width only grows with the terminal. (With four, it steps
    # down where credits turns back into a bar, and the context bar follows; PLAN §4.)
    plan = [Bar("5h", 22), Bar("7d", 48)]
    previous = 0
    for columns in range(50, 160):
        first = lines_text(s, make_ctx(columns), plan, "Ultra")[0]
        n = cells(first, "context") if "context ▆" in first or "context ▁" in first else 0
        assert n >= previous, (columns, first)
        previous = n


def test_context_bar_keeps_the_plan_width_before_the_cache_detail():
    cold = {
        "caching_observed": True,
        "warm": False,
        "recache_tokens_if_cold": 38000,
        "last_miss_cause": {"causes": ["tools_changed"]},
    }
    s = make_session(prompt_cache=cold, context_window={"used_percentage": 57})
    plan = [Bar("5h", 100, NOW + 72 * 60), Bar("7d", 71, NOW + 2 * 86400)]
    lines = lines_text(s, make_ctx(82), plan, "Pro")
    first, second = lines
    assert first.endswith("57% cache cold")  # the detail went, not the bar's cells
    assert cells(first, "context") == cells(second, "5h")
