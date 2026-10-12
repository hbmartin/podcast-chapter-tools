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


@pytest.mark.parametrize("kind", ["parse", "fetch", "http", "transport"])
def test_exception_pickle_preserves_type_message_and_context(kind):
    original = _error(kind)
    original.add_note("More context")
    restored = pickle.loads(pickle.dumps(original))  # noqa: S301 - round-trip a test-owned exception.
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
def test_custom_constructor_error_pickle_preserves_state(cls):
    original = cls(429, "custom failure")
    original.add_note("custom note")
    original.args = ("custom arguments", 7)
    restored = pickle.loads(pickle.dumps(original))  # noqa: S301 - test-owned exception.
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
