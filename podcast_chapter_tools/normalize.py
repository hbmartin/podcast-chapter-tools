"""Validation and normalization helpers for extracted chapters."""

import html
from collections.abc import Iterable

from .entities import Chapter, _re_html_tag


def strip_html(text: str) -> str:
    """Remove HTML tags and unescape entities, collapsing extra whitespace."""
    return " ".join(html.unescape(_re_html_tag.sub(" ", text)).split())


def normalize_chapters(
    chapters: Iterable[Chapter],
    *,
    sort: bool = True,
    dedupe: bool = True,
    max_start: int | None = None,
    strip_titles: bool = False,
) -> list[Chapter]:
    """Clean up a chapter list.

    - ``sort``: order chapters by start time.
    - ``dedupe``: drop chapters that repeat an earlier start time.
    - ``max_start``: drop chapters starting after this many seconds
      (e.g. the episode duration).
    - ``strip_titles``: remove HTML markup from titles.
    """
    cleaned: list[Chapter] = []
    seen_starts: set[int] = set()
    for chapter in chapters:
        chapter_ = Chapter(*chapter)
        if chapter_.start < 0:
            continue
        if max_start is not None and chapter_.start > max_start:
            continue
        if dedupe and chapter_.start in seen_starts:
            continue
        seen_starts.add(chapter_.start)
        if strip_titles:
            chapter_ = chapter_._replace(title=strip_html(chapter_.title))
        cleaned.append(chapter_)
    if sort:
        cleaned.sort(key=lambda c: c.start)
    return cleaned
