from xml.etree import ElementTree

from conftest import FEED_XML, FakeResponse

from podcast_chapter_tools import extractors
from podcast_chapter_tools.extractors import (
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


def test_feed_without_channel(tmp_path):
    bad = tmp_path / "nochannel.xml"
    bad.write_text("<rss></rss>")
    assert extract_psc_chapters_from_file(bad, "guid-1") is None


def test_all_episodes(feed_file):
    all_chapters = extract_all_psc_chapters_from_file(feed_file)
    assert all_chapters == {"guid-1": EXPECTED}


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

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return FakeResponse(text=FEED_XML)

    monkeypatch.setattr(extractors.requests, "get", fake_get)
    chapters = extract_psc_chapters_from_url("https://example.com/feed.xml", "guid-1")
    assert chapters == EXPECTED
    assert captured["url"] == "https://example.com/feed.xml"
    assert captured["timeout"] is not None


def test_extract_from_url_http_error(monkeypatch):
    monkeypatch.setattr(
        extractors.requests,
        "get",
        lambda *a, **kw: FakeResponse(ok=False, status_code=404),
    )
    assert (
        extract_psc_chapters_from_url("https://example.com/feed.xml", "guid-1") is None
    )
