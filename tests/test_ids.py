import pytest

from arxiv2pocketbook.ids import InvalidArxivId, find_arxiv_id, parse_arxiv_id, strip_version


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1706.03762", "1706.03762"),
        ("  2401.12345v2 ", "2401.12345v2"),
        ("https://arxiv.org/abs/1706.03762", "1706.03762"),
        ("https://arxiv.org/abs/1706.03762v7", "1706.03762v7"),
        ("https://arxiv.org/pdf/1706.03762v7.pdf", "1706.03762v7"),
        ("https://arxiv.org/pdf/2401.12345", "2401.12345"),
        ("https://arxiv.org/html/2401.12345v1#S2", "2401.12345v1"),
        ("http://export.arxiv.org/abs/hep-th/9901001v2", "hep-th/9901001v2"),
        ("https://ar5iv.labs.arxiv.org/html/1207.0580", "1207.0580"),
        ("https://ar5iv.org/abs/1207.0580", "1207.0580"),
        ("https://www.alphaxiv.org/abs/2401.12345", "2401.12345"),
        ("https://www.alphaxiv.org/overview/2401.12345v3", "2401.12345v3"),
        ("alphaxiv.org/abs/2401.12345?tab=comments", "2401.12345"),
        ("https://doi.org/10.48550/arXiv.2401.12345", "2401.12345"),
        ("arXiv: 2401.12345", "2401.12345"),
        ("arXiv:math.GT/0309136", "math.GT/0309136"),
    ],
)
def test_parse(text, expected):
    assert parse_arxiv_id(text) == expected


@pytest.mark.parametrize("text", ["", "hello", "https://example.com/1234", "12345.6789012"])
def test_invalid(text):
    with pytest.raises(InvalidArxivId):
        parse_arxiv_id(text)
    assert find_arxiv_id(text) is None


def test_strip_version():
    assert strip_version("2401.12345v3") == "2401.12345"
    assert strip_version("2401.12345") == "2401.12345"
