import codecs
import subprocess
import sys
import traceback
from unittest.mock import Mock

import httpx2
import pytest

from podcast_chapter_tools import (
    ChapterParseError,
    extract_all_psc_chapters_from_file,
    extract_psc_chapters_from_file,
    extract_psc_chapters_from_url,
    extractors,
    find_pci_chapters_url,
    parse_feed_chapters,
    parsers,
    transport,
)
from podcast_chapter_tools.cli import main
from podcast_chapter_tools.extractors import _encoded_feed_index, _fetch_feed_index

URL = "https://example.com/feed.xml"
FEED = '<rss xmlns:psc="http://podlove.org/simple-chapters"><channel><item><guid>g</guid><psc:chapters><psc:chapter start="0:00" title="Café"/></psc:chapters></item></channel></rss>'


class _WithoutWholeFeedDecode(bytes):
    def decode(self, *_args, **_kwargs):
        pytest.fail("Native feed failure decoded the whole document")


def test_unknown_xml_codec_is_typed_and_adapters_recover(tmp_path, monkeypatch, capsys):
    xml = b'<?xml version="1.0" encoding="made-up-codec"?><rss><channel/></rss>'
    with pytest.raises(ChapterParseError) as caught:
        parse_feed_chapters(xml, source=URL)
    assert isinstance(caught.value.__cause__, LookupError)
    assert caught.value.source == URL
    path = tmp_path / "feed.xml"
    path.write_bytes(xml)
    assert extract_psc_chapters_from_file(path, "g") is None
    assert extract_all_psc_chapters_from_file(path) is None
    assert find_pci_chapters_url(path, "g") is None
    monkeypatch.setattr(
        transport.httpx2, "get", Mock(return_value=httpx2.Response(200, content=xml))
    )
    assert extract_psc_chapters_from_url(URL, "g") is None
    for source in [str(path), URL]:
        assert main(["from-psc", source, "--guid", "g"]) == 1
        assert "ChapterParseError" in capsys.readouterr().err


@pytest.mark.parametrize("declaration", ["", '<?xml version="1.0" encoding="UTF-8"?>'])
def test_http_charset_is_respected_even_with_conflicting_declaration(
    declaration, monkeypatch, capsys
):
    response = httpx2.Response(
        200,
        headers={"Content-Type": 'application/rss+xml; charset="iso-8859-1"'},
        content=(declaration + FEED).encode("latin-1"),
    )
    monkeypatch.setattr(transport.httpx2, "get", Mock(return_value=response))
    assert extract_psc_chapters_from_url(URL, "g")[0].title == "Café"
    assert main(["from-psc", URL, "--guid", "g", "--to", "description"]) == 0
    assert capsys.readouterr().out == "0:00 Café\n"


@pytest.mark.parametrize("encoding", ["iso-8859-1", "utf-16", "utf-8-sig"])
def test_feed_bytes_keep_declared_encodings_and_boms(encoding, tmp_path, monkeypatch):
    declared = "UTF-8" if encoding == "utf-8-sig" else encoding
    xml = (f'<?xml version="1.0" encoding="{declared}"?>' + FEED).encode(encoding)
    path = tmp_path / "feed.xml"
    path.write_bytes(xml)
    assert extract_psc_chapters_from_file(path, "g")[0].title == "Café"
    monkeypatch.setattr(
        transport.httpx2, "get", Mock(return_value=httpx2.Response(200, content=xml))
    )
    assert extract_psc_chapters_from_url(URL, "g")[0].title == "Café"


@pytest.mark.parametrize(
    ("charset", "content"), [("unknown-codec", b"<rss/>"), ("utf-8", b"\xff")]
)
def test_invalid_http_charset_and_bytes_are_typed(
    charset, content, monkeypatch, capsys
):
    response = httpx2.Response(
        200,
        headers={"Content-Type": f"application/xml; charset={charset}"},
        content=content,
    )
    monkeypatch.setattr(transport.httpx2, "get", Mock(return_value=response))
    assert extract_psc_chapters_from_url(URL, "g") is None
    assert main(["from-psc", URL, "--guid", "g"]) == 1
    assert "ChapterParseError" in capsys.readouterr().err


