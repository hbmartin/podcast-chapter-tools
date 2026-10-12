"""Typed failures for parsing and fetching; missing chapters are not failures."""

from functools import partial

from .entities import ChapterIssue, ChapterParseResult


class ChapterParseError(ValueError):
    """An invalid document or a strict-validation failure."""

    def __init__(
        self,
        message: str,
        *,
        # Diagnostics retain the immutable public result representation.
        issues: tuple[ChapterIssue, ...] = (),  # garuff: ignore[GAC005]
        source: str | None = None,
        guid: str | None = None,
    ) -> None:
        """Retain parse diagnostics and add source context to the message."""
        self.message = message
        self.issues = issues
        self.source = source
        self.guid = guid
        context = f" [{source or 'input'}; GUID={guid or '-'}]"
        super().__init__(message + context)

    # Pickle reconstruction uses the immutable protocol tuple.
    def __reduce__(self) -> tuple[object, ...]:  # garuff: ignore[GAC005]
        """Describe pickle reconstruction with the original parse context."""
        return (
            partial(type(self), issues=self.issues, source=self.source, guid=self.guid),
            (self.message,),
            self.__dict__,
        )


class ChapterFetchError(Exception):
    """A request failed before a usable chapter document was obtained."""

    def __init__(self, message: str, *, url: str) -> None:
        """Retain the original message and the URL of the failed request."""
        self.message = message
        self.url = url
        super().__init__(f"{message} [{url}]")

    # Pickle reconstruction uses the immutable protocol tuple.
    def __reduce__(self) -> tuple[object, ...]:  # garuff: ignore[GAC005]
        """Describe pickle reconstruction with the original request URL."""
        return (partial(type(self), url=self.url), (self.message,), self.__dict__)


class ChapterHTTPError(ChapterFetchError):
    """An unsuccessful HTTP response, with retry information preserved."""

    def __init__(
        self, *, url: str, status_code: int, retry_after: str | None = None
    ) -> None:
        """Retain the HTTP status, URL, and optional retry header."""
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(f"HTTP {status_code}", url=url)

    # Pickle reconstruction uses the immutable protocol tuple.
    def __reduce__(self) -> tuple[object, ...]:  # garuff: ignore[GAC005]
        """Describe pickle reconstruction with HTTP and retry context."""
        return (
            partial(
                type(self),
                url=self.url,
                status_code=self.status_code,
                retry_after=self.retry_after,
            ),
            (),
            self.__dict__,
        )


class ChapterTransportError(ChapterFetchError):
    """A connection, timeout, or other HTTP transport failure."""


def _validate_result(
    result: ChapterParseResult, *, strict: bool = False, unusable: bool = False
) -> ChapterParseResult:
    """Reject unusable results or strict-mode diagnostics with context."""
    if unusable or (strict and result.issues):
        msg = "Invalid chapter entries"
        raise ChapterParseError(
            msg, issues=result.issues, source=result.source, guid=result.guid
        )
    return result
