import re
from enum import StrEnum, auto
from typing import NamedTuple

PCI = "{https://podcastindex.org/namespace/1.0}"
PSC = "{http://podlove.org/simple-chapters}"


class Chapter(NamedTuple):
    """A single podcast chapter.

    Behaves like the legacy ``tuple[int, str, str | None, str | None]``
    (start time in seconds, title, optional URL, optional image URL) while
    allowing field access by name.
    """

    start: int
    title: str
    url: str | None = None
    image: str | None = None


class ChapterType(StrEnum):
    AI = auto()
    DESCRIPTION = auto()
    GEMINI = auto()  # deprecated: use AI
    ID3 = auto()
    OPENAI = auto()  # deprecated: use AI
    PCI = auto()
    PSC = auto()
    SONNET = auto()  # deprecated: use AI


_description_chapter = re.compile(
    pattern=r">?\s?[(\[]?(\d{0,2}:?\d{1,2}:\d{2})[\])]?[\s-]*([^\[(\n]+?)\s*(?:<|$)",
    flags=re.MULTILINE,
)

_retry_description_chapter = re.compile(
    pattern=r"(\d{0,2}:?\d{1,2}:\d{2})[\])]?[\s-]*([^\[(]+?)(?=\d{1,2}:|$)",
    flags=re.MULTILINE,
)

_re_url = re.compile(r"(?P<url>https?://[^\s\"'<>]+)", re.IGNORECASE)

_re_html_tag = re.compile(r"<[^>]+>")
