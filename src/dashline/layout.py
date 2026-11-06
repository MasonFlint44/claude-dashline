"""Lines 1–2: the session line and the plan-bar line (PLAN §4, layout E3).

A line is a list of (text, sgr) segments, or (text, sgr, url) for an OSC 8 link, so
widths can be measured without escape codes and a line can be cut short cleanly. Every
glyph dashline draws is one column wide in Claude Code and in the terminal (Phase 0,
E4); outside text (names) is measured in columns by text.cols, so CJK counts double.

Bar widths (PLAN §4 rules): plan bars share one width, a third of line 2's free space
at most and 1/n of it with n bars, never under 8. The context bar matches it, limited by
the room left on line 1. Line 1 is the session and line 2 the plan; bars never move
between them. When line 2 is too narrow, its trailing bars turn into text (`label NN%`)
one at a time. On line 1 the context bar keeps that width while the agent, the cache
detail and the end of a long model name go; only then does it shrink, down to 8, and
turn into text. Lines never wrap.
"""

from __future__ import annotations

from dashline import bars
from dashline.text import cols, cut

RESERVE = 4  # columns Claude Code keeps around the statusline (Phase 0, E5)
DEFAULT_COLUMNS = 80
# Plan bars share line 2's free space: 1/n each, but never more than 1/3, so three bars
# fill the row. The context bar matches them when line 1 has the room. Below the
# minimums, bars turn into text.
PLAN_SHARE = 3
PLAN_MIN = 8
CONTEXT_MIN = 8
# A model name longer than this (a Bedrock ARN, say) is cut short, down to this many
# columns, before line 1 gives up its cost or context bar.
MODEL_MIN = 16
BAR_GAP = "  "
EFFORT_TOKENS = {
    "low": ("inactive", False),
    "medium": ("success", False),
    "high": ("warning", False),
    "xhigh": ("error", False),
    "max": ("error", True),
}
# Short forms of the CLI's prompt-cache miss causes; unknown causes print their key.
MISS_CAUSES = {
    "system_prompt_changed": "system prompt changed",
    "tools_changed": "tools changed",
    "model_changed": "model changed",
    "fast_mode_changed": "fast mode toggled",
    "cache_scope_or_ttl_changed": "TTL changed",
    "betas_changed": "betas changed",
    "effort_changed": "effort changed",
    "thinking_mode_changed": "thinking toggled",
    "thinking_display_changed": "thinking toggled",
    "auto_mode_changed": "auto mode toggled",
    "overage_changed": "limit state changed",
    "extra_body_changed": "request changed",
    "defer_loading_changed": "tools changed",
    "messages_rewritten": "history changed",
    "ttl_expired_5m": "idle",
    "ttl_expired_1h": "idle",
    "likely_server_side": "server side",
    "unknown": None,
}


class Bar:
    """One bar. At 100% it is simply full (and coral), countdown and all: no special case."""

    def __init__(self, label: str, percent: float, resets_at: float | None = None):
        self.label = label
        self.percent = percent
        self.resets_at = resets_at


class Ctx:
    """What a render needs besides the session: glyphs, colors, width and the clock."""

    def __init__(self, glyphs: dict, palette, columns: int, now: float):
        self.g = glyphs
        self.p = palette
        self.width = max(1, columns - RESERVE)
        self.now = now

    def seg(self, text: str, token=None, bold: bool = False) -> tuple:
        return (text, self.p.sgr(token, bold) if token else "")


def width(line: list) -> int:
    return sum(cols(seg[0]) for seg in line)


def _seg_str(seg: tuple) -> str:
    text, sgr = seg[0], seg[1]
    out = f"\x1b[{sgr}m{text}\x1b[0m" if sgr else text
    url = seg[2] if len(seg) > 2 else None
    # OSC 8 with the ST terminator; Claude Code re-emits it (Phase 0, E3).
    return f"\x1b]8;;{url}\x1b\\{out}\x1b]8;;\x1b\\" if url else out


