"""Draw the README previews as SVG from the built-in scenarios (PLAN §10).

    uv run python scripts/preview.py            # write docs/preview.svg and docs/plans.svg
    uv run python scripts/preview.py --check    # exit 1 if either is out of date (CI)
    uv run python scripts/preview.py --font SymbolsNerdFontMono-Regular.ttf
                                                # rebuild the embedded icon font

The images come from `dashline.preview`, the same fake data `--preview` prints, with the
dark theme and the `nerd` glyph set. The terminal is drawn on a column grid: bar cells
and separators are rectangles, and each text run is pinned to its columns with
`textLength`, so the viewer's own monospace font can't push anything off the grid.

The Nerd Font icons come from a subset of Symbols Nerd Font Mono, kept in
scripts/assets/ and embedded in each SVG. It covers every icon in the nerd set, so new
scenarios don't need a rebuild; a new icon does (`--font`, from
https://github.com/ryanoasis/nerd-fonts/releases, NerdFontsSymbolsOnly).
"""

from __future__ import annotations

import argparse
import base64
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dashline import glyphs, preview, theme  # noqa: E402
from dashline.colors import THEMES  # noqa: E402

ASSETS = ROOT / "scripts" / "assets"
SUBSET = ASSETS / "SymbolsNerdFontMono-dashline.ttf"
DOCS = ROOT / "docs"
IMAGES = {
    "preview.svg": ["ultra-fable"],
    "plans.svg": ["pro", "team", "enterprise", "api", "limit", "rebase"],
}
COLUMNS = 100

# Geometry, in px. CW is a 14 px monospace font's advance.
CW, LH, FONT = 8.4, 20, 14
PAD_X, PAD_Y = 14, 12  # inside each terminal panel
CAPTION_H = 22  # caption line above a panel (gallery only)
GAP = 14  # between panels
SEP_W = 1.6  # width of a │ separator
BG = "#1e1e1e"
FONT_STACK = "DashlineSymbols, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
CAPTION_FONT = "-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"

# Lower-block glyphs drawn as rectangles: char → share of the cell's height.
BLOCKS = {"▆": 6 / 8, "▁": 1 / 8}
SEP = "│"
SGR = re.compile(r"\x1b\[([0-9;]*)m")
OSC8 = re.compile(r"\x1b\]8;[^;]*;[^\x1b]*\x1b\\")


def rgb_hex(value) -> str:
    return "#{:02x}{:02x}{:02x}".format(*value)


def cells(line: str, default: str) -> list:
    """An ANSI line → [(char, color, bold)], one per column. Links are dropped."""
    line = OSC8.sub("", line)
    color, bold = default, False
    # SGR.split alternates text and the captured codes.
    pieces = SGR.split(line)
    out = []
    for i, piece in enumerate(pieces):
        if i % 2:
            codes = [int(c) if c else 0 for c in piece.split(";")]
            j = 0
            while j < len(codes):
                c = codes[j]
                if c == 0:
                    color, bold = default, False
                elif c == 1:
                    bold = True
                elif c == 22:
                    bold = False
                elif c == 39:
                    color = default
                elif c == 38 and codes[j + 1 : j + 2] == [2]:
                    color = rgb_hex(codes[j + 2 : j + 5])
                    j += 4
                else:
                    raise ValueError(f"unsupported SGR {c} in {line!r}")
                j += 1
        else:
            out.extend((ch, color, bold) for ch in piece)
    return out


def draw_line(row: list, x0: float, top: float) -> list:
    """SVG elements for one terminal line whose cell tops are at `top`."""
    out = []
    base = top + LH * 0.72  # text baseline inside the cell
    col = 0
    while col < len(row):
        ch, color, bold = row[col]
        x = x0 + col * CW
        if ch in BLOCKS:
            end = col
            while end < len(row) and row[end][:2] == (ch, color):
                end += 1
            h = LH * BLOCKS[ch]
            out.append(
                f'<rect x="{x:.1f}" y="{top + LH - h:.1f}" width="{(end - col) * CW:.1f}" '
                f'height="{h:.1f}" fill="{color}"/>'
            )
            col = end
            continue
        if ch == SEP:
            out.append(
                f'<rect x="{x + (CW - SEP_W) / 2:.1f}" y="{top + 2:.1f}" width="{SEP_W}" '
                f'height="{LH - 4}" fill="{color}"/>'
            )
            col += 1
            continue
        end = col
        while (
            end < len(row)
            and row[end][1:] == (color, bold)
            and row[end][0] not in BLOCKS
            and row[end][0] != SEP
        ):
            end += 1
        run = "".join(c[0] for c in row[col:end])
        if run.strip():
            weight = ' font-weight="bold"' if bold else ""
            out.append(
                f'<text x="{x:.1f}" y="{base:.1f}" textLength="{(end - col) * CW:.1f}" '
                f'lengthAdjust="spacingAndGlyphs" fill="{color}"{weight} '
                f'xml:space="preserve">{html.escape(run)}</text>'
            )
        col = end
    return out


