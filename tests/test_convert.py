import shutil
import zipfile
from pathlib import Path

import pytest

from arxiv2pocketbook.arxiv import FullText, PaperMeta
from arxiv2pocketbook.convert import ConvertOptions, html_to_epub
from arxiv2pocketbook.pipeline import safe_filename

FIXTURE = Path(__file__).parent / "fixtures" / "sample.html"
META = PaperMeta(arxiv_id="9999.99999", title="A Sample Paper", authors=["Ada Lovelace"], abstract="We study x^2.", published="2024-01-02", primary_category="cs.LG")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")


def _fulltext():
    html = FIXTURE.read_text().replace("LOREM_FILLER", "lorem ipsum dolor sit amet " * 80)
    return FullText(source="arxiv-html", url="https://arxiv.org/html/9999.99999v1", content=html.encode())


def _build(tmp_path, **opts):
    out = tmp_path / "paper.epub"
    stats = html_to_epub(META, _fulltext(), None, out, ConvertOptions(**opts))
    z = zipfile.ZipFile(out)
    text = {n: z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith((".xhtml", ".opf", ".css"))}
    return stats, z.namelist(), text


@needs_node
def test_math_becomes_images(tmp_path):
    stats, names, text = _build(tmp_path)
    assert stats["math"] == 3 and stats["math_failed"] == 0
    body = "".join(v for k, v in text.items() if k.endswith(".xhtml"))
    assert "<math" not in body
    assert 'class="math inline"' in body and 'class="math display"' in body
    assert 'class="eqno">(1)<' in body
    assert sum(n.startswith("EPUB/images/") for n in names) >= 5  # 3 unique equations + svg figure + cover


def test_structure_and_cleanup(tmp_path):
    stats, names, text = _build(tmp_path, math_images=False)
    assert {"EPUB/front.xhtml", "EPUB/ch01.xhtml", "EPUB/ch02.xhtml", "EPUB/ch03.xhtml", "EPUB/cover.xhtml"} <= set(names)
    body = "".join(v for k, v in text.items() if k.endswith(".xhtml"))
    for junk in ("Report issue", "arXiv header", "<script", "mailto:", "ada@example.org", "thanks: "):
        assert junk not in body
    ch1 = text["EPUB/ch01.xhtml"]
    # cross-chapter references point at the right file; same-paper absolute links become local
    assert 'href="ch02.xhtml#S2.E1"' in ch1
    assert 'href="ch02.xhtml#S2"' in ch1
    # footnotes become EPUB3 popup notes
    assert 'epub:type="noteref"' in ch1 and 'epub:type="footnote"' in ch1 and "A footnote." in ch1
    assert "Work done while dreaming." in text["EPUB/front.xhtml"]
    # inline SVG figure rasterised, table no longer nested inside <p>/<span>
    assert "<svg" not in body and "figure-svg" in body
    assert not any("<p" in seg and "<table" in seg.split("</p>")[0] for seg in text["EPUB/ch02.xhtml"].split('<p class="ltx_p">')[1:])
    opf = text["EPUB/content.opf"]
    assert "A Sample Paper" in opf and "Ada Lovelace" in opf and "arxiv:9999.99999" in opf


def test_empty_html_is_rejected(tmp_path):
    ft = FullText(source="ar5iv", url="https://ar5iv.labs.arxiv.org/html/x", content=b'<article class="ltx_document"><p>tiny</p></article>')
    with pytest.raises(ValueError):
        html_to_epub(META, ft, None, tmp_path / "x.epub")


def test_safe_filename():
    assert safe_filename(META, "epub") == "Lovelace 2024 - A Sample Paper.epub"
    weird = PaperMeta(arxiv_id="hep-th/9711200", title='Title: with "quotes"/slashes?', authors=[], published="")
    assert safe_filename(weird, "pdf") == "arXiv - Title with quotesslashes.pdf"
