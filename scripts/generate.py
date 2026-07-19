#!/usr/bin/env python3
"""Regenerate assets/header.svg from profile.toml + the photo.

    python3 scripts/generate.py

The output is a self-contained animated SVG (CSS animations only, no
JavaScript) that renders on GitHub. If a viewer doesn't run animations,
every element's resting state is fully visible, so it degrades to a
clean static image.

Requires: Pillow  (pip install pillow)
"""

import html
import math
import sys
import tomllib
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent

# Fill ramp, sparse -> dense. Dense chars = bright pixels on a dark bg.
# Every glyph is clearly visible at small sizes, so the subject never
# dissolves into blank-looking rows.
FILL = "::,~=+*!#%@"

# Directional glyphs for detected edges, indexed by edge orientation.
EDGE = "|/-\\"

# A monospace glyph is roughly half as tall as it is wide on screen.
CHAR_ASPECT = 0.5

# --------------------------------------------------------------- palettes
# GitHub-native colors; the README serves the matching variant through a
# <picture> tag keyed on prefers-color-scheme.
PALETTES = {
    "dark": dict(
        bg="#0d1117", chrome="#161b22", border="#30363d",
        text="#e6edf3", dim="#8b949e",
        green="#3fb950", blue="#79c0ff", purple="#d2a8ff",
        grad_a="#7ee787", grad_b="#58a6ff",
    ),
    "light": dict(
        bg="#ffffff", chrome="#f6f8fa", border="#d0d7de",
        text="#1f2328", dim="#6e7781",
        green="#1a7f37", blue="#0550ae", purple="#8250df",
        grad_a="#1a7f37", grad_b="#0969da",
    ),
}


