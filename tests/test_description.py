from podcast_chapter_tools.extractors import extract_description_chapters

PLAIN_TEXT = """Welcome to the show!

0:00 Intro
2:30 Interview with Jane
1:02:03 Wrap-up
"""

HTML_BREAKS = (
    "<p>Chapters:</p>"
    "<p>(00:00) - Intro<br>"
    "(05:10) - The main topic<br>"
    "(59:59) - Outro</p>"
)

BRACKETED = """[0:00] Cold open
[12:34] Listener questions
"""

WITH_LINK = """0:00 Intro
5:00 Sponsor https://example.com/deal
10:00 Outro
"""

SINGLE_HTML_RUN = "<p>0:00 Intro 5:00 Topic two 10:00 The end</p>"


def test_plain_text_lines():
    chapters = extract_description_chapters(PLAIN_TEXT)
    assert chapters == [
        (0, "Intro", None, None),
        (150, "Interview with Jane", None, None),
        (3723, "Wrap-up", None, None),
    ]


def test_html_with_breaks():
    chapters = extract_description_chapters(HTML_BREAKS)
    assert chapters == [
        (0, "Intro", None, None),
        (310, "The main topic", None, None),
        (3599, "Outro", None, None),
    ]


def test_bracketed_timestamps():
    chapters = extract_description_chapters(BRACKETED)
    assert chapters is not None
    assert [c.start for c in chapters] == [0, 754]
    assert chapters[0].title == "Cold open"


def test_url_extracted_from_title():
    chapters = extract_description_chapters(WITH_LINK)
    assert chapters is not None
    assert chapters[1].url == "https://example.com/deal"
    assert chapters[0].url is None


def test_retry_splits_single_run():
    chapters = extract_description_chapters(SINGLE_HTML_RUN)
    assert chapters is not None
    assert [c.start for c in chapters] == [0, 300, 600]
    assert chapters[0].title == "Intro"
    assert chapters[1].title == "Topic two"


def test_invalid_timestamp_is_skipped():
    # "99:99" matches the chapter regex but is not a valid timestamp
    # (minutes/seconds must be < 60), so it is dropped while the valid
    # chapters are kept.
    description = "0:00 Intro\n99:99 Bad timestamp\n10:00 The end\n"
    chapters = extract_description_chapters(description)
    assert chapters == [
        (0, "Intro", None, None),
        (600, "The end", None, None),
    ]


def test_no_chapters_returns_none():
    assert extract_description_chapters("Just some show notes.") is None


def test_single_timestamp_returns_none():
    assert extract_description_chapters("At 12:30 we talk about X.") is None


def test_strip_html_titles():
    description = '0:00 Intro<br>5:00 <a href="https://example.com">A &amp; B</a><br>'
    chapters = extract_description_chapters(description, strip_html=True)
    assert chapters is not None
    assert chapters[1].title == "A & B"
    assert chapters[1].url == "https://example.com"


def test_chapter_fields_accessible_by_name():
    chapters = extract_description_chapters(PLAIN_TEXT)
    assert chapters is not None
    assert chapters[0].start == 0
    assert chapters[0].title == "Intro"
    # Still unpacks like the legacy tuple
    start, title, url, image = chapters[0]
    assert (start, title, url, image) == (0, "Intro", None, None)
