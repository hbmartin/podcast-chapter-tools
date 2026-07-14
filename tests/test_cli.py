import argparse
import json
import runpy
import sys

import pytest

from podcast_chapter_tools import cli, id3
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

    def fake_from_url(feed, guid):
        captured["feed"] = feed
        captured["guid"] = guid
        return [(0, "Intro", None, None), (310, "Main topic", None, None)]

    monkeypatch.setattr(cli, "extract_psc_chapters_from_url", fake_from_url)
    args = ["from-psc", "https://example.com/feed.xml", "--guid", "g1", "--to", "psc"]
    assert main(args) == 0
    assert captured == {"feed": "https://example.com/feed.xml", "guid": "g1"}
    assert 'title="Main topic"' in capsys.readouterr().out


def test_from_pci_url(monkeypatch, capsys):
    captured = {}

    def fake_get(source):
        captured["source"] = source
        return [(0, "Intro", None, None), (310, "Main topic", None, None)]

    monkeypatch.setattr(cli, "get_and_extract_pci_chapters", fake_get)
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


def test_from_pci_file_bad_json_returns_error(tmp_path, capsys):
    source = tmp_path / "chapters.json"
    source.write_text("{")
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
