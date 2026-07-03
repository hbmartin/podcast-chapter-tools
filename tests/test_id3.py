from pathlib import Path

import pytest

mutagen_id3 = pytest.importorskip("mutagen.id3")

from podcast_chapter_tools.id3 import extract_id3_chapters  # noqa: E402


@pytest.fixture
def mp3_with_chapters(tmp_path: Path) -> Path:
    path = tmp_path / "episode.mp3"
    path.write_bytes(b"\x00" * 128)

    tags = mutagen_id3.ID3()
    tags.add(
        mutagen_id3.CTOC(
            element_id="toc",
            flags=mutagen_id3.CTOCFlags.TOP_LEVEL | mutagen_id3.CTOCFlags.ORDERED,
            child_element_ids=["chp1", "chp2"],
            sub_frames=[],
        ),
    )
    tags.add(
        mutagen_id3.CHAP(
            element_id="chp2",
            start_time=310_000,
            end_time=600_000,
            sub_frames=[
                mutagen_id3.TIT2(encoding=3, text=["Main topic"]),
                mutagen_id3.WXXX(encoding=3, desc="", url="https://example.com/topic"),
            ],
        ),
    )
    tags.add(
        mutagen_id3.CHAP(
            element_id="chp1",
            start_time=0,
            end_time=310_000,
            sub_frames=[mutagen_id3.TIT2(encoding=3, text=["Intro"])],
        ),
    )
    tags.save(path)
    return path


def test_extract_id3_chapters(mp3_with_chapters):
    chapters = extract_id3_chapters(mp3_with_chapters)
    assert chapters == [
        (0, "Intro", None, None),
        (310, "Main topic", "https://example.com/topic", None),
    ]


def test_missing_file(tmp_path):
    assert extract_id3_chapters(tmp_path / "nope.mp3") is None


def test_file_without_id3(tmp_path):
    path = tmp_path / "raw.mp3"
    path.write_bytes(b"\x00" * 128)
    assert extract_id3_chapters(path) is None


def test_file_without_chap_frames(tmp_path):
    path = tmp_path / "tagged.mp3"
    path.write_bytes(b"\x00" * 128)
    tags = mutagen_id3.ID3()
    tags.add(mutagen_id3.TIT2(encoding=3, text=["Just a title"]))
    tags.save(path)
    assert extract_id3_chapters(path) is None