def test_cached_failures_have_bounded_tracebacks_and_parse_once(monkeypatch):
    parse = Mock(wraps=parsers.parse_psc_chapters)
    monkeypatch.setattr(parsers, "parse_psc_chapters", parse)
    index = parse_feed_chapters(FEED.replace('start="0:00"', 'start="bad"'), source=URL)
    errors = []
    depths = []
    for _ in range(10):
        with pytest.raises(ChapterParseError) as caught:
            index.psc_for_guid("g")
        errors.append(caught.value)
        depths.append(len(traceback.extract_tb(caught.value.__traceback__)))
        assert caught.value.source == URL
        assert caught.value.guid == "g"
        assert caught.value.issues[0].code == "invalid_start"
    assert len({id(exc) for exc in errors}) == len(errors)
    assert len(set(depths)) == 1
    assert parse.call_count == 1


def test_duplicate_without_chapters_keeps_first_episode_in_all_adapters(
    tmp_path, monkeypatch
):
    xml = FEED.replace("<channel>", "<channel><item><guid>g</guid></item>")
    index = parse_feed_chapters(xml)
    assert not index.psc_for_guid("g").chapters
    assert index.issues[0].code == "duplicate_guid"
    path = tmp_path / "feed.xml"
    path.write_text(xml, encoding="utf-8")
    assert extract_all_psc_chapters_from_file(path) == {}
    assert extract_psc_chapters_from_file(path, "g") is None
    monkeypatch.setattr(
        transport.httpx2, "get", Mock(return_value=httpx2.Response(200, text=xml))
    )
    assert extract_psc_chapters_from_url(URL, "g") is None


@pytest.mark.parametrize("charset", ["binary", "unknown-codec", "us-ascii"])
def test_invalid_http_encoding_falls_back_to_xml_bytes(charset, monkeypatch, capsys):
    response = httpx2.Response(
        200,
        headers={"Content-Type": f"application/xml; charset={charset}"},
        content=('<?xml version="1.0" encoding="UTF-8"?>' + FEED).encode(),
    )
    monkeypatch.setattr(transport.httpx2, "get", Mock(return_value=response))
    warning = Mock()
    monkeypatch.setattr(extractors.logger, "warning", warning)
    result = _fetch_feed_index(URL).psc_for_guid("g", strict=True)
    assert result.chapters[0].title == "Café"
    assert not result.issues
    warning.assert_called_once()
    assert extract_psc_chapters_from_url(URL, "g")[0].title == "Café"
    assert main(["from-psc", URL, "--guid", "g", "--to", "description"]) == 0
    assert capsys.readouterr().out == "0:00 Café\n"


def test_successful_wrong_charset_does_not_trigger_fallback(monkeypatch):
    response = httpx2.Response(
        200,
        headers={"Content-Type": "application/xml; charset=iso-8859-1"},
        content=('<?xml version="1.0" encoding="UTF-8"?>' + FEED).encode(),
    )
    monkeypatch.setattr(transport.httpx2, "get", Mock(return_value=response))
    assert _fetch_feed_index(URL).psc_for_guid("g").chapters[0].title == "CafÃ©"


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-32"])
def test_http_bom_overrides_header_and_declaration(encoding, monkeypatch):
    response = httpx2.Response(
        200,
        headers={"Content-Type": "application/xml; charset=us-ascii"},
        content=('<?xml version="1.0" encoding="iso-8859-1"?>' + FEED).encode(encoding),
    )
    monkeypatch.setattr(transport.httpx2, "get", Mock(return_value=response))
    assert _fetch_feed_index(URL).psc_for_guid("g").chapters[0].title == "Café"


