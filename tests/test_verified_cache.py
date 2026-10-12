import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import httpx2
import pytest
from conftest import FakeResponse

from podcast_chapter_tools import (
    ChapterHTTPError,
    ChapterParseError,
    ChapterTransportError,
    fetch_pci_chapters,
    get_and_extract_pci_chapters,
    transport,
)

URL = "https://example.com/a.json"
OTHER = "https://example.com/b.json"
DOC = {"chapters": [{"startTime": 0.5, "title": "A", "endTime": 60.75}]}


def verified_archive(path, document=DOC, url=URL):
    raw = json.dumps(document).encode()
    path.write_bytes(raw)
    path.with_name(path.name + ".meta.json").write_text(
        json.dumps(
            {"version": 1, "url": url, "sha256": hashlib.sha256(raw).hexdigest()}
        )
    )


def test_verified_cache_reuses_without_fetch(monkeypatch, tmp_path):
    get = Mock(return_value=FakeResponse(json_data=DOC))
    monkeypatch.setattr(transport.httpx2, "get", get)
    path = tmp_path / "chapters.json"
    result = fetch_pci_chapters(URL, archive_path_json=path)
    assert fetch_pci_chapters(URL, archive_path_json=path) == result
    assert get.call_count == 1
    assert json.loads(path.read_text()) == DOC
    assert (
        json.loads(path.with_name(path.name + ".meta.json").read_text())["url"] == URL
    )


@pytest.mark.parametrize("trust", [False, True])
def test_url_mismatch_always_refetches(monkeypatch, tmp_path, trust):
    path = tmp_path / "shared.json"
    verified_archive(path)
    document = {"chapters": [{"startTime": 10, "title": "B"}]}
    get = Mock(return_value=FakeResponse(json_data=document))
    monkeypatch.setattr(transport.httpx2, "get", get)
    result = fetch_pci_chapters(
        OTHER, archive_path_json=path, trust_legacy_archive=trust
    )
    assert result.chapters[0].title == "B"
    assert get.call_count == 1


@pytest.mark.parametrize(
    "corruption",
    [
        "truncated",
        "utf8",
        "digest",
        "metadata",
        "version",
        "missing_metadata",
        "unusable",
    ],
)
def test_bad_archive_refetches_once(monkeypatch, tmp_path, corruption):
    path = tmp_path / "chapters.json"
    verified_archive(path)
    meta = path.with_name(path.name + ".meta.json")
    if corruption == "truncated":
        path.write_text("{")
    elif corruption == "utf8":
        path.write_bytes(b"\xff")
    elif corruption == "digest":
        path.write_text(json.dumps({"chapters": [{"startTime": 0, "title": "Wrong"}]}))
    elif corruption == "metadata":
        meta.write_text("{")
    elif corruption == "version":
        data = json.loads(meta.read_text())
        data["version"] = 99
        meta.write_text(json.dumps(data))
    elif corruption == "missing_metadata":
        meta.unlink()
    else:
        verified_archive(path, {"chapters": [{"startTime": "bad"}]})
    get = Mock(return_value=FakeResponse(json_data=DOC))
    monkeypatch.setattr(transport.httpx2, "get", get)
    assert fetch_pci_chapters(URL, archive_path_json=path).chapters[0].title == "A"
    assert get.call_count == 1
    assert fetch_pci_chapters(URL, archive_path_json=path).chapters[0].title == "A"
    assert get.call_count == 1


def test_legacy_trust_opt_in_without_metadata(monkeypatch, tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps(DOC))
    get = Mock(side_effect=AssertionError("Must remain offline"))
    monkeypatch.setattr(transport.httpx2, "get", get)
    assert (
        fetch_pci_chapters(URL, archive_path_json=path, trust_legacy_archive=True)
        .chapters[0]
        .start
        == 0.5
    )
    assert get.call_count == 0


@pytest.mark.parametrize("status", [404, 429, 500])
def test_http_error_has_context_and_cause(monkeypatch, status):
    get = Mock(
        return_value=FakeResponse(
            is_success=False, status_code=status, headers={"Retry-After": "120"}
        )
    )
    monkeypatch.setattr(transport.httpx2, "get", get)
    with pytest.raises(ChapterHTTPError) as caught:
        fetch_pci_chapters(URL)
    assert caught.value.url == URL
    assert caught.value.status_code == status
    assert caught.value.retry_after == "120"
    assert isinstance(caught.value.__cause__, httpx2.HTTPStatusError)
    assert get.call_count == 1


