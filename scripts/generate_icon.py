"""Generate FoxPort logo / favicon raster set.

Run from the repo root:

    python scripts/generate_icon.py

Writes the following assets (overwrites in place):

* ``assets/icon.ico`` — multi-resolution Windows ICO embedding the
  16/24/32/48/64/128/256-px frames PyInstaller and Explorer want. The
  release workflow + ``foxport.spec`` pick this file up for the signed
  EXE's icon resource, and browsers treat ``icon.ico`` as a usable
  favicon if linked from a web page.
* ``assets/icon-256.png`` — high-resolution PNG for README usage and as
  the source-of-truth bitmap for the icon at display size.
* ``assets/icon-16.png`` / ``assets/icon-32.png`` — PNG favicon frames
  for sites that prefer PNG `<link rel="icon">` over ICO.

The artwork is rendered from code so the icon is reproducible: future
brand tweaks happen here, not by re-exporting from a binary editor. The
palette tracks the Catppuccin Mocha gradient already used in
``assets/banner.svg``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets"

# Catppuccin Mocha — same gradient as assets/banner.svg.
BG_TOP = (30, 30, 46)       # #1e1e2e
BG_BOT = (24, 24, 37)       # #181825
ACCENT_LEFT = (245, 194, 231)   # #f5c2e7 (pink)
ACCENT_MID = (203, 166, 247)    # #cba6f7 (purple)
ACCENT_RIGHT = (137, 180, 250)  # #89b4fa (blue)
FG_TEXT = (205, 214, 244)       # #cdd6f4 (subtext)


def _vlerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(round(a[0] + (b[0] - a[0]) * t)),
        int(round(a[1] + (b[1] - a[1]) * t)),
        int(round(a[2] + (b[2] - a[2]) * t)),
    )


def _gradient_horizontal(size: int) -> Image.Image:
    """Pink → purple → blue horizontal sweep, full RGBA."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for x in range(size):
        t = x / max(1, size - 1)
        if t < 0.5:
            color = _vlerp(ACCENT_LEFT, ACCENT_MID, t * 2)
        else:
            color = _vlerp(ACCENT_MID, ACCENT_RIGHT, (t - 0.5) * 2)
        for y in range(size):
            px[x, y] = color + (255,)
    return img


def _rounded_panel(size: int, radius: float) -> Image.Image:
    """Rounded-square panel with the dark Mocha vertical gradient."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y in range(size):
        t = y / max(1, size - 1)
        color = _vlerp(BG_TOP, BG_BOT, t)
        for x in range(size):
            px[x, y] = color + (255,)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=255
    )
    img.putalpha(mask)
    return img


def _arrow_polygon(
    x0: float, y0: float, x1: float, y1: float, thickness: float, head: float
) -> list[tuple[float, float]]:
    """Horizontal arrow from (x0,y0) to (x1,y1), drawn left-to-right.

    Returns the polygon vertices for a thick horizontal arrow with a
    triangular head. Negative width (x1 < x0) flips direction.
    """
    direction = 1.0 if x1 >= x0 else -1.0
    length = abs(x1 - x0)
    head_w = min(head, length * 0.6)
    body_w = length - head_w
    shaft_top = y0 - thickness / 2
    shaft_bot = y0 + thickness / 2
    head_top = y0 - thickness * 0.95
    head_bot = y0 + thickness * 0.95
    tip = x0 + direction * length
    shaft_end = x0 + direction * body_w
    return [
        (x0, shaft_top),
        (shaft_end, shaft_top),
        (shaft_end, head_top),
        (tip, y0),
        (shaft_end, head_bot),
        (shaft_end, shaft_bot),
        (x0, shaft_bot),
    ]


def _compose_logo(size: int) -> Image.Image:
    """Two arrows pointing in opposite directions on a rounded dark panel.

    The arrows form an ``↔`` glyph filled with the brand gradient — the
    visual shorthand for "FoxPort migrates *both* ways: Chromium →
    Firefox and Firefox → Chromium". Designed to stay legible at 16 px:
    one wide arrow on top, one wide arrow on bottom, with generous
    inset so the rounded corners survive at small sizes.
    """
    panel = _rounded_panel(size, radius=size * 0.22)

    # Brand gradient, used as the arrow fill via an alpha-mask paste.
    grad = _gradient_horizontal(size)

    # Per-arrow mask: white where the arrow is filled, black elsewhere.
    arrow_mask = Image.new("L", (size, size), 0)
    drawer = ImageDraw.Draw(arrow_mask)

    inset = size * 0.18
    left = inset
    right = size - inset
    cy = size / 2
    arm_gap = size * 0.10   # vertical gap between the two arrows
    thickness = size * 0.13
    head = size * 0.26

    # Upper arrow points right (→). Lower arrow points left (←). Stacked.
    upper_y = cy - arm_gap
    lower_y = cy + arm_gap
    drawer.polygon(
        _arrow_polygon(left, upper_y, right, upper_y, thickness, head), fill=255
    )
    drawer.polygon(
        _arrow_polygon(right, lower_y, left, lower_y, thickness, head), fill=255
    )

    # Paste the gradient onto the panel using the arrow mask so the
    # arrows pick up the pink→purple→blue sweep while the dark panel
    # shows through everywhere else.
    panel.paste(grad, (0, 0), arrow_mask)
    return panel


ICO_FRAMES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    master = _compose_logo(512)

    # Re-render each ICO frame at native size so 16 px doesn't look like
    # a downsampled 256-px blob. Pillow accepts the multi-size frames
    # via `sizes=` on save when the base image is large enough; render
    # the smaller frames directly for crisp edges.
    frames = []
    for s in ICO_FRAMES:
        frames.append(_compose_logo(s))
    # Pillow's ICO encoder takes one master image + a list of (w,h)
    # tuples and rescales internally. To preserve our per-size renders,
    # save each frame to a temp PNG then re-open them; but the simpler
    # path Pillow officially supports is `save(..., format="ICO",
    # sizes=[...])` on the largest image. Use the per-size renders by
    # building an ICO via append_images.
    largest = frames[-1]
    smaller = frames[:-1]
    ico_path = OUT / "icon.ico"
    largest.save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in ICO_FRAMES],
        append_images=smaller,
    )

    (OUT / "icon-256.png").write_bytes(_png_bytes(_compose_logo(256)))
    (OUT / "icon-32.png").write_bytes(_png_bytes(_compose_logo(32)))
    (OUT / "icon-16.png").write_bytes(_png_bytes(_compose_logo(16)))

    print(f"Wrote {ico_path} (frames: {', '.join(str(s) for s in ICO_FRAMES)})")
    for name in ("icon-256.png", "icon-32.png", "icon-16.png"):
        print(f"Wrote {OUT / name}")
    return 0


def _png_bytes(img: Image.Image) -> bytes:
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
