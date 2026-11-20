"""Normalise arXiv / alphaXiv links and identifiers to a bare arXiv ID."""

from __future__ import annotations

import re

# New-style IDs (0704.0001 onwards): YYMM.NNNN or YYMM.NNNNN, optional version.
_NEW = r"\d{4}\.\d{4,5}(?:v\d+)?"
# Old-style IDs: archive(.subject)/YYMMNNN, optional version.
_OLD = r"[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?"
_ID = rf"(?:{_NEW}|{_OLD})"

_PATTERNS = [
    # arxiv.org/{abs,pdf,html,format,src}/ID, export.arxiv.org, ar5iv(.labs.arxiv.org)
    re.compile(rf"(?:arxiv\.org|ar5iv(?:\.labs\.arxiv)?\.org)/(?:abs|pdf|html|format|src)/(?P<id>{_ID})", re.I),
    # alphaxiv.org/abs/ID, /overview/ID, /pdf/ID ...
    re.compile(rf"alphaxiv\.org/(?:[a-z]+/)*(?P<id>{_ID})", re.I),
    # DOI form: 10.48550/arXiv.ID
    re.compile(rf"10\.48550/arxiv\.(?P<id>{_ID})", re.I),
    # "arXiv:ID" as found in citations and Zotero "Extra" fields
    re.compile(rf"arxiv:\s*(?P<id>{_ID})", re.I),
    # bare ID
    re.compile(rf"^\s*(?P<id>{_ID})\s*$"),
]


class InvalidArxivId(ValueError):
    pass


def parse_arxiv_id(text: str) -> str:
    """Return the arXiv ID (with version if one was given) found in ``text``.

    Accepts bare IDs, arXiv/ar5iv/alphaXiv URLs, arXiv DOIs and ``arXiv:`` prefixes.
    Raises :class:`InvalidArxivId` if no ID is found.
    """
    candidate = text.strip()
    for pattern in _PATTERNS:
        match = pattern.search(candidate)
        if match:
            ident = match.group("id")
            return ident.removesuffix(".pdf")
    raise InvalidArxivId(f"Could not find an arXiv ID in {text!r}")


def find_arxiv_id(text: str | None) -> str | None:
    """Like :func:`parse_arxiv_id` but returns ``None`` instead of raising."""
    if not text:
        return None
    try:
        return parse_arxiv_id(text)
    except InvalidArxivId:
        return None


def strip_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)
