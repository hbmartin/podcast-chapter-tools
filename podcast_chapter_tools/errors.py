"""Typed failures for parsing and fetching; missing chapters are not failures."""

from copy import deepcopy
from copyreg import dispatch_table
from dataclasses import dataclass
from functools import lru_cache, partial
from types import BuiltinFunctionType, MemberDescriptorType
from typing import TYPE_CHECKING, Any, Literal, Self, cast
from weakref import ReferenceType, ref

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

from .entities import ChapterIssue, ChapterParseResult

_SLOT_STATE_LENGTH = 2
_NATIVE_MIN_ARGS = 2
_NATIVE_NAMES = ("errno", "strerror", "filename", "filename2") + (
    ("winerror",) if "winerror" in vars(OSError) else ()
)
_PLAIN_NATIVE = frozenset({type(None), int, str, bytes, float, bool})
type _PresenceOrigin = Literal["assigned", "deleted", "constructor"]


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
    native_presence: list[tuple[type, str, bool, _PresenceOrigin]]


@dataclass(slots=True)
class _NativePresence:  # garuff: ignore[GAC009] - Private positional registry records.
    """Identity-owned flags with no strong reference to their exception."""

    reference: ReferenceType[BaseException]
    fields: dict[tuple[type, str], bool]
    origins: dict[tuple[type, str], _PresenceOrigin]
    arguments: int
    values: list[int]


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


def _native_values(error: OSError) -> list[object]:
    """Read native descriptors directly without user formatting or dispatch."""
    return [vars(OSError)[name].__get__(error, type(error)) for name in _NATIVE_NAMES]


def _native_entry(error: BaseException) -> _NativePresence:
    """Create identity bookkeeping containing no strong reference to state values."""
    identity = id(error)
    entry = _NATIVE_STATE.get(identity)
    if entry is None or entry.reference() is not error:
        entry = _NativePresence(
            ref(error, partial(_release_native, identity)), {}, {}, 0, []
        )
        _NATIVE_STATE[identity] = entry
    return entry


def _observe_native(error: BaseException) -> None:
    """Checkpoint a successfully observed native mutation or argument assignment."""
    if isinstance(error, OSError):
        entry = _native_entry(error)
        entry.arguments = id(error.args)
        entry.values = [id(value) for value in _native_values(error)]


def _record_native_none(
    error: BaseException,
    owner: type,
    name: str,
    *,
    present: bool | None,
    origin: _PresenceOrigin = "assigned",
) -> None:
    """Record established presence and provenance, or discard uncertain evidence."""
    entry = _native_entry(error)
    key = owner, name
    if present is None:
        entry.fields.pop(key, None)
        entry.origins.pop(key, None)
    else:
        entry.fields[key] = present
        entry.origins[key] = origin


def _record_assignment(error: BaseException, name: str, value: object) -> None:  # noqa: ARG001 - Presence is independent of the assigned value.
    """Record all successful native writes, including non-None assignments."""
    owner = _native_owner(type(error), name)
    if owner is not None:
        _record_native_none(error, owner, name, present=True)


def _capture_native_constructor(error: BaseException) -> None:
    """Verify only unambiguous primitive constructor state at portable checkpoints."""
    if not isinstance(error, OSError):
        return
    values = _native_values(error)
    entry = _native_entry(error)
    if entry.arguments and (
        entry.arguments != id(error.args)
        or entry.values != [id(value) for value in values]
    ):
        # Constructor inference depends on the observed checkpoint. Explicit writes
        # remain independent unless a changed descriptor proves they were overwritten.
        for key, origin in list(entry.origins.items()):
            owner, name = key
            changed = owner is OSError and entry.values[
                _NATIVE_NAMES.index(name)
            ] != id(values[_NATIVE_NAMES.index(name)])
            if origin != "assigned" or changed:
                entry.fields.pop(key, None)
                entry.origins.pop(key, None)
    for name, value in zip(_NATIVE_NAMES, values, strict=True):
        if value is not None and entry.fields.get((OSError, name)) is False:
            _record_native_none(error, OSError, name, present=None)
    candidates = [
        name
        for name, value in zip(_NATIVE_NAMES[:2], values[:2], strict=True)
        if value is None and (OSError, name) not in entry.fields
    ]
    if not candidates:
        _observe_native(error)
        return
    arguments = error.args
    # A multi-argument fallback renders as a tuple, never as a native message.
    # Single arguments can collide with native messages; opaque values can run hooks.
    safe = (
        len(arguments) >= _NATIVE_MIN_ARGS
        and all(type(value) in _PLAIN_NATIVE for value in (*arguments, *values))
        and all(value is None for value in values[2:])
        and not any(entry.fields.get((OSError, name)) for name in _NATIVE_NAMES[2:])
        and not any(
            entry.fields.get((OSError, name)) is False for name in _NATIVE_NAMES[:2]
        )
    )
    if safe and _matches_native_format(error):
        for name in candidates:
            _record_native_none(
                error, OSError, name, present=True, origin="constructor"
            )
    _observe_native(error)