def photo_to_ascii(path: Path, columns: int) -> list[str]:
    """Convert a photo to ASCII line art.

    Flat regions get density glyphs from FILL (tone-quantized); detected
    edges get directional glyphs from EDGE, which keeps outlines — where
    a portrait's definition actually lives — crisp. Subject pixels never
    map to a near-invisible glyph, so the silhouette stays continuous.
    """
    img = Image.open(path).convert("RGB")
    img = img.filter(ImageFilter.UnsharpMask(radius=3, percent=140))
    rows = max(1, round(columns * img.height / img.width * CHAR_ASPECT))
    img = img.resize((columns, rows), Image.LANCZOS)
    px = img.load()

    # Estimate the background color from the four corners.
    corners = [px[0, 0], px[columns - 1, 0], px[0, rows - 1], px[columns - 1, rows - 1]]
    bg = tuple(sum(c[i] for c in corners) / 4 for i in range(3))

    def is_bg(p):
        return sum((p[i] - bg[i]) ** 2 for i in range(3)) ** 0.5 < 42

    def luma(p):
        return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]

    mask = [[not is_bg(px[x, y]) for x in range(columns)] for y in range(rows)]
    # Luma field with background forced to 0, so the silhouette itself
    # registers as a strong edge in the Sobel pass below.
    F = [[luma(px[x, y]) if mask[y][x] else 0.0 for x in range(columns)] for y in range(rows)]

    # Detect edges on a blurred copy: structural lines (silhouette, brows,
    # eyes, nose, mouth) survive the blur; fine hair-curl texture doesn't,
    # so it renders as fill texture instead of scratchy line noise.
    blur = Image.new("L", (columns, rows))
    blur.putdata([round(v) for row in F for v in row])
    blur = blur.filter(ImageFilter.GaussianBlur(1.1))
    bp = blur.load()
    S = [[bp[x, y] for x in range(columns)] for y in range(rows)]

    # Percentile-clipped normalization of subject tones (full equalization
    # posterizes flat cartoon shading into visible bands — avoid it).
    tones = sorted(F[y][x] for y in range(rows) for x in range(columns) if mask[y][x])
    lo = tones[int(len(tones) * 0.03)]
    hi = tones[min(int(len(tones) * 0.97), len(tones) - 1)]
    span = max(hi - lo, 1)

    def sobel(y, x):
        def f(yy, xx):
            return S[min(max(yy, 0), rows - 1)][min(max(xx, 0), columns - 1)]

        gx = (f(y - 1, x + 1) + 2 * f(y, x + 1) + f(y + 1, x + 1)
              - f(y - 1, x - 1) - 2 * f(y, x - 1) - f(y + 1, x - 1))
        # A char cell is ~2x taller than wide, so a vertical step spans
        # twice the image distance; damp gy to compensate.
        gy = (f(y + 1, x - 1) + 2 * f(y + 1, x) + f(y + 1, x + 1)
              - f(y - 1, x - 1) - 2 * f(y - 1, x) - f(y - 1, x + 1)) * 0.5
        return gx, gy

    edge_th = 150  # Sobel magnitude above this renders as a line glyph

    lines = []
    for y in range(rows):
        line = ""
        for x in range(columns):
            if not mask[y][x]:
                line += " "
                continue
            gx, gy = sobel(y, x)
            if (gx * gx + gy * gy) ** 0.5 > edge_th:
                # The edge line runs perpendicular to the gradient.
                phi = (math.atan2(gy, gx) + math.pi) % math.pi
                line += EDGE[round(phi / (math.pi / 4)) % 4]
            else:
                t = min(max((F[y][x] - lo) / span, 0.0), 1.0) ** 1.35
                line += FILL[round(t * (len(FILL) - 1))]
        lines.append(line)

    # Drop fully blank top/bottom rows.
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def build_svg(cfg: dict, ascii_lines: list[str], pal: dict) -> str:
    BG, CHROME, BORDER = pal["bg"], pal["chrome"], pal["border"]
    TEXT, DIM = pal["text"], pal["dim"]
    GREEN, BLUE, PURPLE = pal["green"], pal["blue"], pal["purple"]
    term = cfg["terminal"]
    columns = cfg["photo"]["columns"]

    # ------------------------------------------------------------ geometry
    ascii_w = 330                      # locked width of the ASCII block
    cell_w = ascii_w / columns         # one character cell
    ascii_fs = cell_w * 1.66           # ASCII font size
    ascii_lh = cell_w / CHAR_ASPECT    # ASCII line height (keeps aspect true)
    pane_fs = 12.5
    pane_lh = 20
    pad = 30
    bar_h = 38
    ascii_x = pad + 6
    pane_x = ascii_x + ascii_w + 44
    width = 920

    # Right-hand pane rows: (kind, label, value)
    pane: list[tuple] = [("prompt", None, None), ("gap", None, None)]
    for i, group in enumerate(cfg.get("panel", [])):
        if i:
            pane.append(("gap", None, None))
        for label, value in group["rows"]:
            pane.append(("row", label, value))
    pane += [("gap", None, None), ("cursor", None, None)]

    ascii_h = len(ascii_lines) * ascii_lh
    pane_h = len(pane) * pane_lh
    body_h = max(ascii_h, pane_h) + 34
    height = round(bar_h + body_h + pad * 0.6)

    # Vertically center each column in the body.
    body_top = bar_h + 17
    ascii_y = body_top + (body_h - 34 - ascii_h) / 2 + ascii_fs
    pane_y = body_top + (body_h - 34 - pane_h) / 2 + pane_fs

    mono = "font-family=\"'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace\""

    out = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Terminal-style profile card">'
    )

    # ------------------------------------------------------------- styles
    # Every animated element rests at opacity 1 / un-clipped, so the SVG is
    # fully visible wherever CSS animations don't run (static fallback).
    out.append(f"""<style>
@keyframes rv {{ from {{ opacity: 0 }} }}
@keyframes ty {{ from {{ clip-path: inset(0 100% 0 0) }} to {{ clip-path: inset(0 0 0 0) }} }}
@keyframes bl {{ 0%, 45% {{ opacity: 1 }} 50%, 95% {{ opacity: 0 }} }}
.rv {{ animation: rv .45s ease-out both }}
.ty {{ animation: ty .9s steps(24) both; animation-delay: .3s }}
.a  {{ animation: rv .18s ease-out both }}
.cur {{ animation: rv .2s both, bl 1.1s step-end 4.2s infinite }}
text {{ {'font-family:SFMono-Regular,Consolas,Liberation Mono,Menlo,monospace'} }}
</style>""")

    # gradient for the portrait
    out.append(
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{pal["grad_a"]}"/><stop offset="1" stop-color="{pal["grad_b"]}"/>'
        f'</linearGradient></defs>'
    )

    # ------------------------------------------------------------- chrome
    out.append(f'<rect x="1" y="1" width="{width-2}" height="{height-2}" rx="12" fill="{BG}" stroke="{BORDER}"/>')
    out.append(f'<path d="M1 {bar_h} h{width-2}" stroke="{BORDER}"/>')
    out.append(f'<path d="M13 1 h{width-26} a12 12 0 0 1 12 12 v{bar_h-13} h-{width-2} v-{bar_h-13} a12 12 0 0 1 12-12 Z" fill="{CHROME}"/>')
    for cx, c in ((26, "#ff5f57"), (46, "#febc2e"), (66, "#28c840")):
        out.append(f'<circle cx="{cx}" cy="{bar_h/2}" r="6" fill="{c}"/>')
    out.append(
        f'<text x="{width/2}" y="{bar_h/2 + 4}" text-anchor="middle" font-size="12" '
        f'fill="{DIM}">{esc(term["title"])}</text>'
    )

    # ------------------------------------------------------------ portrait
    for i, line in enumerate(ascii_lines):
        y = ascii_y + i * ascii_lh
        delay = 0.5 + i * 2.4 / max(len(ascii_lines), 1)
        out.append(
            f'<text x="{ascii_x}" y="{y:.1f}" font-size="{ascii_fs}" xml:space="preserve" '
            f'textLength="{ascii_w}" lengthAdjust="spacingAndGlyphs" fill="url(#g)" '
            f'class="a" style="animation-delay:{delay:.2f}s">{esc(line.ljust(columns))}</text>'
        )

    # --------------------------------------------------------------- pane
    label_w = 78  # px reserved for labels
    y = pane_y
    n = 0
    for kind, label, value in pane:
        delay = 0.4 + n * 0.14
        if kind == "prompt":
            out.append(
                f'<text x="{pane_x}" y="{y:.1f}" font-size="{pane_fs}" class="rv" style="animation-delay:{delay:.2f}s">'
                f'<tspan fill="{GREEN}" font-weight="bold">{esc(term["prompt_user"])}@{esc(term["prompt_host"])}</tspan>'
                f'<tspan fill="{DIM}">:</tspan><tspan fill="{PURPLE}">~</tspan>'
                f'<tspan fill="{DIM}">$ </tspan></text>'
            )
            cmd_x = pane_x + (len(term["prompt_user"]) + len(term["prompt_host"]) + 4) * pane_fs * 0.62
            out.append(
                f'<text x="{cmd_x:.0f}" y="{y:.1f}" font-size="{pane_fs}" fill="{TEXT}" '
                f'class="ty">{esc(term["command"])}</text>'
            )
            n += 1
        elif kind == "row":
            out.append(
                f'<text x="{pane_x}" y="{y:.1f}" font-size="{pane_fs}" class="rv" style="animation-delay:{delay:.2f}s">'
                f'<tspan fill="{BLUE}" font-weight="bold">{esc(label)}</tspan>'
                f'<tspan x="{pane_x + label_w}" fill="{DIM}">·· </tspan>'
                f'<tspan fill="{TEXT}">{esc(value)}</tspan></text>'
            )
            n += 1
        elif kind == "cursor":
            out.append(
                f'<text x="{pane_x}" y="{y:.1f}" font-size="{pane_fs}" class="rv" style="animation-delay:{delay:.2f}s">'
                f'<tspan fill="{GREEN}" font-weight="bold">{esc(term["prompt_user"])}@{esc(term["prompt_host"])}</tspan>'
                f'<tspan fill="{DIM}">:</tspan><tspan fill="{PURPLE}">~</tspan><tspan fill="{DIM}">$</tspan></text>'
            )
            cur_x = pane_x + (len(term["prompt_user"]) + len(term["prompt_host"]) + 3) * pane_fs * 0.62 + 6
            out.append(
                f'<rect x="{cur_x:.0f}" y="{y - pane_fs + 2:.1f}" width="{pane_fs * 0.62:.1f}" '
                f'height="{pane_fs + 2}" fill="{TEXT}" class="cur" style="animation-delay:{delay:.2f}s,{delay:.2f}s"/>'
            )
        y += pane_lh

    out.append("</svg>")
    return "\n".join(out)


def main() -> None:
    cfg = tomllib.loads((ROOT / "profile.toml").read_text())
    photo = ROOT / cfg["photo"]["path"]
    if not photo.exists():
        sys.exit(f"photo not found: {photo}")
    ascii_lines = photo_to_ascii(photo, cfg["photo"]["columns"])
    for name, pal in PALETTES.items():
        svg = build_svg(cfg, ascii_lines, pal)
        suffix = "" if name == "dark" else f"-{name}"
        out = ROOT / "assets" / f"header{suffix}.svg"
        out.write_text(svg)
        print(f"wrote {out.relative_to(ROOT)} ({len(svg) / 1024:.0f} KB, {len(ascii_lines)} ASCII rows)")


if __name__ == "__main__":
    main()
