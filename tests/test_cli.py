import argparse
import json
import runpy
import sys

import httpx2
import pytest
from conftest import FEED_XML, FakeResponse

from podcast_chapter_tools import (
    extract_psc_chapters_from_file,
    extract_psc_chapters_from_url,
    id3,
    transport,
)
from podcast_chapter_tools.cli import _extract, main

DESCRIPTION = """0:00 Intro
5:10 Main topic
1:02:02 Outro
"""


@pytest.fixture
def description_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text(DESCRIPTION)
    return path


def test_from_description_to_pci(description_file, capsys):
    assert main(["from-description", str(description_file)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [c["startTime"] for c in doc["chapters"]] == [0, 310, 3722]


def test_from_description_to_psc(description_file, capsys):
    assert main(["from-description", str(description_file), "--to", "psc"]) == 0
    out = capsys.readouterr().out
    assert "psc:chapter" in out
    assert 'title="Main topic"' in out


def test_from_description_to_description(description_file, capsys):
    assert main(["from-description", str(description_file), "--to", "description"]) == 0
    assert "5:10 Main topic" in capsys.readouterr().out


def test_from_psc(feed_file, capsys):
    assert main(["from-psc", str(feed_file), "--guid", "guid-1"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["chapters"][0] == {"startTime": 0, "title": "Intro"}


def test_from_psc_url(monkeypatch, capsys):
    captured = {}

    def fake_from_url(feed, **kwargs):
        captured["feed"] = feed
        return FakeResponse(text=FEED_XML)

    monkeypatch.setattr(transport.httpx2, "get", fake_from_url)
    args = [
        "from-psc",
        "https://example.com/feed.xml",
        "--guid",
        "guid-1",
        "--to",
        "psc",
    ]
    assert main(args) == 0
    assert captured == {"feed": "https://example.com/feed.xml"}
    assert 'title="Main topic"' in capsys.readouterr().out


def test_from_pci_url(monkeypatch, capsys):
    captured = {}

    def fake_get(source, **kwargs):
        captured["source"] = source
        return FakeResponse(
            json_data={
                "chapters": [
                    {"startTime": 0, "title": "Intro"},
                    {"startTime": 310, "title": "Main topic"},
                ]
            }
        )

    monkeypatch.setattr(transport.httpx2, "get", fake_get)
    assert main(["from-pci", "https://example.com/chapters.json"]) == 0
    assert captured == {"source": "https://example.com/chapters.json"}
    assert "startTime" in capsys.readouterr().out


def test_extract_unknown_command_returns_none():
    args = argparse.Namespace(command="from-nowhere")
    assert _extract(args) is None


def test_from_pci_file(pci_json, tmp_path, capsys):
    source = tmp_path / "chapters.json"
    source.write_text(json.dumps(pci_json))
    assert main(["from-pci", str(source), "--to", "description"]) == 0
    assert "5:10 Main topic" in capsys.readouterr().out


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-32"])
def test_from_pci_file_detects_json_encoding(encoding, tmp_path, capsys):
    source = tmp_path / "chapters.json"
    source.write_bytes(
        json.dumps(
            {"chapters": [{"startTime": 0, "title": "Café"}]}, ensure_ascii=False
        ).encode(encoding)
    )
    assert main(["from-pci", str(source), "--to", "description"]) == 0
    assert capsys.readouterr().out == "0:00 Café\n"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-32"])
def test_from_pci_file_bad_json_returns_error(tmp_path, capsys, encoding):
    source = tmp_path / "chapters.json"
    source.write_bytes("{".encode(encoding))
    assert main(["from-pci", str(source)]) == 1
    assert "Expecting" in capsys.readouterr().err


def test_from_pci_file_invalid_utf8_returns_error(tmp_path, capsys):
    source = tmp_path / "chapters.json"
    source.write_bytes(b"\xff")
    assert main(["from-pci", str(source)]) == 1
    assert "utf-8" in capsys.readouterr().err


def test_from_id3_missing_optional_dependency(tmp_path, monkeypatch, capsys):
    source = tmp_path / "episode.mp3"
    source.write_bytes(b"\x00" * 128)
    monkeypatch.setattr(id3, "_id3", None)

    assert main(["from-id3", str(source)]) == 1
    assert "mutagen is required" in capsys.readouterr().err


def test_output_file(description_file, tmp_path):
    out_path = tmp_path / "chapters.json"
    assert main(["from-description", str(description_file), "-o", str(out_path)]) == 0
    assert json.loads(out_path.read_text())["version"] == "1.2.0"


def test_no_chapters_found(tmp_path, capsys):
    empty = tmp_path / "empty.txt"
    empty.write_text("no chapters here")
    assert main(["from-description", str(empty)]) == 1
    assert "No chapters found" in capsys.readouterr().err


def test_normalize_flag(tmp_path, capsys):
    notes = tmp_path / "notes.txt"
    notes.write_text("5:00 <b>Second</b>\n0:00 First\n")
    assert main(["from-description", str(notes), "--normalize"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [c["title"] for c in doc["chapters"]] == ["First", "Second"]


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_module_entrypoint(description_file, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["podcast-chapters", "from-description", str(description_file)],
    )
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("podcast_chapter_tools.cli", run_name="__main__")
    assert exc_info.value.code == 0


def test_inline_description_requires_explicit_cli_mode(tmp_path, capsys):
    path = tmp_path / "notes.txt"
    path.write_text("<p>0:00 Intro 5:00 Main 10:00 End</p>")
    assert main(["from-description", str(path)]) == 1
    assert "No chapters found" in capsys.readouterr().err
    assert main(["from-description", str(path), "--description-mode", "lenient"]) == 0
    assert len(json.loads(capsys.readouterr().out)["chapters"]) == 3


def test_rich_pci_cli_preserves_metadata_and_reports_recovery(tmp_path, capsys):
    path = tmp_path / "chapters.json"
    path.write_text(
        json.dumps(
            {
                "chapters": [
                    {"startTime": 0.5, "title": "Good", "endTime": 60.75},
                    {"startTime": 60.75, "toc": False},
                    {"startTime": "bad"},
                ]
            }
        )
    )
    assert main(["from-pci", str(path)]) == 0
    output = capsys.readouterr()
    entries = json.loads(output.out)["chapters"]
    assert entries == [
        {"startTime": 0.5, "title": "Good", "endTime": 60.75},
        {"startTime": 60.75, "toc": False},
    ]
    assert str(path) in output.err
    assert "entry=2" in output.err
    assert "field=startTime" in output.err


def test_cli_distinguishes_http_failure_from_absence(monkeypatch, capsys):
    monkeypatch.setattr(
        transport.httpx2,
        "get",
        lambda *a, **kw: FakeResponse(is_success=False, status_code=404),
    )
    assert main(["from-pci", "https://example.com/chapters.json"]) == 1
    error = capsys.readouterr().err
    assert "ChapterHTTPError" in error
    assert "404" in error
    assert "No chapters found" not in error


def test_cli_reports_failed_entry_with_episode_context(tmp_path, capsys):
    path = tmp_path / "feed.xml"
    path.write_text(
        '<rss xmlns:psc="http://podlove.org/simple-chapters"><channel><item><guid>bad</guid><psc:chapters><psc:chapter start="infinity" title="Broken"/></psc:chapters></item></channel></rss>'
    )
    assert main(["from-psc", str(path), "--guid", "bad"]) == 1
    error = capsys.readouterr().err
    assert "ChapterParseError" in error
    assert str(path) in error
    assert "GUID=bad" in error
    assert "entry=0" in error
    assert "field=start" in error
    assert "No chapters found" not in error


def test_feed_adapters_respect_xml_encoding(tmp_path, monkeypatch, capsys):
    xml = '<?xml version="1.0" encoding="iso-8859-1"?><rss xmlns:psc="http://podlove.org/simple-chapters"><channel><item><guid>g</guid><psc:chapters><psc:chapter start="0" title="Caf\u00e9"/></psc:chapters></item></channel></rss>'.encode(
        "iso-8859-1"
    )
    path = tmp_path / "feed.xml"
    path.write_bytes(xml)
    assert extract_psc_chapters_from_file(path, "g")[0].title == "Caf\u00e9"
    assert main(["from-psc", str(path), "--guid", "g"]) == 0
    assert json.loads(capsys.readouterr().out)["chapters"][0]["title"] == "Caf\u00e9"
    url = "https://example.com/feed.xml"
    response = httpx2.Response(200, content=xml, request=httpx2.Request("GET", url))
    monkeypatch.setattr(transport.httpx2, "get", lambda *a, **kw: response)
    assert extract_psc_chapters_from_url(url, "g")[0].title == "Caf\u00e9"
    assert main(["from-psc", url, "--guid", "g"]) == 0
    assert json.loads(capsys.readouterr().out)["chapters"][0]["title"] == "Caf\u00e9"