def _matches_native_format(error: OSError) -> bool:
    """Distinguish native fields from the unambiguous primitive tuple fallback."""
    return OSError.__str__(error) != BaseException.__str__(error)


def _set_error_attribute(
    error: BaseException,
    name: str,
    value: object,
    setter: "Callable[[str, object], None]",
) -> None:
    """Capture before a normal write and checkpoint only after it succeeds."""
    tracked = name == "args" or _native_owner(type(error), name) is not None
    if tracked:
        _capture_native_constructor(error)
    setter(name, value)
    _record_assignment(error, name, value)
    if tracked:
        _observe_native(error)


def _delete_error_attribute(
    error: BaseException, name: str, deleter: "Callable[[str], None]"
) -> None:
    """Record native deletion after successful normal descriptor dispatch."""
    owner = _native_owner(type(error), name)
    if name == "args" or owner is not None:
        _capture_native_constructor(error)
    deleter(name)
    if owner is not None:
        _record_native_none(error, owner, name, present=False, origin="deleted")
        _observe_native(error)


def _error_state(error: BaseException) -> _ErrorState:
    """Capture native fields and either default or subclass-owned Python state."""
    custom_getter = type(error).__getstate__ is not object.__getstate__
    python_state = error.__getstate__() if custom_getter else error.__dict__
    _capture_native_constructor(error)
    recorded = _native_fields(error)
    presence: list[tuple[type, str, bool, _PresenceOrigin]] = []
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
                        presence.append(
                            (
                                owner,
                                name,
                                recorded[owner, name],
                                _native_entry(error).origins[owner, name],
                            )
                        )
                    if value is None and not recorded.get((owner, name), False):
                        continue
                slots.append((owner, name, value))
    return _ErrorState(error.args, slots, python_state, presence)


def _state_parts(
    state: object,
) -> tuple[object, object]:  # garuff: ignore[GAC005] - Reconstruction state pair.
    """Unpack the shared dictionary and optional slot-dictionary convention."""
    return (
        state
        if isinstance(state, tuple) and len(state) == _SLOT_STATE_LENGTH
        else (state, None)
    )


def _assign_slots(restored: object, slots: dict[str, object]) -> None:
    """Apply standard named Python-slot state through normal attribute dispatch."""
    for name, value in slots.items():
        setattr(restored, name, value)


def _apply_python_state(error: BaseException, state: object) -> None:
    """Apply a custom setter or the standard dictionary/slot-dictionary state."""
    if state is None:
        return
    if type(error).__setstate__ is not BaseException.__setstate__:
        cast("Callable[[object], None]", error.__setstate__)(state)
        return
    dictionary, slots = _state_parts(state)
    if dictionary is not None:
        if not isinstance(dictionary, dict):
            msg = "Exception state is not a dictionary"
            raise TypeError(msg)
        BaseException.__setstate__(error, dictionary)
    if slots is not None:
        if not isinstance(slots, dict):
            msg = "Exception slot state is not a dictionary"
            raise TypeError(msg)
        _assign_slots(error, slots)


def _apply_error_state(error: BaseException, state: _ErrorState) -> None:
    """Restore memoized arguments and slots before invoking Python state hooks."""
    BaseException.__init__(error, *state.args)
    for owner, name, present, origin in state.native_presence:
        _record_native_none(error, owner, name, present=present, origin=origin)
    for owner, name, value in state.slots:
        vars(owner)[name].__set__(error, value)
        if (
            owner.__module__ == "builtins"
            and value is None
            and (owner, name) not in _native_fields(error)
        ):
            _record_native_none(error, owner, name, present=True)
    _observe_native(error)
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
    dictionary, slots = _state_parts(state)
    if dictionary is not None:
        vars(restored).update(cast("dict[str, object]", dictionary))
    if slots is not None:
        _assign_slots(restored, cast("dict[str, object]", slots))


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
        _capture_native_constructor(self)

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
        _set_error_attribute(self, name, value, super().__setattr__)

    def __delattr__(self, name: str) -> None:
        """Clear native presence records only after successful deletion."""
        _delete_error_attribute(self, name, super().__delattr__)


class ChapterFetchError(Exception):
    """A request failed before a usable chapter document was obtained."""

    def __init__(self, message: str, *, url: str) -> None:
        """Retain the original message and the URL of the failed request."""
        _capture_native_constructor(self)
        self.message = message
        self.url = url
        super().__init__(f"{message} [{url}]")
        _capture_native_constructor(self)

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
        _set_error_attribute(self, name, value, super().__setattr__)

    def __delattr__(self, name: str) -> None:
        """Clear native presence records only after successful deletion."""
        _delete_error_attribute(self, name, super().__delattr__)


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