def test_transport_failure_preserves_cause(monkeypatch):
    failure = httpx2.ConnectError("offline")
    monkeypatch.setattr(transport.httpx2, "get", Mock(side_effect=failure))
    with pytest.raises(ChapterTransportError) as caught:
        fetch_pci_chapters(URL)
    assert caught.value.url == URL
    assert caught.value.__cause__ is failure


def test_bad_json_typed_and_never_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(
        transport.httpx2, "get", Mock(return_value=FakeResponse(text="{"))
    )
    path = tmp_path / "chapters.json"
    with pytest.raises(ChapterParseError) as caught:
        fetch_pci_chapters(URL, archive_path_json=path)
    assert isinstance(caught.value.__cause__, ValueError)
    assert caught.value.source == URL
    assert not path.exists()


def test_unusable_response_not_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(
        transport.httpx2,
        "get",
        Mock(return_value=FakeResponse(json_data={"chapters": [{"startTime": "bad"}]})),
    )
    path = tmp_path / "chapters.json"
    with pytest.raises(ChapterParseError):
        fetch_pci_chapters(URL, archive_path_json=path)
    assert not path.exists()


def test_empty_response_is_cached_absence(monkeypatch, tmp_path):
    get = Mock(return_value=FakeResponse(json_data={"chapters": []}))
    monkeypatch.setattr(transport.httpx2, "get", get)
    path = tmp_path / "chapters.json"
    assert not fetch_pci_chapters(URL, archive_path_json=path).chapters
    assert not fetch_pci_chapters(URL, archive_path_json=path).chapters
    assert get.call_count == 1


def test_cache_recovery_failure_raises_fetch_error_legacy_returns_none(
    monkeypatch, tmp_path
):
    path = tmp_path / "chapters.json"
    path.write_text("{")
    get = Mock(return_value=FakeResponse(is_success=False, status_code=404))
    monkeypatch.setattr(transport.httpx2, "get", get)
    with pytest.raises(ChapterHTTPError):
        fetch_pci_chapters(URL, archive_path_json=path)
    assert get_and_extract_pci_chapters(URL, archive_path_json=path) is None
    assert get.call_count == 2


def test_interrupted_metadata_write_cannot_reuse_wrong_document(monkeypatch, tmp_path):
    path = tmp_path / "chapters.json"
    verified_archive(path)
    original = transport._atomic_write  # noqa: SLF001 - inject an interrupted cache write

    def interrupted(destination, raw):
        if destination.name.endswith(".meta.json"):
            raise OSError("interrupted")
        original(destination, raw)

    monkeypatch.setattr(transport, "_atomic_write", interrupted)
    other_doc = {"chapters": [{"startTime": 2, "title": "B"}]}
    get = Mock(return_value=FakeResponse(json_data=other_doc))
    monkeypatch.setattr(transport.httpx2, "get", get)
    assert fetch_pci_chapters(OTHER, archive_path_json=path).chapters[0].title == "B"
    monkeypatch.setattr(transport, "_atomic_write", original)
    get.return_value = FakeResponse(json_data=DOC)
    assert fetch_pci_chapters(URL, archive_path_json=path).chapters[0].title == "A"
    assert get.call_count == 2


def test_failed_replace_cleans_temporary_file(monkeypatch, tmp_path):
    path = tmp_path / "chapters.json"
    monkeypatch.setattr(
        transport.httpx2, "get", Mock(return_value=FakeResponse(json_data=DOC))
    )

    def fail_replace(self, target):
        raise OSError("interrupted")

    monkeypatch.setattr(Path, "replace", fail_replace)
    assert fetch_pci_chapters(URL, archive_path_json=path).chapters
    assert list(tmp_path.iterdir()) == []


def test_strict_failure_on_usable_cache_does_not_fetch(monkeypatch, tmp_path):
    path = tmp_path / "chapters.json"
    verified_archive(path, {"chapters": [{"startTime": "1.5"}]})
    get = Mock(side_effect=AssertionError("Cache is usable"))
    monkeypatch.setattr(transport.httpx2, "get", get)
    with pytest.raises(ChapterParseError):
        fetch_pci_chapters(URL, archive_path_json=path, strict=True)
    assert get.call_count == 0
