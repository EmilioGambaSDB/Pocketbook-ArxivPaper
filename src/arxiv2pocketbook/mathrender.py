"""Render equations to grayscale PNG images (via MathJax + cairosvg)."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cairosvg
from PIL import Image

MATHJAX_DIR = Path(__file__).parent / "mathjax"

# Pixels per MathJax "ex". An e-reader body font of ~12pt at 300 dpi has an x-height of ~22px,
# so 28px/ex keeps formulas crisp when the reader scales them.
PX_PER_EX = 28
# CSS em per ex used when sizing the <img> in the book, so math follows the reader's font size.
EM_PER_EX = 0.48


class MathRenderError(RuntimeError):
    pass


@dataclass
class RenderedMath:
    png: bytes
    width_em: float
    height_em: float
    valign_em: float  # CSS vertical-align (negative = below baseline)


def ensure_mathjax() -> None:
    """Install the MathJax node package next to the helper script on first use."""
    if shutil.which("node") is None:
        raise MathRenderError("Node.js is required to render equations (https://nodejs.org)")
    if not (MATHJAX_DIR / "node_modules" / "mathjax-full").exists():
        npm = shutil.which("npm")
        if npm is None:
            raise MathRenderError("npm is required to install MathJax")
        subprocess.run([npm, "install", "--no-audit", "--no-fund", "--silent"], cwd=MATHJAX_DIR, check=True)


def render_svgs(items: list[dict]) -> dict[str, str | None]:
    """items: [{id, mml?, tex?, display}] -> {id: svg or None}"""
    if not items:
        return {}
    ensure_mathjax()
    proc = subprocess.run(
        ["node", str(MATHJAX_DIR / "tex2svg.js")],
        input=json.dumps(items),
        capture_output=True,
        text=True,
        cwd=MATHJAX_DIR,
    )
    if proc.returncode != 0:
        raise MathRenderError(f"MathJax failed: {proc.stderr.strip()[:500]}")
    return json.loads(proc.stdout)


_EX = re.compile(r'(width|height)="([\d.]+)ex"')
_VALIGN = re.compile(r"vertical-align:\s*(-?[\d.]+)ex")


def svg_to_png(svg: str) -> RenderedMath:
    sizes = {k: float(v) for k, v in _EX.findall(svg)}
    if "width" not in sizes or "height" not in sizes:
        raise MathRenderError("Unexpected SVG from MathJax (no ex size)")
    valign_m = _VALIGN.search(svg)
    valign = float(valign_m.group(1)) if valign_m else 0.0
    w_px = max(1, round(sizes["width"] * PX_PER_EX))
    h_px = max(1, round(sizes["height"] * PX_PER_EX))
    svg = _EX.sub(lambda m: f'{m.group(1)}="{w_px if m.group(1) == "width" else h_px}"', svg, count=2)
    svg = svg.replace("currentColor", "#000000")
    png = cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=w_px, output_height=h_px, background_color="white")
    return RenderedMath(
        png=to_grayscale_png(png),
        width_em=round(sizes["width"] * EM_PER_EX, 3),
        height_em=round(sizes["height"] * EM_PER_EX, 3),
        valign_em=round(valign * EM_PER_EX, 3),
    )


def to_grayscale_png(data: bytes, max_width: int | None = None) -> bytes:
    img = Image.open(io.BytesIO(data))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        img = bg
    img = img.convert("L")
    if max_width and img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
