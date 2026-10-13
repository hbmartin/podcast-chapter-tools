# Private scanner/state regressions intentionally inspect internal contracts.
# ruff: noqa: SLF001

import copy
import multiprocessing
import pickle
from concurrent.futures import ProcessPoolExecutor

import pytest

from podcast_chapter_tools import (
    ChapterTransportError,
    errors,
    markup,
    parse_description_chapters,
)
from podcast_chapter_tools.normalize import strip_html


@pytest.mark.parametrize("raw", ["script", "style"])
def test_literal_tag_start_keeps_lookahead_context(raw):
    text = f"0:00 Intro\n< 0:30 Prose <{raw}\n>1:00 Hidden</{raw}>\n2:00 End"
    for prefix in ("", "<b\n>"):
        result = parse_description_chapters(prefix + text)
        assert [(c.start, c.title) for c in result.chapters] == [
            (0, "Intro"),
            (120, "End"),
        ]


@pytest.mark.parametrize("tag", ["img", "br", "b"])
def test_malformed_formatted_tag_preserves_literal_title(tag):
    result = parse_description_chapters(f"0:00 Intro <{tag} x=<y\n>1:00 Next\n2:00 End")
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, f"Intro <{tag} x=<y"),
        (60, "Next"),
        (120, "End"),
    ]


@pytest.mark.parametrize("quote", ["'", '"'])
def test_quote_adjacent_name_does_not_consume_later_tags(quote):
    text = f"before <b{quote} broken <i>visible</i>"
    assert strip_html(text) == f"before <b{quote} broken visible"
    text = f"0:00 before <b{quote}\n<script>\n1:00 Hidden\n</script>\n2:00 End"
    assert [(c.start, c.title) for c in parse_description_chapters(text).chapters] == [
        (0, f"before <b{quote}"),
        (120, "End"),
    ]


def test_cache_keeps_lexical_raw_opening():
    text = "<b\n>0:00 Intro <script\n>1:00 Next</script></b>"
    cache = markup._TagCache(text, recover_chapters=True)
    visible = markup._ChapterPrefix()
    source = markup._SourcePrefix()
    assert cache.balanced(cache.token(0), visible=visible, source=source)
    token = cache.token(text.index("<script"))
    assert token.complete
    assert text[token.end] == ">"
    assert token.cut == text.index("\n", token.start)


class _NativeError(ChapterTransportError, OSError):
    pass


_OPERATIONS = [*range(pickle.HIGHEST_PROTOCOL + 1), "copy", "deepcopy"]


def _roundtrip(error, operation):
    if isinstance(operation, int):
        return pickle.loads(pickle.dumps(error, protocol=operation))  # noqa: S301 - Test-owned exception state.
    return copy.copy(error) if operation == "copy" else copy.deepcopy(error)


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_explicit_non_none_is_not_constructor_evidence(operation):
    error = _NativeError("failure", url="u")
    error.strerror = "m"
    error.args = (None, "m", {"k": 1})
    restored = _roundtrip(error, operation)
    assert str(restored) == str(error) == "(None, 'm', {'k': 1})"
    assert not errors._native_fields(restored).get((OSError, "errno"))


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize("argument", [{"k": 1}, "[Errno None] None"])
def test_unobserved_reset_does_not_keep_constructor_presence(operation, argument):
    error = _NativeError("failure", url="u")
    OSError.__init__(error, None, None)
    error.args = ("saved",)
    OSError.__init__(error, argument)
    restored = _roundtrip(error, operation)
    assert restored.args == error.args
    assert str(restored) == str(error)
    error.strerror = "z"
    restored.strerror = "z"
    assert str(restored) == str(error)


class _Opaque:
    def __str__(self):  # noqa: PLE0307 - Hooks must never run in these regressions.
        pytest.fail("Serialization called user formatting")

    def __repr__(self):
        pytest.fail("Serialization called user formatting")


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_unknown_builtin_bypass_keeps_arguments_and_custom_state(operation):
    error = _NativeError("failure", url="u")
    OSError.__init__(error, None, "m")
    BaseException.__init__(error, None, _Opaque())
    error.extra = "custom"
    restored = _roundtrip(error, operation)
    assert restored.args[0] is None
    assert isinstance(restored.args[1], _Opaque)
    assert restored.strerror == "m"
    assert restored.extra == "custom"
    assert not errors._native_fields(restored).get((OSError, "errno"))


def _restore_known_native(cls, args, dictionary):
    error = OSError.__new__(cls)
    BaseException.__init__(error, *args)
    OSError.errno.__set__(error, None)
    OSError.strerror.__set__(error, "m")
    vars(error).update(dictionary)
    return error


class _CustomNativeReducerError(_NativeError):
    def __reduce__(self):
        return _restore_known_native, (type(self), self.args, vars(self))


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_custom_reducer_preserves_unobservable_native_presence(operation):
    error = _CustomNativeReducerError("failure", url="u")
    OSError.__init__(error, None, "m")
    BaseException.__init__(error, None, _Opaque())
    restored = _roundtrip(error, operation)
    assert isinstance(restored.args[1], _Opaque)
    assert vars(restored) == vars(error)
    error.strerror = "z"
    restored.strerror = "z"
    assert str(restored) == str(error) == "[Errno None] z"


