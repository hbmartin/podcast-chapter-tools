import copy
import multiprocessing
import pickle
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from html import escape
from urllib.parse import quote

import pytest

from podcast_chapter_tools import (
    ChapterData,
    ChapterTransportError,
    errors,
    markup,
    parse_description_chapters,
)
from podcast_chapter_tools.normalize import strip_html
from podcast_chapter_tools.writers import chapters_to_description


@pytest.mark.parametrize("pending", ["script", "style"])
@pytest.mark.parametrize("raw", ["script", "style"])
def test_cached_recovered_raw_opening_does_not_hide_later_blocks(pending, raw):
    text = (
        f"00:00 Intro\n00:01 Part <{pending}\n>00:02 Next\n"
        f"<{raw}>.x{{}}</{raw}>\n00:03 Last\n00:04 End"
    )
    expected = [
        (0, "Intro"),
        (1, f"Part <{pending}"),
        (2, "Next"),
        (3, "Last"),
        (4, "End"),
    ]
    for prefix in ("", "<b\n>"):
        result = parse_description_chapters(
            prefix + text, strict=True, require_monotonic=True
        )
        assert [(c.start, c.title) for c in result.chapters] == expected


@pytest.mark.parametrize("pending", ["script", "style"])
@pytest.mark.parametrize("inline", ["i", "custom", 'a href="https://e.com"'])
def test_cached_recovered_region_retains_inline_balance_and_link(pending, inline):
    tag = inline.split()[0]
    text = (
        f"0:00 Intro\n0:30 Part <{pending}\n>1:00 Next <{inline}\n"
        f">2:00 Third</{tag}> tail\n3:00 End"
    )
    ordinary = parse_description_chapters(text).chapters
    cached = parse_description_chapters("<b\n>" + text).chapters
    assert cached == ordinary
    assert cached[2].title == "Next"
    assert cached[3].title == "Third tail"
    assert cached[3].url == ("https://e.com" if tag == "a" else None)


@pytest.mark.parametrize("boundary", ["<br>", "</p><p>", "&#10;", "&NewLine;"])
@pytest.mark.parametrize("tag", ["script", "style"])
def test_lookahead_uses_visible_boundaries_and_keeps_prose_raw_blocks(boundary, tag):
    text = (
        f"0:00 Intro{boundary}Join us at <{tag}\n>0:30 Hidden</{tag}>\n"
        "1:00 Next\n2:00 End"
    )
    for prefix in ("", "<unclosed\n>"):
        result = parse_description_chapters(
            prefix + text, strict=True, require_monotonic=True
        )
        assert [c.start for c in result.chapters] == [0, 60, 120]


@pytest.mark.parametrize("prefix", ["<p>", "<br>&gt;", "&#10;&gt;"])
def test_lookahead_recognizes_html_wrapped_raw_recovery(prefix):
    text = (
        f"0:00 Intro{prefix}0:30 Part <script\n>1:00 Next\n<style>x</style>\n2:00 End"
    )
    normal = parse_description_chapters(text).chapters
    cached = parse_description_chapters("<unclosed\n>" + text).chapters
    assert cached == normal
    assert [c.start for c in cached] == [0, 30, 60, 120]


@pytest.mark.parametrize(
    "comment",
    ["<!--<b>after", "<!-- <a href='x'>link</a> world", "<!-- <script>hidden"],
)
def test_unfinished_comment_keeps_remaining_text_literal(comment):
    text = "before" + comment
    assert strip_html(text) == text
    assert markup.inline_fragment(text) == text
    assert [
        line.text for line in markup.description_lines(text, recover_chapters=True)
    ] == [text]
    result = parse_description_chapters("0:00 " + text + "\n1:00 End")
    assert [c.title for c in result.chapters] == [text, "End"]


@pytest.mark.parametrize("quote_char", ["'", '"'])
@pytest.mark.parametrize("stripped", [False, True])
def test_quote_adjacent_to_tag_name_stays_literal(quote_char, stripped):
    title = f"if a<b{quote_char} and c{quote_char}> d"
    result = parse_description_chapters(f"0:00 {title}\n1:00 End", strip_html=stripped)
    assert [c.title for c in result.chapters] == [title, "End"]
    assert strip_html(title) == title
    assert markup.inline_fragment(title) == title


def test_formatted_terminator_cannot_complete_a_nested_malformed_tag():
    result = parse_description_chapters("0:00 if a<b x=<c\n>1:00 Next</b>\n2:00 End")
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, "if a<b x=<c"),
        (60, "Next"),
        (120, "End"),
    ]


class _NativeError(ChapterTransportError, OSError):
    pass


class _Opaque:
    def __repr__(self):
        pytest.fail("Serialization invoked opaque formatting")

    def __str__(self):  # noqa: PLE0307 - Formatting must fail if invoked.
        pytest.fail("Serialization invoked opaque formatting")


_OPERATIONS = [*range(pickle.HIGHEST_PROTOCOL + 1), "copy", "deepcopy"]


