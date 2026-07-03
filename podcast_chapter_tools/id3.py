"""Extract chapters from ID3v2 CHAP/CTOC frames in MP3 files.

Requires the ``mutagen`` optional dependency::

    pip install podcast-chapter-tools[id3]
"""

import logging
from pathlib import Path
from typing import Any

from .entities import Chapter

logger = logging.getLogger(__name__)

_MS_PER_SEC = 1000

try:
    from mutagen import id3 as _id3
except ImportError:  # pragma: no cover - exercised only without the extra
    _id3 = None  # type: ignore[assignment]


def extract_id3_chapters(audio_file: Path) -> None | list[Chapter]:
    """Extract chapters from the ID3v2 CHAP frames of an MP3 file.

    Chapter order follows the CTOC (table of contents) frame when present,
    otherwise chapters are sorted by start time.
    """
    if _id3 is None:
        msg = (
            "mutagen is required for ID3 chapter extraction: "
            "pip install podcast-chapter-tools[id3]"
        )
        raise ImportError(msg)
    if not audio_file.exists():
        logger.error("File not found %s", audio_file)
        return None

    try:
        tags = _id3.ID3(audio_file)
    except _id3.ID3NoHeaderError:
        logger.info("No ID3 header in %s", audio_file)
        return None

    chap_frames = {frame.element_id: frame for frame in tags.getall("CHAP")}
    if not chap_frames:
        return None

    ordered_ids = _ctoc_order(tags, chap_frames)
    return [_chap_to_chapter(chap_frames[cid]) for cid in ordered_ids]


def _ctoc_order(tags: Any, chap_frames: dict[str, Any]) -> list[str]:  # noqa: ANN401
    sorted_ids = sorted(chap_frames, key=lambda cid: chap_frames[cid].start_time)
    for ctoc in tags.getall("CTOC"):
        child_ids = [cid for cid in ctoc.child_element_ids if cid in chap_frames]
        if child_ids:
            return child_ids + [cid for cid in sorted_ids if cid not in child_ids]
    return sorted_ids


def _chap_to_chapter(chap: Any) -> Chapter:  # noqa: ANN401
    title = None
    url = None
    for sub_frame in chap.sub_frames.values():
        frame_id = getattr(sub_frame, "FrameID", "")
        if frame_id == "TIT2":
            title = str(sub_frame.text[0]) if sub_frame.text else None
        elif frame_id in ("WXXX", "WOAR", "WORS"):
            url = sub_frame.url or url
    return Chapter(
        int(chap.start_time) // _MS_PER_SEC,
        title or chap.element_id,
        url,
        None,
    )
