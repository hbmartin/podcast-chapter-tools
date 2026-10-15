# Private scanner facts and spans are intentional regression targets.
# ruff: noqa: SLF001

import pytest

from podcast_chapter_tools import markup, parse_description_chapters
from podcast_chapter_tools.normalize import strip_html


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize("quote", ["", ' x="never', "'"])
@pytest.mark.parametrize("raw", ["script", "style"])
def test_unfinished_nul_closing_does_not_consume_later_raw_blocks(recovery, quote, raw):
    fragment = "</a\x00" + quote
    text = f"0:00 Intro{fragment}<{raw}>secret</{raw}>\n1:00 Next\n2:00 Last"
    lines = markup.description_lines(text, recover_chapters=recovery)
    assert [line.text for line in lines] == [
        f"0:00 Intro{fragment}",
        "1:00 Next",
        "2:00 Last",
    ]
    assert strip_html(text) == f"0:00 Intro{fragment} 1:00 Next 2:00 Last"
    assert [c.title for c in parse_description_chapters(text).chapters] == [
        f"Intro{fragment}",
        "Next",
        "Last",
    ]


@pytest.mark.parametrize("prefix", ["", "<unclosed\n>"])
@pytest.mark.parametrize("suffix", ["\x00>", "\x00x>", '\x00 title="x>y">'])
def test_nul_closing_does_not_shorten_names_or_close_the_outer_link(prefix, suffix):
    text = (
        prefix
        + f'0:00 <a href="https://e.com">Intro<a\x00x>Inner</a{suffix}\n1:00 Tail</a>\n2:00 Last'
    )
    chapters = parse_description_chapters(text).chapters
    assert [(c.start, c.url) for c in chapters] == [
        (0, "https://e.com"),
        (60, "https://e.com"),
        (120, None),
    ]
    assert (
        chapters[0].title
        == f'<a href="https://e.com">Intro<a\x00x>Inner</a{suffix}</a>'
    )
    assert chapters[1].title == "Tail"


@pytest.mark.parametrize("recovery", [False, True])
def test_nul_closing_prefix_keeps_later_anchor_markup_and_offsets(recovery):
    text = '0:00 <b>Intro</b\x00<a href="https://e.com">Link</a></b>\n1:00 Next'
    lines = markup.description_lines(text, recover_chapters=recovery)
    assert lines[0].text == "0:00 Intro</b\x00Link"
    start = lines[0].text.index("Link")
    assert lines[0].url_at(start) == "https://e.com"
    assert (
        lines[0].raw[lines[0].raw_start(start) : lines[0].raw_end(start + 3)] == "Link"
    )
    title = '<b>Intro</b\x00<a href="https://e.com">Link</a></b>'
    assert markup.inline_fragment(title) == title
    assert parse_description_chapters(text).chapters[0].title == title


@pytest.mark.parametrize("closing", [False, True])
@pytest.mark.parametrize("suffix", ['\x00x title="never', '\x00\n title="never'])
def test_nul_names_have_the_same_literal_boundary(closing, suffix):
    text = f"<{'/' if closing else ''}b{suffix}<strong>Visible</strong>\n0:00 Intro\n1:00 Next"
    for recovery in (False, True):
        cache = markup._TagCache(text, recover_chapters=recovery)
        token = cache.token(0)
        assert not token.complete
        assert token.end == text.index("\x00") + 1
        assert text[token.following :].startswith(suffix[1:])
        assert not cache.balanced(token, visible=None, source=None)
    assert "Visible" in strip_html(text)
    assert [c.start for c in parse_description_chapters(text).chapters] == [0, 60]


@pytest.mark.parametrize("gap", ["\n", "\r", "\r\n", " \n\t\n "])
@pytest.mark.parametrize("value", ["5", ">", "\n>", '"unfinished', "\n5"])
def test_cross_line_plain_values_that_are_not_closed_quotes_recover(gap, value):
    text = f'<img src="x.png"\n0:00 Intro{gap}= {value} > 3 facts\n1:00 Next\n2:00 Last'
    result = parse_description_chapters(text, strict=True, require_monotonic=True)
    assert [c.start for c in result.chapters] == [0, 60, 120]
    assert result.chapters[0].title == "Intro"


