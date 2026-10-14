# Private lexer, cache, and checkpoint contracts are regression targets.
# ruff: noqa: SLF001

import copy
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

from podcast_chapter_tools import (
    ChapterData,
    ChapterTransportError,
    errors,
    markup,
    parse_description_chapters,
)
from podcast_chapter_tools.writers import chapters_to_psc_element, chapters_to_psc_xml

_BREAKS = ["\r\n", *"\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"]
_BAD_XML = [
    *map(chr, [*range(9), 11, 12, *range(14, 32)]),
    "\ud800",
    "\udfff",
    "\ufffe",
    "\uffff",
]


@pytest.mark.parametrize("separator", _BREAKS)
@pytest.mark.parametrize(
    "bridge", ["", "<!-- hidden -->", "<script>x<y</script>", "<style>a{}</style>"]
)
def test_line_separators_survive_invisible_markup(separator, bridge):
    text = (
        f'0:00 Intro{separator}{bridge}<a href="https://e.com/1">1:00 Topic</a>'
        f'{separator}<a href="https://e.com/2">2:00 Outro</a>'
    )
    result = parse_description_chapters(text, strict=True, require_monotonic=True)
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (0, "Intro", None),
        (60, "Topic", "https://e.com/1"),
        (120, "Outro", "https://e.com/2"),
    ]


@pytest.mark.parametrize(
    "separator", ["&#8232;", "&#x2029;", "&#12;", "&NewLine;", "&#13;&#10;"]
)
def test_decoded_separators_split_chapters(separator):
    result = parse_description_chapters(
        f"0:00 A{separator}<i>1:00 B</i>\n2:00 C", strict=True
    )
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, "A"),
        (60, "B"),
        (120, "C"),
    ]


@pytest.mark.parametrize("entity", ["&#11;", "&#28;", "&#133;", "&amp;#8232;"])
def test_entity_substitutions_do_not_invent_boundaries(entity):
    result = parse_description_chapters(f"0:00 A{entity}1:00 B\n2:00 C")
    assert [c.start for c in result.chapters] == [0, 120]


@pytest.mark.parametrize("separator", _BREAKS)
def test_boundary_preserves_closing_tags_and_next_link_offsets(separator):
    text = f'0:00 Intro <b>bold{separator}</b><a href="https://e.com/1">1:00 Next</a>\n2:00 End'
    result = parse_description_chapters(text)
    assert [(c.title, c.url) for c in result.chapters] == [
        ("Intro <b>bold</b>", None),
        ("Next", "https://e.com/1"),
        ("End", None),
    ]
    line = markup.description_lines(text, recover_chapters=True)[1]
    start = line.text.index("Next")
    assert line.raw[line.raw_start(start)] == "N"
    assert line.url_at(start) == "https://e.com/1"


@pytest.mark.parametrize("part", ['="x', 'x="1"="y', '/="x', 'x=<"y'])
def test_misplaced_assignments_do_not_hide_tag_terminators(part):
    text = f'<b {part}>0:00 Visible">'
    cache = markup._TagCache(text, recover_chapters=True)
    assert cache.token(0).end == text.index(">")


@pytest.mark.parametrize("attribute", ['x="a>b"', "x = 'a>b'", '=="a>b"', 'x="a\n>b"'])
def test_valid_quoted_attribute_runs_still_protect_terminators(attribute):
    text = f"<custom {attribute}>"
    cache = markup._TagCache(text, recover_chapters=True)
    assert cache.token(0).end == len(text) - 1


@pytest.mark.parametrize(
    "attributes",
    [
        'x=="a>b"',
        '=="a>b"',
        'x= ="a>b"',
        'x="1"z="a>b"',
        '="x',
        "\"==\"' =/=' = ",
        " /''== \"x  =",
    ],
)
def test_attribute_boundaries_match_supported_html_parser(
    attributes, html_start_boundary
):
    text = "<b " + attributes + '>0:00 Visible">'
    end = html_start_boundary(text)
    cache = markup._TagCache(text, recover_chapters=False)
    assert cache.token(0).end + 1 == end


def test_unclosed_ordinary_tag_does_not_block_enclosing_link():
    text = (
        '0:00 Old <a href="https://e.com"\n>0:30 Part <b\n>1:00 Next <i>q</a>\n2:00 End'
    )
    assert [
        (c.start, c.title, c.url) for c in parse_description_chapters(text).chapters
    ] == [
        (0, "Old", None),
        (30, "Part <b", "https://e.com"),
        (60, "Next <i>q</i>", "https://e.com"),
        (120, "End", None),
    ]


def test_crossed_formatted_tags_keep_independent_matches():
    text = "0:00 Old <b\n>0:30 Part <i\n>1:00 Next</b>\n2:00 End</i>"
    assert [(c.start, c.title) for c in parse_description_chapters(text).chapters] == [
        (0, "Old"),
        (30, "Part"),
        (60, "Next"),
        (120, "End"),
    ]


