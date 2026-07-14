from xml.etree import ElementTree

from conftest import FEED_XML, FakeResponse

from podcast_chapter_tools import extractors
from podcast_chapter_tools.extractors import (
    _iter_feed_items,
    extract_all_psc_chapters_from_file,
    extract_psc_chapters,
    extract_psc_chapters_from_file,
    extract_psc_chapters_from_url,
)

EXPECTED = [
    (0, "Intro", None, None),
    (310, "Main topic", "https://example.com/topic", None),
    (3600, "Outro", None, "https://example.com/outro.png"),
]


def test_extract_by_guid(feed_file):
    assert extract_psc_chapters_from_file(feed_file, "guid-1") == EXPECTED


def test_missing_guid(feed_file):
    assert extract_psc_chapters_from_file(feed_file, "no-such-guid") is None


def test_episode_without_chapters(feed_file):
    assert extract_psc_chapters_from_file(feed_file, "guid-3") is None


def test_missing_file(tmp_path):
    assert extract_psc_chapters_from_file(tmp_path / "nope.xml", "guid-1") is None


def test_unparseable_feed(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("not xml at all <<<")
    assert extract_psc_chapters_from_file(bad, "guid-1") is None


def test_invalid_utf8_feed_returns_none(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_bytes(b"\xff")
    assert extract_psc_chapters_from_file(bad, "guid-1") is None
    assert extract_all_psc_chapters_from_file(bad) is None


def test_feed_without_channel(tmp_path):
    bad = tmp_path / "nochannel.xml"
    bad.write_text("<rss></rss>")
    assert extract_psc_chapters_from_file(bad, "guid-1") is None


def test_all_episodes(feed_file):
    all_chapters = extract_all_psc_chapters_from_file(feed_file)
    assert all_chapters == {"guid-1": EXPECTED}


def test_all_missing_file(tmp_path):
    assert extract_all_psc_chapters_from_file(tmp_path / "nope.xml") is None


def test_all_unparseable_feed(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("not xml at all <<<")
    assert extract_all_psc_chapters_from_file(bad) is None


def test_all_skips_item_without_guid(tmp_path):
    feed = tmp_path / "feed.xml"
    feed.write_text(
        '<rss xmlns:psc="http://podlove.org/simple-chapters"><channel>'
        "<item><title>No guid</title>"
        '<psc:chapters><psc:chapter start="0:00" title="A"/>'
        '<psc:chapter start="1:00" title="B"/></psc:chapters></item>'
        "<item><title>Has guid</title><guid>guid-1</guid>"
        '<psc:chapters><psc:chapter start="0:00" title="Intro"/>'
        '<psc:chapter start="5:10" title="Main topic" '
        'href="https://example.com/topic"/>'
        '<psc:chapter start="01:00:00" title="Outro" '
        'image="https://example.com/outro.png"/></psc:chapters></item>'
        "</channel></rss>",
    )
    assert extract_all_psc_chapters_from_file(feed) == {"guid-1": EXPECTED}


def test_iter_feed_items_without_channel():
    root = ElementTree.fromstring("<rss></rss>")
    assert list(_iter_feed_items(root)) == []


def test_extract_from_url_unparseable_feed(monkeypatch):
    monkeypatch.setattr(
        extractors.httpx2,
        "get",
        lambda *a, **kw: FakeResponse(text="not xml at all <<<"),
    )
    assert (
        extract_psc_chapters_from_url("https://example.com/feed.xml", "guid-1") is None
    )


def test_extract_from_element_with_bad_start():
    element = ElementTree.fromstring(
        '<chapters><chapter start="bogus" title="X"/></chapters>',
    )
    assert extract_psc_chapters(element) is None


def test_extract_from_element_missing_title():
    element = ElementTree.fromstring(
        '<chapters><chapter start="0:10"/></chapters>',
    )
    assert extract_psc_chapters(element) is None


def test_extract_from_url(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None, *, follow_redirects=False):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["follow_redirects"] = follow_redirects
        return FakeResponse(text=FEED_XML)

    monkeypatch.setattr(extractors.httpx2, "get", fake_get)
    chapters = extract_psc_chapters_from_url("https://example.com/feed.xml", "guid-1")
    assert chapters == EXPECTED
    assert captured["url"] == "https://example.com/feed.xml"
    assert captured["timeout"] is not None
    assert captured["follow_redirects"] is True


def test_extract_from_url_http_error(monkeypatch):
    monkeypatch.setattr(
        extractors.httpx2,
        "get",
        lambda *a, **kw: FakeResponse(is_success=False, status_code=404),
    )
    assert (
        extract_psc_chapters_from_url("https://example.com/feed.xml", "guid-1") is None
    )


def test_extract_from_url_request_error(monkeypatch):
    def boom(*a, **kw):
        raise extractors.httpx2.RequestError("timeout")

    monkeypatch.setattr(extractors.httpx2, "get", boom)
    assert (
        extract_psc_chapters_from_url("https://example.com/feed.xml", "guid-1") is None
    )
