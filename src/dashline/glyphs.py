"""Glyph tables for the nerd, unicode and ascii sets (PLAN §7).

Every slot exists in every set. An empty icon means "no icon": the text stands alone.
Nerd glyphs are Material Design icons from plane 15 (codepoints in the comments).
"""

from __future__ import annotations

NERD = {
    # line 1
    "fast": "\U000f140b",  # md-lightning_bolt
    "cache_timer": "\U000f051f ",  # md-timer_sand
    "cache_cold": "\U000f0717 cold",  # md-snowflake
    "recache": "\U000f0450",  # md-refresh, no space: "󰑐38k"
    "agent": "\U000f167a ",  # md-robot_outline
    "sep_item": " · ",
    "sep_group": " │ ",
    "bar_fill": "▆",
    "bar_empty": "▁",
    "ellipsis": "…",
    "minus": "−",
    # line 3 (Phase 4)
    "project": "\U000f02a2 ",  # md-git
    "folder": "\U000f0770 ",  # md-folder_open
    "worktree": " \U000f0645 ",  # md-file_tree
    "branch": "\U000f062c ",  # md-source_branch
    "detached": "\U000f0718 ",  # md-source_commit
    "tag": "\U000f04f9 ",  # md-tag
    "uncommitted": "\U000f03eb",  # md-pencil
    "untracked": "\U000f0752",  # md-file_plus
    "ahead": "\U000f0737",  # md-arrow_up_bold
    "behind": "\U000f072e",  # md-arrow_down_bold
    "never_pushed": "\U000f0b7e",  # md-cloud_upload_outline
    "upstream_gone": "\U000f14cc",  # md-source_branch_remove
    "conflicts": "\U000f0026 ",  # md-alert
    "drift": "\U000f060d ",  # md-subdirectory_arrow_right
    "op_rebase": "\U000f14ce ",  # md-source_branch_sync
    "op_merge": "\U000f062d ",  # md-source_merge
    "op_cherry_pick": "\U000f1042 ",  # md-fruit_cherries
    "op_revert": "\U000f054c ",  # md-undo
    "op_bisect": "\U000f04fe ",  # md-target
    "op_am": "\U000f01ef ",  # md-email_open
}

UNICODE = {
    "fast": "↯",
    "cache_timer": "⧗ ",
    "cache_cold": "cache cold",
    "recache": "↻",
    "agent": "@",
    "sep_item": " · ",
    "sep_group": " │ ",
    "bar_fill": "▆",
    "bar_empty": "▁",
    "ellipsis": "…",
    "minus": "−",
    "project": "",
    "folder": "",
    "worktree": " ⑂ ",
    "branch": "⎇ ",
    "detached": "#",
    "tag": "tag:",
    "uncommitted": "✎",
    "untracked": "?",
    "ahead": "⇡",
    "behind": "⇣",
    "never_pushed": "local",
    "upstream_gone": "gone",
    "conflicts": "✗ ",
    "drift": "↳ ",
    "op_rebase": "",
    "op_merge": "",
    "op_cherry_pick": "",
    "op_revert": "",
    "op_bisect": "",
    "op_am": "",
}

ASCII = {
    "fast": "fast",
    "cache_timer": "cache ",
    "cache_cold": "cache cold",
    "recache": "recache ",
    "agent": "@",
    "sep_item": " / ",
    "sep_group": " | ",
    "bar_fill": "#",
    "bar_empty": "-",
    "ellipsis": "...",
    "minus": "-",
    "project": "",
    "folder": "",
    "worktree": " [",  # "name [wt]": the closing bracket comes from the row
    "branch": "(",
    "detached": "(#",
    "tag": "(tag:",
    "uncommitted": "*",
    "untracked": "?",
    "ahead": ">",
    "behind": "<",
    "never_pushed": "local",
    "upstream_gone": "gone",
    "conflicts": "! ",
    "drift": "",
    "op_rebase": "",
    "op_merge": "",
    "op_cherry_pick": "",
    "op_revert": "",
    "op_bisect": "",
    "op_am": "",
}

SETS = {"nerd": NERD, "unicode": UNICODE, "ascii": ASCII}


def get(name: str) -> dict:
    return SETS.get(name, UNICODE)
