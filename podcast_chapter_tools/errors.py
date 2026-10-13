"""Typed failures for parsing and fetching; missing chapters are not failures."""

from types import BuiltinFunctionType, MemberDescriptorType

from .entities import ChapterIssue, ChapterParseResult


def _allocate_error[E: BaseException](cls: type[E]) -> E:
    """Allocate through a compatible built-in, bypassing subclass constructors."""
    for owner in cls.__mro__:
        allocator = vars(owner).get("__new__")
        if isinstance(allocator, BuiltinFunctionType) and issubclass(
            owner, BaseException
        ):
            try:
                return allocator(cls)
            except TypeError:
                continue
    msg = f"No compatible built-in exception allocator for {cls.__qualname__}"
    raise TypeError(msg)


def _restore_error[E: BaseException](
    cls: type[E],
    # Exception arguments retain their immutable pickle representation.
    args: tuple[object, ...],  # garuff: ignore[GAC005]
    slots: list[tuple[type, str, object]],
) -> E:
    """Restore exception state without invoking subclass constructors."""
    error = _allocate_error(cls)
    BaseException.__init__(error, *args)
    for owner, name, value in slots:
        vars(owner)[name].__set__(error, value)
    return error


def _error_reduction(
    error: BaseException,
) -> tuple[object, ...]:  # garuff: ignore[GAC005] - Pickle requires a protocol tuple.
    """Capture dictionary and declared slot state, including private slots."""
    slots: list[tuple[type, str, object]] = []
    for owner in type(error).__mro__:
        for name, descriptor in vars(owner).items():
            if isinstance(descriptor, MemberDescriptorType):
                try:
                    value = descriptor.__get__(error, type(error))
                except AttributeError:
                    continue
                # Unset native fields read as None; assigning it changes formatting.
                if value is None and owner.__module__ == "builtins":
                    continue
                slots.append((owner, name, value))
    return (_restore_error, (type(error), error.args, slots), error.__dict__)


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
        return _error_reduction(self)


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
        return _error_reduction(self)


class ChapterHTTPError(ChapterFetchError):
    """An unsuccessful HTTP response, with retry information preserved."""

    def __init__(
        self, *, url: str, status_code: int, retry_after: str | None = None
    ) -> None:
        """Retain the HTTP status, URL, and optional retry header."""
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(f"HTTP {status_code}", url=url)


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
