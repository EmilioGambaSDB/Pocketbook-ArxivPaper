"""Turn an arXiv / ar5iv LaTeXML HTML page into an e-reader friendly EPUB 3."""

from __future__ import annotations

import copy
import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import cairosvg
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from ebooklib import epub
from PIL import Image

from . import __version__
from .arxiv import FullText, PaperMeta, download
from .cover import make_cover
from .mathrender import MathRenderError, render_svgs, svg_to_png, to_grayscale_png

log = logging.getLogger(__name__)

STYLESHEET = (Path(__file__).parent / "epub.css").read_text(encoding="utf-8")

# Widest bitmap we keep for figures; PocketBook screens are 1072-1680 px wide.
MAX_FIGURE_WIDTH = 1400
# Below this much text we assume the HTML conversion failed and fall back to the PDF.
MIN_TEXT_CHARS = 1500

REMOVE_SELECTORS = [
    "script",
    "style",
    "noscript",
    "button",
    "input",
    "form",
    "nav",
    "header",
    "footer",
    "link",
    "meta",
    ".ltx_page_header",
    ".ltx_page_footer",
    ".ltx_page_navbar",
    ".ltx_pagination",
    ".ltx_role_newpage",
    ".ar5iv-footer",
    ".ar5iv-toggle-color-scheme",
    ".ltx_dates",
    ".ltx_role_email",
    ".package-alerts",
    ".section-nav",
    "#license-tr",
    "#watermark-tr",
]


@dataclass
class ConvertOptions:
    math_images: bool = True  # False keeps MathML (smaller, but PocketBook support is patchy)
    grayscale_figures: bool = True
    include_cover: bool = True


@dataclass
class _Chapter:
    title: str
    file_name: str
    nodes: list[Tag] = field(default_factory=list)


