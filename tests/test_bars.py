import pytest

from dashline import bars, theme
from dashline.colors import THEMES

DARK = theme.Palette(THEMES["dark"])
GREEN, GOLD, CORAL = (78, 186, 101), (255, 193, 7), (255, 107, 128)


@pytest.mark.parametrize(
    ("percent", "expected"),
    [(0, GREEN), (40, GREEN), (70, GOLD), (90, CORAL), (100, CORAL), (250, CORAL)],
)
def test_ramp_anchors(percent, expected):
    assert bars.ramp(percent, DARK) == expected


def test_ramp_blends_between_anchors():
    mid = bars.ramp(55, DARK)  # halfway green → gold
    assert mid == tuple(round((g + o) / 2) for g, o in zip(GREEN, GOLD))
    assert bars.ramp(80, DARK) == tuple(round((o + c) / 2) for o, c in zip(GOLD, CORAL))


@pytest.mark.parametrize(
    ("percent", "token"),
    [(10, "success"), (54, "success"), (55, "warning"), (79, "warning"), (80, "error")],
)
def test_ramp_steps_on_ansi_themes(percent, token):
    assert bars.ramp(percent, theme.Palette(THEMES["dark-ansi"])) == token


@pytest.mark.parametrize(
    ("percent", "width", "cells"),
    [
        (0, 10, 0),
        (-5, 10, 0),
        (0.1, 10, 1),  # anything above 0% shows
        (41, 10, 4),
        (45, 10, 5),  # half rounds up
        (55, 10, 6),
        (46, 10, 5),
        (99.9, 10, 9),  # full only at the limit
        (100, 10, 10),
        (180, 10, 10),
        (50, 0, 0),
    ],
)
def test_filled(percent, width, cells):
    assert bars.filled(percent, width) == cells


@pytest.mark.parametrize(
    ("percent", "text"),
    [
        (0, "0%"),
        (41.4, "41%"),
        (41.5, "42%"),
        (42.5, "43%"),
        (99.6, "99%"),
        (100, "100%"),
        (140.2, "140%"),
    ],
)
def test_percent_text(percent, text):
    assert bars.percent_text(percent) == text


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (-3, "0s"),
        (45, "45s"),
        (60, "1m"),
        (61, "2m"),
        (40 * 60, "40m"),
        (100 * 60, "1h40m"),
        (2 * 3600, "2h"),
        (52 * 3600, "2d4h"),
        (48 * 3600, "2d"),
    ],
)
def test_duration(seconds, text):
    assert bars.duration(seconds) == text


@pytest.mark.parametrize(
    ("count", "text"), [(950, "950"), (38_400, "38k"), (999_600, "1.0M"), (1_234_000, "1.2M")]
)
def test_tokens(count, text):
    assert bars.tokens(count) == text
