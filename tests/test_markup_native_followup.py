import copy
import copyreg
import gc
import json
import multiprocessing
import os
import pickle
import subprocess
import sys
import weakref
from concurrent.futures import ProcessPoolExecutor

import pytest

from podcast_chapter_tools import (
    ChapterData,
    ChapterTransportError,
    errors,
    markup,
    parse_description_chapters,
)
from podcast_chapter_tools.cli import main
from podcast_chapter_tools.writers import chapters_to_description


@pytest.mark.parametrize("mode", ["strict", "lenient"])
@pytest.mark.parametrize("suffix", ["", " -> proofs", " > proofs"])
@pytest.mark.parametrize(
    "title",
    ["Why 1+1 = 2", "Q&A: rating = 5", "(Part 2) score=10", "example.com?ref=pod"],
)
def test_prose_assignments_recover_chapters(title, suffix, mode):
    text = f'0:00 Intro <img src="x"\n1:00 {title}{suffix}\n2:00 End'
    result = parse_description_chapters(text, mode=mode, strict=True)
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, 'Intro <img src="x"'),
        (60, title + suffix),
        (120, "End"),
    ]


@pytest.mark.parametrize(
    "name", ["@click", "[prop]", "(evt)", "#ref", "1x", "cafe\u0301"]
)
def test_conservative_framework_attributes_remain_hidden(name):
    result = parse_description_chapters(
        f'<custom\n0:00 #ref {name}="y>z">hidden</custom>\n1:00 Intro\n2:00 End'
    )
    assert [c.title for c in result.chapters] == ["Intro", "End"]


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize(
    "prefix", ["0:00 Intro ", "<p>0:00 Intro ", "<p>text<br>0:00 Intro "]
)
def test_inline_formatted_anchor_owns_next_chapter(newline, prefix):
    text = (
        f'{prefix}<a href="https://e.com/1"{newline}'
        f"    >1:00 <b>N&amp;ext</b></a{newline}>{newline}2:00 End"
    )
    result = parse_description_chapters(text, strict=True)
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (0, "Intro", None),
        (60, "<b>N&amp;ext</b>", "https://e.com/1"),
        (120, "End", None),
    ]


@pytest.mark.parametrize("fragment", ["<b\n", "<script>x</script\n", '<a href="x"\n'])
def test_anchor_lookahead_respects_earlier_recovered_fragments(fragment):
    result = parse_description_chapters(
        fragment + '0:00 Intro <a href="https://e.com/1"\n>1:00 Next</a>\n2:00 End'
    )
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (0, "Intro", None),
        (60, "Next", "https://e.com/1"),
        (120, "End", None),
    ]


def test_formatted_anchor_after_prose_starts_a_visible_chapter():
    result = parse_description_chapters(
        'Preface <a href="https://e.com/1"\n>0:00 Intro</a>\n1:00 End'
    )
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (0, "Intro", "https://e.com/1"),
        (60, "End", None),
    ]


@pytest.mark.parametrize(
    "false_close",
    ["<!-- </a> -->", '<script>"</a>"</script>', '<span title="</a>">text</span>'],
)
def test_incomplete_anchors_ignore_nonmarkup_closings(false_close):
    result = parse_description_chapters(
        f'0:00 Intro <a href="https://e.com/1"\n>1:00 Next {false_close}\n>2:00 End'
    )
    assert [c.start for c in result.chapters] == [0, 60, 120]
    assert result.chapters[1].url is None


@pytest.mark.parametrize("prefix", ["<p>", "<p>text<br>", "<p>&gt; ", "<p><b>0</b>:"])
def test_visible_html_chapter_context_recovers_blockquotes(prefix):
    numeric = "00" if prefix.endswith(":") else "0:00"
    result = parse_description_chapters(
        f"{prefix}{numeric} Intro <b\n> 1:00 Next\n> 2:00 End"
    )
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, "Intro <b"),
        (60, "Next"),
        (120, "End"),
    ]


@pytest.mark.parametrize("tag", ["script", "style"])
def test_raw_closing_recovery_keeps_blockquote_boundary(tag):
    result = parse_description_chapters(
        f"<p>0:00 Intro <{tag}>hidden</{tag}\n> 1:00 Next\n> 2:00 End"
    )
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, "Intro"),
        (60, "Next"),
        (120, "End"),
    ]


