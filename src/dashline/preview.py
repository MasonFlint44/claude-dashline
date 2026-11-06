"""--preview: built-in scenarios rendered with fake data (PLAN §9, §10).

Each scenario is a whole statusline (session, plan, directory row) at a fixed clock, so
the output depends only on the scenario, the glyph set, the theme and the width. Nothing
is read from the account, the network or git. The install skill shows these to pick a
glyph set; the README preview is drawn from them.
"""

from __future__ import annotations

import sys

# 2026-11-05 00:00:00 UTC, the same clock as the tests.
NOW = 1793836800.0
INDENT = "  "  # Claude Code draws the statusline two columns in (Phase 0, E5)


def _session(**overrides):
    from dashline.stdin import Session

    data = {
        "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
        "effort": {"level": "high"},
        "cost": {"total_cost_usd": 4.12},
        "context_window": {"used_percentage": 41},
        "workspace": {"project_dir": "/home/user/claude-dashline"},
        "prompt_cache": {
            "caching_observed": True,
            "warm": True,
            "ttl": "1h",
            "expires_at": NOW + 3000,
        },
    }
    data.update(overrides)
    return Session(data)


def _bar(label, percent, resets_in=None):
    from dashline.layout import Bar

    return Bar(label, percent, NOW + resets_in if resets_in else None)


def _repo(name="claude-dashline", **attrs):
    from dashline.repo import RepoState

    state = RepoState(f"/home/user/{name}")
    state.git = True
    state.root = state.project_dir
    state.repo_name = name
    state.branch = "main"
    state.upstream = "origin/main"
    state.has_remote = True
    for key, value in attrs.items():
        setattr(state, key, value)
    return state


def _cold_cache(cause="tools_changed", tokens=38_000):
    return {
        "caching_observed": True,
        "warm": False,
        "ttl": "1h",
        "recache_tokens_if_cold": tokens,
        "last_miss_cause": {"causes": [cause]},
    }


def scenarios() -> dict:
    """name → (description, session, plan bars, plan label, repo state, columns or None)."""
    sonnet = {"id": "claude-sonnet-5-5", "display_name": "Sonnet 5.5"}
    return {
        "pro-trial": (
            "Pro during a Claude Code trial",
            _session(model=sonnet, effort={"level": "medium"}, cost={"total_cost_usd": 0.84}),
            [_bar("5h", 22, 3 * 3600), _bar("7d", 9, 5 * 86400)],
            ("Pro", "trial 5d"),
            _repo(),
            None,
        ),
        "pro": (
            "Pro, deep into the 5-hour window, uncommitted work",
            _session(context_window={"used_percentage": 63}),
            [_bar("5h", 81, 100 * 60), _bar("7d", 34, 4 * 86400)],
            "Pro",
            _repo(
                branch="feat/cache",
                upstream="origin/feat/cache",
                dirty=True,
                added=120,
                removed=45,
                untracked=True,
            ),
            None,
        ),
        "ultra-fable": (
            "Ultra on Fable with fast mode, credits in use, cache about to expire",
            *_ultra_fable(),
            None,
        ),
        "team": (
            "Team seat in a linked worktree, monthly cap",
            _session(agent={"name": "code-reviewer"}),
            [_bar("5h", 74, 2 * 3600 + 600), _bar("7d", 52, 2 * 86400), _bar("month", 35)],
            "Team",
            _repo(
                worktree="wt-cache",
                branch="feat/cache",
                upstream="origin/feat/cache",
                dirty=True,
                added=12,
            ),
            None,
        ),
        "enterprise": (
            "Enterprise: usage-based seat, the monthly cap is the only bar",
            _session(context_window={"used_percentage": 18}, cost={"total_cost_usd": 2.37}),
            [_bar("month", 18)],
            "Enterprise",
            _repo(
                name="platform",
                project_dir="/home/user/platform/services/api",
                root="/home/user/platform",
                behind=3,
            ),
            None,
        ),
        "api": (
            "API key: no plan, so no plan line; not a git repo",
            _session(
                model=sonnet,
                effort={"level": "medium"},
                cost={"total_cost_usd": 0.57},
                context_window={"used_percentage": 12},
            ),
            [],
            "API",
            _plain_dir("/home/user/scratch/notes"),
            None,
        ),
        "limit": (
            "Pro at its 5-hour limit after the cache went cold",
            _session(prompt_cache=_cold_cache(), context_window={"used_percentage": 57}),
            [_bar("5h", 100, 72 * 60), _bar("7d", 71, 2 * 86400 + 5 * 3600)],
            "Pro",
            _repo(),
            None,
        ),
        "rebase": (
            "Rebase stopped on conflicts, branch diverged from its upstream",
            _session(),
            [_bar("5h", 22, 3 * 3600), _bar("7d", 48, 3 * 86400)],
            "Max",
            _repo(
                branch="feat/cache",
                upstream="origin/feat/cache",
                operation="rebase",
                progress="3/7",
                conflicts=2,
                dirty=True,
                added=30,
                removed=2,
                ahead=2,
                behind=1,
            ),
            None,
        ),
        "narrow": (
            "Ultra with four bars at 80 columns: credits turns into text",
            _session(
                model={"id": "claude-fable-5-1", "display_name": "Fable 5.1"},
                context_window={"used_percentage": 22},
            ),
            [
                _bar("5h", 38, 3 * 3600),
                _bar("7d", 48, 3 * 86400),
                _bar("Fable", 24, 3 * 86400),
                _bar("credits", 12),
            ],
            "Ultra",
            _repo(),
            80,
        ),
        "tiny": (
            "ultra-fable at 64 columns: the plan bars become text",
            *_ultra_fable(dirty=True, added=120, removed=45),
            64,
        ),
    }


