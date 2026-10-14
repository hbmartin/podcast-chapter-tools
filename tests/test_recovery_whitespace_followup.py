# Private lexical facts and source spans are deliberate regression targets.
# ruff: noqa: SLF001

import os
import subprocess
import sys
from pathlib import Path

import pytest

from podcast_chapter_tools import markup, parse_description_chapters
from podcast_chapter_tools.normalize import strip_html


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize(
    "padding",
    [("\n", "\r"), ("\r\n", "\r\n"), ("\u2003", "\u2003"), ("\v", "\n"), ("", "\n")],
)
@pytest.mark.parametrize(
    "assignment", ['x="a>b"', 'x=="a>b"', 'x= "', "x\"='", "x'==\""]
)
def test_assignment_padding_matches_public_parser(
    padding, assignment, recovery, html_start_boundary
):
    before, after = padding
    name, equals, value = assignment.partition("=")
    text = f"<b {name}{before}{equals}{after}{value}>Notes</b>\n0:00 Intro"
    expected = html_start_boundary(text)
    token = markup._TagCache(text, recover_chapters=recovery).token(0)
    assert token.end == (expected - 1 if expected >= 0 else len(text))


@pytest.mark.parametrize("newline", ["\n", "\r", "\r\n"])
def test_assignment_after_newline_protects_quoted_chapter_text(newline):
    text = (
        f'<b title{newline}="x>{newline}0:00 Fake">Real</b>{newline}'
        f'0:00 <a href="https://e.com">Intro</a>{newline}1:00 Next'
    )
    result = parse_description_chapters(text, strict=True, require_monotonic=True)
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (0, '<a href="https://e.com">Intro</a>', "https://e.com"),
        (60, "Next", None),
    ]
    lines = markup.description_lines(text, recover_chapters=True)
    assert [line.text for line in lines] == ["Real", "0:00 Intro", "1:00 Next"]
    assert lines[1].url_at(5) == "https://e.com"
    start, end = lines[1].raw_start(5), lines[1].raw_end(9)
    assert lines[1].raw[start:end] == "Intro"


@pytest.mark.parametrize("newline", ["\n", "\r", "\r\n"])
def test_repeated_assignment_after_newline_keeps_later_chapters(newline):
    text = f'<p><b x{newline}==">Notes</b></p><p>0:00 Intro</p><p>1:00 Next</p>'
    assert [(c.start, c.title) for c in parse_description_chapters(text).chapters] == [
        (0, "Intro"),
        (60, "Next"),
    ]


@pytest.mark.parametrize("recovery", [False, True])
def test_lowercase_expansion_cannot_expose_closing_attributes(recovery):
    name = "a" + "İ" * 6
    text = f'0:00 <{name}>Intro</{name} x=">"> Tail\n1:00 Next'
    lines = markup.description_lines(text, recover_chapters=recovery)
    assert [line.text for line in lines] == ["0:00 Intro Tail", "1:00 Next"]
    assert lines[0].raw == f"0:00 <{name}>Intro</{name.lower()}> Tail"
    assert strip_html(text) == "0:00 Intro Tail 1:00 Next"


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize("name", ["i\x00", "i\x00tail", "script\x00", "style\x00tail"])
def test_nul_names_are_literal_without_hiding_following_markup(name, recovery):
    fragment = f'<{name} title="x>y">Intro'
    text = f'0:00 {fragment}</i>\n1:00 <a href="https://e.com">Next</a>'
    lines = markup.description_lines(text, recover_chapters=recovery)
    assert [line.text for line in lines] == [f"0:00 {fragment}", "1:00 Next"]
    assert lines[1].url_at(5) == "https://e.com"
    assert markup.inline_fragment(fragment) == fragment
    token = markup._TagCache(text, recover_chapters=recovery).token(5)
    assert not token.complete
    assert text[token.end - 1] == "\x00"


@pytest.mark.parametrize("name", ["i\x00", "script\x00", "style\x00tail"])
def test_nul_classification_is_independent_of_cached_lookahead(name):
    text = f'0:00 Start\n0:30 <{name}>Part</i>\n1:00 <a href="https://e.com">Next</a>'
    expected = parse_description_chapters(text).chapters
    assert parse_description_chapters("<unclosed\n>" + text).chapters == expected


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize("attribute", ['x<="a>b"', "/<=x<x='x =//<<x=\n ", 'x=<"a>b"'])
def test_nested_attribute_fragments_keep_tolerant_boundaries(
    attribute, recovery, html_start_boundary
):
    text = f"<b {attribute}>Notes</b>\n0:00 Intro\n1:00 Next"
    expected = html_start_boundary(text)
    end, nested = markup._tag_end(text, 2, recover_chapters=recovery)
    assert nested
    assert end == (expected - 1 if expected >= 0 else len(text))


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize(
    "assignment", ['x= "', "x\"='", "x'==\"", "x = '", 'x="a>b"z= "']
)
def test_incomplete_quote_fallback_keeps_searches_forward(assignment, recovery):
    class TrackedText(str):
        __slots__ = ()

        def find(self, sub, start=0, end=None):
            result = super().find(sub, start, len(self) if end is None else end)
            if sub in {"'", '"'}:
                assert start >= searches.get(sub, 0)
                searches[sub] = start
                if result < 0:
                    assert sub not in missing
                    missing.add(sub)
            return result

    searches, missing = {}, set()
    text = TrackedText(f"<b {assignment}>Notes</b>\n0:00 Intro")
    markup._tag_end(text, 2, recover_chapters=recovery)


@pytest.mark.parametrize("value", [False, True, 0, 1, 2, "yes", "", None])
def test_scanner_keeps_recovery_option_truthiness(value):
    text = '<b title\n="x>\n0:00 Fake">Real</b>'
    assert markup._tag_end(text, 2, recover_chapters=value) == markup._tag_end(
        text, 2, recover_chapters=bool(value)
    )


def test_import_probes_use_only_public_parser_methods():
    root = Path(__file__).resolve().parents[1]
    code = """
import html.parser
Original = html.parser.HTMLParser
class OriginalProbe(Original):
    def __init__(self, text):
        super().__init__()
        self.text = text
        self.whole = False
        self.feed(text)
        self.close()
    def handle_starttag(self, tag, attrs):
        self.whole = self.get_starttag_text() == self.text
equals = OriginalProbe('<b x=="a>b">').whole
space = OriginalProbe('<b x=\\v"a>b">').whole
class PublicParser:
    __slots__ = ('_parser',)
    def __init__(self, *args, **kwargs):
        owner = self
        class Bridge(Original):
            def handle_starttag(self, tag, attrs):
                owner.handle_starttag(tag, attrs)
        self._parser = Bridge(*args, **kwargs)
    def feed(self, text):
        self._parser.feed(text)
    def close(self):
        self._parser.close()
    def get_starttag_text(self):
        return self._parser.get_starttag_text()
    def handle_starttag(self, tag, attrs):
        pass
html.parser.HTMLParser = PublicParser
from podcast_chapter_tools import markup
assert not hasattr(PublicParser, 'check_for_whole_start_tag')
assert markup._REPEATED_EQUALS == equals
assert markup._UNICODE_ATTRIBUTE_SPACE == space
"""
    subprocess.run(  # noqa: S603 - Fixed public-interface probe regression.
        [sys.executable, "-c", code],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
