import copy
import json
import multiprocessing
import pickle
import threading
from concurrent.futures import ProcessPoolExecutor

import pytest

from podcast_chapter_tools import (
    ChapterData,
    ChapterFetchError,
    ChapterHTTPError,
    ChapterParseError,
    ChapterTransportError,
    parse_description_chapters,
)
from podcast_chapter_tools import description as description_module
from podcast_chapter_tools.cli import main
from podcast_chapter_tools.writers import chapters_to_description


@pytest.mark.parametrize("mode", ["strict", "lenient"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("prefix", ["> ", "", "Chapters: ", "1. ", "• ", "\ufeff> "])
def test_chapter_context_recovers_blockquotes(prefix, newline, mode):
    text = f"{prefix}0:00 Intro <b{newline}> 1:00 Next{newline}> 2:00 End"
    result = parse_description_chapters(text, mode=mode, strict=True)
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, "Intro <b"),
        (60, "Next"),
        (120, "End"),
    ]
    assert chapters_to_description(result.chapters).splitlines() == [
        "0:00 Intro <b",
        "1:00 Next",
        "2:00 End",
    ]


@pytest.mark.parametrize("padding", ["", " ", "\t"])
@pytest.mark.parametrize("after", ["", " "])
def test_nonchapter_tag_context_preserves_formatted_links(padding, after):
    result = parse_description_chapters(
        f'0:00 Previous\n<a href="https://e.com/1"\n{padding}>{after}1:00 Intro</a>\n2:00 End'
    )
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (0, "Previous", None),
        (60, "Intro", "https://e.com/1"),
        (120, "End", None),
    ]


def test_multiline_comment_updates_pending_tag_origin():
    result = parse_description_chapters(
        '0:00 Intro<!--\ncomment\n--><br><a href="https://e.com/1"\n>1:00 Next</a>\n2:00 End'
    )
    assert [(c.start, c.url) for c in result.chapters] == [
        (0, None),
        (60, "https://e.com/1"),
        (120, None),
    ]


@pytest.mark.parametrize("name", ["@click", "[prop]", "(evt)", "#ref", "1x", "café"])
@pytest.mark.parametrize("boolean", ["", "#ref "])
def test_framework_attribute_assignments_remain_hidden(name, boolean):
    text = f'<img src="x"\n0:00 {boolean}{name}="y>z">\n1:00 Intro\n2:00 End'
    result = parse_description_chapters(text, mode="lenient", strict=True)
    assert [(c.start, c.title) for c in result.chapters] == [
        (60, "Intro"),
        (120, "End"),
    ]


def test_framework_boolean_only_continuation_recovers():
    result = parse_description_chapters("0:00 Intro <span\n1:00 #ref\n2:00 End >")
    assert [c.title for c in result.chapters] == ["Intro <span", "#ref", "End >"]


@pytest.mark.parametrize("newline", ["\r\n", "\r", "\n"])
def test_description_writer_flattens_title_newlines_without_changing_data(newline):
    chapter = ChapterData(0, f"First{newline}<b>second</b>{newline}third")
    assert chapters_to_description([chapter, ChapterData(60, "End")]) == (
        "0:00 First <b>second</b> third\n1:00 End"
    )
    assert chapter.title == f"First{newline}<b>second</b>{newline}third"


@pytest.mark.parametrize("encoded", [True, False])
@pytest.mark.parametrize("fmt", ["pci", "psc", "description"])
def test_cli_surrogates_do_not_truncate_output(tmp_path, capsys, encoded, fmt):
    source, output = tmp_path / "input.json", tmp_path / "output.txt"
    title = b"a\xed\xa0\x80b" if encoded else b"a\\ud800b"
    source.write_bytes(b'{"chapters":[{"startTime":0,"title":"' + title + b'"}]}')
    original = b"KEEP EXISTING OUTPUT\n"
    output.write_bytes(original)
    output.chmod(0o640)
    status = main(["from-pci", str(source), "--to", fmt, "-o", str(output)])
    if fmt == "pci":
        assert status == 0
        assert json.loads(output.read_bytes())["chapters"][0]["title"] == "a\ud800b"
    else:
        assert status == 1
        assert output.read_bytes() == original
        assert "UnicodeEncodeError" in capsys.readouterr().err
    assert output.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("mode", ["strict", "lenient"])
