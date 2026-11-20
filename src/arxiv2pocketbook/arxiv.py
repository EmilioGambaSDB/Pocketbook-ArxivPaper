"""Fetch paper metadata and full text from arXiv."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

from . import __version__
from .ids import strip_version

USER_AGENT = f"arxiv2pocketbook/{__version__} (+https://github.com/EmilioGambaSDB/Pocketbook-ArxivPaper)"
API_URL = "https://export.arxiv.org/api/query"
HTML_SOURCES = [
    ("arxiv-html", "https://arxiv.org/html/{id}"),
    ("ar5iv", "https://ar5iv.labs.arxiv.org/html/{id}"),
]
PDF_URL = "https://arxiv.org/pdf/{id}"

_ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class FetchError(RuntimeError):
    pass


@dataclass
class PaperMeta:
    arxiv_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    published: str = ""  # ISO date (YYYY-MM-DD)
    primary_category: str = ""

    @property
    def abs_url(self) -> str:
        return f"https://arxiv.org/abs/{self.arxiv_id}"


@dataclass
class FullText:
    source: str  # "arxiv-html", "ar5iv" or "pdf"
    url: str  # final URL after redirects (used to resolve relative links)
    content: bytes


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _get(sess: requests.Session, url: str, *, retries: int = 3, **kw) -> requests.Response:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = sess.get(url, timeout=60, **kw)
            if resp.status_code in (429, 502, 503, 504):
                raise FetchError(f"HTTP {resp.status_code} for {url}")
            return resp
        except (requests.RequestException, FetchError) as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise FetchError(f"Giving up on {url}: {last}")


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def fetch_metadata(arxiv_id: str, sess: requests.Session | None = None) -> PaperMeta:
    sess = sess or session()
    resp = _get(sess, API_URL, params={"id_list": arxiv_id, "max_results": 1})
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    entry = root.find("a:entry", _ATOM)
    if entry is None or entry.find("a:title", _ATOM) is None:
        raise FetchError(f"arXiv has no paper with ID {arxiv_id}")
    title = _clean(entry.findtext("a:title", namespaces=_ATOM))
    if title.lower() == "error":
        raise FetchError(f"arXiv API error for {arxiv_id}: {_clean(entry.findtext('a:summary', namespaces=_ATOM))}")
    authors = [_clean(a.findtext("a:name", namespaces=_ATOM)) for a in entry.findall("a:author", _ATOM)]
    primary = entry.find("arxiv:primary_category", _ATOM)
    return PaperMeta(
        arxiv_id=arxiv_id,
        title=title,
        authors=[a for a in authors if a],
        abstract=_clean(entry.findtext("a:summary", namespaces=_ATOM)),
        published=(entry.findtext("a:published", namespaces=_ATOM) or "")[:10],
        primary_category=primary.get("term", "") if primary is not None else "",
    )


def _looks_like_paper(resp: requests.Response) -> bool:
    return (
        resp.status_code == 200
        and "html" in resp.headers.get("Content-Type", "")
        and b"ltx_document" in resp.content
        # LaTeXML sometimes gives up; ar5iv then serves an (almost) empty page
        and b"Conversion to HTML had a Fatal error" not in resp.content
    )


def fetch_fulltext(arxiv_id: str, sess: requests.Session | None = None, *, allow_pdf: bool = True) -> FullText:
    """Return the best available full text: arXiv HTML, then ar5iv, then the PDF."""
    sess = sess or session()
    for source, template in HTML_SOURCES:
        # ar5iv only knows unversioned IDs
        ident = arxiv_id if source == "arxiv-html" else strip_version(arxiv_id)
        try:
            resp = _get(sess, template.format(id=ident))
        except FetchError:
            continue
        if _looks_like_paper(resp):
            return FullText(source=source, url=resp.url, content=resp.content)
    if not allow_pdf:
        raise FetchError(f"No HTML version found for {arxiv_id}")
    resp = _get(sess, PDF_URL.format(id=arxiv_id))
    if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
        raise FetchError(f"Could not download PDF for {arxiv_id} (HTTP {resp.status_code})")
    return FullText(source="pdf", url=resp.url, content=resp.content)


def download(sess: requests.Session, url: str) -> bytes:
    resp = _get(sess, url)
    resp.raise_for_status()
    return resp.content
