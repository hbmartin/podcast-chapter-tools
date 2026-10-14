# Private checkpoints and scanner events are intentional regression targets.
# ruff: noqa: SLF001

import copy
import gc
import multiprocessing
import pickle
import weakref
from concurrent.futures import ProcessPoolExecutor

import pytest

from podcast_chapter_tools import (
    ChapterParseError,
    ChapterTransportError,
    errors,
    markup,
    parse_description_chapters,
)

_SOFT_BREAKS = "\v\f\x1c\x1d\x1e\x85\u2028\u2029"
_OPERATIONS = [*range(pickle.HIGHEST_PROTOCOL + 1), "copy", "deepcopy"]


def _roundtrip(error, operation):
    if isinstance(operation, int):
        return pickle.loads(pickle.dumps(error, protocol=operation))  # noqa: S301 - Test-owned exception state.
    return copy.copy(error) if operation == "copy" else copy.deepcopy(error)


@pytest.mark.parametrize("separator", _SOFT_BREAKS)
def test_trailing_soft_separator_before_inline_tag_preserves_title(separator):
    text = f"0:00 A{separator}<b>B</b>\n1:00 Next"
    result = parse_description_chapters(text)
    assert [c.title for c in result.chapters] == [f"A{separator}<b>B</b>", "Next"]
    line = markup.description_lines(text, recover_chapters=True)[0]
    assert line.text == f"0:00 A{separator}B"
    assert line.raw[line.raw_start(7)] == "B"


@pytest.mark.parametrize("separator", _SOFT_BREAKS)
@pytest.mark.parametrize("suffix", ["", "0:30 Next", "<"])
def test_soft_separator_context_matches_normal_data_chunks(separator, suffix):
    normal = markup._Lines(recover_chapters=True)
    context = markup._RecoveryContext(normal.line_context(), normal._source)
    text = f"0:00 A{separator}{suffix}"
    normal.handle_data(text)
    context.data(text, 0, len(text))
    assert vars(context.visible) == vars(normal.line_context())
    assert vars(context.source.prefix) == vars(normal._source.prefix)
    if not suffix:
        assert normal.line_context().chapter


@pytest.mark.parametrize("quote", ["'", '"'])
@pytest.mark.parametrize("attribute", ["", "value=bare"])
def test_attribute_position_quotes_do_not_protect_terminators(quote, attribute):
    text = f"<b {attribute}{quote}x>0:00 Visible{quote}>"
    cache = markup._TagCache(text, recover_chapters=True)
    token = cache.token(0)
    assert token.end == text.index(">")
    normal = markup._Lines(recover_chapters=True)
    context = markup._RecoveryContext(normal.line_context(), normal._source)
    event = markup._recovery_event(
        token, context.visible, context.source, protected=False
    )
    context.consume(text, token, event)
    normal.feed(text[: token.end + 1])
    normal.close()
    context.data(text, token.end + 1, len(text))
    normal.handle_data(text[token.end + 1 :])
    assert vars(context.visible) == vars(normal.line_context())


@pytest.mark.parametrize("tag", ["b", "i", "custom"])
def test_literal_formatted_opening_does_not_block_outer_anchor(tag):
    text = (
        f'0:00 Old <a href="https://e.com"\n>0:30 Part <{tag}\n>1:00 Next</a>\n2:00 End'
    )
    assert [
        (c.start, c.title, c.url) for c in parse_description_chapters(text).chapters
    ] == [
        (0, "Old", None),
        (30, f"Part <{tag}", "https://e.com"),
        (60, "Next", "https://e.com"),
        (120, "End", None),
    ]


@pytest.mark.parametrize("raw", ["script", "style"])
def test_context_free_balance_consumes_recovered_raw_closing(raw):
    text = f"<b><{raw}>x</{raw}\n0:30 Next</b>"
    cache = markup._TagCache(text, recover_chapters=True)
    assert cache.balanced(cache.token(0), visible=None, source=None)


class _NativeError(ChapterTransportError, OSError):
    pass


class _ShadowArgsError(_NativeError):
    @property
    def args(self):
        pytest.fail("Bookkeeping called the subclass args getter")


