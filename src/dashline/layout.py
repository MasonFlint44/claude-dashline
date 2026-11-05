"""Lines 1–2: the session line and the plan-bar line (PLAN §4, layout E3).

A line is a list of (text, sgr) segments, so widths can be measured without escape codes
and a line can be cut short cleanly. Every glyph dashline draws is one column wide in
Claude Code and in the terminal (Phase 0, E4), so a segment's width is its length.

Bar widths (PLAN §4 rules): plan bars share one width, 8–24. The context bar is twice
that, at most 48 and at least 8, limited by the room left on line 1. When line 2 can't
hold every plan bar at 8, trailing plan bars move to the end of line 1, one at a time.
When nothing fits at 8, every bar becomes `label NN%`. Lines never wrap.
"""

from __future__ import annotations

from dashline import bars

RESERVE = 4  # columns Claude Code keeps around the statusline (Phase 0, E5)
DEFAULT_COLUMNS = 80
PLAN_MAX, PLAN_MIN = 24, 8
CONTEXT_MAX, CONTEXT_MIN = 48, 8
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
    return sum(len(text) for text, _ in line)


def to_str(line: list) -> str:
    return "".join(f"\x1b[{sgr}m{text}\x1b[0m" if sgr else text for text, sgr in line if text)


def truncate(line: list, limit: int, ellipsis: str, style: str) -> list:
    """Cut a line to `limit` columns, ending in an ellipsis."""
    if width(line) <= limit:
        return line
    room = max(0, limit - len(ellipsis))
    out = []
    for text, sgr in line:
        if room <= 0:
            break
        out.append((text[:room], sgr))
        room -= len(text[:room])
    out.append((ellipsis[:limit], style))
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
    return len(bar.label) + 1 + width(bar_suffix(bar, ctx, countdown))


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


def session_items(session, ctx: Ctx, plan_label: str | None, with_agent: bool) -> list:
    """Line 1's text part: `model · effort fast · agent · plan · cost`."""
    items = []
    if session.model:
        items.append([ctx.seg(session.model, "text", bold=True)])
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
        items.append([ctx.seg(f"${session.cost:.2f}", "text")])
    line = []
    for i, item in enumerate(items):
        if i:
            line.append(ctx.seg(ctx.g["sep_item"], "inactive"))
        line += item
    return line


# ---- fitting ----


class Fit:
    def __init__(self, moved: int, plan_width: int | None, context_width: int | None):
        self.moved = moved
        self.plan_width = plan_width
        self.context_width = context_width


def fit(ctx: Ctx, text_w: int, context: Bar | None, plan: list, prefix_w: int, tail_w: int):
    """Largest widths that fit, moving the fewest plan bars up to line 1; None if none do.

    text_w: line 1's text part; prefix_w: line 2's plan-name prefix with its separator;
    tail_w: what follows the bars on line 1 (the cache state, with its leading space).
    At least one plan bar stays on line 2.
    """
    gap, sep = len(BAR_GAP), len(ctx.g["sep_group"])
    n = len(plan)
    for moved in range(max(1, n)):
        stay, up = plan[: n - moved], plan[n - moved :]
        for p in range(PLAN_MAX, PLAN_MIN - 1, -1) if n else [None]:
            if stay:
                need2 = prefix_w + sum(bar_overhead(b, ctx, True) + p for b in stay)
                if need2 + gap * (len(stay) - 1) > ctx.width:
                    continue
            count1 = len(up) + (1 if context else 0)
            used1 = text_w + tail_w + sum(bar_overhead(b, ctx, True) + p for b in up)
            used1 += ((sep if text_w else 0) + gap * (count1 - 1)) if count1 else 0
            if context is None:
                if used1 <= ctx.width:
                    return Fit(moved, p, None)
                continue
            room = ctx.width - used1 - bar_overhead(context, ctx, True)
            c = min(CONTEXT_MAX, 2 * p if p else CONTEXT_MAX, room)
            if c >= CONTEXT_MIN:
                return Fit(moved, p, c)
    return None


# ---- assembly ----


def assemble(text, context, plan, prefix, tail, ctx, f: Fit | None, countdown=True):
    """Build both lines from a fit (or text-only bars when f is None)."""
    n = len(plan)
    moved = f.moved if f else 0
    stay, up = plan[: n - moved], plan[n - moved :]
    pw = f.plan_width if f else None
    sep = ctx.seg(ctx.g["sep_group"], "inactive")

    drawn1 = []
    if context:
        drawn1.append(draw_bar(context, f.context_width if f else None, ctx, countdown))
    drawn1 += [draw_bar(b, pw, ctx, countdown) for b in up]
    line1 = list(text)
    if drawn1:
        if line1:
            line1.append(sep)
        for i, d in enumerate(drawn1):
            line1 += ([(BAR_GAP, "")] if i else []) + d
    line1 += tail

    lines = [line1]
    if stay:
        line2 = list(prefix)
        for i, b in enumerate(stay):
            line2 += ([(BAR_GAP, "")] if i else []) + draw_bar(b, pw, ctx, countdown)
        lines.append(line2)
    return lines


def lay_out(session, ctx: Ctx, plan: list, plan_label: str | None = None) -> list:
    """Lines 1–2 as segment lists, fitted to ctx.width."""
    context = None
    if session.context_percent is not None:
        context = Bar("context", session.context_percent)
    label_on_line1 = plan_label if not plan else None
    prefix = []
    if plan and plan_label:
        prefix = [ctx.seg(plan_label, "inactive"), ctx.seg(ctx.g["sep_group"], "inactive")]

    # Narrow terminals give up line-1 detail in this order: agent, then cache text.
    variants = [(True, False), (False, False), (False, True)]
    for with_agent, compact in variants:
        text = session_items(session, ctx, label_on_line1, with_agent)
        tail = cache_state(session, ctx, compact)
        tail = [(" ", ""), *tail] if tail else []
        f = fit(ctx, width(text), context, plan, width(prefix), width(tail))
        if f:
            return assemble(text, context, plan, prefix, tail, ctx, f)

    # Text-only bars, then no countdowns, then cut short.
    for countdown in (True, False):
        for with_agent, compact in variants:
            text = session_items(session, ctx, label_on_line1, with_agent)
            tail = cache_state(session, ctx, compact)
            tail = [(" ", ""), *tail] if tail else []
            lines = assemble(text, context, plan, prefix, tail, ctx, None, countdown)
            if all(width(line) <= ctx.width for line in lines):
                return lines
    ell = ctx.p.sgr("inactive")
    return [truncate(line, ctx.width, ctx.g["ellipsis"], ell) for line in lines]


def stdin_plan_bars(session) -> list:
    """Plan bars from stdin alone (before the usage endpoint is wired in)."""
    out = []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        window = session.windows.get(key)
        if window:
            out.append(Bar(label, window.percent, window.resets_at))
    return out


def render(session, glyphs: dict, palette, columns: int | None, now: float) -> list:
    """The status lines as strings."""
    ctx = Ctx(glyphs, palette, columns or DEFAULT_COLUMNS, now)
    lines = lay_out(session, ctx, stdin_plan_bars(session))
    return [to_str(line) for line in lines if line]