@pytest.mark.parametrize("failure", [ValueError, OverflowError])
@pytest.mark.parametrize("helper", ["inline_fragment", "plain_text"])
def test_title_failures_are_not_timestamp_diagnostics(
    monkeypatch, mode, failure, helper
):
    def fail_title(*args, **kwargs):
        raise failure("title preparation failed")

    monkeypatch.setattr(description_module, helper, fail_title)
    prefix = "At " if mode == "lenient" else ""
    with pytest.raises(failure, match="title preparation failed"):
        parse_description_chapters(f"{prefix}0:00 Intro\n1:00 End", mode=mode)


def _roundtrip(error, operation):
    if isinstance(operation, int):
        return pickle.loads(pickle.dumps(error, protocol=operation))  # noqa: S301 - Test-owned state.
    return copy.copy(error) if operation == "copy" else copy.deepcopy(error)


_OPERATIONS = [*range(pickle.HIGHEST_PROTOCOL + 1), "copy", "deepcopy"]


class _CyclicError(ChapterTransportError, TimeoutError):
    __slots__ = ("__detail", "peer", "unset")

    def __init__(self):
        self.peer = self
        self.__detail = "private detail"
        super().__init__("failure", url="https://e.com")

    def detail(self):
        return self.__detail


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize("mutual", [False, True])
def test_cyclic_slots_roundtrip(operation, mutual):
    original = _CyclicError()
    original.add_note("context")
    if mutual:
        other = _CyclicError()
        original.peer, other.peer = other, original
    restored = _roundtrip(original, operation)
    assert type(restored) is _CyclicError
    assert restored.args == original.args
    assert restored.detail() == original.detail()
    assert not hasattr(restored, "unset")
    assert restored.__notes__ == original.__notes__
    if operation == "copy":
        assert restored.peer is original.peer
    else:
        assert (restored.peer.peer if mutual else restored.peer) is restored


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_cyclic_exception_arguments_are_restored_after_memoization(operation):
    original = _CyclicError()
    original.args = (original,)
    restored = _roundtrip(original, operation)
    assert restored.args[0] is (original if operation == "copy" else restored)


class _LockStateError(_CyclicError):
    __slots__ = ("lock",)

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.dictionary_lock = threading.Lock()

    def __getstate__(self):
        state = {
            key: value
            for key, value in self.__dict__.items()
            if key != "dictionary_lock"
        }
        return (state, self.peer, self.detail())

    def __setstate__(self, state):
        dictionary, self.peer, detail = state
        self.__dict__.update(dictionary)
        self._CyclicError__detail = detail
        self.lock = threading.Lock()
        self.dictionary_lock = threading.Lock()
        self.hook_ran = True


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_custom_hooks_own_dictionary_and_slotted_state(operation):
    original = _LockStateError()
    original.add_note("hook note")
    restored = _roundtrip(original, operation)
    assert restored.hook_ran
    assert restored.message == original.message
    assert restored.url == original.url
    assert restored.detail() == original.detail()
    assert restored.__notes__ == original.__notes__
    assert restored.lock is not original.lock
    assert restored.dictionary_lock is not original.dictionary_lock
    assert restored.peer is (original if operation == "copy" else restored)


class _TupleStateError(_CyclicError):
    def __getstate__(self):
        return (
            dict(self.__dict__),
            {"peer": self.peer, "_CyclicError__detail": self.detail()},
        )


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_custom_standard_slot_state_without_setter(operation):
    original = _TupleStateError()
    restored = _roundtrip(original, operation)
    assert restored.message == original.message
    assert restored.detail() == original.detail()
    assert restored.peer is (original if operation == "copy" else restored)


