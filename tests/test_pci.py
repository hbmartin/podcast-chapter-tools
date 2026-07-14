import json
from unittest.mock import Mock

from conftest import FakeResponse

from podcast_chapter_tools import extractors
from podcast_chapter_tools.extractors import (
    extract_pci_chapters,
    find_pci_chapters_url,
    get_and_extract_pci_chapters,
)

EXPECTED = [
    (0, "Intro", None, None),
    (310, "Main topic", "https://example.com/topic", "https://example.com/topic.png"),
]


def test_extract_pci_chapters(pci_json):
    assert extract_pci_chapters(pci_json) == EXPECTED


def test_extract_pci_chapters_missing_key():
    assert extract_pci_chapters({"nope": []}) is None


def test_extract_pci_chapters_bad_start(pci_json):
    pci_json["chapters"][0]["startTime"] = "not-a-number"
    assert extract_pci_chapters(pci_json) is None


def test_get_and_extract_fetches(monkeypatch, pci_json):
    monkeypatch.setattr(
        extractors.httpx2,
        "get",
        lambda *a, **kw: FakeResponse(json_data=pci_json),
    )
    chapters = get_and_extract_pci_chapters("https://example.com/chapters.json")
    assert chapters == EXPECTED


def test_get_and_extract_http_error(monkeypatch):
    monkeypatch.setattr(
        extractors.httpx2,
        "get",
        lambda *a, **kw: FakeResponse(is_success=False, status_code=500),
    )
    assert get_and_extract_pci_chapters("https://example.com/chapters.json") is None


def test_get_and_extract_request_error(monkeypatch):
    def boom(*a, **kw):
        raise extractors.httpx2.RequestError("timeout")

    monkeypatch.setattr(extractors.httpx2, "get", boom)
    assert get_and_extract_pci_chapters("https://example.com/chapters.json") is None


def test_get_and_extract_bad_json_response(monkeypatch):
    class BadJsonResponse:
        is_success = True
        status_code = 200

        def json(self):
            raise ValueError("bad json")

    monkeypatch.setattr(
        extractors.httpx2,
        "get",
        lambda *a, **kw: BadJsonResponse(),
    )
    assert get_and_extract_pci_chapters("https://example.com/chapters.json") is None


def test_get_and_extract_writes_archive(monkeypatch, pci_json, tmp_path):
    monkeypatch.setattr(
        extractors.httpx2,
        "get",
        lambda *a, **kw: FakeResponse(json_data=pci_json),
    )
    archive = tmp_path / "chapters.json"
    chapters = get_and_extract_pci_chapters(
        "https://example.com/chapters.json",
        archive_path_json=archive,
    )
    assert chapters == EXPECTED
    assert json.loads(archive.read_text()) == pci_json


def test_get_and_extract_returns_chapters_when_archive_write_fails(
    monkeypatch,
    pci_json,
    tmp_path,
):
    monkeypatch.setattr(
        extractors.httpx2,
        "get",
        lambda *a, **kw: FakeResponse(json_data=pci_json),
    )
    archive = tmp_path / "chapters.json"

    def fail_write(self, data, encoding=None):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(type(archive), "write_text", fail_write)
    chapters = get_and_extract_pci_chapters(
        "https://example.com/chapters.json",
        archive_path_json=archive,
    )

    assert chapters == EXPECTED


def test_get_and_extract_reads_archive(monkeypatch, pci_json, tmp_path):
    archive = tmp_path / "chapters.json"
    archive.write_text(json.dumps(pci_json))

    def boom(*a, **kw):
        raise AssertionError("should not fetch when archive exists")

    monkeypatch.setattr(extractors.httpx2, "get", boom)
    chapters = get_and_extract_pci_chapters(
        "https://example.com/chapters.json",
        archive_path_json=archive,
    )
    assert chapters == EXPECTED


def test_get_and_extract_bad_archive_json(tmp_path):
    archive = tmp_path / "chapters.json"
    archive.write_text("{")
    assert (
        get_and_extract_pci_chapters(
            "https://example.com/chapters.json",
            archive_path_json=archive,
        )
        is None
    )


def test_get_and_extract_bad_archive_utf8(tmp_path):
    archive = tmp_path / "chapters.json"
    archive.write_bytes(b"\xff")
    assert (
        get_and_extract_pci_chapters(
            "https://example.com/chapters.json",
            archive_path_json=archive,
        )
        is None
    )


def test_find_pci_chapters_url(feed_file):
    assert (
        find_pci_chapters_url(feed_file, "guid-2")
        == "https://example.com/chapters-2.json"
    )


def test_find_pci_chapters_url_not_declared(feed_file):
    assert find_pci_chapters_url(feed_file, "guid-1") is None
    assert find_pci_chapters_url(feed_file, "no-such-guid") is None


def test_find_pci_chapters_url_invalid_utf8(tmp_path):
    feed = tmp_path / "feed.xml"
    feed.write_bytes(b"\xff")
    assert find_pci_chapters_url(feed, "guid-1") is None


def test_find_pci_chapters_url_missing_file(tmp_path):
    assert find_pci_chapters_url(tmp_path / "nope.xml", "guid-1") is None


def test_find_pci_chapters_url_unparseable_feed(tmp_path):
    feed = tmp_path / "feed.xml"
    feed.write_text("not xml at all <<<")
    assert find_pci_chapters_url(feed, "guid-1") is None


def test_get_and_extract_logs_when_extraction_fails(monkeypatch):
    warning = Mock(wraps=extractors.logger.warning)
    monkeypatch.setattr(extractors.logger, "warning", warning)
    url = "https://example.com/chapters.json"
    # A well-formed JSON response that has no "chapters" key: the fetch
    # succeeds but extraction returns None.
    monkeypatch.setattr(
        extractors.httpx2,
        "get",
        lambda *a, **kw: FakeResponse(json_data={"version": "1.2.0"}),
    )
    assert get_and_extract_pci_chapters(url) is None
    warning.assert_called_with("Failed to extract PCI for {} @ {}", url, None)
