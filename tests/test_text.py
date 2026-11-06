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
        # A text-style character with VS16 is drawn as an emoji: two columns.
        ("\u2764\ufe0f", 2),
        ("\u26a0\ufe0f", 2),
        ("\u2601\ufe0f", 2),
        ("\u2764", 1),
        ("\u26a0\ufe0f main", 7),
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


def test_cut_keeps_a_character_with_its_vs16():
    heart = "\u2764\ufe0f"
    assert cut(f"a{heart}b", 2) == "a"  # the pair takes two columns, or none
    assert cut(f"a{heart}b", 3) == f"a{heart}"
    assert cut(f"a{heart}b", 4) == f"a{heart}b"


def test_zwj_sequences_stay_sane():
    family = "\U0001f468\u200d\U0001f469\u200d\U0001f467"
    # Counted as its three emoji (a terminal may draw one): too wide at worst, never
    # too narrow, and cut never leaves more than the limit.
    assert cols(family) == 6
    for limit in range(8):
        assert cols(cut(family, limit)) <= limit
