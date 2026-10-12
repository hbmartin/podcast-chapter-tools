import subprocess
import sys

import pytest

from podcast_chapter_tools import (
    ChapterParseError,
    extract_description_chapters,
    parse_description_chapters,
    strip_html,
)


@pytest.mark.parametrize("punctuation", ["(part 1)", "[part 1]"])
def test_punctuation_titles_are_retained(punctuation):
    text = f"0:00 Intro\n5:00 Interview {punctuation}\n10:00 Interview {punctuation}\n15:00 Wrap-up"
    assert len(parse_description_chapters(text).chapters) == 4
    assert extract_description_chapters(text)[1].title == f"Interview {punctuation}"


def test_prose_is_not_a_chapter_list():
    assert not parse_description_chapters("10:30 to 11:45 on a Tuesday").chapters
    assert extract_description_chapters("At 0:00 we start\nAt 5:00 we end") is None


def test_unicode_separators_and_fractional_wrappers():
    text = "[0:00.25] \u2013 Intro\r\n(5:00.5) \u2014 Main"
    result = parse_description_chapters(text)
    assert [(c.start, c.title) for c in result.chapters] == [
        (0.25, "Intro"),
        (300.5, "Main"),
    ]


def test_optional_sequence_rules():
    descending = "5:00 Second\n0:00 First"
    assert len(parse_description_chapters(descending).chapters) == 2
    with pytest.raises(ChapterParseError):
        parse_description_chapters(descending, require_monotonic=True)
    with pytest.raises(ChapterParseError):
        parse_description_chapters("1:00 A\n2:00 B", require_zero_start=True)
    assert parse_description_chapters(
        "0:00.5 A\n2:00 B", require_zero_start=True
    ).chapters


def test_invalid_time_is_reported_without_suffix_reinterpretation():
    result = parse_description_chapters(
        "0:00 Intro\n1:99 Bad\n100:00:00 Long\n2:00 End"
    )
    assert [c.start for c in result.chapters] == [0, 360000, 120]
    assert len(result.issues) == 1
    with pytest.raises(ChapterParseError):
        parse_description_chapters("0:00 A\n99:99 B\n1:00 C", strict=True)


def test_tag_attributes_comments_scripts_are_not_chapters():
    text = '<div title="0:00 Intro 5:00 Main"></div><!-- 0:00 Intro 5:00 Main --><script>0:00 Intro\n5:00 Main</script>'
    assert not parse_description_chapters(text, mode="lenient").chapters


def test_html_boundaries_markup_and_escaped_text():
    text = '<div>0:00 <a href="https://example.com">A &amp; B</a></div><li>5:00 <b>Next</b></li>'
    rich = parse_description_chapters(text)
    assert rich.chapters[0].title == '<a href="https://example.com">A &amp; B</a>'
    assert rich.chapters[0].url == "https://example.com"
    stripped = parse_description_chapters(text, strip_html=True)
    assert [c.title for c in stripped.chapters] == ["A & B", "Next"]
    assert strip_html("A &lt;concept&gt; &amp; B") == "A <concept> & B"


@pytest.mark.parametrize(
    "tag", ["p", "div", "li", "header", "dt", "dd", "td", "figure"]
)
def test_block_tags_establish_description_lines(tag):
    text = f"<{tag}>0:00 Intro</{tag}><{tag}>1:00 End</{tag}>"
    assert [chapter.title for chapter in parse_description_chapters(text).chapters] == [
        "Intro",
        "End",
    ]


@pytest.mark.parametrize("mode", ["strict", "lenient"])
def test_adversarial_inputs_finish_under_five_seconds(mode):
    # A subprocess timeout protects the entire suite if a scanner regresses.
    code = """
import sys
from podcast_chapter_tools import extract_description_chapters, parse_description_chapters, normalize_chapters
mode = sys.argv[1]
for whitespace in (' ', '\\t', '\\u00a0'):
    for bracket in ('(', '['):
        text = '[0:00]' + whitespace * 100_000 + bracket + '\\n1:00 End'
        parse_description_chapters(text, mode=mode)
        extract_description_chapters('<p>' + text + '</p>', mode=mode, strip_html=True)
for markup in ('<' * 100_000, '<a ' + ' ' * 100_000, '<a x="' + 'x' * 100_000):
    text = '0:00 Intro ' + markup + '\\n1:00 End'
    chapters = extract_description_chapters(text, mode=mode, strip_html=True)
    normalize_chapters(chapters or [], strip_titles=True)
inline = ' '.join(f'{i // 60}:{i % 60:02} Chapter' for i in range(4000))
result = parse_description_chapters(inline, mode='lenient')
assert len(result.chapters) == 4000
attributes = '<custom\\n' + '0:00 disabled alt="x"\\n' * 4000 + '>\\n0:00 Intro\\n1:00 End'
assert len(parse_description_chapters(attributes, mode=mode).chapters) == 2
closings = '<script>' + '</scripture>' * 100_000 + '</script foo=">">\\n0:00 Intro\\n1:00 End'
assert len(parse_description_chapters(closings, mode=mode).chapters) == 2
raw_tags = '<script/><style/><script x=/>a<b</script><style>a<b</style>' * 2000
assert len(parse_description_chapters(raw_tags + '\\n0:00 Intro\\n1:00 End', mode=mode).chapters) == 2
"""
    subprocess.run(  # noqa: S603 - fixed test script, interpreter, and mode fixture
        [sys.executable, "-c", code, mode], check=True, timeout=5, capture_output=True
    )


def test_logging_disabled_and_http_not_imported_for_pure_parsers():
    code = """
import sys
from podcast_chapter_tools import extract_pci_chapters, parse_description_chapters
assert 'httpx2' not in sys.modules
assert extract_pci_chapters({'chapters': [{'startTime': 'bad'}]}) is None
assert len(parse_description_chapters('0:00 A\\n1:00 B').chapters) == 2
"""
    run = subprocess.run(  # noqa: S603 - fixed test script and interpreter
        [sys.executable, "-c", code], check=True, timeout=5, capture_output=True
    )
    assert run.stderr == b""


def test_plain_punctuation_is_not_html_escaped_by_default():
    result = parse_description_chapters("0:00 A & B\n1:00 C > D")
    assert [c.title for c in result.chapters] == ["A & B", "C > D"]


def test_wrappers_around_timestamp_do_not_leave_closing_tags():
    result = parse_description_chapters("<b>0:00 Intro</b><br><b>1:00 End</b>")
    assert [c.title for c in result.chapters] == ["Intro", "End"]
    result = parse_description_chapters(
        '<a href="https://example.com">0:00 Intro</a><br>1:00 End'
    )
    assert result.chapters[0].title == "Intro"
    assert result.chapters[0].url == "https://example.com"


def test_unfinished_comment_preserves_following_plain_text():
    result = parse_description_chapters("0:00 Literal <!-- today\n1:00 End")
    assert [c.title for c in result.chapters] == ["Literal <!-- today", "End"]
    assert (
        strip_html("Explain <!-- and its HTML meaning")
        == "Explain <!-- and its HTML meaning"
    )