class _NoneStateError(_CyclicError):
    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pytest.fail("None state invoked a custom setter")


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_none_custom_state_omits_python_slots_and_skips_setter(operation):
    original = _NoneStateError()
    restored = _roundtrip(original, operation)
    assert restored.args == original.args
    assert not hasattr(restored, "peer")
    assert not hasattr(restored, "message")


class _ClassStateError(ChapterFetchError):
    @classmethod
    def __setstate__(cls, state):
        cls.received = state


class _StaticStateError(ChapterFetchError):
    @staticmethod
    def __setstate__(state):
        _StaticStateError.received = state


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize("cls", [_ClassStateError, _StaticStateError])
def test_state_hooks_follow_normal_method_binding(operation, cls):
    original = cls("failure", url="https://e.com")
    restored = _roundtrip(original, operation)
    assert type(restored) is cls
    assert restored.args == original.args
    assert cls.received == original.__dict__


class _NativeError(ChapterTransportError, OSError):
    pass


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize("field", ["filename", "filename2"])
@pytest.mark.parametrize("status", ["unset", "explicit", "deleted"])
def test_native_none_presence_roundtrip(operation, field, status):
    original = _NativeError("failure", url="https://e.com")
    original.errno, original.strerror = 2, "missing"
    if field == "filename2":
        original.filename = "first"
    if status != "unset":
        setattr(original, field, None)
    if status == "deleted":
        delattr(original, field)
    restored = _roundtrip(original, operation)
    assert str(restored) == str(original)
    assert restored.args == original.args
    assert restored.url == original.url


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_native_none_remains_present_before_first_filename_is_set(operation):
    original = _NativeError("failure", url="https://e.com")
    original.filename2 = None
    restored = _roundtrip(original, operation)
    original.filename = restored.filename = "first"
    assert str(restored) == str(original)


class _ConstructorNoneError(_NativeError):
    def __new__(cls):
        return OSError.__new__(cls, 2, "missing", "first", None, None)

    def __init__(self):
        OSError.__init__(self, 2, "missing", "first", None, None)
        super().__init__("failure", url="https://e.com")


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_native_constructor_none_presence_roundtrip(operation):
    original = _ConstructorNoneError()
    restored = _roundtrip(original, operation)
    assert str(restored) == str(original)
    assert restored.args == original.args


def test_shallow_copy_native_presence_records_are_independent():
    original = _NativeError("failure", url="https://e.com")
    original.filename, original.filename2 = "first", None
    restored = copy.copy(original)
    restored.filename2 = "second"
    assert str(_roundtrip(original, pickle.HIGHEST_PROTOCOL)) == str(original)


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
@pytest.mark.parametrize(
    "cls",
    [ChapterParseError, ChapterFetchError, ChapterHTTPError, ChapterTransportError],
)
def test_all_root_errors_support_every_pickle_protocol(protocol, cls):
    if cls is ChapterParseError:
        original = cls("failure", source="feed", guid="g")
    elif cls is ChapterHTTPError:
        original = cls(url="https://e.com", status_code=429, retry_after="60")
    else:
        original = cls("failure", url="https://e.com")
    original.add_note("note")
    restored = _roundtrip(original, protocol)
    assert type(restored) is cls
    assert restored.args == original.args
    assert restored.__dict__ == original.__dict__


def _raise_stateful_error(cls):
    raise cls()


@pytest.mark.parametrize("cls", [_CyclicError, _LockStateError, _ConstructorNoneError])
def test_cyclic_and_custom_state_worker_errors_leave_pool_usable(cls):
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        with pytest.raises(cls) as caught:
            pool.submit(_raise_stateful_error, cls).result(timeout=20)
        assert str(caught.value) == str(cls())
        if cls is not _ConstructorNoneError:
            assert caught.value.peer is caught.value
        assert pool.submit(abs, -3).result(timeout=20) == 3