@pytest.mark.parametrize(
    "newline",
    [
        "\r\n",
        "\r",
        "\n",
        "\v",
        "\f",
        "\x1c",
        "\x1d",
        "\x1e",
        "\x85",
        "\u2028",
        "\u2029",
    ],
)
def test_writer_flattens_all_line_boundaries_including_trailing(newline):
    chapter = ChapterData(0, f"A{newline}B{newline}")
    rendered = chapters_to_description([chapter, ChapterData(60, "End")])
    assert rendered == "0:00 A B \n1:00 End"
    assert chapter.title == f"A{newline}B{newline}"
    assert [c.title for c in parse_description_chapters(rendered).chapters] == [
        "A B",
        "End",
    ]


class _NativeError(ChapterTransportError, OSError):
    def __new__(cls, *native):
        return OSError.__new__(cls, *native)

    def __init__(self, *native):
        OSError.__init__(self, *native)
        super().__init__("failure", url="https://e.com")


def _roundtrip(error, operation):
    if isinstance(operation, int):
        return pickle.loads(pickle.dumps(error, protocol=operation))  # noqa: S301 - Test-owned state.
    return copy.copy(error) if operation == "copy" else copy.deepcopy(error)


_OPERATIONS = [*range(pickle.HIGHEST_PROTOCOL + 1), "copy", "deepcopy"]


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize(
    "arguments",
    [
        (2, "missing", None),
        (2, "missing", None, None, None),
        (None, "missing"),
        (2, None),
        (None, None),
    ],
)
def test_native_constructor_none_preserves_formatting(operation, arguments):
    original = _NativeError(*arguments)
    restored = _roundtrip(original, operation)
    assert str(restored) == str(original)
    assert restored.args == original.args
    assert restored.__dict__ == original.__dict__


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize("field", ["errno", "strerror", "filename", "filename2"])
@pytest.mark.parametrize("deleted", [False, True])
def test_native_none_tracking_stays_out_of_python_state(operation, field, deleted):
    original = _NativeError(2, "missing", "first")
    setattr(original, field, None)
    if deleted:
        delattr(original, field)
    assert json.loads(json.dumps(vars(original))) == {
        "message": "failure",
        "url": "https://e.com",
    }
    restored = _roundtrip(original, operation)
    assert str(restored) == str(original)
    assert vars(restored) == vars(original)


class _UnhashableError(_NativeError):
    __hash__ = None

    def __eq__(self, other):
        return isinstance(other, _UnhashableError)


def test_presence_registry_uses_identity_and_does_not_retain_errors():
    first, second = _UnhashableError(2, "missing"), _UnhashableError(2, "missing")
    first.filename = None
    assert str(copy.copy(first)) == str(first)
    assert str(copy.copy(second)) == str(second)
    reference = weakref.ref(first)
    identity = id(first)
    del first
    gc.collect()
    assert reference() is None
    assert identity not in errors._NATIVE_STATE  # noqa: SLF001 - Verify internal weak-reference cleanup.


def test_native_presence_serialization_does_not_depend_on_hash_seed():
    code = """
import hashlib, pickle
from podcast_chapter_tools import ChapterTransportError
class E(ChapterTransportError, OSError): pass
error = E('failure', url='https://e.com')
error.errno = error.strerror = error.filename = error.filename2 = None
print(hashlib.sha256(pickle.dumps(error, protocol=5)).hexdigest())
"""
    results = [
        subprocess.run(  # noqa: S603 - Fixed serialization regression.
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
            capture_output=True,
            timeout=5,
        ).stdout
        for seed in ("1", "2", "3")
    ]
    assert len(set(results)) == 1


def _restore_reduced(message):
    return _ReducedError(message, url="https://e.com")


class _ReducedError(ChapterTransportError):
    def __reduce__(self):
        return _restore_reduced, ("custom reduction",)


class _ReduceExError(_ReducedError):
    def __reduce_ex__(self, protocol):
        return _restore_reduced, (f"protocol {protocol}",)


@pytest.mark.parametrize("operation", ["copy", "deepcopy"])
@pytest.mark.parametrize(
    ("cls", "expected"),
    [(_ReducedError, "custom reduction"), (_ReduceExError, "protocol 4")],
)
def test_copy_honors_subclass_reducers(operation, cls, expected):
    original = cls("original", url="https://e.com")
    assert _roundtrip(original, operation).message == expected


@pytest.mark.parametrize("operation", ["copy", "deepcopy"])
def test_copy_registered_reducer_takes_precedence(operation, monkeypatch):
    monkeypatch.setitem(
        copyreg.dispatch_table,
        _ReduceExError,
        lambda error: (_restore_reduced, ("registered",)),
    )
    assert (
        _roundtrip(_ReduceExError("original", url="https://e.com"), operation).message
        == "registered"
    )


