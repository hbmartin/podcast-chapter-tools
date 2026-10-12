import subprocess
import sys

import pytest

from podcast_chapter_tools import (
    ChapterParseError,
    extract_description_chapters,
    normalize_chapters,
    parse_description_chapters,
    strip_html,
)
from podcast_chapter_tools.cli import main


@pytest.mark.parametrize(
    "prefix",
    ["- ", "* ", "+ ", "• ", "1. ", "1) ", "Chapters: ", "> Chapters: - "],
)
@pytest.mark.parametrize("mode", ["strict", "lenient"])
def test_common_chapter_prefixes(prefix, mode):
    result = parse_description_chapters(
        f"{prefix}[0:00] Intro\n{prefix}(5:00) Next", mode=mode, strict=True
    )
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, "Intro"),
        (300, "Next"),
    ]


@pytest.mark.parametrize("prefix", ["-", "*", "+", "•", "1.", "1)", "At "])
def test_strict_recognition_rejects_non_list_prefixes(prefix):
    assert not parse_description_chapters(
        f"{prefix}0:00 Intro\n{prefix}5:00 Next"
    ).chapters


@pytest.mark.parametrize("prefix", ["\ufeff", "\u200b", " \ufeff\u200b"])
@pytest.mark.parametrize("mode", ["strict", "lenient"])
def test_leading_format_characters_preserve_chapters_and_title_offsets(prefix, mode):
    result = parse_description_chapters(
        f'{prefix}cHaPtErS: 0:00 <a href="https://example.com">In\u200btro</a>'
        f"\n{prefix}1:00 Next",
        mode=mode,
        strict=True,
    )
    assert result.chapters[0].title == '<a href="https://example.com">In\u200btro</a>'
    assert result.chapters[0].url == "https://example.com"
    assert [c.start for c in result.chapters] == [0, 60]


@pytest.mark.parametrize("prefix", ["\ufeff", "\u200b"])
def test_cli_description_accepts_bom_and_zero_width_space(tmp_path, capsys, prefix):
    path = tmp_path / "notes.txt"
    path.write_text(f"{prefix}0:00 Intro\n1:00 Next", encoding="utf-8")
    assert main(["from-description", str(path), "--to", "description"]) == 0
    assert capsys.readouterr().out == "0:00 Intro\n1:00 Next\n"


@pytest.mark.parametrize("mode", ["strict", "lenient"])
def test_punctuation_delimiters_and_fractions(mode):
    result = parse_description_chapters(
        "00:00: Intro\n0:01. Next\n[0:02.] Third\n(0:03:) Fourth\n0:04.25 Fifth",
        mode=mode,
        strict=True,
    )
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, "Intro"),
        (1, "Next"),
        (2, "Third"),
        (3, "Fourth"),
        (4.25, "Fifth"),
    ]


@pytest.mark.parametrize("mode", ["strict", "lenient"])
def test_invalid_timestamp_is_not_reinterpreted(mode):
    result = parse_description_chapters(
        "0:00 Intro\n1:99. Invalid\n1:00:: Invalid\n1:00.. Invalid\n2:00 End",
        mode=mode,
    )
    assert [c.start for c in result.chapters] == [0, 120]
    assert len(result.issues) == 3
    with pytest.raises(ChapterParseError):
        parse_description_chapters(
            "0:00 Intro\n99:99. Invalid\n2:00 End", mode=mode, strict=True
        )


def test_lenient_prose_without_title_is_ignored_but_explicit_lines_are_diagnosed():
    result = parse_description_chapters(
        "We start at 1:00.\n0:00 Intro\n2:00 End", mode="lenient", strict=True
    )
    assert not result.issues
    assert [c.start for c in result.chapters] == [0, 120]
    with pytest.raises(ChapterParseError) as caught:
        parse_description_chapters("0:00.\n1:00 Next", mode="lenient", strict=True)
    assert caught.value.issues[0].code == "missing_title"


@pytest.mark.parametrize("prefix", ["", "- ", "Chapters: ", "\ufeff"])
def test_unfinished_tag_does_not_swallow_chapter_lines(prefix):
    result = parse_description_chapters(
        f"0:00 Intro\n1:00 When x<y it matters\n{prefix}2:00 Next\n3:00 Last > end"
    )
    assert [c.title for c in result.chapters] == [
        "Intro",
        "When x<y it matters",
        "Next",
        "Last > end",
    ]


