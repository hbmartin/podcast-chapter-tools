# Private source spans and lexical facts are deliberate regression targets.
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
    "suffix",
    ["\x00>", '\x00 class=">">', '\x00tail class="x>y">', '\x00\n class="x>y">'],
)
def test_nul_closings_discard_attributes_and_close_links(suffix, recovery):
    text = f'0:00 <a href="https://e.com">Intro</a{suffix}\n1:00 Next\n2:00 Last'
    lines = markup.description_lines(text, recover_chapters=recovery)
    assert [line.text for line in lines] == ["0:00 Intro", "1:00 Next", "2:00 Last"]
    assert lines[0].raw == '0:00 <a href="https://e.com">Intro</a>'
    assert [line.url_at(5) for line in lines] == ["https://e.com", None, None]
    assert lines[0].raw[lines[0].raw_start(5) : lines[0].raw_end(9)] == "Intro"
    assert strip_html(text) == "0:00 Intro 1:00 Next 2:00 Last"
    assert [(c.title, c.url) for c in parse_description_chapters(text).chapters] == [
        ('<a href="https://e.com">Intro</a>', "https://e.com"),
        ("Next", None),
        ("Last", None),
    ]


@pytest.mark.parametrize("name", ["b", "custom", "aİİ"])
def test_nul_closing_fragment_is_canonical(name):
    text = f'<{name}>Intro</{name}\x00 class=">">'
    assert strip_html(text) == "Intro"
    assert markup.inline_fragment(text) == f"<{name}>Intro</{name.lower()}>"


@pytest.mark.parametrize("prefix", ["", "<unclosed\n>"])
def test_nul_closing_still_balances_formatted_anchor(prefix):
    text = prefix + '<a href="https://e.com"\n>0:00 Intro</a\x00 class=">">\n1:00 Next'
    assert [
        (c.start, c.title, c.url) for c in parse_description_chapters(text).chapters
    ] == [
        (0, "Intro", "https://e.com"),
        (60, "Next", None),
    ]


def test_unfinished_nul_closing_remains_literal():
    text = '<a href="https://e.com">Intro</a\x00'
    assert strip_html(text) == "Intro</a\x00"


@pytest.mark.parametrize("tag", ["script", "style"])
def test_nul_does_not_widen_raw_closing_name_matching(tag):
    assert strip_html(f"<{tag}>hidden</{tag}\x00>visible") == ""


@pytest.mark.parametrize("gap", ["\n", "\r", "\r\n", " \n\t\n ", "\r\n\t\r\n"])
@pytest.mark.parametrize(
    "name", ["title", "1x", "标题", "@click", "[(ngModel)]", "on:click|once"]
)
@pytest.mark.parametrize("boolean", ["", "#ref "])
def test_timestamp_attribute_evidence_connects_multiline_assignment(gap, name, boolean):
    text = (
        f'<b\n0:00 {boolean}{name}{gap}="x>\n1:00 Fake">Real</b>\n'
        '2:00 <a href="https://e.com">Intro</a>\n3:00 Next'
    )
    control = text.replace(f"{name}{gap}=", f"{name} =")
    result = parse_description_chapters(text, strict=True, require_monotonic=True)
    assert result.chapters == parse_description_chapters(control).chapters
    assert [(c.start, c.title, c.url) for c in result.chapters] == [
        (120, '<a href="https://e.com">Intro</a>', "https://e.com"),
        (180, "Next", None),
    ]


@pytest.mark.parametrize(
    "continuation",
    ['title\nx="y"', '#ref\nx="y"', 'Why 1+1\n="y"', 'example.com?ref=pod\n="y"'],
)
def test_multiline_evidence_does_not_follow_new_tokens(continuation):
    text = "<b\n0:00 " + continuation + ">Real</b>\n1:00 Next"
    assert [c.start for c in parse_description_chapters(text).chapters] == [0, 60]


@pytest.mark.parametrize("value", [">", " \t>", '"x>y">', "bare>", '=">'])
@pytest.mark.parametrize("name", ["title", "@click"])
def test_multiline_evidence_preserves_same_line_value_rules(name, value):
    text = f"0:00 {name} =" + value
    multiline = text.replace(f"{name} =", f"{name}\n=")
    end = markup.chapter_timestamp_end(text, 0)
    assert markup._has_attribute_assignment(
        multiline, end
    ) == markup._has_attribute_assignment(text, end)


def test_long_whitespace_assignment_keeps_quoted_timestamps_hidden():
    gap = "\n\t " * 20000
    text = f'<b\n0:00 title{gap}="x>\n1:00 Fake">Real</b>\n2:00 Intro\n3:00 Next'
    assert [c.start for c in parse_description_chapters(text).chapters] == [120, 180]


@pytest.mark.parametrize("value", ["", None, 0, False, True, 2, "yes"])
def test_cache_stores_boolean_recovery_flags(value):
    cache = markup._TagCache("<b>x</b>", recover_chapters=value)
    assert cache.recover is bool(value)
    token = cache.token(0)
    assert isinstance(token.multiline, bool)
    assert cache.balanced(token, visible=None, source=None)


def test_import_path_control_can_select_competing_package(competing_package):
    root = Path(__file__).resolve().parents[1]
    code = "from podcast_chapter_tools import errors; print(errors.__file__)"
    correct = subprocess.run(  # noqa: S603 - Fixed positive/negative import control.
        [sys.executable, "-P", "-c", code],
        cwd=root,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(root), str(competing_package))),
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    assert (
        Path(correct.stdout.strip()).resolve()
        == root / "podcast_chapter_tools" / "errors.py"
    )
    competing = subprocess.run(  # noqa: S603 - Deliberately select the decoy.
        [sys.executable, "-P", "-c", code],
        cwd=root,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(competing_package), str(root))),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert competing.returncode != 0
    assert "Imported the competing installed copy" in competing.stderr
