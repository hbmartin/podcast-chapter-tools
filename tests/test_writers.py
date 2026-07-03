import json
from xml.etree import ElementTree

from podcast_chapter_tools.entities import Chapter
from podcast_chapter_tools.extractors import (
    extract_description_chapters,
    extract_pci_chapters,
    extract_psc_chapters,
)
from podcast_chapter_tools.writers import (
    chapters_to_description,
    chapters_to_pci_dict,
    chapters_to_pci_json,
    chapters_to_psc_xml,
)

CHAPTERS = [
    Chapter(0, "Intro"),
    Chapter(310, "Main topic", "https://example.com/topic"),
    Chapter(3722, "Outro", None, "https://example.com/outro.png"),
]


def test_pci_dict():
    doc = chapters_to_pci_dict(CHAPTERS)
    assert doc["version"] == "1.2.0"
    assert doc["chapters"] == [
        {"startTime": 0, "title": "Intro"},
        {"startTime": 310, "title": "Main topic", "url": "https://example.com/topic"},
        {"startTime": 3722, "title": "Outro", "img": "https://example.com/outro.png"},
    ]


def test_pci_json_roundtrip():
    rendered = chapters_to_pci_json(CHAPTERS, indent=2)
    assert extract_pci_chapters(json.loads(rendered)) == [
        (0, "Intro", None, None),
        (310, "Main topic", "https://example.com/topic", None),
        (3722, "Outro", None, "https://example.com/outro.png"),
    ]


def test_psc_xml_roundtrip():
    rendered = chapters_to_psc_xml(CHAPTERS)
    assert 'xmlns:psc="http://podlove.org/simple-chapters"' in rendered
    element = ElementTree.fromstring(rendered)
    assert extract_psc_chapters(element) == [
        (0, "Intro", None, None),
        (310, "Main topic", "https://example.com/topic", None),
        (3722, "Outro", None, "https://example.com/outro.png"),
    ]


def test_psc_xml_escapes_titles():
    rendered = chapters_to_psc_xml([Chapter(0, 'Q&A "special" <session>')])
    element = ElementTree.fromstring(rendered)
    chapters = extract_psc_chapters(element)
    assert chapters is not None
    assert chapters[0].title == 'Q&A "special" <session>'


def test_description_output():
    rendered = chapters_to_description(CHAPTERS)
    assert rendered.splitlines() == [
        "0:00 Intro",
        "5:10 Main topic https://example.com/topic",
        "1:02:02 Outro",
    ]


def test_description_roundtrip():
    rendered = chapters_to_description(CHAPTERS)
    chapters = extract_description_chapters(rendered)
    assert chapters is not None
    assert [c.start for c in chapters] == [0, 310, 3722]
    assert [c.title for c in chapters] == [
        "Intro",
        "Main topic https://example.com/topic",
        "Outro",
    ]
    assert chapters[1].url == "https://example.com/topic"


def test_writers_accept_plain_tuples():
    doc = chapters_to_pci_dict([(0, "Intro", None, None)])
    assert doc["chapters"] == [{"startTime": 0, "title": "Intro"}]