@pytest.mark.parametrize("tag", ["script", "style"])
@pytest.mark.parametrize(
    "body", ["if (a<b) run();", 'a<b && c<d; "<"', "'<a x=\"unterminated'"]
)
def test_raw_text_closing_tags_survive_comparisons_and_quotes(tag, body):
    result = parse_description_chapters(
        f"<{tag}>{body}</{tag.upper()} >\n0:00 Intro\n1:00 End", strict=True
    )
    assert [c.title for c in result.chapters] == ["Intro", "End"]
    assert not parse_description_chapters(
        f"<{tag}>{body}\n0:00 Intro\n1:00 End"
    ).chapters


def test_arbitrary_tags_multiline_attributes_and_entity_offsets():
    text = (
        '0:00 <custom\n attr="value">Intro</custom>\n'
        '1:00 <a href="https://example.com/?a=1&amp;b=2" title="\n2:00 Hidden">'
        "A &amp; B &#x1F600; &NotEqualTilde;</a>\n2:00 End"
    )
    result = parse_description_chapters(text)
    assert len(result.chapters) == 3
    assert result.chapters[0].title == '<custom\n attr="value">Intro</custom>'
    assert result.chapters[1].url == "https://example.com/?a=1&b=2"
    assert (
        parse_description_chapters(text, strip_html=True).chapters[1].title
        == "A & B 😀 ≂̸"
    )


def test_visible_inline_spacing_is_retained():
    assert strip_html("Part<b>One</b>") == "PartOne"
    chapters = extract_description_chapters("0:00 pod<b>cast</b>\n1:00 End")
    assert normalize_chapters(chapters, strip_titles=True)[0].title == "podcast"


@pytest.mark.parametrize("mode", ["strict", "lenient"])
def test_decoded_timestamp_and_inline_entity_boundaries(mode):
    separator = "\n" if mode == "strict" else " "
    result = parse_description_chapters(
        "(&#48;&#58;00) <b>A &amp; B</b>"
        + separator
        + '[&#49;&#58;00] <a href="https://example.com">Next&nbsp;part</a>',
        mode=mode,
        strict=True,
    )
    assert [c.title for c in result.chapters] == [
        "<b>A &amp; B</b>",
        '<a href="https://example.com">Next&nbsp;part</a>',
    ]
    assert result.chapters[1].url == "https://example.com"


def test_large_description_memory_is_bounded():
    code = """
import tracemalloc
from podcast_chapter_tools import parse_description_chapters
size = 5 * 1024 * 1024
text = '0:00 ' + 'x' * size + '\\n1:00 End'
tracemalloc.start()
result = parse_description_chapters(text)
_, peak = tracemalloc.get_traced_memory()
assert len(result.chapters) == 2
assert len(result.chapters[0].title) == size
assert peak < 64 * 1024 * 1024, peak
"""
    subprocess.run(  # noqa: S603 - fixed memory regression in an isolated interpreter.
        [sys.executable, "-c", code], check=True, capture_output=True, timeout=30
    )


@pytest.mark.parametrize(
    "tag", ["scr\u0131pt", "scr\u0130pt", "\u017fcript", "\u017ftyle"]
)
def test_unicode_raw_tag_lookalikes_do_not_crash(tag, tmp_path, capsys):
    text = f"<{tag}>hidden</{tag}>\n0:00 Intro\n1:00 End"
    assert [c.title for c in parse_description_chapters(text).chapters] == [
        "Intro",
        "End",
    ]
    assert "End" in strip_html(text)
    path = tmp_path / "notes.txt"
    path.write_text(text, encoding="utf-8")
    assert main(["from-description", str(path)]) == 0
    capsys.readouterr()


@pytest.mark.parametrize("tag", ["script", "style"])
@pytest.mark.parametrize("suffix", ["/>", " foo>", ' foo=">">', '\nfoo="x">'])
def test_raw_closing_tag_suffixes_restore_chapters(tag, suffix):
    text = f"<{tag}>if (a<b) go();</{tag.upper()}{suffix}\n0:00 Intro\n1:00 End"
    assert [c.title for c in parse_description_chapters(text).chapters] == [
        "Intro",
        "End",
    ]
    assert strip_html(text) == "0:00 Intro 1:00 End"


