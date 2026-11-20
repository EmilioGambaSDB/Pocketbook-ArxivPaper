"""Command line interface: ``arxiv2pb convert|send|zotero-sync``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .arxiv import session
from .config import ConfigError, load_dotenv
from .convert import ConvertOptions
from .ids import InvalidArxivId
from .pipeline import convert_paper

log = logging.getLogger("arxiv2pb")


def _split_refs(values: list[str]) -> list[str]:
    """Accept refs separated by spaces, commas or newlines (handy for the GitHub Action input)."""
    refs: list[str] = []
    for v in values:
        refs.extend(x for x in v.replace(",", " ").split() if x)
    return refs


def _options(args) -> ConvertOptions:
    return ConvertOptions(math_images=not args.mathml, grayscale_figures=not args.color_figures)


def cmd_convert(args) -> int:
    from .sendmail import SmtpConfig, send_files

    refs = _split_refs(args.papers)
    if not refs:
        log.error("No papers given")
        return 2
    smtp = SmtpConfig.from_env() if args.send else None  # fail fast on missing settings
    sess = session()
    produced, failures = [], 0
    for ref in refs:
        try:
            res = convert_paper(ref, Path(args.output), options=_options(args), allow_pdf=not args.no_pdf, sess=sess)
            produced.append(res.path)
            print(res.path)
        except InvalidArxivId as exc:
            log.error("%s", exc)
            failures += 1
        except Exception as exc:  # noqa: BLE001 - report and continue with the next paper
            log.error("%s: %s", ref, exc, exc_info=args.verbose)
            failures += 1
    if args.send and produced:
        send_files(produced, smtp)
    return 1 if failures else 0


def cmd_send(args) -> int:
    from .sendmail import send_files

    send_files([Path(p) for p in args.files])
    return 0


def cmd_zotero(args) -> int:
    from .sendmail import SmtpConfig, send_files
    from .zotero import ZoteroConfig, ZoteroInbox

    inbox = ZoteroInbox(ZoteroConfig.from_env())
    items = inbox.pending()
    log.info("Zotero inbox: %d item(s)", len(items))
    if not items:
        return 0
    smtp = None if args.dry_run or args.no_send else SmtpConfig.from_env()
    sess = session()
    failures = 0
    for item in items:
        if not item.arxiv_id:
            log.warning("Skipping %r: no arXiv ID found", item.title)
            if not args.dry_run:
                inbox.mark(item, ok=False)
            failures += 1
            continue
        if args.dry_run:
            print(f"would convert {item.arxiv_id}: {item.title}")
            continue
        try:
            res = convert_paper(item.arxiv_id, Path(args.output), options=_options(args), allow_pdf=not args.no_pdf, sess=sess)
            if smtp:
                send_files([res.path], smtp)
            inbox.mark(item, ok=True)
            print(res.path)
        except Exception as exc:  # noqa: BLE001
            log.error("%s (%s): %s", item.arxiv_id, item.title, exc, exc_info=args.verbose)
            inbox.mark(item, ok=False)
            failures += 1
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arxiv2pb", description="arXiv / alphaXiv papers -> EPUB -> PocketBook")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def conv_opts(sp):
        sp.add_argument("-o", "--output", default="out", help="output folder (default: out)")
        sp.add_argument("--mathml", action="store_true", help="keep MathML instead of rendering equations to images")
        sp.add_argument("--color-figures", action="store_true", help="keep figures in colour (default: grayscale)")
        sp.add_argument("--no-pdf", action="store_true", help="fail instead of falling back to the PDF")

    c = sub.add_parser("convert", help="convert papers (IDs or arXiv/alphaXiv links)")
    c.add_argument("papers", nargs="+", help="arXiv IDs or arxiv.org / alphaxiv.org links")
    c.add_argument("--send", action="store_true", help="e-mail the results to your PocketBook")
    conv_opts(c)
    c.set_defaults(func=cmd_convert)

    s = sub.add_parser("send", help="e-mail existing files to your PocketBook")
    s.add_argument("files", nargs="+")
    s.set_defaults(func=cmd_send)

    z = sub.add_parser("zotero-sync", help="convert and send everything tagged in your Zotero inbox")
    z.add_argument("--dry-run", action="store_true", help="only list what would be sent")
    z.add_argument("--no-send", action="store_true", help="convert and tag, but do not e-mail")
    conv_opts(z)
    z.set_defaults(func=cmd_zotero)
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    try:
        return args.func(args)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
