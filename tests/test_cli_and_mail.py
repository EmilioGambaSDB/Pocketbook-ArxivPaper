from email import message_from_bytes

from arxiv2pocketbook.cli import _split_refs, build_parser
from arxiv2pocketbook.sendmail import SmtpConfig, build_message


def test_split_refs():
    assert _split_refs(["2401.1 , 2401.2\nhttps://alphaxiv.org/abs/2401.3", "x"]) == ["2401.1", "2401.2", "https://alphaxiv.org/abs/2401.3", "x"]


def test_parser():
    args = build_parser().parse_args(["convert", "--send", "-o", "o", "--", "1706.03762"])
    assert args.send and args.papers == ["1706.03762"] and args.output == "o"


def test_build_message(tmp_path):
    f = tmp_path / "Vaswani 2017 - Attention.epub"
    f.write_bytes(b"PK\x03\x04epub")
    cfg = SmtpConfig("smtp.example.org", 587, "me@example.org", "pw", "me@example.org", "me@pbsync.com")
    msg = message_from_bytes(build_message(cfg, f).as_bytes())
    assert msg["To"] == "me@pbsync.com" and msg["From"] == "me@example.org"
    att = [p for p in msg.walk() if p.get_filename()]
    assert att[0].get_filename() == f.name
    assert att[0].get_content_type() == "application/epub+zip"
    assert att[0].get_payload(decode=True) == b"PK\x03\x04epub"
