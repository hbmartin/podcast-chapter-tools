"""Typed failures for parsing and fetching; missing chapters are not failures."""

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from types import BuiltinFunctionType, MemberDescriptorType
from typing import TYPE_CHECKING, Any, Self, cast

if TYPE_CHECKING:
    from collections.abc import Callable

from .entities import ChapterIssue, ChapterParseResult

_SLOT_STATE_LENGTH = 2


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


# Reconstruction state is applied only after the new exception is memoized.
@dataclass(frozen=True, slots=True)
class _ErrorState:  # garuff: ignore[GAC009]
    """Arguments, descriptor state, and optional subclass-owned Python state."""

    # Exception arguments retain their immutable representation.
    args: tuple[object, ...]  # garuff: ignore[GAC005]
    slots: list[tuple[type, str, object]]
    python_state: object


@lru_cache(maxsize=128)
def _native_owner(cls: type[BaseException], name: str) -> type | None:
    """Find the actual native descriptor reached by normal attribute assignment."""
    for owner in cls.__mro__:
        if name in vars(owner):
            descriptor = vars(owner)[name]
            if owner.__module__ == "builtins" and isinstance(
                descriptor, MemberDescriptorType
            ):
                return owner
            return None
    return None


def _record_native_none(
    error: BaseException, owner: type, name: str, *, present: bool
) -> None:
    """Remember explicit native None fields without changing ordinary error state."""
    dictionary = object.__getattribute__(error, "__dict__")
    key = (owner, name)
    if present:
        dictionary.setdefault("_chapter_native_none", set()).add(key)
    else:
        recorded = dictionary.get("_chapter_native_none")
        if recorded is not None:
            recorded.discard(key)
            if not recorded:
                dictionary.pop("_chapter_native_none")


def _record_assignment(error: BaseException, name: str, value: object) -> None:
    """Track explicit native None assignments after the descriptor succeeds."""
    owner = _native_owner(type(error), name)
    if owner is not None:
        _record_native_none(error, owner, name, present=value is None)


def _capture_native_constructor(error: BaseException) -> None:
    """Retain native filename presence before chapter initialization replaces args."""
    if isinstance(error, OSError):
        arguments = OSError.__reduce__(error)[1]
        for index, name in ((2, "filename"), (4, "filename2")):
            if len(arguments) > index and arguments[index] is None:
                _record_native_none(error, OSError, name, present=True)


def _error_state(error: BaseException) -> _ErrorState:
    """Capture native fields and either default or subclass-owned Python state."""
    custom_getter = type(error).__getstate__ is not object.__getstate__
    python_state = error.__getstate__() if custom_getter else error.__dict__
    recorded = error.__dict__.get("_chapter_native_none", ())
    slots: list[tuple[type, str, object]] = []
    for owner in type(error).__mro__:
        native = owner.__module__ == "builtins"
        if custom_getter and not native:
            continue
        for name, descriptor in vars(owner).items():
            if isinstance(descriptor, MemberDescriptorType):
                try:
                    value = descriptor.__get__(error, type(error))
                except AttributeError:
                    continue
                if native and value is None and (owner, name) not in recorded:
                    continue
                slots.append((owner, name, value))
    return _ErrorState(error.args, slots, python_state)


def _apply_python_state(error: BaseException, state: object) -> None:
    """Apply a custom setter or the standard dictionary/slot-dictionary state."""
    if state is None:
        return
    if type(error).__setstate__ is not BaseException.__setstate__:
        cast("Callable[[object], None]", error.__setstate__)(state)
        return
    dictionary, slots = state, None
    if isinstance(state, tuple) and len(state) == _SLOT_STATE_LENGTH:
        dictionary, slots = state
    if dictionary is not None:
        if not isinstance(dictionary, dict):
            msg = "Exception state is not a dictionary"
            raise TypeError(msg)
        BaseException.__setstate__(error, dictionary)
    if slots is not None:
        if not isinstance(slots, dict):
            msg = "Exception slot state is not a dictionary"
            raise TypeError(msg)
        for name, value in slots.items():
            setattr(error, name, value)


def _apply_error_state(error: BaseException, state: _ErrorState) -> None:
    """Restore memoized arguments and slots before invoking Python state hooks."""
    BaseException.__init__(error, *state.args)
    for owner, name, value in state.slots:
        vars(owner)[name].__set__(error, value)
        if owner.__module__ == "builtins" and value is None:
            _record_native_none(error, owner, name, present=True)
    _apply_python_state(error, state.python_state)
    # Presence records are internal; shallow copies must not share mutable flags.
    dictionary = object.__getattribute__(error, "__dict__")
    if "_chapter_native_none" in dictionary:
        dictionary["_chapter_native_none"] = set(dictionary["_chapter_native_none"])


def _error_reduction(
    error: BaseException,
) -> tuple[object, ...]:  # garuff: ignore[GAC005] - Pickle requires a protocol tuple.
    """Allocate first, then apply cyclic state through pickle's state updater."""
    return (
        _allocate_error,
        (type(error),),
        _error_state(error),
        None,
        None,
        _apply_error_state,
    )


def _copy_error[E: BaseException](error: E, memo: dict[int, Any] | None = None) -> E:
    """Copy exception state with deep-copy memoization before following cycles."""
    restored = _allocate_error(type(error))
    if memo is not None:
        memo[id(error)] = restored
    state = _error_state(error)
    if memo is not None:
        state = deepcopy(state, memo)
    _apply_error_state(restored, state)
    return restored


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
        _capture_native_constructor(self)
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

    def __copy__(self) -> Self:
        """Apply the same state contract during shallow copying."""
        return _copy_error(self)

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        """Memoize before following cyclic exception state during deep copying."""
        return _copy_error(self, memo)

    def __setattr__(self, name: str, value: object) -> None:
        """Record successful explicit assignments to native None fields."""
        super().__setattr__(name, value)
        _record_assignment(self, name, value)

    def __delattr__(self, name: str) -> None:
        """Clear native presence records only after successful deletion."""
        super().__delattr__(name)
        owner = _native_owner(type(self), name)
        if owner is not None:
            _record_native_none(self, owner, name, present=False)


class ChapterFetchError(Exception):
    """A request failed before a usable chapter document was obtained."""

    def __init__(self, message: str, *, url: str) -> None:
        """Retain the original message and the URL of the failed request."""
        _capture_native_constructor(self)
        self.message = message
        self.url = url
        super().__init__(f"{message} [{url}]")

    # Pickle reconstruction uses the immutable protocol tuple.
    def __reduce__(self) -> tuple[object, ...]:  # garuff: ignore[GAC005]
        """Describe pickle reconstruction with the original request URL."""
        return _error_reduction(self)

    def __copy__(self) -> Self:
        """Apply the same state contract during shallow copying."""
        return _copy_error(self)

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        """Memoize before following cyclic exception state during deep copying."""
        return _copy_error(self, memo)

    def __setattr__(self, name: str, value: object) -> None:
        """Record successful explicit assignments to native None fields."""
        super().__setattr__(name, value)
        _record_assignment(self, name, value)

    def __delattr__(self, name: str) -> None:
        """Clear native presence records only after successful deletion."""
        super().__delattr__(name)
        owner = _native_owner(type(self), name)
        if owner is not None:
            _record_native_none(self, owner, name, present=False)


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