class Converter:
    def __init__(self, meta: PaperMeta, fulltext: FullText, sess: requests.Session, options: ConvertOptions | None = None):
        self.meta = meta
        self.fulltext = fulltext
        self.sess = sess
        self.opts = options or ConvertOptions()
        self.book = epub.EpubBook()
        self.images: dict[str, epub.EpubItem] = {}  # file name -> item
        self._image_by_url: dict[str, str] = {}
        self._math_cache: dict[tuple[str, bool], tuple[str, object]] = {}
        self.stats = {"math": 0, "math_failed": 0, "figures": 0, "figures_failed": 0}

    # ------------------------------------------------------------------ public

    def build(self) -> epub.EpubBook:
        soup = BeautifulSoup(self.fulltext.content, "lxml")
        base = self._base_url(soup)
        article = soup.find("article", class_="ltx_document") or soup.find(class_="ltx_document")
        if article is None:
            raise ValueError("Page does not look like a LaTeXML paper (no .ltx_document)")
        if len(article.get_text(" ", strip=True)) < MIN_TEXT_CHARS:
            raise ValueError("HTML version is (nearly) empty; the conversion on arXiv probably failed")
        self._clean(article)
        self._convert_svgs(article)
        self._convert_images(article, base)
        self._convert_math(article)
        self._flatten_equation_tables(article)
        self._fix_block_nesting(article)
        chapters = self._split(article)
        self._assemble(chapters)
        return self.book

    # ------------------------------------------------------------- utilities

    def _base_url(self, soup: BeautifulSoup) -> str:
        base = soup.find("base", href=True)
        return urljoin(self.fulltext.url, base["href"]) if base else self.fulltext.url

    def _add_image(self, data: bytes, ext: str, key: str) -> str:
        name = f"images/{hashlib.sha1(key.encode()).hexdigest()[:16]}.{ext}"
        if name not in self.images:
            media = "image/png" if ext == "png" else "image/jpeg"
            item = epub.EpubItem(uid="img_" + Path(name).stem, file_name=name, media_type=media, content=data)
            self.images[name] = item
        return name

    # ------------------------------------------------------------- cleaning

    def _clean(self, article: Tag) -> None:
        for sel in REMOVE_SELECTORS:
            for node in article.select(sel):
                node.decompose()
        # LaTeXML error markers for unknown macros are noise on paper
        for node in article.select(".ltx_ERROR"):
            node.unwrap()
        # Drop attributes that are only meaningful to arXiv's web viewer
        for node in article.find_all(True):
            for attr in list(node.attrs):
                if attr.startswith(("data-", "aria-", "on")) or attr in ("tabindex", "role", "style", "intent"):
                    if not (attr == "style" and node.name in ("td", "th", "col")):
                        del node.attrs[attr]
        # Links to anchors on the same paper's web page become local anchors
        for a in article.find_all("a"):
            href = a.get("href", "").strip()
            if not href or href.startswith(("mailto:", "javascript:")) or " " in href:
                a.unwrap()
                continue
            parsed = urlparse(href)
            if parsed.fragment and (not parsed.netloc or "arxiv.org" in parsed.netloc) and self.meta.arxiv_id.split("v")[0] in href:
                a["href"] = "#" + parsed.fragment

    # ------------------------------------------------------------- figures

    def _convert_svgs(self, article: Tag) -> None:
        """Inline SVG drawings (TikZ pictures etc.) become PNGs: older PocketBook firmware is weak on SVG."""
        for svg in article.find_all("svg"):
            if svg.find_parent("math"):
                continue
            markup = str(svg)
            if "xmlns=" not in markup[:200]:
                markup = markup.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
            try:
                png = cairosvg.svg2png(bytestring=markup.encode(), scale=3, background_color="white")
                name = self._add_image(to_grayscale_png(png, MAX_FIGURE_WIDTH), "png", markup)
                img = Tag(name="img", attrs={"src": name, "alt": "figure", "class": "figure-svg"})
                svg.replace_with(img)
                self.stats["figures"] += 1
            except Exception as exc:  # noqa: BLE001 - keep going, the drawing is just dropped
                log.warning("Could not rasterise inline SVG: %s", exc)
                svg.decompose()
                self.stats["figures_failed"] += 1

    def _convert_images(self, article: Tag, base: str) -> None:
        # LaTeXML embeds SVG figures as <object>/<embed>; treat them as plain images
        for obj in article.find_all(["object", "embed"]):
            src = obj.get("data") or obj.get("src")
            if not src:
                obj.decompose()
                continue
            obj.replace_with(Tag(name="img", attrs={"src": src, "alt": obj.get("alt", "figure"), "class": "ltx_graphics"}))
        for img in article.find_all("img"):
            src = img.get("src", "")
            if not src or src.startswith("images/"):
                continue
            url = urljoin(base, src)
            try:
                name = self._image_by_url.get(url) or self._fetch_image(url)
                self._image_by_url[url] = name
                img["src"] = name
                img.attrs.pop("srcset", None)
                img.attrs.pop("height", None)  # width is kept as a size hint; CSS caps it at the screen width
                if img.get("width") and not str(img["width"]).isdigit():
                    del img["width"]
                img["alt"] = img.get("alt") or "figure"
                self.stats["figures"] += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not fetch figure %s: %s", url, exc)
                img.replace_with(NavigableString(f"[figure unavailable: {url}]"))
                self.stats["figures_failed"] += 1

    def _fetch_image(self, url: str) -> str:
        data = download(self.sess, url)
        if url.lower().endswith(".svg") or data.lstrip()[:5] in (b"<?xml", b"<svg "):
            data = cairosvg.svg2png(bytestring=data, scale=2, background_color="white")
        img = Image.open(io.BytesIO(data))
        if self.opts.grayscale_figures:
            return self._add_image(to_grayscale_png(data, MAX_FIGURE_WIDTH), "png", url)
        img = img.convert("RGB")
        if img.width > MAX_FIGURE_WIDTH:
            img = img.resize((MAX_FIGURE_WIDTH, round(img.height * MAX_FIGURE_WIDTH / img.width)), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=88)
        return self._add_image(out.getvalue(), "jpg", url)

    # ------------------------------------------------------------- math

    def _convert_math(self, article: Tag) -> None:
        maths = article.find_all("math")
        if not maths:
            return
        if not self.opts.math_images:
            for m in maths:
                m["xmlns"] = "http://www.w3.org/1998/Math/MathML"
            return
        jobs: list[dict] = []
        keyed: list[tuple[Tag, tuple[str, bool]]] = []
        seen: set[tuple[str, bool]] = set()
        for m in maths:
            display = m.get("display") == "block"
            tex = m.get("alttext", "")
            mml = self._mathml_source(m)
            key = (mml or tex, display)
            keyed.append((m, key))
            if key not in seen:
                seen.add(key)
                jobs.append({"id": str(len(jobs)), "mml": mml, "tex": tex, "display": display, "_key": key})
        try:
            svgs = render_svgs([{k: v for k, v in j.items() if k != "_key"} for j in jobs])
        except MathRenderError as exc:
            log.warning("Math rendering unavailable (%s); keeping TeX source as text", exc)
            svgs = {}
        rendered: dict[tuple[str, bool], tuple[str, object] | None] = {}
        for job in jobs:
            svg = svgs.get(job["id"])
            if not svg:
                rendered[job["_key"]] = None
                continue
            try:
                r = svg_to_png(svg)
                name = self._add_image(r.png, "png", "math:" + svg)
                rendered[job["_key"]] = (name, r)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not rasterise equation: %s", exc)
                rendered[job["_key"]] = None
        for m, key in keyed:
            hit = rendered.get(key)
            display = key[1]
            tex = m.get("alttext", "")
            if hit is None:
                self.stats["math_failed"] += 1
                span = Tag(name="span", attrs={"class": "math-fallback"})
                span.string = tex or m.get_text(" ", strip=True)
                m.replace_with(span)
                continue
            name, r = hit
            self.stats["math"] += 1
            cls = "math display" if display else "math inline"
            if display:
                style = f"width:{r.width_em}em"
            else:
                style = f"height:{r.height_em}em;vertical-align:{r.valign_em}em"
            img = Tag(name="img", attrs={"src": name, "alt": tex[:500], "class": cls, "style": style})
            m.replace_with(img)

    @staticmethod
    def _mathml_source(m: Tag) -> str:
        clone = copy.copy(m)
        for ann in clone.find_all(["annotation", "annotation-xml"]):
            ann.decompose()
        for attr in ("id", "class", "alttext"):
            clone.attrs.pop(attr, None)
        clone.attrs["xmlns"] = "http://www.w3.org/1998/Math/MathML"
        return str(clone)

    def _flatten_equation_tables(self, article: Tag) -> None:
        """LaTeXML lays out display equations as tables; on small screens a centred block reads better."""
        for table in article.select("table.ltx_equation, table.ltx_equationgroup, table.ltx_eqn_table"):
            if table.find_parent("table", class_=re.compile("ltx_eqn")):
                continue
            block = Tag(name="div", attrs={"class": "equation"})
            if table.get("id"):
                block["id"] = table["id"]
            for row in table.find_all("tr"):
                line = Tag(name="div", attrs={"class": "eq-line"})
                if row.get("id"):
                    line["id"] = row["id"]
                eqno = None
                for cell in row.find_all("td", recursive=False):
                    classes = cell.get("class", [])
                    if "ltx_eqn_eqno" in classes:
                        if cell.get_text(strip=True):
                            eqno = cell.get_text(strip=True)
                        continue
                    for child in list(cell.contents):
                        line.append(child.extract())
                if eqno:
                    num = Tag(name="span", attrs={"class": "eqno"})
                    num.string = eqno
                    line.append(num)
                if line.contents:
                    block.append(line)
            table.replace_with(block)

    BLOCK_TAGS = ("table", "div", "figure", "section", "ul", "ol", "dl", "blockquote", "pre", "aside", "h1", "h2", "h3", "h4", "h5", "h6")

    def _fix_block_nesting(self, article: Tag) -> None:
        """LaTeXML happily nests tables inside <p>/<span>; XHTML readers may choke, so promote the parents."""
        for block in article.find_all(self.BLOCK_TAGS):
            parent = block.parent
            while parent is not None and parent is not article:
                if parent.name in ("p", "span", "em", "strong", "cite", "b", "i", "small", "label"):
                    parent.name = "div"
                parent = parent.parent

    # ------------------------------------------------------------- structure

    def _split(self, article: Tag) -> list[_Chapter]:
        chapters = [_Chapter(title="Title page", file_name="front.xhtml")]
        for child in list(article.children):
            if isinstance(child, NavigableString):
                continue
            is_section = child.name == "section" or "ltx_appendix" in child.get("class", []) or "ltx_bibliography" in child.get("class", [])
            if is_section:
                heading = child.find(re.compile("^h[1-6]$"))
                title = " ".join(heading.get_text(" ", strip=True).split()) if heading else "Section"
                chapters.append(_Chapter(title=title, file_name=f"ch{len(chapters):02d}.xhtml", nodes=[child]))
            else:
                chapters[-1].nodes.append(child)
        self._move_footnotes(chapters)
        self._fix_links(chapters)
        return chapters

    def _move_footnotes(self, chapters: list[_Chapter]) -> None:
        """Turn LaTeXML hover-footnotes into EPUB 3 popup notes collected at the end of each chapter."""
        counter = 0
        for ch in chapters:
            notes: list[Tag] = []
            for node in ch.nodes:
                for mark_only in node.select(".ltx_note.ltx_role_footnotemark"):
                    mark = mark_only.select_one(".ltx_note_mark")
                    sup = Tag(name="sup")
                    sup.string = mark.get_text(strip=True) if mark else "*"
                    mark_only.replace_with(sup)
                for note in node.select(".ltx_note.ltx_role_footnote, .ltx_note.ltx_role_thanks"):
                    content = note.select_one(".ltx_note_content")
                    mark = note.select_one(".ltx_note_mark")
                    if content is None:
                        continue
                    counter += 1
                    label = mark.get_text(strip=True) if mark else str(counter)
                    for inner_mark in content.select(".ltx_note_mark, .ltx_tag_note, .ltx_note_type"):
                        inner_mark.decompose()
                    nid = f"fn{counter}"
                    ref = Tag(name="a", attrs={"href": f"#{nid}", "id": f"{nid}-ref", "class": "noteref", "epub:type": "noteref"})
                    sup = Tag(name="sup")
                    sup.string = label
                    ref.append(sup)
                    aside = Tag(name="aside", attrs={"id": nid, "class": "footnote", "epub:type": "footnote"})
                    p = Tag(name="p")
                    back = Tag(name="a", attrs={"href": f"#{nid}-ref"})
                    back.string = label
                    p.append(back)
                    p.append(NavigableString(" "))
                    for c in list(content.contents):
                        p.append(c.extract())
                    aside.append(p)
                    notes.append(aside)
                    note.replace_with(ref)
            if notes:
                wrap = Tag(name="section", attrs={"class": "footnotes", "epub:type": "footnotes"})
                wrap.append(Tag(name="hr"))
                for n in notes:
                    wrap.append(n)
                ch.nodes.append(wrap)

    def _fix_links(self, chapters: list[_Chapter]) -> None:
        where: dict[str, str] = {}
        for ch in chapters:
            for node in ch.nodes:
                if node.get("id"):
                    where[node["id"]] = ch.file_name
                for el in node.find_all(id=True):
                    where.setdefault(el["id"], ch.file_name)
        for ch in chapters:
            for node in ch.nodes:
                for a in node.find_all("a", href=True):
                    if a["href"].startswith("#"):
                        frag = a["href"][1:]
                        target = where.get(frag)
                        if target is None:
                            a.unwrap()
                        elif target != ch.file_name:
                            a["href"] = f"{Path(target).name}#{frag}"

    # ------------------------------------------------------------- assembly

    def _assemble(self, chapters: list[_Chapter]) -> None:
        book, meta = self.book, self.meta
        book.set_identifier(f"arxiv:{meta.arxiv_id}")
        book.set_title(meta.title)
        book.set_language("en")
        for author in meta.authors:
            book.add_author(author)
        if meta.abstract:
            book.add_metadata("DC", "description", meta.abstract)
        if meta.published:
            book.add_metadata("DC", "date", meta.published)
        book.add_metadata("DC", "source", meta.abs_url)
        book.add_metadata("DC", "publisher", "arXiv")
        if meta.primary_category:
            book.add_metadata("DC", "subject", meta.primary_category)
        book.add_metadata(None, "meta", "", {"name": "generator", "content": f"arxiv2pocketbook {__version__}"})

        css = epub.EpubItem(uid="style", file_name="style/paper.css", media_type="text/css", content=STYLESHEET.encode())
        book.add_item(css)

        if self.opts.include_cover:
            book.set_cover("images/cover.png", make_cover(meta), create_page=True)
            book.get_item_with_id("cover").is_linear = True  # epubcheck: non-linear pages must be linked

        spine: list = ["cover"] if self.opts.include_cover else []
        toc: list = []
        for ch in chapters:
            if not ch.nodes:
                continue
            body = "".join(str(n) for n in ch.nodes)
            if ch.file_name == "front.xhtml":
                body = self._front_header() + body
            page = epub.EpubHtml(title=ch.title, file_name=ch.file_name, lang="en")
            page.content = body
            if "<math" in body:
                page.properties.append("mathml")
            page.add_item(css)
            book.add_item(page)
            spine.append(page)
            toc.append(page)
        for item in self.images.values():
            book.add_item(item)
        book.toc = toc
        book.spine = ["nav", *spine] if not self.opts.include_cover else [spine[0], "nav", *spine[1:]]
        book.add_item(epub.EpubNcx())
        nav = epub.EpubNav()
        nav.add_item(css)
        book.add_item(nav)

    def _front_header(self) -> str:
        m = self.meta
        src = {"arxiv-html": "arXiv HTML", "ar5iv": "ar5iv"}.get(self.fulltext.source, self.fulltext.source)
        return (
            f'<p class="paper-source">arXiv:{_esc(m.arxiv_id)}'
            + (f" [{_esc(m.primary_category)}]" if m.primary_category else "")
            + (f" · {_esc(m.published)}" if m.published else "")
            + f' · converted from {src}</p>'
        )


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def html_to_epub(meta: PaperMeta, fulltext: FullText, sess: requests.Session, out_path: Path, options: ConvertOptions | None = None) -> dict:
    conv = Converter(meta, fulltext, sess, options)
    book = conv.build()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book, {"epub3_pages": False})
    return conv.stats
