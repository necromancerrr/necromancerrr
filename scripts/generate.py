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
import sys
import tomllib
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent

# Character ramp, sparse -> dense. Dense chars = bright pixels on a dark bg.
RAMP = " .`':,^-~=+*!?#%@"

# A monospace glyph is roughly half as tall as it is wide on screen.
CHAR_ASPECT = 0.5

# ---------------------------------------------------------------- palette
BG = "#0d1117"
CHROME = "#161b22"
BORDER = "#30363d"
TEXT = "#e6edf3"
DIM = "#8b949e"
GREEN = "#3fb950"
BLUE = "#79c0ff"
PURPLE = "#d2a8ff"


def photo_to_ascii(path: Path, columns: int) -> list[str]:
    """Convert a photo to ASCII lines, keying out a flat background."""
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

    # Stretch contrast over the subject only, so the full ramp gets used.
    # Histogram-equalize the subject so every step of the ramp gets used,
    # which keeps facial features from mushing into one midtone.
    subject = sorted(luma(px[x, y]) for y in range(rows) for x in range(columns) if not is_bg(px[x, y]))

    def rank(v):
        lo, hi = 0, len(subject)
        while lo < hi:
            mid = (lo + hi) // 2
            if subject[mid] < v:
                lo = mid + 1
            else:
                hi = mid
        return lo / max(len(subject) - 1, 1)

    lines = []
    for y in range(rows):
        line = ""
        for x in range(columns):
            p = px[x, y]
            if is_bg(p):
                line += " "
            else:
                line += RAMP[round(rank(luma(p)) * (len(RAMP) - 1))]
        lines.append(line)

    # Drop fully blank top/bottom rows.
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def build_svg(cfg: dict, ascii_lines: list[str]) -> str:
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
.a  {{ animation: rv .12s steps(1) both }}
.cur {{ animation: rv .2s both, bl 1.1s step-end 4.2s infinite }}
text {{ {'font-family:SFMono-Regular,Consolas,Liberation Mono,Menlo,monospace'} }}
</style>""")

    # gradient for the portrait
    out.append(
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#7ee787"/><stop offset="1" stop-color="#58a6ff"/>'
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
    svg = build_svg(cfg, ascii_lines)
    out = ROOT / "assets" / "header.svg"
    out.write_text(svg)
    print(f"wrote {out.relative_to(ROOT)} ({len(svg) / 1024:.0f} KB, {len(ascii_lines)} ASCII rows)")


if __name__ == "__main__":
    main()
