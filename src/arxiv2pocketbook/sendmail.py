"""Deliver files to a PocketBook through Send-to-PocketBook (e-mail to <name>@pbsync.com)."""

from __future__ import annotations

import logging
import mimetypes
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from .config import env, require

log = logging.getLogger(__name__)

# Send-to-PocketBook rejects large mails; stay well below common provider limits.
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


@dataclass
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    sender: str
    recipient: str

    @classmethod
    def from_env(cls) -> "SmtpConfig":
        username = require("SMTP_USERNAME")
        return cls(
            host=require("SMTP_HOST"),
            port=int(env("SMTP_PORT", "587")),
            username=username,
            password=require("SMTP_PASSWORD"),
            sender=env("SMTP_FROM") or username,
            recipient=require("POCKETBOOK_EMAIL"),
        )


def build_message(cfg: SmtpConfig, path: Path, subject: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = cfg.sender
    msg["To"] = cfg.recipient
    msg["Subject"] = subject or path.stem
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=cfg.sender.split("@")[-1] or None)
    msg.set_content(f"{path.name}\n\nSent by arxiv2pocketbook.")
    ctype = mimetypes.guess_type(path.name)[0] or (
        "application/epub+zip" if path.suffix == ".epub" else "application/octet-stream"
    )
    maintype, subtype = ctype.split("/", 1)
    msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    return msg


def send_files(paths: list[Path], cfg: SmtpConfig | None = None) -> None:
    """Send each file as its own e-mail (one book per mail is what Send-to-PocketBook handles best)."""
    cfg = cfg or SmtpConfig.from_env()
    for p in paths:
        if p.stat().st_size > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"{p.name} is {p.stat().st_size / 1e6:.1f} MB, above the {MAX_ATTACHMENT_BYTES / 1e6:.0f} MB mail limit")
    context = ssl.create_default_context()
    if cfg.port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(cfg.host, cfg.port, context=context, timeout=60)
    else:
        server = smtplib.SMTP(cfg.host, cfg.port, timeout=60)
        server.starttls(context=context)
    with server:
        server.login(cfg.username, cfg.password)
        for p in paths:
            server.send_message(build_message(cfg, p))
            log.info("Sent %s to %s", p.name, cfg.recipient)
