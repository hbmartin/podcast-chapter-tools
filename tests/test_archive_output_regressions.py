import json
import os
import stat
import subprocess
import sys
from unittest.mock import Mock

import httpx2
import pytest

from podcast_chapter_tools import (
    ChapterData,
    chapters_to_pci_json,
    fetch_pci_chapters,
    transport,
)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits and umask")
@pytest.mark.parametrize(("mask", "expected"), [("022", 0o644), ("077", 0o600)])
def test_new_archives_follow_umask(tmp_path, mask, expected):
    code = """
import os, stat, sys
from pathlib import Path
from unittest.mock import Mock
import httpx2
from podcast_chapter_tools import fetch_pci_chapters, transport
os.umask(int(sys.argv[2], 8))
path = Path(sys.argv[1])
transport.httpx2.get = Mock(return_value=httpx2.Response(200, json={'chapters': [{'startTime': 0, 'title': 'Intro'}]}))
fetch_pci_chapters('https://example.com', archive_path_json=path)
for file in (path, path.with_name(path.name + '.meta.json')):
    assert stat.S_IMODE(file.stat().st_mode) == int(sys.argv[3])
fetch_pci_chapters('https://example.com', archive_path_json=path)
assert transport.httpx2.get.call_count == 1
"""
    subprocess.run(  # noqa: S603 - isolate the process-global umask in a subprocess.
        [
            sys.executable,
            "-c",
            code,
            str(tmp_path / "chapters.json"),
            mask,
            str(expected),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
@pytest.mark.parametrize(
    ("archive_mode", "metadata_mode"), [(0o644, 0o640), (0o600, 0o600)]
)
def test_atomic_replacements_preserve_each_existing_file_mode(
    tmp_path, monkeypatch, archive_mode, metadata_mode
):
    path = tmp_path / "chapters.json"
    metadata = path.with_name(path.name + ".meta.json")
    path.write_text("invalid", encoding="utf-8")
    metadata.write_text("invalid", encoding="utf-8")
    path.chmod(archive_mode)
    metadata.chmod(metadata_mode)
    get = Mock(
        return_value=httpx2.Response(
            200, json={"chapters": [{"startTime": 0, "title": "Intro"}]}
        )
    )
    monkeypatch.setattr(transport.httpx2, "get", get)
    assert fetch_pci_chapters("https://example.com", archive_path_json=path).chapters
    assert stat.S_IMODE(path.stat().st_mode) == archive_mode
    assert stat.S_IMODE(metadata.stat().st_mode) == metadata_mode
    assert fetch_pci_chapters("https://example.com", archive_path_json=path).chapters
    assert get.call_count == 1


def test_integral_pci_times_use_json_integers_without_losing_fractions():
    doc = json.loads(
        chapters_to_pci_json(
            [
                ChapterData(0.0, "Intro", end=310.0),
                ChapterData(310.25, "Next", end=3722.5),
            ]
        )
    )
    first, second = doc["chapters"]
    assert type(first["startTime"]) is int
    assert type(first["endTime"]) is int
    assert second["startTime"] == 310.25
    assert second["endTime"] == 3722.5
    assert type(second["startTime"]) is float
    assert type(second["endTime"]) is float
