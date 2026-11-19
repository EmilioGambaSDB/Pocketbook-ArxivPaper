"""Use a Zotero tag (or collection) as an inbox for papers to send to the PocketBook.

Flow: every item carrying the inbox tag (default ``to-pocketbook``) that has an arXiv ID is
converted and sent; afterwards the inbox tag is replaced by ``sent-to-pocketbook`` (or
``pocketbook-failed`` when conversion failed) so the next run skips it.
Uses the Zotero Web API v3 with an API key that has read/write access to the library.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from .arxiv import USER_AGENT
from .config import env, require
from .ids import find_arxiv_id

log = logging.getLogger(__name__)
API = "https://api.zotero.org"


@dataclass
class ZoteroConfig:
    api_key: str
    library_type: str  # "users" or "groups"
    library_id: str
    inbox_tag: str = "to-pocketbook"
    done_tag: str = "sent-to-pocketbook"
    failed_tag: str = "pocketbook-failed"
    collection: str | None = None  # optional collection key; then the inbox tag is not needed

    @classmethod
    def from_env(cls) -> "ZoteroConfig":
        group = env("ZOTERO_GROUP_ID")
        return cls(
            api_key=require("ZOTERO_API_KEY"),
            library_type="groups" if group else "users",
            library_id=group or require("ZOTERO_USER_ID"),
            inbox_tag=env("ZOTERO_INBOX_TAG", "to-pocketbook"),
            done_tag=env("ZOTERO_DONE_TAG", "sent-to-pocketbook"),
            failed_tag=env("ZOTERO_FAILED_TAG", "pocketbook-failed"),
            collection=env("ZOTERO_COLLECTION"),
        )


@dataclass
class InboxItem:
    key: str
    version: int
    title: str
    arxiv_id: str | None
    tags: list[dict]


def arxiv_id_from_item(data: dict) -> str | None:
    """Find an arXiv ID in the fields the Zotero connector fills for arXiv / alphaXiv saves."""
    for field in ("archiveID", "url", "DOI", "extra", "publicationTitle", "repository", "number", "attachmentURL"):
        found = find_arxiv_id(str(data.get(field) or ""))
        if found:
            return found
    return None


class ZoteroInbox:
    def __init__(self, cfg: ZoteroConfig, sess: requests.Session | None = None):
        self.cfg = cfg
        self.sess = sess or requests.Session()
        self.sess.headers.update({"Zotero-API-Key": cfg.api_key, "Zotero-API-Version": "3", "User-Agent": USER_AGENT})
        self.base = f"{API}/{cfg.library_type}/{cfg.library_id}"

    def pending(self) -> list[InboxItem]:
        cfg = self.cfg
        path = f"/collections/{cfg.collection}/items/top" if cfg.collection else "/items/top"
        params: dict = {"format": "json", "limit": 100}
        if not cfg.collection:
            params["tag"] = cfg.inbox_tag
        items: list[InboxItem] = []
        start = 0
        while True:
            resp = self.sess.get(self.base + path, params={**params, "start": start}, timeout=60)
            resp.raise_for_status()
            batch = resp.json()
            for raw in batch:
                data = raw["data"]
                tag_names = {t["tag"] for t in data.get("tags", [])}
                if cfg.done_tag in tag_names or cfg.failed_tag in tag_names:
                    continue
                items.append(
                    InboxItem(
                        key=raw["key"],
                        version=raw["version"],
                        title=data.get("title", ""),
                        arxiv_id=arxiv_id_from_item(data),
                        tags=data.get("tags", []),
                    )
                )
            total = int(resp.headers.get("Total-Results", len(batch)))
            start += len(batch)
            if not batch or start >= total:
                return items

    def mark(self, item: InboxItem, ok: bool) -> None:
        new_tag = self.cfg.done_tag if ok else self.cfg.failed_tag
        tags = [t for t in item.tags if t["tag"] != self.cfg.inbox_tag]
        tags.append({"tag": new_tag})
        resp = self.sess.patch(
            f"{self.base}/items/{item.key}",
            json={"tags": tags},
            headers={"If-Unmodified-Since-Version": str(item.version)},
            timeout=60,
        )
        if resp.status_code == 412:  # item changed meanwhile: refetch version and retry once
            fresh = self.sess.get(f"{self.base}/items/{item.key}", timeout=60)
            fresh.raise_for_status()
            item.version = fresh.json()["version"]
            item.tags = fresh.json()["data"].get("tags", [])
            return self.mark(item, ok)
        resp.raise_for_status()