@pytest.mark.parametrize(
    "entity",
    [
        "&#10;",
        "&#xA;",
        "&#00000000101;",
        "&NewLine;",
        "&NewLineX;",
        "&#13;",
        "&#x0000000d0;",
        "&#62;",
        "&nbsp;",
        "\u2028",
        "<",
    ],
)
def test_prefix_only_data_matches_normal_visible_and_source_events(entity):
    text = "prose " + entity + ">0:00 Chapter &amp; stuff\n"
    normal = markup._Lines(recover_chapters=True)
    context = markup._RecoveryContext(normal.line_context(), normal._source)
    normal.handle_data(text)
    context.data(text, 0, len(text))
    assert vars(context.visible) == vars(normal.line_context())
    assert vars(context.source.prefix) == vars(normal._source.prefix)
    assert not isinstance(context, markup.HTMLParser)
    assert not hasattr(context, "_spans")


def test_no_context_balance_does_not_create_leading_state():
    cache = markup._TagCache("<b\n>0:00 Text</b>", recover_chapters=True)
    assert cache.balanced(cache.token(0), visible=None, source=None)
    assert cache.context is None


def test_unfinished_raw_closing_cannot_balance_opening():
    cache = markup._TagCache("<script>x</script", recover_chapters=True)
    assert not cache.balanced(cache.token(0), visible=None, source=None)


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_explicit_presence_survives_unobserved_argument_only_change(operation):
    error = _NativeError("failure", url="u")
    error.errno = None
    error.strerror = "m"
    BaseException.__init__(error, None, _Opaque())
    restored = _roundtrip(error, operation)
    assert str(restored) == str(error) == "[Errno None] m"
    assert errors._native_fields(restored)[OSError, "errno"]


class _AttributeAuditError(Exception):
    def __setattr__(self, name, value):
        writes = vars(self).setdefault("writes", [])
        writes.append(name)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        vars(self).setdefault("deletes", []).append(name)
        super().__delattr__(name)


class _AuditedError(ChapterTransportError, _AttributeAuditError):
    pass


def test_shared_attribute_helpers_preserve_super_dispatch():
    error = _AuditedError("failure", url="u")
    error.custom = "value"
    del error.custom
    assert error.writes == ["message", "url", "custom"]
    assert error.deletes == ["custom"]


def test_formatted_lexical_token_retains_multiline_source_prefix():
    cache = markup._TagCache("<strong\n>0:00 Text", recover_chapters=True)
    token = cache.token(0)
    assert token.complete
    assert token.formatted
    assert token.multiline


@pytest.mark.parametrize("raw", ["script", "style"])
def test_literal_raw_opening_does_not_block_enclosing_anchor_balance(raw):
    text = (
        f'0:00 Old <a href="https://e.com"\n>0:30 Part <{raw}\n>1:00 Next</a>\n2:00 End'
    )
    result = parse_description_chapters(text)
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (0, "Old", None),
        (30, f"Part <{raw}", "https://e.com"),
        (60, "Next", "https://e.com"),
        (120, "End", None),
    ]


def _raise_portable_native_error(cls):
    error = cls("failure", url="u")
    OSError.__init__(error, None, "m")
    BaseException.__init__(error, None, _Opaque())
    raise error


@pytest.mark.parametrize("cls", [_NativeError, _CustomNativeReducerError])
def test_portable_opaque_worker_errors_leave_pool_usable(cls):
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        with pytest.raises(cls) as caught:
            pool.submit(_raise_portable_native_error, cls).result(timeout=20)
        assert isinstance(caught.value.args[1], _Opaque)
        assert caught.value.message == "failure"
        assert caught.value.url == "u"
        if cls is _CustomNativeReducerError:
            caught.value.strerror = "z"
            assert str(caught.value) == "[Errno None] z"
        assert pool.submit(abs, -3).result(timeout=20) == 3


@pytest.mark.parametrize("raw", ["script", "style"])
def test_consumed_malformed_raw_closing_retains_outer_balance(raw):
    text = f'0:00 Old <a href="https://e.com"\n>0:30 Part <{raw}>x</{raw} <b>> after</a>\n1:00 End'
    result = parse_description_chapters(text)
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (0, "Old", None),
        (30, "Part > after", "https://e.com"),
        (60, "End", None),
    ]


@pytest.mark.parametrize("raw", ["script", "style"])
def test_recovered_raw_closing_keeps_boundary_in_lookahead(raw):
    text = f"0:00 Intro\nprose <{raw}>x</{raw}\n0:30 Part <{raw}\n>1:00 Next <i\n>1:30 Third</i></{raw}>\n2:00 End"
    expected = [
        (0, "Intro"),
        (30, f"Part <{raw}"),
        (60, "Next"),
        (90, "Third"),
        (120, "End"),
    ]
    for prefix in ("", "<b\n>"):
        assert [
            (c.start, c.title)
            for c in parse_description_chapters(prefix + text).chapters
        ] == expected