def test_pairing_survives_consumed_opening_chunks(monkeypatch):
    monkeypatch.setattr(markup, "_TOKEN_CHUNK_SIZE", 1)
    text = "<b\n>0:00 First <i\n>0:30 Next</b>\n1:00 End</i>"
    cache = markup._TagCache(text, recover_chapters=True)
    visible, source = markup._ChapterPrefix(), markup._SourcePrefix()
    assert cache.balanced(cache.token(0), visible=visible, source=source)
    inner = cache.token(text.index("<i"))
    assert 1 not in cache.tokens.blocks
    assert cache.balanced(inner, visible=visible, source=source)


@pytest.mark.parametrize("character", _BAD_XML)
@pytest.mark.parametrize("field", ["title", "url", "image"])
@pytest.mark.parametrize("writer", [chapters_to_psc_element, chapters_to_psc_xml])
def test_psc_replaces_forbidden_characters_without_mutating_data(
    character, field, writer
):
    original = "A" + character + character + "B"
    chapter = ChapterData(0, **{field: original})
    rendered = writer([chapter])
    element = (
        ElementTree.fromstring(rendered) if isinstance(rendered, str) else rendered
    )
    attribute = {"title": "title", "url": "href", "image": "image"}[field]
    assert element[0].attrib[attribute] == "A  B"
    assert getattr(chapter, field) == original
    ElementTree.fromstring(ElementTree.tostring(element, encoding="unicode"))


@pytest.mark.parametrize(
    "character",
    [
        "\t",
        "\r",
        "\n",
        "\x85",
        "\u2028",
        "\ud7ff",
        "\ue000",
        "\ufffd",
        "\U00010000",
        "\U0010ffff",
        "\U0001fffe",
    ],
)
def test_psc_retains_xml_allowed_characters(character):
    chapter = ChapterData(0, "A" + character + "B")
    element = ElementTree.fromstring(chapters_to_psc_xml([chapter]))
    assert element[0].attrib["title"] == chapter.title


class _NativeError(ChapterTransportError, OSError):
    pass


def test_unchanged_large_primitive_is_fingerprinted_once_per_assignment(monkeypatch):
    value = "large argument " * 10000
    error = _NativeError("failure", url="u")
    error.errno = None
    error.strerror = value
    error.args = (value,)
    calls = []
    original = errors._witness

    def witness(current):
        if current is value:
            calls.append(current)
        return original(current)

    monkeypatch.setattr(errors, "_witness", witness)
    error.filename = "new"
    assert len(calls) == 1


class _SetterBaseError(OSError):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name == "args":
            OSError.strerror.__set__(self, "changed")


class _SetterError(ChapterTransportError, _SetterBaseError):
    pass


def test_post_setter_snapshot_observes_changed_native_values():
    error = _SetterError("failure", url="u")
    error.errno = None
    error.args = ("custom",)
    restored = copy.copy(error)
    assert restored.strerror == error.strerror == "changed"
    assert str(restored) == str(error) == "[Errno None] changed"


@pytest.mark.parametrize(
    "value",
    [0, 127, 128, -128, -129, (1 << 200000) - 1, -(1 << 200000)],
    ids=[
        "zero",
        "127",
        "128",
        "negative-128",
        "negative-129",
        "large-positive",
        "large-negative",
    ],
)
def test_integer_fingerprints_keep_canonical_representation(value):
    size = max(1, (value.bit_length() + 8) // 8)
    digest = hashlib.sha256(b"int")
    digest.update(size.to_bytes(8, "little"))
    digest.update(value.to_bytes(size, "little", signed=True))
    assert errors._integer_fingerprint(value) == digest.digest()


@pytest.mark.parametrize("negative", [False, True])
def test_large_integer_fingerprint_allocation_is_linear(
    negative, tmp_path, monkeypatch
):
    root = Path(__file__).resolve().parents[1]
    package = tmp_path / "podcast_chapter_tools"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "errors.py").write_text(
        'raise RuntimeError("Imported the competing installed copy")', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    code = f"""
import tracemalloc
import sys
from pathlib import Path
from podcast_chapter_tools import errors
assert Path(errors.__file__).resolve() == Path(sys.argv[1]) / 'podcast_chapter_tools' / 'errors.py'
paths = [Path(value).resolve() for value in sys.path]
assert paths.index(Path(sys.argv[1])) < paths.index(Path(sys.argv[2]))
value = (1 << (20 * 1024 * 1024 * 8)) - 1
if {negative!r}:
    value = -value
tracemalloc.start()
errors._integer_fingerprint(value)
_, peak = tracemalloc.get_traced_memory()
assert peak <= 25 * 1024 * 1024, peak
"""
    subprocess.run(  # noqa: S603 - Fixed isolated allocation regression.
        [sys.executable, "-c", code, str(root), str(tmp_path)],
        cwd=root,
        env={**os.environ, "PYTHONPATH": os.pathsep.join((str(root), str(tmp_path)))},
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
