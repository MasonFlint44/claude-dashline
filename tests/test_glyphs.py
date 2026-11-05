"""Every glyph is one column wide everywhere (PLAN §7, Phase 0 E4)."""

import re
import unicodedata

import pytest

from dashline import glyphs, layout, preview, theme
from dashline.colors import THEMES

# Codepoints below U+3300 with the Unicode Emoji property, apart from ASCII. Terminals
# may draw any of them two columns wide (emoji presentation), so no glyph uses them.
# From emoji-data.txt; the U+1F000–U+1FFFF emoji blocks are ruled out whole.
EMOJI_RANGES = [
    (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C), (0x2049, 0x2049),
    (0x2122, 0x2122), (0x2139, 0x2139), (0x2194, 0x2199), (0x21A9, 0x21AA),
    (0x231A, 0x231B), (0x2328, 0x2328), (0x23CF, 0x23CF), (0x23E9, 0x23F3),
    (0x23F8, 0x23FA), (0x24C2, 0x24C2), (0x25AA, 0x25AB), (0x25B6, 0x25B6),
    (0x25C0, 0x25C0), (0x25FB, 0x25FE), (0x2600, 0x2604), (0x260E, 0x260E),
    (0x2611, 0x2611), (0x2614, 0x2615), (0x2618, 0x2618), (0x261D, 0x261D),
    (0x2620, 0x2620), (0x2622, 0x2623), (0x2626, 0x2626), (0x262A, 0x262A),
    (0x262E, 0x262F), (0x2638, 0x263A), (0x2640, 0x2640), (0x2642, 0x2642),
    (0x2648, 0x2653), (0x265F, 0x2660), (0x2663, 0x2663), (0x2665, 0x2666),
    (0x2668, 0x2668), (0x267B, 0x267B), (0x267E, 0x267F), (0x2692, 0x2697),
    (0x2699, 0x2699), (0x269B, 0x269C), (0x26A0, 0x26A1), (0x26A7, 0x26A7),
    (0x26AA, 0x26AB), (0x26B0, 0x26B1), (0x26BD, 0x26BE), (0x26C4, 0x26C5),
    (0x26C8, 0x26C8), (0x26CE, 0x26CF), (0x26D1, 0x26D1), (0x26D3, 0x26D4),
    (0x26E9, 0x26EA), (0x26F0, 0x26F5), (0x26F7, 0x26FA), (0x26FD, 0x26FD),
    (0x2702, 0x2702), (0x2705, 0x2705), (0x2708, 0x270D), (0x270F, 0x270F),
    (0x2712, 0x2712), (0x2714, 0x2714), (0x2716, 0x2716), (0x271D, 0x271D),
    (0x2721, 0x2721), (0x2728, 0x2728), (0x2733, 0x2734), (0x2744, 0x2744),
    (0x2747, 0x2747), (0x274C, 0x274C), (0x274E, 0x274E), (0x2753, 0x2755),
    (0x2757, 0x2757), (0x2763, 0x2764), (0x2795, 0x2797), (0x27A1, 0x27A1),
    (0x27B0, 0x27B0), (0x27BF, 0x27BF), (0x2934, 0x2935), (0x2B05, 0x2B07),
    (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55), (0x3030, 0x3030),
    (0x303D, 0x303D), (0x3297, 0x3297), (0x3299, 0x3299),
]  # fmt: skip
# The four emoji-capable characters the plan names as traps, as a check on the table.
KNOWN_EMOJI = "⚠❄☁⚡✖✔✏"
# Material Design icons in the Nerd Font plane-15 private use area.
NERD_ICONS = (0xF0001, 0xF1AF0)


def emoji_capable(ch: str) -> bool:
    cp = ord(ch)
    return 0x1F000 <= cp <= 0x1FFFF or any(lo <= cp <= hi for lo, hi in EMOJI_RANGES)


def private_use(ch: str) -> bool:
    return unicodedata.category(ch) == "Co"


def chars(glyph_set: str):
    for slot, value in glyphs.SETS[glyph_set].items():
        for ch in value:
            yield slot, ch


def test_emoji_table_catches_the_known_traps():
    assert all(emoji_capable(ch) for ch in KNOWN_EMOJI)


def test_every_set_has_every_slot():
    assert set(glyphs.NERD) == set(glyphs.UNICODE) == set(glyphs.ASCII)


@pytest.mark.parametrize("glyph_set", ["nerd", "unicode", "ascii"])
def test_one_column_each(glyph_set):
    for slot, ch in chars(glyph_set):
        assert unicodedata.east_asian_width(ch) not in ("W", "F"), (slot, ch)
        assert unicodedata.category(ch) not in ("Mn", "Me", "Cf", "Cc"), (slot, ch)
        assert not emoji_capable(ch), (slot, ch)


def test_unicode_set_has_no_nerd_glyphs():
    for slot, ch in chars("unicode"):
        assert not private_use(ch), slot


def test_ascii_set_is_ascii():
    for slot, ch in chars("ascii"):
        assert ord(ch) < 128, (slot, ch)


def test_nerd_icons_are_material_design():
    for slot, ch in chars("nerd"):
        if private_use(ch):
            assert NERD_ICONS[0] <= ord(ch) <= NERD_ICONS[1], (slot, hex(ord(ch)))


@pytest.mark.parametrize("glyph_set", ["nerd", "unicode", "ascii"])
def test_rendered_text_follows_the_set(glyph_set):
    """Not just the table: every character dashline prints obeys the set's rules."""
    palette = theme.Palette(THEMES["dark"], color=False)
    ansi = re.compile(r"\x1b\[[0-9;]*m|\x1b\]8;;[^\x1b]*\x1b\\")
    for name in preview.scenarios():
        for line in preview.render(name, glyph_set, palette, 120):
            for ch in ansi.sub("", line):
                assert not emoji_capable(ch), (name, ch)
                assert unicodedata.east_asian_width(ch) not in ("W", "F"), (name, ch)
                if glyph_set == "ascii":
                    assert ord(ch) < 128, (name, ch)
                if glyph_set == "unicode":
                    assert not private_use(ch), (name, ch)


@pytest.mark.parametrize("glyph_set", ["nerd", "unicode", "ascii"])
def test_bars_read_without_color(glyph_set):
    """Fill and empty differ in shape, so a bar still reads with NO_COLOR."""
    g = glyphs.get(glyph_set)
    assert g["bar_fill"] != g["bar_empty"]
    assert layout.width([(g["bar_fill"], "")]) == 1