def to_str(line: list) -> str:
    return "".join(_seg_str(seg) for seg in line if seg[0])


def truncate(line: list, limit: int, ellipsis: str, style: str) -> list:
    """Cut a line to `limit` columns, ending in an ellipsis."""
    if width(line) <= limit:
        return line
    room = max(0, limit - cols(ellipsis))
    out = []
    for text, *rest in line:
        if room <= 0:
            break
        part = cut(text, room)
        out.append((part, *rest))
        if part != text:
            break  # cut short: a narrower character from later must not fill the gap
        room -= cols(part)
    out.append((cut(ellipsis, limit), style))
    return out


# ---- pieces ----


def bar_suffix(bar: Bar, ctx: Ctx, countdown: bool) -> list:
    out = [(" ", ""), ctx.seg(bars.percent_text(bar.percent), "text")]
    if countdown and bar.resets_at and bar.percent >= bars.COUNTDOWN_FROM:
        left = bar.resets_at - ctx.now
        if left > 0:
            out += [(" ", ""), ctx.seg(f"({bars.duration(left)})", "inactive")]
    return out


def bar_overhead(bar: Bar, ctx: Ctx, countdown: bool) -> int:
    """Columns a bar takes besides its cells."""
    return cols(bar.label) + 1 + width(bar_suffix(bar, ctx, countdown))


def draw_bar(bar: Bar, cells: int | None, ctx: Ctx, countdown: bool) -> list:
    """`label ▆▆▆▁▁▁ 41% (1h40m)`; with cells=None, text only: `label 41%`."""
    out = [ctx.seg(bar.label, "text")]
    if cells is not None:
        n = bars.filled(bar.percent, cells)
        out += [
            (" ", ""),
            ctx.seg(ctx.g["bar_fill"] * n, bars.ramp(bar.percent, ctx.p)),
            ctx.seg(ctx.g["bar_empty"] * (cells - n), "subtle"),
        ]
    return out + bar_suffix(bar, ctx, countdown)


def cache_state(session, ctx: Ctx, compact: bool) -> list:
    """Nothing while the prompt cache is warm; a countdown near expiry; why it went cold."""
    cache = session.cache
    if cache is None or not cache.observed:
        return []
    cold = not cache.warm
    if cache.warm and cache.expires_at is not None:
        left = cache.expires_at - ctx.now
        if left > (600 if cache.ttl == "1h" else 60):
            return []
        if left > 0:
            return [ctx.seg(ctx.g["cache_timer"] + bars.duration(left), "warning")]
        cold = True
    if not cold:
        return []
    text = ctx.g["cache_cold"]
    if not compact:
        cause = MISS_CAUSES.get(cache.miss_cause, (cache.miss_cause or "").replace("_", " "))
        if cause:
            text += f" ({cause})"
        if cache.recache_tokens:
            text += f" {ctx.g['recache']}{bars.tokens(cache.recache_tokens)}"
    return [ctx.seg(text, "error")]


def session_items(
    session, ctx: Ctx, plan_label: str | None, with_agent: bool, model_max: int | None = None
) -> list:
    """Line 1's text part: `model · effort fast · agent · plan · cost`.

    model_max: cut the model name to this many columns, ending in an ellipsis.
    """
    items = []
    if session.model:
        model = session.model
        if model_max is not None and cols(model) > model_max:
            ell = ctx.g["ellipsis"]
            model = cut(model, model_max - cols(ell)) + ell
        items.append([ctx.seg(model, "text", bold=True)])
    fast = [ctx.seg(ctx.g["fast"], "fastMode")] if session.fast else []
    if session.effort:
        token, bold = EFFORT_TOKENS.get(session.effort, ("inactive", False))
        effort = [ctx.seg(session.effort, token, bold)]
        items.append(effort + ([(" ", ""), *fast] if fast else []))
    elif fast and items:
        items[-1] += [(" ", ""), *fast]
    elif fast:
        items.append(fast)
    if with_agent and session.agent:
        items.append([ctx.seg(ctx.g["agent"] + session.agent, "inactive")])
    if plan_label:
        items.append([ctx.seg(plan_label, "inactive")])
    if session.cost is not None:
        items.append([ctx.seg(bars.money(session.cost), "text")])
    line = []
    for i, item in enumerate(items):
        if i:
            line.append(ctx.seg(ctx.g["sep_item"], "inactive"))
        line += item
    return line


