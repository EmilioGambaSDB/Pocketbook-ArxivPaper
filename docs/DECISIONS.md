# Decision log

Decided by the user in the grilling round of 2026-11-19.

| # | Topic | Decision |
| --- | --- | --- |
| 1 | Input | Any arXiv or alphaXiv link or ID, normalised to one arXiv ID |
| 2 | Conversion source | arXiv HTML (LaTeXML), with a PDF fallback |
| 3 | Equations on e-ink | High-resolution grayscale PNG images |
| 4 | Delivery | Send-to-PocketBook e-mail (`…@pbsync.com`) over SMTP |
| 5 | Trigger | Python CLI plus a manual GitHub Action |
| 6 | Zotero | A Zotero tag (or collection) is the inbox; sent items are re-tagged |

## Implementation choices (not yet confirmed by the user)

- **ar5iv before PDF.** Between arXiv HTML and the PDF, ar5iv's HTML is tried. If no usable HTML exists, the
  *original PDF* is sent as-is (no PDF→EPUB conversion: reflowing two-column PDFs gives poor results).
- **Equation rendering** uses MathJax (Node.js) on LaTeXML's already macro-expanded MathML, falling back to the TeX
  source, then cairosvg → grayscale PNG at 28 px/ex. Images are sized in `em`, so they follow the reader's font size.
- **Figures** are converted to grayscale PNG, max 1400 px wide (`--color-figures` to keep colour).
- **EPUB is built with EbookLib** directly from the cleaned HTML (not pandoc), so LaTeXML structure and classes are
  kept. One chapter per top-level section; footnotes become EPUB 3 popup notes; a simple cover is generated.
- **One e-mail per paper**, 20 MB attachment cap.
- **Zotero schedule**: hourly (`:17`), with a cheap inbox check so empty runs take seconds. Items without an arXiv
  ID or whose conversion fails get the `pocketbook-failed` tag so they are not retried forever.
- Author e-mail addresses are dropped from the title page.
