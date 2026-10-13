import copy
import json
import multiprocessing
import pickle
from concurrent.futures import ProcessPoolExecutor
from urllib.parse import quote

import pytest

from podcast_chapter_tools import (
    ChapterData,
    ChapterTransportError,
    markup,
    parse_description_chapters,
    parse_pci_chapters,
)
from podcast_chapter_tools.recognition import _ChapterPrefix, line_timestamp_start
from podcast_chapter_tools.writers import chapters_to_description


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize(
    "tag", ['a href="https://e.com/live"', 'a href="/live"', "strong", "custom"]
)
def test_formatted_prose_does_not_create_strict_chapters(newline, tag):
    name = tag.split()[0]
    text = (
        f"Join us live at <{tag}{newline}  >12:30 PM ET</{name}{newline}"
        "  > every Tuesday.\n0:00 Intro\n1:00 Next\n2:00 End"
    )
    result = parse_description_chapters(text, strict=True, require_monotonic=True)
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, "Intro"),
        (60, "Next"),
        (120, "End"),
    ]
    assert parse_description_chapters(text, mode="lenient").chapters[0].start == 750


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize(
    "tag", ['a href="https://e.com/1"', 'a href="/ep/1"', "strong", "arbitrary-tag"]
)
def test_balanced_formatted_tags_own_next_chapter(newline, tag):
    name = tag.split()[0]
    result = parse_description_chapters(
        f"0:00 Intro <{tag}{newline}>1:00 Next</{name}{newline}>{newline}2:00 End",
        strict=True,
    )
    url = "https://e.com/1" if "https:" in tag else None
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (0, "Intro", None),
        (60, "Next", url),
        (120, "End", None),
    ]


@pytest.mark.parametrize(
    ("tag", "terminator"),
    [('img src="x"', ">"), ("custom", "/>"), ("strong", "/>"), ('custom x="y"', "/>")],
)
def test_complete_void_and_self_closing_formatted_tags(tag, terminator):
    result = parse_description_chapters(
        f"0:00 Intro <{tag}\n{terminator}1:00 Next\n2:00 End"
    )
    assert [c.title for c in result.chapters] == ["Intro", "Next", "End"]


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("closing", ["a", 'a title="y>z"', "a/"])
def test_split_closing_tag_releases_link_context(newline, closing):
    result = parse_description_chapters(
        f'<a href="https://e.com/0">0:00 Intro</{closing}{newline}>1:00 Next\n2:00 End'
    )
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (0, "Intro", "https://e.com/0"),
        (60, "Next", None),
        (120, "End", None),
    ]


def test_physical_prefix_survives_formatted_prose_tag():
    result = parse_description_chapters(
        "Text <strong\n>0:00 Intro <b\n> 1:00 Next</b>\n2:00 End"
    )
    assert [(c.start, c.title) for c in result.chapters] == [(60, "Next"), (120, "End")]


@pytest.mark.parametrize(
    "name", ["[(ngModel)]", "*ngIf", ".value", "v-bind:[key]", "on:click|once"]
)
@pytest.mark.parametrize("boolean", ["", "#ref ", "*enabled "])
def test_extended_framework_assignments_stay_in_tags(name, boolean):
    text = f'<custom\n0:00 {boolean}{name}="y>z">hidden</custom>\n1:00 Intro\n2:00 End'
    assert [c.title for c in parse_description_chapters(text).chapters] == [
        "Intro",
        "End",
    ]


@pytest.mark.parametrize(
    "title",
    [
        "Why 1+1 = 2",
        "Q&A: rating = 5",
        "(Part 2) score=10",
        "example.com?ref=pod",
        "*",
        "[(broken]",
        "on:click|",
        "v-bind:[]",
    ],
)
def test_invalid_framework_and_prose_tokens_recover(title):
    text = f"0:00 Intro <b\n1:00 {title} x=y -> more\n2:00 End"
    assert [c.start for c in parse_description_chapters(text).chapters] == [0, 60, 120]


_BREAKS = [
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
]


@pytest.mark.parametrize(
    ("source", "separator"),
    [
        *[(source, separator) for source in ("data", "pci") for separator in _BREAKS],
        *[
            ("href", separator)
            for separator in ("\r\n", "\r", "\n", "\f", "\u2028", "\u2029")
        ],
    ],
)
def test_url_boundaries_cannot_inject_description_chapters(separator, source):
    url = "https://x.com/" + separator + "0:30"
    if source == "pci":
        chapters = parse_pci_chapters(
            {"chapters": [{"startTime": 0, "title": "Intro", "url": url}]}
        ).chapters
    elif source == "href":
        entity = "".join(f"&#{ord(char)};" for char in separator)
        chapters = parse_description_chapters(
            f'<a href="https://x.com/{entity}0:30">0:00 Intro</a>\n1:00 End',
            strip_html=True,
        ).chapters[:1]
    else:
        chapters = (ChapterData(0, "Intro", url),)
    assert chapters[0].url == url
    rendered = chapters_to_description([*chapters, ChapterData(60, "End")])
    assert (
        rendered
        == f"0:00 Intro https://x.com/{quote(separator, safe='')}0:30\n1:00 End"
    )
    for mode in ("strict", "lenient"):
        assert [
            c.start for c in parse_description_chapters(rendered, mode=mode).chapters
        ] == [0, 60]
    assert chapters[0].url == url


def test_description_url_escaping_preserves_existing_escapes_and_deduplicates():
    url = "https://x.com/%20?a=b\n0:30#fragment"
    escaped = "https://x.com/%20?a=b%0A0:30#fragment"
    chapter = ChapterData(0, f"Intro {escaped}", url)
    assert chapters_to_description([chapter]) == f"0:00 Intro {escaped}"


