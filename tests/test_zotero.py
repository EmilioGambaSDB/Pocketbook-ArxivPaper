from arxiv2pocketbook.zotero import arxiv_id_from_item


def test_preprint_item():
    assert arxiv_id_from_item({"itemType": "preprint", "archiveID": "arXiv:2401.12345", "url": "http://arxiv.org/abs/2401.12345v2"}) == "2401.12345"


def test_alphaxiv_url():
    assert arxiv_id_from_item({"url": "https://www.alphaxiv.org/abs/2401.12345"}) == "2401.12345"


def test_doi_and_extra():
    assert arxiv_id_from_item({"DOI": "10.48550/arXiv.2312.00001"}) == "2312.00001"
    assert arxiv_id_from_item({"extra": "arXiv: 2312.00002\nTex.ids: foo"}) == "2312.00002"


def test_journal_article_without_arxiv():
    assert arxiv_id_from_item({"DOI": "10.1038/nature14539", "url": "https://www.nature.com/articles/nature14539"}) is None


class _Resp:
    def __init__(self, data, status=200, headers=None):
        self._data, self.status_code, self.headers = data, status, headers or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _FakeSession:
    def __init__(self, items):
        self.headers = {}
        self.items = items
        self.patches = []

    def get(self, url, params=None, timeout=None):
        assert url.endswith("/users/42/items/top") and params["tag"] == "to-pocketbook"
        return _Resp(self.items, headers={"Total-Results": str(len(self.items))})

    def patch(self, url, json=None, headers=None, timeout=None):
        self.patches.append((url, json, headers))
        return _Resp({}, 204)


def test_inbox_pending_and_mark():
    from arxiv2pocketbook.zotero import ZoteroConfig, ZoteroInbox

    items = [
        {"key": "AAA", "version": 5, "data": {"title": "Paper", "url": "https://arxiv.org/abs/2401.12345", "tags": [{"tag": "to-pocketbook"}, {"tag": "ml"}]}},
        {"key": "BBB", "version": 6, "data": {"title": "Old", "url": "https://arxiv.org/abs/2401.1", "tags": [{"tag": "to-pocketbook"}, {"tag": "sent-to-pocketbook"}]}},
    ]
    sess = _FakeSession(items)
    inbox = ZoteroInbox(ZoteroConfig(api_key="k", library_type="users", library_id="42"), sess)
    pending = inbox.pending()
    assert [p.key for p in pending] == ["AAA"] and pending[0].arxiv_id == "2401.12345"
    inbox.mark(pending[0], ok=True)
    url, body, headers = sess.patches[0]
    assert url.endswith("/users/42/items/AAA")
    assert body == {"tags": [{"tag": "ml"}, {"tag": "sent-to-pocketbook"}]}
    assert headers == {"If-Unmodified-Since-Version": "5"}
