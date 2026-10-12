"""Typed failures for parsing and fetching; missing chapters are not failures."""

from .entities import ChapterIssue


class ChapterParseError(ValueError):
    """An invalid document or a strict-validation failure."""

    def __init__(
        self,
        message: str,
        *,
        issues: tuple[ChapterIssue, ...] = (),
        source: str | None = None,
        guid: str | None = None,
    ) -> None:
        self.issues = issues
        self.source = source
        self.guid = guid
        context = f" [{source or 'input'}; GUID={guid or '-'}]"
        super().__init__(message + context)


class ChapterFetchError(Exception):
    """A request failed before a usable chapter document was obtained."""

    def __init__(self, message: str, *, url: str) -> None:
        self.url = url
        super().__init__(f"{message} [{url}]")


class ChapterHTTPError(ChapterFetchError):
    """An unsuccessful HTTP response, with retry information preserved."""

    def __init__(
        self, *, url: str, status_code: int, retry_after: str | None = None
    ) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(f"HTTP {status_code}", url=url)


class ChapterTransportError(ChapterFetchError):
    """A connection, timeout, or other HTTP transport failure."""
