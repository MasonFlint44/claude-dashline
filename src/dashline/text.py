"""Text from outside dashline (model and agent names, folders, branches, URLs): made safe
to print, and measured in terminal columns.

A control character in a name would reach the terminal as-is: a newline splits a line,
an ESC starts an escape sequence. `clean` turns each one into `?`, along with the
Unicode line separators and the bidirectional overrides that reorder what follows them.

A terminal draws East Asian Wide and Fullwidth characters (CJK, most emoji) two columns
wide and combining marks over the character before them, so `cols` counts columns, not
characters. A character followed by VS16 (U+FE0F, "draw as emoji", as in ❤️) is drawn as
an emoji, two columns. Ambiguous-width characters count 1, as Claude Code draws them
(PLAN §7), and so do Nerd Font icons (private use). ASCII, the usual case, skips the
lookup.
"""

from __future__ import annotations

from functools import lru_cache

VS16 = "\ufe0f"
# Bidirectional marks, embeddings, overrides and isolates.
BIDI = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def clean(text: str) -> str:
    """`text` with control characters, line separators and bidi controls as `?`."""
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
    """(end index, columns) per drawn unit: a character, with its VS16 if one follows."""
    i, n = 0, len(text)
    while i < n:
        w = _char_cols(text[i])
        i += 1
        if w and i < n and text[i] == VS16:
            w, i = 2, i + 1
        yield i, w


def _char_cols(c: str) -> int:
    import unicodedata

    if unicodedata.east_asian_width(c) in ("W", "F"):
        return 2
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