@pytest.mark.parametrize("tag", ["script", "style"])
def test_raw_attribute_slash_is_not_a_self_closing_marker(tag):
    assert (
        len(
            parse_description_chapters(
                f"<{tag} x=/>if (a<b) go();</{tag}>\n0:00 Intro\n1:00 End"
            ).chapters
        )
        == 2
    )
    assert not parse_description_chapters(f"<{tag} x=/>\n0:00 Intro\n1:00 End").chapters
    assert (
        len(parse_description_chapters(f"<{tag}/>\n0:00 Intro\n1:00 End").chapters) == 2
    )
    assert not parse_description_chapters(
        f"<{tag}>hidden</{tag}\xa0>\n0:00 Intro\n1:00 End"
    ).chapters


@pytest.mark.parametrize(
    "continuation",
    [
        '0:00 alt="y"',
        "0:00 disabled alt = y",
        '0:00 alt="\n2:00 hidden"',
        '0:00 alt =\n"y"',
    ],
)
def test_timestamp_like_attribute_continuations_stay_in_tags(continuation):
    text = f'<img src="x"\n{continuation}>\n1:00 Intro\n2:00 End'
    result = parse_description_chapters(text, mode="lenient", strict=True)
    assert [(c.start, c.title) for c in result.chapters] == [
        (60, "Intro"),
        (120, "End"),
    ]


def test_generic_stripping_does_not_recover_chapter_boundaries():
    assert strip_html("Call me at <a\n9:30 href=x>here</a>") == "Call me at here"
    assert strip_html("Call me at <a\n9:30 disabled>here</a>") == "Call me at here"


@pytest.mark.parametrize(
    "continuation", ["1:00 Next", '1:00 Intro "alt=y"', "1:00 Intro alt=>"]
)
def test_ambiguous_boolean_attributes_recover_chapters(continuation):
    text = f"0:00 Intro <span\n{continuation}\n2:00 End >"
    assert len(parse_description_chapters(text).chapters) == 3
    assert parse_description_chapters(text).chapters[0].title == "Intro <span"


@pytest.mark.parametrize("mode", ["strict", "lenient"])
@pytest.mark.parametrize(
    "separator", [":-", ":\u2013", ":\u2014", ".-", ".\u2013", ".\u2014"]
)
def test_timestamp_punctuation_before_dash_separators(mode, separator):
    result = parse_description_chapters(
        f"0:00{separator} Intro\n0:01.25-End", mode=mode, strict=True
    )
    assert [(c.start, c.title) for c in result.chapters] == [
        (0, "Intro"),
        (1.25, "End"),
    ]
    result = parse_description_chapters(
        f"0:99{separator} Invalid\n0:00 Intro\n1:00 End", mode=mode
    )
    assert [i.code for i in result.issues] == ["invalid_start"]


@pytest.mark.parametrize("token", ["12:30", "12:75", "12:75.", "12:30::"])
def test_titleless_lenient_prose_is_ignored_before_validation(token):
    result = parse_description_chapters(
        f"Discussed at {token}\n0:00 Intro\n1:00 End", mode="lenient", strict=True
    )
    assert not result.issues
    assert len(result.chapters) == 2
    with pytest.raises(ChapterParseError):
        parse_description_chapters(
            f"{token}\n0:00 Intro\n1:00 End", mode="lenient", strict=True
        )


@pytest.mark.parametrize(
    "mark", ["\u200c", "\u200d", "\u200e", "\u200f", "\u2060", "\u00ad", "\U000e0001"]
)
@pytest.mark.parametrize("mode", ["strict", "lenient"])
def test_all_leading_format_marks_preserve_title_characters(mark, mode):
    result = parse_description_chapters(
        f"{mark}0:00 <b>In{mark}tro</b>\n{mark}1:00 End", mode=mode, strict=True
    )
    assert [c.title for c in result.chapters] == [f"<b>In{mark}tro</b>", "End"]


def test_cli_pci_accepts_utf8_bom(tmp_path, capsys):
    path = tmp_path / "chapters.json"
    path.write_text(
        '{"chapters":[{"startTime":0,"title":"Intro"}]}', encoding="utf-8-sig"
    )
    assert main(["from-pci", str(path), "--to", "description"]) == 0
    assert capsys.readouterr().out == "0:00 Intro\n"