@pytest.mark.parametrize("encoding", ["utf-16-be", "utf-32-be"])
def test_big_endian_http_bom_overrides_unknown_charset(encoding, monkeypatch):
    bom = codecs.BOM_UTF16_BE if encoding == "utf-16-be" else codecs.BOM_UTF32_BE
    response = httpx2.Response(
        200,
        headers={"Content-Type": "application/xml; charset=binary"},
        content=bom + FEED.encode(encoding),
    )
    monkeypatch.setattr(transport.httpx2, "get", Mock(return_value=response))
    assert _fetch_feed_index(URL).psc_for_guid("g").chapters[0].title == "Café"


def test_invalid_bom_encoding_stays_authoritative_and_typed(monkeypatch):
    response = httpx2.Response(
        200,
        headers={"Content-Type": "application/xml; charset=iso-8859-1"},
        content=b"\xff\xfea",
    )
    monkeypatch.setattr(transport.httpx2, "get", Mock(return_value=response))
    with pytest.raises(ChapterParseError) as caught:
        _fetch_feed_index(URL)
    assert isinstance(caught.value.__cause__, UnicodeError)
    assert extract_psc_chapters_from_url(URL, "g") is None


@pytest.mark.parametrize(
    ("charset", "title"), [("windows-1252", "Café"), ("shift_jis", "日本語")]
)
def test_non_native_http_codecs_keep_python_decoder_support(
    charset, title, monkeypatch
):
    response = httpx2.Response(
        200,
        headers={"Content-Type": f"application/xml; charset={charset}"},
        content=(
            '<?xml version="1.0" encoding="UTF-8"?>' + FEED.replace("Café", title)
        ).encode(charset),
    )
    monkeypatch.setattr(transport.httpx2, "get", Mock(return_value=response))
    assert _fetch_feed_index(URL).psc_for_guid("g").chapters[0].title == title


@pytest.mark.parametrize("charset", ["utf-8", "shift_jis"])
def test_structural_xml_failure_does_not_retry(charset, monkeypatch):
    response = httpx2.Response(
        200,
        headers={"Content-Type": f"application/xml; charset={charset}"},
        content=b"<rss><channel></rss>",
    )
    monkeypatch.setattr(transport.httpx2, "get", Mock(return_value=response))
    parse = Mock(wraps=parsers.ElementTree.fromstring)
    monkeypatch.setattr(parsers.ElementTree, "fromstring", parse)
    with pytest.raises(ChapterParseError) as caught:
        _fetch_feed_index(URL)
    assert caught.value.source == URL
    assert isinstance(caught.value.__cause__, parsers.ElementTree.ParseError)
    assert parse.call_count == 1


@pytest.mark.parametrize("charset", ["binary", "us-ascii"])
def test_failed_charset_fallback_retains_typed_contract(charset, monkeypatch, capsys):
    response = httpx2.Response(
        200,
        headers={"Content-Type": f"application/xml; charset={charset}"},
        content=b"\xff",
    )
    monkeypatch.setattr(transport.httpx2, "get", Mock(return_value=response))
    with pytest.raises(ChapterParseError) as caught:
        _fetch_feed_index(URL)
    assert caught.value.source == URL
    assert isinstance(caught.value.__cause__, (LookupError, UnicodeError))
    assert caught.value.__notes__
    assert extract_psc_chapters_from_url(URL, "g") is None
    assert main(["from-psc", URL, "--guid", "g"]) == 1
    assert "ChapterParseError" in capsys.readouterr().err