def _apply_custom_state(error, state):
    error.__dict__.update(state)
    error.state_updater_ran = True


class _UpdaterError(_ReducedError):
    def __reduce__(self):
        return (
            _restore_reduced,
            ("custom",),
            {"peer": self},
            None,
            None,
            _apply_custom_state,
        )


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_custom_six_item_reduction_applies_state_and_memoizes(operation):
    original = _UpdaterError("original", url="https://e.com")
    restored = _roundtrip(original, operation)
    assert restored.state_updater_ran
    assert restored.peer is (original if operation == "copy" else restored)


def _raise_native(arguments):
    raise _NativeError(*arguments)


@pytest.mark.parametrize(
    "arguments", [(2, "missing", None, None, None), (None, "missing")]
)
def test_native_constructor_worker_errors_leave_pool_usable(arguments):
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        with pytest.raises(_NativeError) as caught:
            pool.submit(_raise_native, arguments).result(timeout=20)
        assert str(caught.value) == str(_NativeError(*arguments))
        assert pool.submit(abs, -3).result(timeout=20) == 3


def test_cli_writes_validated_utf8_bytes_once(tmp_path, monkeypatch):
    source, output = tmp_path / "source.json", tmp_path / "output.txt"
    source.write_text('{"chapters":[{"startTime":0,"title":"Café"}]}', encoding="utf-8")
    output.write_bytes(b"old")
    output.chmod(0o640)

    def forbidden_text_write(*args, **kwargs):
        pytest.fail("CLI encoded output again through text writing")

    monkeypatch.setattr(type(output), "write_text", forbidden_text_write)
    assert (
        main(["from-pci", str(source), "--to", "description", "-o", str(output)]) == 0
    )
    assert output.read_bytes() == "0:00 Café\n".encode()
    assert output.stat().st_mode & 0o777 == 0o640


def test_generic_markup_does_not_create_recovery_context(monkeypatch):
    def forbidden_context():
        pytest.fail("Recovery context was created during generic markup processing")

    monkeypatch.setattr(markup, "_ChapterPrefix", forbidden_context)
    assert markup.inline_fragment("one <b>two</b>") == "one <b>two</b>"
    assert markup.plain_text("one <b>two</b>") == "one two"


def test_many_formatted_anchors_have_bounded_lookahead():
    code = """
from podcast_chapter_tools import parse_description_chapters
text = ('0:00 Intro <a href="https://e.com/1"\\n>1:00 Next</a>\\n' * 2000) + '2:00 End'
chapters = parse_description_chapters(text).chapters
assert len(chapters) == 4001
assert all(c.url == 'https://e.com/1' for c in chapters[1::2])
"""
    subprocess.run(  # noqa: S603 - Fixed parser regression in an isolated subprocess.
        [sys.executable, "-c", code], check=True, timeout=5, capture_output=True
    )


class _OpaqueFilename:
    def __repr__(self):
        pytest.fail("Error construction invoked the filename's repr")


@pytest.mark.parametrize("errno", [2, None])
def test_native_bookkeeping_does_not_format_user_objects(errno):
    original = _NativeError(errno, "missing", _OpaqueFilename())
    assert original.errno == errno
    assert isinstance(copy.deepcopy(original).filename, _OpaqueFilename)


class _ShadowedNativeError(_NativeError):
    @property
    def errno(self):
        pytest.fail("Native bookkeeping invoked a subclass property")


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_native_constructor_capture_bypasses_shadowing_properties(operation):
    original = _ShadowedNativeError(None, "missing")
    restored = _roundtrip(original, operation)
    assert str(restored) == str(original)


class _CollectionState:
    def __init__(self):
        self.items = []
        self.pairs = {}

    def append(self, item):
        self.items.append(item)

    def __setitem__(self, key, value):
        self.pairs[key] = value


class _CollectionReducerError(_ReducedError):
    def __reduce__(self):
        return (
            _CollectionState,
            (),
            ({"peer": self}, {"label": "state"}),
            iter([self]),
            iter([("peer", self)]),
        )


@pytest.mark.parametrize("operation", ["copy", "deepcopy"])
def test_custom_copy_factory_handles_standard_state_and_collection_items(operation):
    original = _CollectionReducerError("failure", url="https://e.com")
    restored = _roundtrip(original, operation)
    assert restored.label == "state"
    assert restored.peer is (original if operation == "copy" else restored)
    assert restored.items[0] is restored.peer
    assert restored.pairs["peer"] is restored.peer
