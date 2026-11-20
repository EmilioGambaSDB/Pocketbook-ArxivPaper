"""Generate a simple, high-contrast cover so papers are recognisable in the PocketBook library."""

from __future__ import annotations

import io
import textwrap
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .arxiv import PaperMeta

W, H = 1072, 1448  # PocketBook 6" screen
_FONT_CANDIDATES = {
    "serif-bold": ["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf", "FreeSerifBold.ttf"],
    "serif": ["DejaVuSerif.ttf", "LiberationSerif-Regular.ttf", "FreeSerif.ttf"],
    "sans": ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "FreeSans.ttf"],
}


@lru_cache(maxsize=None)
def _font(kind: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in _FONT_CANDIDATES[kind]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    avg = max(1, draw.textlength("abcdefghijklmnopqrstuvwxyz", font=font) / 26)
    width = max(10, int(max_width / avg))
    lines = textwrap.wrap(text, width=width)
    while lines and any(draw.textlength(l, font=font) > max_width for l in lines) and width > 10:
        width -= 2
        lines = textwrap.wrap(text, width=width)
    return lines


def make_cover(meta: PaperMeta) -> bytes:
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    margin = 80
    d.rectangle([0, 0, W, 150], fill=0)
    d.text((margin, 50), f"arXiv:{meta.arxiv_id}", font=_font("sans", 48), fill=255)

    y = 240
    title_size = 76 if len(meta.title) < 80 else 62 if len(meta.title) < 140 else 50
    tfont = _font("serif-bold", title_size)
    for line in _wrap(d, meta.title, tfont, W - 2 * margin)[:8]:
        d.text((margin, y), line, font=tfont, fill=0)
        y += int(title_size * 1.25)

    y += 50
    d.line([margin, y, W - margin, y], fill=0, width=4)
    y += 50
    afont = _font("serif", 40)
    authors = meta.authors if len(meta.authors) <= 6 else meta.authors[:5] + [f"and {len(meta.authors) - 5} more"]
    for line in _wrap(d, ", ".join(authors), afont, W - 2 * margin)[:6]:
        d.text((margin, y), line, font=afont, fill=60)
        y += 54

    footer = " · ".join(x for x in (meta.primary_category, meta.published) if x)
    if footer:
        d.text((margin, H - 120), footer, font=_font("sans", 40), fill=60)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