class _LateNativeError(ChapterTransportError, OSError):
    def __init__(self, *arguments):
        super().__init__("failure", url="https://e.com")
        OSError.__init__(self, *arguments)


_OPERATIONS = [*range(pickle.HIGHEST_PROTOCOL + 1), "copy", "deepcopy"]


def _roundtrip(error, operation):
    if isinstance(operation, int):
        return pickle.loads(pickle.dumps(error, protocol=operation))  # noqa: S301 - Test-owned state.
    return copy.copy(error) if operation == "copy" else copy.deepcopy(error)


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize(
    "arguments", [(None, "m"), (2, None), (None, None), (2, "m", None, None, None)]
)
def test_late_native_initialization_preserves_none_state(operation, arguments):
    original = _LateNativeError(*arguments)
    original.add_note("note")
    original.peer = original
    restored = _roundtrip(original, operation)
    assert str(restored) == str(original)
    assert restored.args == original.args
    assert restored.__notes__ == original.__notes__
    assert restored.peer is (original if operation == "copy" else restored)
    assert json.loads(
        json.dumps({k: v for k, v in vars(original).items() if k != "peer"})
    ) == {"message": "failure", "url": "https://e.com", "__notes__": ["note"]}


class _GetterInitializesNativeError(_LateNativeError):
    def __getstate__(self):
        OSError.__init__(self, None, "changed")
        return self.__dict__


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_native_snapshot_follows_custom_getstate(operation):
    original = _GetterInitializesNativeError(2, "initial")
    restored = _roundtrip(original, operation)
    assert str(restored) == str(original) == "[Errno None] changed"


@pytest.mark.parametrize("operation", _OPERATIONS)
@pytest.mark.parametrize("field", ["errno", "strerror"])
def test_native_reinitialization_reconciles_previous_deletions(operation, field):
    original = _LateNativeError(2, "initial")
    setattr(original, field, None)
    delattr(original, field)
    OSError.__init__(original, None, "changed")
    restored = _roundtrip(original, operation)
    assert str(restored) == str(original) == "[Errno None] changed"


def test_nested_formatted_tags_preserve_url_and_title_ownership():
    result = parse_description_chapters(
        '0:00 Intro <strong\n>1:00 <a href="https://e.com/1"\n'
        ">Nested</a\n></strong\n>2:00 End",
        strict=True,
    )
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (0, "Intro", None),
        (60, '<a href="https://e.com/1"\n>Nested</a>', "https://e.com/1"),
        (120, "End", None),
    ]


@pytest.mark.parametrize(
    "false_close",
    [
        "<!-- </strong> -->",
        '<script>"</strong>"</script>',
        '<span title="</strong>">text</span>',
    ],
)
def test_balance_cache_ignores_closings_in_nonmarkup_contexts(false_close):
    result = parse_description_chapters(
        f"0:00 Intro <strong\n>1:00 Next {false_close}\n>2:00 End"
    )
    assert [c.start for c in result.chapters] == [0, 60, 120]
    assert result.chapters[0].title == "Intro <strong"


@pytest.mark.parametrize("tag", ["strong", 'a href="https://e.com/1"'])
@pytest.mark.parametrize("quote_char", ['"', "'"])
def test_quoted_formatted_terminators_cannot_create_chapters(tag, quote_char):
    name = tag.split()[0]
    result = parse_description_chapters(
        f"0:00 Intro <{tag} title={quote_char}x\n>1:00 Fake{quote_char}>"
        f"bold</{name}>\n2:00 End",
        strip_html=True,
        strict=True,
    )
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, "Intro bold"),
        (120, "End"),
    ]


def test_balance_lookahead_reuses_boundaries_after_unbalanced_tag(monkeypatch):
    scanned = []
    original = markup._TagCache._scan  # noqa: SLF001 - Instrument bounded scanning.

    def scan(cache, start):
        scanned.append(start)
        return original(cache, start)

    monkeypatch.setattr(markup._TagCache, "_scan", scan)  # noqa: SLF001 - Instrument bounded scanning.
    text = "0:00 Intro <unclosed\n>1:00 Next " + " ".join(
        f"<custom\n>{index + 2}:00 Title</custom>" for index in range(40)
    )
    markup.description_lines(text, recover_chapters=True)
    assert len(scanned) == len(set(scanned))
    assert len(scanned) == 81


def test_generic_stripping_does_not_construct_recovery_context(monkeypatch):
    def forbidden():
        pytest.fail("Generic stripping constructed chapter recovery context")

    monkeypatch.setattr(markup, "_SourcePrefix", forbidden)
    monkeypatch.setattr(markup, "_ChapterPrefix", forbidden)
    assert markup.plain_text('<a href="x"\n>Text</a>') == "Text"


def _raise_late_native():
    raise _LateNativeError(None, "m")


def test_late_native_worker_failure_leaves_pool_usable():
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        with pytest.raises(_LateNativeError, match=r"\[Errno None\] m"):
            pool.submit(_raise_late_native).result(timeout=20)
        assert pool.submit(abs, -3).result(timeout=20) == 3


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        "> ",
        "Chapters: ",
        "> Chapters: ",
        "- ",
        "* ",
        "+ ",
        "• ",
        "1. ",
        "1) ",
        "[",
        "(",
        "\u2060> • ",
    ],
)
def test_batch_and_incremental_prefix_offsets_match(prefix):
    text = prefix + "0:00 Title"
    recognizer = _ChapterPrefix()
    for char in text:
        recognizer.feed(char)
    assert recognizer.chapter
    assert recognizer.numeric_start == line_timestamp_start(text) == len(prefix)
    recognizer.reset()
    recognizer.feed("Ordinary prose at 0:00")
    assert not recognizer.chapter
    assert recognizer.numeric_start is None