# ---- fitting ----


def text_width(bar: Bar, ctx: Ctx, countdown: bool) -> int:
    """Columns a bar takes as text: `label 41%`."""
    return bar_overhead(bar, ctx, countdown) - 1


def plan_fit(ctx: Ctx, plan: list, prefix_w: int, suffix_w: int):
    """Line 2: (bars drawn with cells, cell width), or None if even text doesn't fit.

    Line 2's free space is its width less everything but bar cells. Each drawn bar gets
    1/n of it, at most 1/3, so three bars fill the row. When that is under 8, the last
    bar drawn turns into text, then the one before it, until the rest fit. (0, None)
    means every bar is text; None that line 2 doesn't fit even so, and must drop its
    countdowns, then be cut short.
    prefix_w: the plan name with its separator; suffix_w: the stale-data age.
    """
    n = len(plan)
    base = ctx.width - prefix_w - suffix_w - len(BAR_GAP) * (n - 1)
    for drawn in range(n, 0, -1):
        free = base - sum(bar_overhead(b, ctx, True) for b in plan[:drawn])
        free -= sum(text_width(b, ctx, True) for b in plan[drawn:])
        p = free // max(PLAN_SHARE, drawn)
        if p >= PLAN_MIN:
            return drawn, p
    if base - sum(text_width(b, ctx, True) for b in plan) >= 0:
        return 0, None
    return None


def context_width(ctx: Ctx, text_w: int, tail_w: int, context: Bar, share: int) -> int | None:
    """Cells for the context bar: the plan-bar width, limited by the room left on line 1.

    text_w: line 1's text part; tail_w: the cache state after the bar. None if line 1
    can't fit it at 8.
    """
    sep = cols(ctx.g["sep_group"]) if text_w else 0
    room = ctx.width - text_w - sep - tail_w - bar_overhead(context, ctx, True)
    c = min(share, room)
    return c if c >= CONTEXT_MIN else None


# ---- assembly ----


def line_1(text: list, context: Bar | None, cells: int | None, tail: list, ctx: Ctx) -> list:
    """`text │ context ▆▆▁▁ 41% tail`; cells=None draws the context bar as text."""
    line = list(text)
    if context:
        if line:
            line.append(ctx.seg(ctx.g["sep_group"], "inactive"))
        line += draw_bar(context, cells, ctx, True)
    return line + list(tail)


def line_2(plan: list, drawn: int, cells: int | None, prefix, suffix, ctx, countdown) -> list:
    """`Ultra │ 5h ▆▆▁▁ 22%  7d ▆▆▆▁ 48%  credits 12% ·12m`: bars past `drawn` are text."""
    line = list(prefix)
    for i, b in enumerate(plan):
        line += ([(BAR_GAP, "")] if i else []) + draw_bar(
            b, cells if i < drawn else None, ctx, countdown
        )
    return line + list(suffix)