@pytest.mark.parametrize("gap", ["\n", "\r", "\r\n", " \n\t\n "])
@pytest.mark.parametrize("value_gap", ["", " ", "\n", "\r", "\r\n", "\n\n\t"])
@pytest.mark.parametrize("name", ["title", "@click"])
@pytest.mark.parametrize("quote", ["'", '"'])
def test_closed_quoted_values_may_begin_after_later_line_padding(
    gap, value_gap, name, quote
):
    text = f"<b\n0:00 {name}{gap}={value_gap}{quote}x>\n1:00 Fake{quote}>Real</b>\n2:00 Intro\n3:00 Next"
    result = parse_description_chapters(text, strict=True, require_monotonic=True)
    assert [(c.start, c.title) for c in result.chapters] == [
        (120, "Intro"),
        (180, "Next"),
    ]


@pytest.mark.parametrize("space", ["\v", "\x85", "\u2003", "\u2028"])
@pytest.mark.parametrize("position", ["name", "value"])
def test_evidence_uses_runtime_whitespace(space, position):
    name_gap = space if position == "name" else "\n"
    value_gap = space if position == "value" else ""
    text = f'<b\n0:00 title{name_gap}={value_gap}"x>\n1:00 Fake">Real</b>\n2:00 Intro\n3:00 Next'
    end = markup.chapter_timestamp_end(text, text.index("0:00"))
    assert (
        markup._has_attribute_assignment(text, end) is markup._UNICODE_ATTRIBUTE_SPACE
    )
    if markup._UNICODE_ATTRIBUTE_SPACE:
        assert [c.start for c in parse_description_chapters(text).chapters] == [
            120,
            180,
        ]


@pytest.mark.parametrize("equals", ["=", "==", "==="])
def test_cross_line_equals_follow_runtime_value_grammar(equals):
    text = f'0:00 title\n{equals}"x>y">'
    end = markup.chapter_timestamp_end(text, 0)
    assert markup._has_attribute_assignment(text, end) is (
        equals == "=" or markup._REPEATED_EQUALS
    )


@pytest.mark.parametrize("value", ["\n>", "\r>", "\r\n>", "\n5"])
def test_same_line_assignment_does_not_accept_a_boundary_as_bare_value(value):
    text = f"0:00 title ={value}"
    assert not markup._has_attribute_assignment(
        text, markup.chapter_timestamp_end(text, 0)
    )


@pytest.mark.parametrize("name", ["title", "#ref", "example.com?ref=pod", "Why 1+1"])
def test_evidence_does_not_follow_new_attribute_tokens_across_lines(name):
    text = f'0:00 {name}\nx="quoted">'
    assert not markup._has_attribute_assignment(
        text, markup.chapter_timestamp_end(text, 0)
    )


@pytest.mark.parametrize("separator", ["\f", "\v", "\x85", "\u2028"])
@pytest.mark.parametrize("boolean", ["", "#ref"])
def test_evidence_does_not_start_a_new_name_after_a_soft_separator(separator, boolean):
    text = f'0:00 {boolean}{separator}title="x>y">'
    assert not markup._has_attribute_assignment(
        text, markup.chapter_timestamp_end(text, 0)
    )


def test_same_line_bare_assignment_remains_deliberately_ambiguous():
    text = "0:00 Show x=y>"
    assert markup._has_attribute_assignment(text, markup.chapter_timestamp_end(text, 0))


def test_assignment_evidence_reuses_failed_quote_searches():
    class TrackedText(str):
        __slots__ = ()

        def find(self, sub, start=0, end=None):
            if sub == '"':
                searches.append(start)
            return super().find(sub, start, len(self) if end is None else end)

    searches = []
    missing = set()
    text = TrackedText('0:00 title\n="unfinished')
    end = markup.chapter_timestamp_end(text, 0)
    assert not markup._has_attribute_assignment(text, end, missing)
    assert not markup._has_attribute_assignment(text, end, missing)
    assert searches == [text.index('"') + 1]


@pytest.mark.parametrize("recovery", [False, True])
def test_quoted_evidence_and_scanning_use_bounded_shared_searches(recovery):
    class TrackedText(str):
        __slots__ = ()

        def find(self, sub, start=0, end=None):
            if sub == '"':
                searches.append(start)
            return super().find(sub, start, len(self) if end is None else end)

    searches = []
    text = TrackedText('<b\n0:00 title\n="x>\n1:00 Fake">Real</b>')
    end, nested = markup._tag_end(text, 2, recover_chapters=recovery)
    assert end == text.index('">') + 1
    assert not nested
    assert 1 <= len(searches) <= 2
    assert set(searches) == {text.index('"') + 1}
