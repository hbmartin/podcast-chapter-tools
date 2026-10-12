"""Validation and normalization helpers for extracted chapters."""

import math
from collections.abc import Iterable
from dataclasses import replace

from .entities import Chapter, ChapterData
from .markup import plain_text


def strip_html(text: str) -> str:
    """Remove HTML tags and unescape entities, collapsing extra whitespace."""
    return plain_text(text)


def normalize_chapter_data(
    chapters: Iterable[ChapterData],
    *,
    sort: bool = True,
    dedupe: bool = True,
    max_start: float | None = None,
    strip_titles: bool = False,
) -> list[ChapterData]:
    """Sort/filter rich chapters without losing optional fields or fractions."""
    cleaned: list[ChapterData] = []
    seen: set[float] = set()
    for chapter in chapters:
        if not math.isfinite(chapter.start) or chapter.start < 0:
            continue
        if max_start is not None and chapter.start > max_start:
            continue
        if dedupe and chapter.start in seen:
            continue
        seen.add(chapter.start)
        cleaned_chapter = chapter
        if strip_titles and chapter.title is not None:
            cleaned_chapter = replace(chapter, title=strip_html(chapter.title))
        cleaned.append(cleaned_chapter)
    if sort:
        cleaned.sort(key=lambda c: c.start)
    return cleaned


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
