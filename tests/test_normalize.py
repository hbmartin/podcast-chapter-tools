from podcast_chapter_tools.entities import Chapter
from podcast_chapter_tools.normalize import normalize_chapters, strip_html


def test_strip_html():
    assert strip_html('<a href="https://x.com">A &amp; B</a>') == "A & B"
    assert strip_html("plain title") == "plain title"
    assert strip_html("a<br>b") == "a b"


def test_sorts_by_start():
    chapters = [Chapter(60, "b"), Chapter(0, "a"), Chapter(30, "c")]
    assert [c.title for c in normalize_chapters(chapters)] == ["a", "c", "b"]


def test_sort_disabled():
    chapters = [Chapter(60, "b"), Chapter(0, "a")]
    assert [c.title for c in normalize_chapters(chapters, sort=False)] == ["b", "a"]


def test_dedupes_repeated_starts():
    chapters = [Chapter(0, "a"), Chapter(0, "dup"), Chapter(10, "b")]
    assert [c.title for c in normalize_chapters(chapters)] == ["a", "b"]


def test_dedupe_disabled():
    chapters = [Chapter(0, "a"), Chapter(0, "dup")]
    assert len(normalize_chapters(chapters, dedupe=False)) == 2


def test_clamps_to_max_start():
    chapters = [Chapter(0, "a"), Chapter(5000, "past-the-end")]
    assert [c.title for c in normalize_chapters(chapters, max_start=3600)] == ["a"]


def test_drops_negative_starts():
    chapters = [Chapter(-5, "bad"), Chapter(0, "a")]
    assert [c.title for c in normalize_chapters(chapters)] == ["a"]


def test_strip_titles():
    chapters = [Chapter(0, "<b>Intro</b>")]
    assert normalize_chapters(chapters, strip_titles=True)[0].title == "Intro"


def test_accepts_plain_tuples():
    result = normalize_chapters([(10, "b", None, None), (0, "a", None, None)])
    assert result == [Chapter(0, "a"), Chapter(10, "b")]
    assert isinstance(result[0], Chapter)
