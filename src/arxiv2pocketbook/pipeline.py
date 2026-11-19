"""High-level: paper reference in, e-reader file out."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .arxiv import PDF_URL, FetchError, PaperMeta, download, fetch_fulltext, fetch_metadata, session
from .convert import ConvertOptions, html_to_epub
from .ids import parse_arxiv_id

log = logging.getLogger(__name__)


@dataclass
class Result:
    arxiv_id: str
    meta: PaperMeta
    path: Path
    source: str  # arxiv-html | ar5iv | pdf
    stats: dict = field(default_factory=dict)


def safe_filename(meta: PaperMeta, ext: str) -> str:
    first = meta.authors[0].split()[-1] if meta.authors else "arXiv"
    year = meta.published[:4]
    stem = f"{first} {year} - {meta.title}" if year else f"{first} - {meta.title}"
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^\w\s.,()-]", "", stem)
    stem = re.sub(r"\s+", " ", stem).strip()[:120].rstrip(" .-")
    return f"{stem or meta.arxiv_id.replace('/', '_')}.{ext}"


def convert_paper(
    ref: str,
    out_dir: Path,
    *,
    options: ConvertOptions | None = None,
    allow_pdf: bool = True,
    sess: requests.Session | None = None,
) -> Result:
    """Convert one arXiv / alphaXiv reference to an EPUB (or the PDF when no HTML exists)."""
    arxiv_id = parse_arxiv_id(ref)
    sess = sess or session()
    meta = fetch_metadata(arxiv_id, sess)
    log.info("%s: %s", arxiv_id, meta.title)
    fulltext = fetch_fulltext(arxiv_id, sess, allow_pdf=allow_pdf)
    out_dir.mkdir(parents=True, exist_ok=True)
    if fulltext.source == "pdf":
        log.warning("%s: no HTML version on arXiv or ar5iv, falling back to the PDF", arxiv_id)
        path = out_dir / safe_filename(meta, "pdf")
        path.write_bytes(fulltext.content)
        return Result(arxiv_id, meta, path, "pdf")
    path = out_dir / safe_filename(meta, "epub")
    try:
        stats = html_to_epub(meta, fulltext, sess, path, options)
    except Exception as exc:
        if not allow_pdf:
            raise
        log.warning("%s: EPUB conversion failed (%s), falling back to the PDF", arxiv_id, exc)
        path = out_dir / safe_filename(meta, "pdf")
        path.write_bytes(download(sess, PDF_URL.format(id=arxiv_id)))
        return Result(arxiv_id, meta, path, "pdf")
    log.info(
        "%s: wrote %s from %s (%d equations, %d figures, %d equations kept as TeX)",
        arxiv_id, path.name, fulltext.source, stats["math"], stats["figures"], stats["math_failed"],
    )
    return Result(arxiv_id, meta, path, fulltext.source, stats)


__all__ = ["Result", "convert_paper", "safe_filename", "FetchError"]