def fit_line_1(session, ctx: Ctx, context: Bar | None, share: int, label: str | None) -> list:
    """Line 1. The context bar keeps the plan-bar width (`share`) while detail goes: the
    agent, then the cache detail, then the end of a long model name. Only with all of it
    gone does the bar shrink, down to 8; then it turns into text, and then the line is
    cut short. So a wider terminal never shows a narrower bar.
    """
    # (with the agent, compact cache text, model name cut short), most detail first
    variants = [(True, False, False), (False, False, False), (False, True, False)]
    if not session.agent:
        del variants[0]
    variants.append((False, True, True))
    model_w = cols(session.model or "")

    def build(with_agent, compact, short, cells):
        """(line, the bar's cells) for a variant, or None if it can't have a bar."""
        tail = cache_state(session, ctx, compact)
        tail = [(" ", ""), *tail] if tail else []
        model_max = None
        if short:
            if model_w <= MODEL_MIN:
                return None
            # Cut just enough for the bar at `cells` (or the text) to fit.
            full = line_1(session_items(session, ctx, label, with_agent), context, cells, tail, ctx)
            model_max = max(MODEL_MIN, model_w - (width(full) - ctx.width))
        text = session_items(session, ctx, label, with_agent, model_max)
        if cells is not None:
            cells = context_width(ctx, width(text), width(tail), context, cells)
            if cells is None:
                return None
        return line_1(text, context, cells, tail, ctx), cells

    if context:
        best = None  # each variant leaves more room, so the last that fits is widest
        for variant in variants:
            built = build(*variant, share)
            if built is None or width(built[0]) > ctx.width:
                continue
            if built[1] >= share:
                return built[0]
            best = built[0]
        if best is not None:
            return best
    line = []
    for variant in variants:  # the context bar as text, or no bar at all
        built = build(*variant, None)
        if built is None:
            continue
        line = built[0]
        if width(line) <= ctx.width:
            return line
    return truncate(line, ctx.width, ctx.g["ellipsis"], ctx.p.sgr("inactive"))


def lay_out(
    session, ctx: Ctx, plan: list, plan_label: str | None = None, stale: float | None = None
) -> list:
    """Lines 1–2 as segment lists, fitted to ctx.width. stale: the usage data's age.

    Line 1 is the session and line 2 the plan; nothing moves between them. Each line
    gives up detail on its own, so a narrow line 1 never costs line 2 its bars.
    """
    context = None
    if session.context_percent is not None:
        context = Bar("context", session.context_percent)
    label_on_line1 = plan_label if not plan else None
    prefix = []
    if plan and plan_label:
        prefix = [ctx.seg(plan_label, "inactive"), ctx.seg(ctx.g["sep_group"], "inactive")]
    suffix = []
    if plan and stale is not None:
        suffix = [(" ", ""), ctx.seg(ctx.g["stale"] + bars.duration(stale), "inactive")]

    # Line 2: trailing bars turn into text one at a time, then countdowns go, then it's cut.
    plan_cells, second = None, None
    if plan:
        f = plan_fit(ctx, plan, width(prefix), width(suffix))
        if f:
            drawn, plan_cells = f
            second = line_2(plan, drawn, plan_cells, prefix, suffix, ctx, True)
        else:
            second = line_2(plan, 0, None, prefix, suffix, ctx, False)
            ell = ctx.p.sgr("inactive")
            second = truncate(second, ctx.width, ctx.g["ellipsis"], ell)

    # The context bar matches the plan bars. With no plan bars it sizes as if line 2
    # existed; when they're all text, it keeps the smallest bar.
    if plan_cells is not None:
        share = plan_cells
    else:
        share = CONTEXT_MIN if plan else ctx.width // PLAN_SHARE
    first = fit_line_1(session, ctx, context, share, label_on_line1)
    return [first, second] if second is not None else [first]


def render(
    session,
    glyphs: dict,
    palette,
    columns: int | None,
    now: float,
    plan: list = (),
    plan_label: str | None = None,
    stale: float | None = None,
    repo_state=None,
    home: str | None = None,
) -> list:
    """The status lines as strings: lines 1–2, then the directory row."""
    from dashline import repo

    ctx = Ctx(glyphs, palette, columns or DEFAULT_COLUMNS, now)
    lines = lay_out(session, ctx, list(plan), plan_label, stale)
    lines.append(repo.draw(repo_state, ctx, home))
    return [to_str(line) for line in lines if line]
