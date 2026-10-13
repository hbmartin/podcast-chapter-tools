import copy
import multiprocessing
import pickle
from concurrent.futures import ProcessPoolExecutor

import pytest

from podcast_chapter_tools import (
    ChapterFetchError,
    ChapterHTTPError,
    ChapterIssue,
    ChapterParseError,
    ChapterTransportError,
)


def _error(kind):
    if kind == "parse":
        return ChapterParseError(
            "Invalid",
            issues=(ChapterIssue(0, "start", "invalid_start", "Bad"),),
            source="feed",
            guid="g",
        )
    if kind == "http":
        return ChapterHTTPError(
            url="https://example.com", status_code=429, retry_after="60"
        )
    cls = ChapterTransportError if kind == "transport" else ChapterFetchError
    return cls("Failed", url="https://example.com")


def _raise_error(kind):
    raise _error(kind)


def _roundtrip(error, operation):
    if operation == "pickle":
        return pickle.loads(pickle.dumps(error))  # noqa: S301 - test-owned exception.
    return copy.copy(error) if operation == "copy" else copy.deepcopy(error)


@pytest.mark.parametrize("operation", ["pickle", "copy", "deepcopy"])
@pytest.mark.parametrize("kind", ["parse", "fetch", "http", "transport"])
def test_exception_pickle_preserves_type_message_and_context(kind, operation):
    original = _error(kind)
    original.add_note("More context")
    restored = _roundtrip(original, operation)
    assert type(restored) is type(original)
    assert str(restored) == str(original)
    assert restored.__dict__ == original.__dict__


@pytest.mark.parametrize("kind", ["parse", "fetch", "http", "transport"])
def test_worker_errors_leave_process_pool_usable(kind):
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        with pytest.raises(type(_error(kind))) as caught:
            pool.submit(_raise_error, kind).result(timeout=20)
        assert str(caught.value) == str(_error(kind))
        assert pool.submit(abs, -3).result(timeout=20) == 3


class _CustomParseError(ChapterParseError):
    __slots__ = ("__detail", "code", "unset")

    def __init__(self, code, detail):
        self.code = code
        self.__detail = detail
        super().__init__(detail, source="custom", guid="g")

    def detail(self):
        return self.__detail