class _ShadowParseArgsError(ChapterParseError, OSError):
    @property
    def args(self):
        pytest.fail("Bookkeeping called the subclass args getter")


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize("cls", [_ShadowArgsError, _ShadowParseArgsError])
def test_args_descriptor_bypasses_subclass_getter(operation, cls):
    error = cls("failure", **({"url": "u"} if cls is _ShadowArgsError else {}))
    restored = _roundtrip(error, operation)
    assert BaseException.args.__get__(restored) == BaseException.args.__get__(error)
    assert restored.message == "failure"


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_detectable_native_reset_clears_explicit_none_records(operation):
    error = _NativeError("failure", url="u")
    error.errno = None
    error.strerror = None
    OSError.__init__(error, "plain")
    restored = _roundtrip(error, operation)
    assert str(restored) == str(error) == "plain"
    assert not errors._native_fields(restored)


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_discarded_argument_tuples_cannot_hide_native_reset(operation):
    error = _NativeError("failure", url="u")
    error.errno = None
    error.strerror = None
    error.args = tuple(str(index) for index in range(1))
    for index in range(20):
        OSError.__init__(error, *(str(index + value) for value in range(1)))
    restored = _roundtrip(error, operation)
    assert str(restored) == str(error)
    assert not errors._native_fields(restored)


class _Opaque:
    __hash__ = None

    def __eq__(self, other):
        pytest.fail("Checkpoint called opaque equality")

    def __str__(self):  # noqa: PLE0307 - Hooks must never run.
        pytest.fail("Checkpoint called opaque formatting")

    def __repr__(self):
        pytest.fail("Checkpoint called opaque formatting")


class _UnweakValue:
    __slots__ = ("owner",)
    __hash__ = None

    def __eq__(self, other):
        pytest.fail("Checkpoint compared unweak opaque values")

    def __repr__(self):
        pytest.fail("Checkpoint formatted unweak opaque values")


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_normal_opaque_argument_changes_preserve_native_none(operation):
    error = _NativeError("failure", url="u")
    OSError.__init__(error, None, "m")
    error.args = (_Opaque(),)
    restored = _roundtrip(error, operation)
    assert str(restored) == str(error) == "[Errno None] m"
    assert isinstance(BaseException.args.__get__(restored)[0], _Opaque)


@pytest.mark.parametrize("cls", [_Opaque, _UnweakValue])
def test_checkpoint_does_not_retain_cyclic_custom_values(cls):
    error = _NativeError("failure", url="u")
    value = cls()
    value.owner = error
    error.args = (value,)
    identity = id(error)
    reference = weakref.ref(error)
    del error, value
    gc.collect()
    assert reference() is None
    assert identity not in errors._NATIVE_STATE


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize(
    "argument",
    [None, True, -257, 1 << 12000, float("nan"), b"bytes", "surrogate\ud800"],
    ids=["none", "bool", "negative", "large-int", "nan", "bytes", "surrogate"],
)
def test_primitive_checkpoints_preserve_normal_native_presence(operation, argument):
    error = _NativeError("failure", url="u")
    error.errno = None
    error.strerror = "m"
    error.args = (argument,)
    restored = _roundtrip(error, operation)
    assert str(restored) == str(error) == "[Errno None] m"


def test_unknown_witnesses_do_not_clear_reliable_presence():
    error = _NativeError("failure", url="u")
    error.errno = None
    error.strerror = "m"
    error.args = (_UnweakValue(),)
    assert str(copy.copy(error)) == "[Errno None] m"


def test_checkpoint_reads_large_text_and_bytes_in_bounded_chunks(monkeypatch):
    original = errors.sha256
    sizes = []

    class Digest:
        def __init__(self, data):
            self._digest = original(data)

        def update(self, data):
            sizes.append(len(data))
            self._digest.update(data)

        def digest(self):
            return self._digest.digest()

    monkeypatch.setattr(errors, "sha256", Digest)
    for value in ["\U0001f600" * 50000, b"x" * 200000, 1 << 200000, -(1 << 200000)]:
        assert errors._witness(value)
    assert max(sizes) <= 16 * 1024


def _raise_shadow_args_error():
    raise _ShadowArgsError("failure", url="u")


def test_shadow_args_worker_error_leaves_pool_usable():
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        with pytest.raises(_ShadowArgsError):
            pool.submit(_raise_shadow_args_error).result(timeout=20)
        assert pool.submit(abs, -3).result(timeout=20) == 3
