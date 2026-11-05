# Preview font

`SymbolsNerdFontMono-dashline.ttf` is a subset of `SymbolsNerdFontMono-Regular.ttf` from
[Nerd Fonts](https://github.com/ryanoasis/nerd-fonts) v3.5.1 (`NerdFontsSymbolsOnly.tar.xz`,
sha256 `01172f37db8543edb102e5cb5c64101c9f4686630804d49b419aa07b23a69996`). It holds only
the icons in dashline's `nerd` glyph set, and `scripts/preview.py` embeds it in
`docs/preview.svg` and `docs/plans.svg`.

- Nerd Fonts: MIT License, see `LICENSE-nerd-fonts`.
- The icons come from [Material Design Icons](https://github.com/Templarian/MaterialDesign-Font):
  Apache License 2.0, see `LICENSE-material-design-icons`.

Rebuild it after adding an icon to the nerd set:

    uv run python scripts/preview.py --font path/to/SymbolsNerdFontMono-Regular.ttf