def _roundtrip(error, operation):
    if isinstance(operation, int):
        return pickle.loads(pickle.dumps(error, protocol=operation))  # noqa: S301 - Test-owned state.
    return copy.copy(error) if operation == "copy" else copy.deepcopy(error)


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize("native_init", [False, True])
def test_opaque_arguments_do_not_infer_unset_native_fields(operation, native_init):
    error = _NativeError("failure", url="u")
    if native_init:
        BaseException.__init__(error, None, {"k": 1})
    else:
        error.args = (None, {"k": 1})
    restored = _roundtrip(error, operation)
    assert str(restored) == str(error) == "(None, {'k': 1})"
    assert restored.args == error.args
    assert not errors._native_fields(restored)  # noqa: SLF001 - Distinguish absent from populated None.


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_opaque_formatters_never_run_for_unset_or_populated_native_state(operation):
    unset = _NativeError("failure", url="u")
    unset.args = (None, _Opaque())
    restored = _roundtrip(unset, operation)
    assert not errors._native_fields(restored)  # noqa: SLF001 - Opaque state cannot be formatted for comparison.
    populated = _NativeError("failure", url="u")
    OSError.__init__(populated, None, _Opaque())
    restored = _roundtrip(populated, operation)
    assert errors._native_fields(restored)[OSError, "errno"]  # noqa: SLF001 - Genuine native initialization has independent descriptor evidence.
    assert isinstance(restored.strerror, _Opaque)


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize("native", [(None, "m"), (2, None), (None, None)])
@pytest.mark.parametrize("assigned", [("x", "y", "z"), (None, {"k": 1})])
@pytest.mark.parametrize("early", [False, True])
def test_native_none_survives_args_reassignment(operation, native, assigned, early):
    if early:
        error = OSError.__new__(_NativeError)
        OSError.__init__(error, *native)
        ChapterTransportError.__init__(error, "failure", url="u")
    else:
        error = _NativeError("failure", url="u")
        OSError.__init__(error, *native)
    error.args = assigned
    error.add_note("note")
    restored = _roundtrip(error, operation)
    assert str(restored) == str(error)
    assert restored.args == assigned
    assert restored.__notes__ == ["note"]


class _GetterReassignsArgsError(_NativeError):
    def __getstate__(self):
        self.args = (None, {"k": 1})
        return self.__dict__


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_state_getter_reassignment_preserves_native_presence(operation):
    error = _GetterReassignsArgsError("failure", url="u")
    OSError.__init__(error, None, "m")
    restored = _roundtrip(error, operation)
    assert restored.args == error.args
    assert str(restored) == str(error) == "[Errno None] m"


def _raise_reassigned_native():
    error = _NativeError("failure", url="u")
    OSError.__init__(error, None, "m")
    error.args = ("x", "y", "z")
    raise error


def test_reassigned_native_worker_failure_preserves_type_and_pool():
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        with pytest.raises(_NativeError, match=r"\[Errno None\] m"):
            pool.submit(_raise_reassigned_native).result(timeout=20)
        assert pool.submit(abs, -3).result(timeout=20) == 3


@pytest.mark.parametrize(
    "whitespace", [" ", "\t", "\u00a0", "\u1680", "\u2003", "\u202f", "\u3000", "\x1f"]
)
@pytest.mark.parametrize("title_kind", ["absent", "raw", "rendered"])
def test_url_whitespace_is_encoded_and_retained_on_reparse(whitespace, title_kind):
    url = f"https://x.com/{whitespace}0:30{whitespace}Injected?a=1&b=%20"
    encoded = url.replace(whitespace, quote(whitespace, safe=""))
    safe = escape(encoded, quote=False)
    title = (
        "Intro"
        if title_kind == "absent"
        else "Intro " + (url if title_kind == "raw" else safe)
    )
    chapter = ChapterData(0, title, url)
    rendered = chapters_to_description([chapter, ChapterData(60, "End")])
    assert rendered == f"0:00 Intro {safe}\n1:00 End"
    for mode in ("strict", "lenient"):
        parsed = parse_description_chapters(rendered, mode=mode)
        assert [c.start for c in parsed.chapters] == [0, 60]
        assert parsed.chapters[0].url == encoded
    assert chapter.title == title
    assert chapter.url == url


def test_cached_raw_closing_materializes_once(monkeypatch):
    text = "<b\n>0:00 Intro<script>x</script></b>"
    cache = markup._TagCache(text, recover_chapters=True)  # noqa: SLF001 - Exercise cache consumption.
    assert cache.balanced(cache.token(0))
    calls = Counter()
    original = markup._TokenChunk.token  # noqa: SLF001 - Count materializations.

    def token(block, offset):
        calls[block.starts[offset]] += 1
        return original(block, offset)

    monkeypatch.setattr(markup._TokenChunk, "token", token)  # noqa: SLF001 - Private token instrumentation.
    start = text.index("<script>")
    cache.token(start)
    cache.raw_closing(start + len("<script>"), "script")
    assert calls == {start: 1, text.index("</script>"): 1}


def test_raw_absence_is_based_on_searched_range_not_global_eof():
    text = "<style>x</style>"
    cache = markup._TagCache(text, recover_chapters=True)  # noqa: SLF001 - Model a frontier with no relevant coverage.
    cache.cursor = len(text)
    closing = cache.raw_closing(len("<style>"), "style")
    assert closing is not None
    assert closing.start == text.index("</style>")
