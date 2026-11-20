# Pocketbook-ArxivPaper

Read arXiv papers on a PocketBook e-reader as real, reflowable EPUBs instead of squinting at two-column PDFs.

```
arXiv ID / arxiv.org link / alphaxiv.org link / Zotero tag
        │
        ▼
arXiv HTML (LaTeXML) ──► ar5iv HTML ──► PDF (last resort)
        │
        ▼
clean-up for e-ink: equations → crisp grayscale PNGs (MathJax), figures → grayscale,
footnotes → popup notes, one chapter per section, generated cover
        │
        ▼
EPUB 3 (passes epubcheck) ──► e-mail to you@pbsync.com (Send-to-PocketBook)
```

## Three ways to use it

| Trigger | How |
| --- | --- |
| **CLI** | `arxiv2pb convert 1706.03762 https://www.alphaxiv.org/abs/2312.00752 --send` |
| **GitHub Action** (phone friendly) | Actions → *Send paper to PocketBook* → *Run workflow* → paste IDs or links |
| **Zotero inbox** | Tag a paper `to-pocketbook` in Zotero. The hourly *Zotero inbox to PocketBook* workflow converts it, mails it, and re-tags it `sent-to-pocketbook` (or `pocketbook-failed`). |

Accepted inputs: `2401.12345`, `2401.12345v2`, `hep-th/9711200`, `arxiv.org/abs|pdf|html/...`,
`alphaxiv.org/abs|overview/...`, `ar5iv` links, `10.48550/arXiv.…` DOIs and `arXiv:…` strings.

## One-time setup

1. **Send-to-PocketBook**: on the device or in [PocketBook Cloud](https://cloud.pocketbook.digital), enable
   Send-to-PocketBook and note your `…@pbsync.com` address. Add the address you will send *from* to the
   allowed senders list (the first mail from a new sender must be confirmed).
2. **SMTP account** to send from. With Gmail or Outlook create an *app password*.
3. **GitHub secrets** (Settings → Secrets and variables → Actions → *New repository secret*):
   `POCKETBOOK_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`.
4. **Zotero (optional)**: at <https://www.zotero.org/settings/keys> copy your *userID* and create a key with
   library read + **write** access. Add secrets `ZOTERO_USER_ID` and `ZOTERO_API_KEY`. The tag names can be
   changed with repository variables `ZOTERO_INBOX_TAG`, `ZOTERO_DONE_TAG`, `ZOTERO_FAILED_TAG`;
   `ZOTERO_COLLECTION` (a collection key) uses a collection as the inbox instead.
   Papers saved from arxiv.org or alphaxiv.org with the Zotero Connector are recognised automatically.

See [`.env.example`](.env.example) for every setting.

## Local install

Needs Python ≥ 3.10, Node.js ≥ 18 (for MathJax) and the Cairo library (`apt install libcairo2`,
`brew install cairo`).

```bash
pip install -e .
npm ci --prefix src/arxiv2pocketbook/mathjax   # optional, otherwise done on first run
cp .env.example .env                           # fill in
arxiv2pb convert 1706.03762                    # writes out/Vaswani 2017 - Attention Is All You Need.epub
arxiv2pb convert 1706.03762 --send             # ...and mails it
arxiv2pb send out/*.epub                       # mail files you already have
arxiv2pb zotero-sync --dry-run                 # see what the Zotero inbox would send
```

Options: `--mathml` keeps native MathML instead of images, `--color-figures` keeps figures in colour,
`--no-pdf` fails instead of falling back to the PDF.

## Prior art

Nothing found did arXiv → EPUB → PocketBook end to end, so this was built from scratch:

- [arxiv2epub](https://github.com/trog-levrai/arxiv2epub), [arxiv2kindle](https://github.com/soumik12345/arxiv2kindle):
  recompile the LaTeX source into a small-page PDF; need a full TeX Live install and the source.
- [paper2epub](https://pypi.org/project/paper2epub/): PDF → EPUB with the Nougat OCR model (PyTorch, too heavy for CI).
- [send-to-pocket-book](https://github.com/cobrinhas/send-to-pocket-book): browser extension that mails a tab to `@pbsync.com`.
- arXiv's own [HTML papers](https://blog.arxiv.org/2023/12/21/accessibility-update-arxiv-now-offers-papers-in-html-format)
  and [ar5iv](https://ar5iv.labs.arxiv.org/) (LaTeXML) are the source used here.

Design decisions are recorded in [docs/DECISIONS.md](docs/DECISIONS.md).