def font_face() -> str:
    data = base64.b64encode(SUBSET.read_bytes()).decode()
    return (
        "<style>@font-face{font-family:DashlineSymbols;"
        f'src:url("data:font/ttf;base64,{data}") format("truetype");}}</style>'
    )


NOTICE = (
    "<!-- Generated by scripts/preview.py from dashline's built-in scenarios; do not edit.\n"
    "Embedded icons: a subset of Symbols Nerd Font Mono (Nerd Fonts, MIT License,\n"
    "Copyright (c) 2014 Ryan L McIntyre) whose glyphs come from Material Design Icons\n"
    "(Apache License 2.0). See scripts/assets/ for the license texts. -->\n"
)


def svg(names: list) -> str:
    """One SVG: a terminal panel per scenario, with captions when there are several."""
    palette = theme.Palette(THEMES["dark"])
    default = rgb_hex(palette.rgb("inactive"))
    table = preview.scenarios()
    gallery = len(names) > 1
    panels = []
    for name in names:
        lines = preview.render(name, "nerd", palette, COLUMNS)
        panels.append((table[name][0], [cells(line, default) for line in lines]))
    width = round(COLUMNS * CW + 2 * PAD_X)
    body, y = [], 0.0
    for caption, rows in panels:
        if gallery:
            body.append(
                f'<text x="2" y="{y + 15:.1f}" font-family="{CAPTION_FONT}" font-size="13" '
                f'fill="#8b949e">{html.escape(caption)}</text>'
            )
            y += CAPTION_H
        h = len(rows) * LH + 2 * PAD_Y
        body.append(f'<rect y="{y:.1f}" width="{width}" height="{h}" rx="8" fill="{BG}"/>')
        for i, row in enumerate(rows):
            body.extend(draw_line(row, PAD_X, y + PAD_Y + i * LH))
        y += h + GAP
    height = round(y - GAP)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{FONT_STACK}" font-size="{FONT}">\n'
        + NOTICE
        + font_face()
        + "\n"
        + "\n".join(body)
        + "\n</svg>\n"
    )


def nerd_icons() -> list:
    """Every private-use code point in the nerd glyph set."""
    found = {ord(c) for value in glyphs.get("nerd").values() for c in str(value)}
    return sorted(c for c in found if 0xE000 <= c <= 0xF8FF or c >= 0xF0000)


def build_subset(source: Path) -> None:
    from fontTools import subset

    options = subset.Options()
    options.hinting = False
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6]  # keep copyright and naming
    options.notdef_outline = True
    font = subset.load_font(str(source), options)
    sub = subset.Subsetter(options)
    sub.populate(unicodes=nerd_icons())
    sub.subset(font)
    ASSETS.mkdir(parents=True, exist_ok=True)
    subset.save_font(font, str(SUBSET), options)


def missing_icons() -> list:
    from fontTools.ttLib import TTFont

    cmap = TTFont(str(SUBSET)).getBestCmap()
    return [c for c in nerd_icons() if c not in cmap]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if an image is stale")
    parser.add_argument("--font", type=Path, help="rebuild the icon subset from this font")
    args = parser.parse_args(argv)

    if args.font:
        build_subset(args.font)
        print(f"wrote {SUBSET.relative_to(ROOT)} ({SUBSET.stat().st_size} bytes)")
    missing = missing_icons()
    if missing:
        listed = " ".join(f"U+{c:04X}" for c in missing)
        print(f"the icon subset lacks {listed}: rebuild it with --font", file=sys.stderr)
        return 1
    stale = []
    for filename, names in IMAGES.items():
        path = DOCS / filename
        text = svg(names)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if text == current:
            continue
        stale.append(filename)
        if not args.check:
            path.write_text(text, encoding="utf-8")
            print(f"wrote docs/{filename}")
    if args.check and stale:
        print(f"out of date: {', '.join(stale)}; run scripts/preview.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