class _CustomFetchError(ChapterFetchError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(detail, url="https://example.com")


class _CustomHTTPError(ChapterHTTPError):
    def __init__(self, code, detail):
        self.detail = detail
        super().__init__(url="https://example.com", status_code=code, retry_after="30")


class _CustomTransportError(ChapterTransportError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(detail, url="https://example.com")


@pytest.mark.parametrize(
    "cls",
    [_CustomParseError, _CustomFetchError, _CustomHTTPError, _CustomTransportError],
)
@pytest.mark.parametrize("operation", ["pickle", "copy", "deepcopy"])
def test_custom_constructor_error_pickle_preserves_state(cls, operation):
    original = cls(429, "custom failure")
    original.add_note("custom note")
    original.args = ("custom arguments", 7)
    restored = _roundtrip(original, operation)
    assert type(restored) is cls
    assert restored.args == original.args
    assert str(restored) == str(original)
    assert restored.__dict__ == original.__dict__
    if cls is _CustomParseError:
        assert restored.code == 429
        assert restored.detail() == "custom failure"
        assert not hasattr(restored, "unset")


def _raise_custom_error(cls):
    raise cls(429, "custom failure")


@pytest.mark.parametrize(
    "cls",
    [_CustomParseError, _CustomFetchError, _CustomHTTPError, _CustomTransportError],
)
def test_custom_worker_errors_leave_process_pool_usable(cls):
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        with pytest.raises(cls) as caught:
            pool.submit(_raise_custom_error, cls).result(timeout=20)
        assert str(caught.value) == str(cls(429, "custom failure"))
        assert pool.submit(abs, -3).result(timeout=20) == 3


class _OSErrorTransportError(ChapterTransportError, OSError):
    pass


class _TimeoutTransportError(ChapterTransportError, TimeoutError):
    pass


class _OSErrorParseError(ChapterParseError, OSError):
    pass


@pytest.mark.parametrize(
    "cls", [_OSErrorTransportError, _TimeoutTransportError, _OSErrorParseError]
)
@pytest.mark.parametrize("operation", ["pickle", "copy", "deepcopy"])
def test_native_exception_subclasses_roundtrip(cls, operation):
    kwargs = (
        {"source": "feed"} if cls is _OSErrorParseError else {"url": "https://e.com"}
    )
    original = cls("failure", **kwargs)
    original.errno = 110
    original.filename = "feed.xml"
    original.add_note("native context")
    restored = _roundtrip(original, operation)
    assert type(restored) is cls
    assert restored.args == original.args
    assert str(restored) == str(original)
    assert restored.__dict__ == original.__dict__
    assert restored.errno == 110
    assert restored.filename == "feed.xml"


class _SlottedTimeoutError(_TimeoutTransportError):
    __slots__ = ("__detail", "optional", "unset")

    def detail(self):
        return self.__detail


class _StatefulTimeoutError(_SlottedTimeoutError):
    __slots__ = ("code",)

    def __new__(cls, code, detail):
        assert code == 429
        return OSError.__new__(cls, detail)

    def __init__(self, code, detail):
        self.code = code
        self._SlottedTimeoutError__detail = detail
        self.optional = None
        super().__init__(detail, url="https://e.com")

    def __setstate__(self, state):
        assert self.code == 429
        assert self.detail() == "custom failure"
        self.__dict__.update(state)
        self.state_applied = True


@pytest.mark.parametrize("operation", ["pickle", "copy", "deepcopy"])
def test_custom_native_constructor_slots_and_state_hook(operation, monkeypatch):
    original = _StatefulTimeoutError(429, "custom failure")
    original.args = ("original arguments", 7)
    original.add_note("custom note")
    original.extra = {"labels": ["context"]}

    def forbidden_constructor(*args, **kwargs):
        pytest.fail("Reconstruction invoked a subclass constructor")

    monkeypatch.setattr(_StatefulTimeoutError, "__new__", forbidden_constructor)
    monkeypatch.setattr(_StatefulTimeoutError, "__init__", forbidden_constructor)
    restored = _roundtrip(original, operation)
    assert type(restored) is _StatefulTimeoutError
    assert restored.args == original.args
    assert restored.code == 429
    assert restored.detail() == "custom failure"
    assert restored.optional is None
    assert not hasattr(restored, "unset")
    assert restored.state_applied
    assert restored.__notes__ == original.__notes__
    assert restored.extra == original.extra
    if operation == "deepcopy":
        assert restored.extra is not original.extra


class _StateHookFetchError(ChapterFetchError):
    def __setstate__(self, state):
        self.__dict__.update(state)
        self.state_applied = True


@pytest.mark.parametrize("operation", ["pickle", "copy", "deepcopy"])
def test_exception_state_hook_is_applied(operation):
    original = _StateHookFetchError("failure", url="https://e.com")
    restored = _roundtrip(original, operation)
    assert restored.state_applied
    assert restored.url == original.url
    assert restored.message == original.message


def _raise_native_error(cls):
    if cls is _StatefulTimeoutError:
        raise cls(429, "custom failure")
    raise cls("failure", url="https://e.com")


@pytest.mark.parametrize(
    "cls", [_OSErrorTransportError, _TimeoutTransportError, _StatefulTimeoutError]
)
def test_native_worker_errors_leave_process_pool_usable(cls):
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        with pytest.raises(cls) as caught:
            pool.submit(_raise_native_error, cls).result(timeout=20)
        assert type(caught.value) is cls
        if cls is _StatefulTimeoutError:
            assert caught.value.code == 429
            assert caught.value.state_applied
        else:
            assert str(caught.value) == str(cls("failure", url="https://e.com"))
        assert pool.submit(abs, -3).result(timeout=20) == 3
