# Private lexical boundaries are intentional regression targets.
# ruff: noqa: SLF001

import re

import pytest

from podcast_chapter_tools import markup, parse_description_chapters
from podcast_chapter_tools._boundaries import LINE_BREAK_PATTERN, is_line_break
from podcast_chapter_tools.normalize import strip_html


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize(
    "space", ["", " ", "\t", "\f", "\v", "\u2003", "\n", "\r", "\r\n"]
)
@pytest.mark.parametrize(
    "assignment",
    [
        'x=="a>b"',
        'x="a>b"',
        "x\"='",
        "x'=\"",
        "\"='",
        'x="1"="y',
        'x="',
        "x='",
        'x= "',
        "x= '",
        "== '",
        "x\"=='",
        "x'==\"",
        "\"=='x",
    ],
)
def test_assignment_boundaries_follow_the_runtime_parser(
    space, assignment, recovery, html_start_boundary
):
    name, equals, value = assignment.partition("=")
    text = f"<b {name}{space}{equals}{value}>Notes</b>\n0:00 Intro"
    expected = html_start_boundary(text)
    token = markup._TagCache(text, recover_chapters=recovery).token(0)
    assert token.end == (expected - 1 if expected >= 0 else len(text))


@pytest.mark.parametrize("name", ['"', 'x"', "'", "x'"])
@pytest.mark.parametrize("space", ["", " ", "\t"])
def test_incomplete_assignment_fallback_keeps_later_links(name, space):
    value_quote = "'" if name.endswith('"') else '"'
    text = (
        f"<b {name}{space}={value_quote}>Notes</b>\n"
        "0:00 <a href=https://e.com>Intro</a>\n1:00 Next\n2:00 End"
    )
    result = parse_description_chapters(text, strict=True, require_monotonic=True)
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (0, "<a href=https://e.com>Intro</a>", "https://e.com"),
        (60, "Next", None),
        (120, "End", None),
    ]
    line = next(
        line
        for line in markup.description_lines(text, recover_chapters=True)
        if line.text.startswith("0:00")
    )
    assert line.url_at(line.text.index("Intro")) == "https://e.com"
    assert strip_html(text) == "Notes 0:00 Intro 1:00 Next 2:00 End"


@pytest.mark.parametrize("newline", ["\n", "\r", "\r\n"])
def test_complete_closing_attributes_never_become_visible_data(newline):
    text = f'<a href="https://e.com">Intro</a title="x>y"{newline}>1:00 Next'
    assert strip_html(text) == "Intro1:00 Next"
    assert markup.inline_fragment(text).startswith(
        '<a href="https://e.com">Intro</a>1:00 Next'
    )


def test_separator_pattern_and_membership_match_splitlines():
    pattern = re.compile(LINE_BREAK_PATTERN)
    for value in ["\r\n", *map(chr, range(256)), "\u2028", "\u2029", "\v\n", ""]:
        expected = bool(value) and value.splitlines() == [""]
        assert bool(pattern.fullmatch(value)) == expected
        assert is_line_break(value) == expected


def test_visible_entity_boundary_does_not_sanitize_quoted_attributes():
    result = parse_description_chapters(
        '0:00 <i title="x\u2028y">Q</i>&#8232;A and more\n1:00 Next'
    )
    assert [c.title for c in result.chapters] == [
        '<i title="x\u2028y">Q</i>',
        "Next",
    ]
