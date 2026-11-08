"""Text from outside dashline (model and agent names, folders, branches, URLs): made safe
to print, and measured in terminal columns.

A control character in a name would reach the terminal as-is: a newline splits a line,
an ESC starts an escape sequence. `clean` turns each one into `?`, along with the
Unicode line separators and the bidirectional overrides that reorder what follows them.

A terminal draws East Asian Wide and Fullwidth characters (CJK, most emoji) two columns
wide and combining marks over the character before them, so `cols` counts columns, not
characters. A character followed by VS16 (U+FE0F, "draw as emoji", as in ❤️) is drawn as
an emoji, two columns. A flag is a pair of regional indicators drawn as one emoji, two
columns, and never cut in half; a lone indicator counts 2 too. Hangul jamo vowels and
finals join the initial consonant before them (decomposed Hangul, as some file systems
store names), so they count 0. Ambiguous-width characters count 1, as Claude Code draws
them (PLAN §7), and so do Nerd Font icons (private use). ASCII, the usual case, skips the
lookup.
"""

from __future__ import annotations

from functools import lru_cache

VS16 = "\ufe0f"
# Bidirectional marks, embeddings, overrides and isolates.
BIDI = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def collapse_home(path: str, home: str | None) -> str:
    """`/home/me/x` → `~/x`. A home of `/` (or none) collapses nothing.

    On Windows the match ignores case and the result uses `/`: Git Bash and PowerShell
    both read that, and a path in a message may be pasted into either.
    """
    import os

    home = (home or "").rstrip("/" + os.sep)
    near, base = os.path.normcase(path), os.path.normcase(home)
    if home and (near == base or near.startswith(base + os.sep)):
        path = "~" + path[len(home) :]
    return path if os.sep == "/" else path.replace(os.sep, "/")


# The most of a name clean() keeps: past any row's width (COLUMNS is capped at 1000).
# Measuring every character of a huge one (from a broken endpoint, say) is what costs.
MAX_SHOWN = 4096


def clean(text: str) -> str:
    """`text` with control characters, line separators and bidi controls as `?`, cut to
    MAX_SHOWN characters."""
    text = text[:MAX_SHOWN]
    if text.isprintable():  # the usual case, and cheap
        return text
    import unicodedata

    return "".join(
        "?" if c in BIDI or unicodedata.category(c) in ("Cc", "Zl", "Zp") else c for c in text
    )


def cols(text: str) -> int:
    """Columns `text` takes in a terminal."""
    return len(text) if text.isascii() else _cols(text)


@lru_cache(maxsize=512)
def _cols(text: str) -> int:
    return sum(w for _, w in _units(text))


def _units(text: str):
    """(end index, columns) per drawn unit: a character with its VS16 if one follows, or
    a flag (two regional indicators)."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        w = _char_cols(c)
        i += 1
        if _regional(c) and i < n and _regional(text[i]):
            i += 1  # the second half of a flag
        elif w and i < n and text[i] == VS16:
            w, i = 2, i + 1
        yield i, w


def _regional(c: str) -> bool:
    return "\U0001f1e6" <= c <= "\U0001f1ff"


def _char_cols(c: str) -> int:
    import unicodedata

    if "\u1160" <= c <= "\u11ff" or "\ud7b0" <= c <= "\ud7ff":
        return 0  # a Hangul vowel or final, joined to the syllable before it
    if _regional(c) or unicodedata.east_asian_width(c) in ("W", "F"):
        return 2
    if c == "\u00ad":
        return 1  # a soft hyphen: a format character, but most terminals draw it
    if unicodedata.combining(c) or unicodedata.category(c) in ("Mn", "Me", "Cf"):
        return 0  # drawn over the character before it (or not at all: ZWJ, VS16)
    return 1


def cut(text: str, limit: int) -> str:
    """The longest start of `text` that fits in `limit` columns."""
    if text.isascii():
        return text[: max(0, limit)]
    used, start = 0, 0
    for end, w in _units(text):
        used += w
        if used > limit:
            return text[:start]
        start = end
    return text
