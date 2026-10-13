"""Typed failures for parsing and fetching; missing chapters are not failures."""

from copy import deepcopy
from copyreg import dispatch_table
from dataclasses import dataclass
from functools import lru_cache, partial
from types import BuiltinFunctionType, MemberDescriptorType
from typing import TYPE_CHECKING, Any, Self, cast
from weakref import ReferenceType, ref

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

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
    native_presence: list[tuple[type, str, bool]]


@dataclass(frozen=True, slots=True)
class _NativePresence:  # garuff: ignore[GAC009] - Private positional registry records.
    """Identity-owned flags with no strong reference to their exception."""

    reference: ReferenceType[BaseException]
    fields: dict[tuple[type, str], bool]


_NATIVE_STATE: dict[int, _NativePresence] = {}


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


def _release_native(identity: int, reference: ReferenceType[BaseException]) -> None:
    """Remove only the registry entry belonging to this collected identity."""
    entry = _NATIVE_STATE.get(identity)
    if entry is not None and entry.reference is reference:
        del _NATIVE_STATE[identity]


def _native_fields(error: BaseException) -> dict[tuple[type, str], bool]:
    """Read presence flags by identity without invoking equality or hashing."""
    entry = _NATIVE_STATE.get(id(error))
    return entry.fields if entry is not None and entry.reference() is error else {}


def _record_native_none(
    error: BaseException, owner: type, name: str, *, present: bool | None
) -> None:
    """Track populated None, explicit deletion, or a cleared native override."""
    identity = id(error)
    fields = _native_fields(error)
    if present is None:
        fields.pop((owner, name), None)
        if not fields:
            _NATIVE_STATE.pop(identity, None)
        return
    if not fields:
        fields = {}
        _NATIVE_STATE[identity] = _NativePresence(
            ref(error, partial(_release_native, identity)), fields
        )
    fields[owner, name] = present


def _record_assignment(error: BaseException, name: str, value: object) -> None:
    """Track explicit None only after successful native descriptor assignment."""
    owner = _native_owner(type(error), name)
    if owner is not None:
        _record_native_none(error, owner, name, present=True if value is None else None)


def _capture_native_constructor(error: BaseException) -> None:
    """Distinguish native initialization from explicit filename assignments."""
    if not isinstance(error, OSError):
        return
    arguments = cast("tuple[object, ...]", OSError.__reduce__(error)[1])
    if not 2 <= len(arguments) <= 5:  # noqa: PLR2004 - OSError's native constructor arity.
        return
    native_values = [
        vars(OSError)[name].__get__(error, type(error))
        for name in ("errno", "strerror", "filename", "filename2")
    ]
    errno, strerror, _, _ = native_values
    if arguments[0] is not errno or arguments[1] is not strerror:
        return
    fields = _native_fields(error)
    candidates = [
        name
        for name, value in (("errno", errno), ("strerror", strerror))
        if value is None and (OSError, name) not in fields
    ]
    if not candidates:
        return
    # Native construction ignores None filenames, but populates errno/strerror.
    # Check plain native formatting without invoking user-defined str/repr hooks.
    plain = all(
        type(value) in {type(None), int, str, bytes, float, bool}
        for value in (*arguments, *native_values)
    )
    if plain and not _matches_native_format(error, arguments, fields):
        return
    for name in candidates:
        _record_native_none(error, OSError, name, present=True)


def _matches_native_format(
    error: OSError,
    arguments: tuple[object, ...],  # garuff: ignore[GAC005] - Native reduction tuple.
    fields: dict[tuple[type, str], bool],
) -> bool:
    """Confirm plain native initialization, including recorded field overrides."""
    probe = OSError(*arguments)
    for (owner, name), present in fields.items():
        descriptor = vars(owner)[name]
        if present:
            descriptor.__set__(probe, None)
        else:
            descriptor.__delete__(probe)
    return OSError.__str__(probe) == OSError.__str__(error)


def _error_state(error: BaseException) -> _ErrorState:
    """Capture native fields and either default or subclass-owned Python state."""
    custom_getter = type(error).__getstate__ is not object.__getstate__
    python_state = error.__getstate__() if custom_getter else error.__dict__
    recorded = _native_fields(error)
    presence: list[tuple[type, str, bool]] = []
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
                if native:
                    if (owner, name) in recorded:
                        presence.append((owner, name, recorded[owner, name]))
                    if value is None and not recorded.get((owner, name), False):
                        continue
                slots.append((owner, name, value))
    return _ErrorState(error.args, slots, python_state, presence)


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
    for owner, name, present in state.native_presence:
        _record_native_none(error, owner, name, present=present)
    for owner, name, value in state.slots:
        vars(owner)[name].__set__(error, value)
        if owner.__module__ == "builtins" and value is None:
            _record_native_none(error, owner, name, present=True)
    _apply_python_state(error, state.python_state)


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


def _copy_python_state(restored: object, state: object) -> None:
    """Apply standard copy state to the arbitrary object chosen by a reducer."""
    setter = getattr(restored, "__setstate__", None)
    if setter is not None:
        setter(state)
        return
    dictionary, slots = state, None
    if isinstance(state, tuple) and len(state) == _SLOT_STATE_LENGTH:
        dictionary, slots = state
    if dictionary is not None:
        vars(restored).update(cast("dict[str, object]", dictionary))
    if slots is not None:
        for name, value in cast("dict[str, object]", slots).items():
            setattr(restored, name, value)


def _copy_collection_items(
    restored: object, items: object, pairs: object, memo: dict[int, Any] | None
) -> None:
    """Populate optional iterable and mapping state using normal copy semantics."""
    target = cast("Any", restored)
    if items is not None:
        for item in cast("Iterable[object]", items):
            target.append(deepcopy(item, memo) if memo is not None else item)
    if pairs is not None:
        for key, value in cast("Iterable[tuple[object, object]]", pairs):
            copied_key = deepcopy(key, memo) if memo is not None else key
            copied_value = deepcopy(value, memo) if memo is not None else value
            target[copied_key] = copied_value


def _copy_reduction[E: BaseException](
    error: E, reduction: object, memo: dict[int, Any] | None
) -> E:
    """Apply a custom reducer with normal copy ordering and optional state updater."""
    if isinstance(reduction, str):
        return error
    factory, arguments, *optional = cast("tuple[Any, ...]", reduction)
    state, items, pairs, updater = [*optional, None, None, None, None][:4]
    if memo is not None:
        arguments = deepcopy(arguments, memo)
    restored = factory(*arguments)
    if memo is not None:
        memo[id(error)] = restored
    if state is not None:
        if memo is not None:
            state = deepcopy(state, memo)
        if updater is not None:
            updater(restored, state)
        else:
            _copy_python_state(restored, state)
    _copy_collection_items(restored, items, pairs, memo)
    return cast("E", restored)


def _copy_error[E: BaseException](error: E, memo: dict[int, Any] | None = None) -> E:
    """Honor custom reducers, otherwise memoize before copying cyclic state."""
    reducer = dispatch_table.get(type(error))
    if reducer is not None:
        return _copy_reduction(error, reducer(error), memo)
    if type(error).__reduce_ex__ is not object.__reduce_ex__ or type(
        error
    ).__reduce__ not in {ChapterParseError.__reduce__, ChapterFetchError.__reduce__}:
        return _copy_reduction(error, error.__reduce_ex__(4), memo)
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
