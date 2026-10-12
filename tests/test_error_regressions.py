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