def test_native_feed_encoding_avoids_full_string_allocation():
    code = """
import tracemalloc
from unittest.mock import Mock
import httpx2
from podcast_chapter_tools import parse_feed_chapters, transport
from podcast_chapter_tools.extractors import _fetch_feed_index
raw = ('<rss><channel><description>' + 'x' * (5 * 1024 * 1024) + '</description></channel></rss>').encode()
transport.httpx2.get = Mock(return_value=httpx2.Response(200, headers={'Content-Type': 'application/xml; charset=iso-8859-1'}, content=raw))
peaks = []
for parse in (lambda: _fetch_feed_index('https://example.com'), lambda: parse_feed_chapters(raw.decode('iso-8859-1'))):
    tracemalloc.start()
    result = parse()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peaks.append(peak)
    del result
assert peaks[0] + 3 * 1024 * 1024 < peaks[1], peaks
"""
    subprocess.run(  # noqa: S603 - isolated allocation regression with fixed code.
        [sys.executable, "-c", code], check=True, capture_output=True, timeout=30
    )


@pytest.mark.parametrize(
    ("charset", "raw"),
    [
        ("iso-8859-1", b"<rss><channel></rss>"),
        ("utf-8", b"<rss/>"),
        ("us-ascii", b"<rss/>"),
    ],
)
def test_native_failures_without_encoding_ambiguity_skip_decoding(
    charset, raw, monkeypatch
):
    decoder = Mock(side_effect=AssertionError("Unnecessary encoding validation"))
    monkeypatch.setattr(extractors.codecs, "getincrementaldecoder", decoder)
    with pytest.raises(ChapterParseError):
        _encoded_feed_index(_WithoutWholeFeedDecode(raw), charset, URL)
    decoder.assert_not_called()


def test_native_xml_failure_validates_bounded_chunks_and_flushes(monkeypatch):
    prefix = b"<rss><channel><description>"
    raw = prefix + b"x" * (16383 - len(prefix)) + "é".encode() + b"x" * 20000
    raw += b"</description></rss>"
    chunks = []
    real_decoder = codecs.getincrementaldecoder

    def decoder_factory(encoding):
        factory = real_decoder(encoding)

        class Decoder:
            def __init__(self, errors="strict"):
                self.decoder = factory(errors=errors)

            def decode(self, data, final=False):  # noqa: FBT002 - Match the codec callback.
                chunks.append((len(data), final))
                return self.decoder.decode(data, final=final)

        return Decoder

    monkeypatch.setattr(extractors.codecs, "getincrementaldecoder", decoder_factory)
    with pytest.raises(ChapterParseError) as caught:
        _encoded_feed_index(raw, "utf-8", URL)
    assert isinstance(caught.value.__cause__, parsers.ElementTree.ParseError)
    assert sum(size for size, _ in chunks) == len(raw)
    assert max(size for size, _ in chunks) <= 16 * 1024
    assert chunks[-1] == (0, True)


@pytest.mark.parametrize("charset", ["utf-8", "utf-16"])
def test_native_xml_failure_flush_detects_incomplete_encoding(charset):
    raw = "<rss><channel>".encode(charset)
    raw += b"\xc3" if charset == "utf-8" else b"a"
    with pytest.raises(UnicodeDecodeError):
        _encoded_feed_index(raw, charset, URL)


def test_native_encoding_validation_allocation_is_bounded():
    code = """
import tracemalloc
from unittest.mock import patch
from xml.etree import ElementTree
from podcast_chapter_tools import ChapterParseError
from podcast_chapter_tools.extractors import _encoded_feed_index
raw = b'x' * (5 * 1024 * 1024)
def failed_xml(*args, **kwargs):
    try:
        raise ElementTree.ParseError('malformed XML')
    except ElementTree.ParseError as error:
        raise ChapterParseError('Invalid feed XML') from error
with patch('podcast_chapter_tools.extractors._parse_feed_chapters', failed_xml):
    tracemalloc.start()
    try:
        _encoded_feed_index(raw, 'utf-8', 'input')
    except ChapterParseError:
        pass
    else:
        raise AssertionError('Malformed XML was accepted')
    _, peak = tracemalloc.get_traced_memory()
    assert peak < 256 * 1024, peak
"""
    subprocess.run(  # noqa: S603 - fixed allocation regression in an isolated interpreter.
        [sys.executable, "-c", code], check=True, capture_output=True, timeout=30
    )