def _plain_dir(path):
    from dashline.repo import RepoState

    return RepoState(path)


def _ultra_fable(**repo):
    """(session, plan bars, label, repo) for the Ultra-on-Fable scenarios."""
    session = _session(
        model={"id": "claude-fable-5-1", "display_name": "Fable 5.1"},
        effort={"level": "xhigh"},
        fast_mode=True,
        cost={"total_cost_usd": 11.8},
        context_window={"used_percentage": 63},
        prompt_cache={"caching_observed": True, "warm": True, "ttl": "1h", "expires_at": NOW + 180},
    )
    plan = [_bar("7d", 48, 3 * 86400), _bar("Fable", 24, 3 * 86400), _bar("credits", 12)]
    state = _repo(branch="feat/cache", upstream="origin/feat/cache", ahead=2, **repo)
    return session, plan, "Ultra", state


def render(name: str, glyphs: str, palette, columns: int) -> list:
    """One scenario's lines, as Claude Code would draw them."""
    from dashline import glyphs as glyph_sets
    from dashline import layout

    _, session, plan, label, repo, fixed = scenarios()[name]
    g = glyph_sets.get(glyphs)
    if isinstance(label, tuple):
        label = g["sep_item"].join(label)  # plan name and trial, joined as account.py does
    return layout.render(
        session,
        g,
        palette,
        fixed or columns,
        NOW,
        plan,
        label,
        None,
        repo,
        "/home/user",
    )


def run(scenario: str | None, glyphs: str = "unicode", env=None, out=None) -> int:
    import os
    import shutil

    from dashline import theme

    env = os.environ if env is None else env
    out = out or sys.stdout
    table = scenarios()
    names = list(table) if scenario in (None, "all") else [scenario]
    unknown = [n for n in names if n not in table]
    if unknown:
        sys.stderr.write(
            f"dashline: unknown scenario {unknown[0]!r}; choose from: all, {', '.join(table)}\n"
        )
        return 2
    columns = env.get("COLUMNS", "")
    columns = int(columns) if columns.isdigit() else shutil.get_terminal_size((100, 24)).columns
    palette = theme.load(None, env)
    dim = palette.sgr("inactive")
    sets = ("nerd", "unicode", "ascii") if glyphs == "all" else (glyphs,)
    blocks = [(g, name) for g in sets for name in names]
    for i, (g, name) in enumerate(blocks):
        if len(blocks) > 1:
            parts = [g] if len(sets) > 1 else []
            if len(names) > 1:
                parts.append(f"{name}: {table[name][0]}")
            head = " · ".join(parts)
            out.write(("\n" if i else "") + (f"\x1b[{dim}m{head}\x1b[0m" if dim else head) + "\n")
        for line in render(name, g, palette, columns):
            out.write(INDENT + line + "\n")
    return 0
