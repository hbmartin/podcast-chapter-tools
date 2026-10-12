import re
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import NamedTuple

PCI = "{https://podcastindex.org/namespace/1.0}"
PCI_LEGACY = (
    "{https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/1.0.md}"
)
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


@dataclass(frozen=True, slots=True)
class ChapterData:
    """A chapter or silent marker, retaining fractional time and PCI metadata."""

    start: float
    title: str | None = None
    url: str | None = None
    image: str | None = None
    end: float | None = None
    toc: bool = True


@dataclass(frozen=True, slots=True)
class ChapterIssue:
    """A recoverable validation issue; entry indexes are zero-based."""

    index: int | None
    field: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ChapterParseResult:
    """Successfully parsed chapters, possibly empty, with recovery diagnostics."""

    chapters: tuple[ChapterData, ...] = ()
    issues: tuple[ChapterIssue, ...] = ()
    source: str | None = None
    guid: str | None = None

    @property
    def diagnostics(self) -> tuple[ChapterIssue, ...]:
        """Validation diagnostics, also available through ``issues``."""
        return self.issues

    def to_legacy(self, *, include_non_toc: bool = False) -> list[Chapter]:
        """Convert to four-field chapters, truncating time and omitting metadata."""
        return [
            Chapter(int(c.start), c.title or "", c.url, c.image)
            for c in self.chapters
            if c.toc or include_non_toc
        ]


class ChapterType(StrEnum):
    AI = auto()
    DESCRIPTION = auto()
    GEMINI = auto()  # deprecated: use AI
    ID3 = auto()
    OPENAI = auto()  # deprecated: use AI
    PCI = auto()
    PSC = auto()
    SONNET = auto()  # deprecated: use AI


_re_url = re.compile(r"(?P<url>https?://[^\s\"'<>]+)", re.IGNORECASE)
