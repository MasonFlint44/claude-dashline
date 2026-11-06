"""Outside text: cleaned of control characters and measured in terminal columns."""

import pytest

from dashline.text import clean, cols, cut


@pytest.mark.parametrize(
    ("text", "width"),
    [
        ("main", 4),
        ("修正", 4),  # East Asian Wide: two columns each
        ("\uff46\uff55\uff4c\uff4c", 8),  # Fullwidth
        ("e\u0301", 1),  # a combining accent sits on the e
        ("👍", 2),
        ("\U0001f44d\ufe0f", 2),  # the emoji variation selector takes no column
        ("▆▁│·…", 5),  # ambiguous width: one column, as Claude Code draws them
        ("\U000f02a2", 1),  # a Nerd Font icon (private use)
        ("", 0),
    ],
)
def test_cols(text, width):
    assert cols(text) == width


@pytest.mark.parametrize(
    ("text", "limit", "start"),
    [
        ("feature", 4, "feat"),
        ("修正ab", 3, "修"),  # a wide character never straddles the limit
        ("修正ab", 4, "修正"),
        ("修正ab", 5, "修正a"),
        ("e\u0301x", 1, "e\u0301"),
        ("abc", 0, ""),
        ("abc", -2, ""),
        ("修", 1, ""),
    ],
)
def test_cut(text, limit, start):
    assert cut(text, limit) == start
    assert cols(cut(text, limit)) <= max(0, limit)


def test_clean():
    assert clean("ok name") == "ok name"
    assert clean("a\nb\x1b[0m\x7f\u2028\u202e") == "a?b?[0m???"
    assert clean("修正 👍") == "修正 👍"
