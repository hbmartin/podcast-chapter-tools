import json
from dataclasses import FrozenInstanceError
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest
from conftest import FEED_XML

from podcast_chapter_tools import (
    Chapter,
    ChapterData,
    ChapterParseError,
    chapters_to_description,
    chapters_to_pci_dict,
    chapters_to_pci_json,
    chapters_to_psc_xml,
    extract_all_psc_chapters_from_file,
    extract_pci_chapters,
    extract_psc_chapters,
    format_timestamp,
    normalize_chapter_data,
    parse_feed_chapters,
    parse_pci_chapters,
    parse_psc_chapters,
    parse_timestamp,
    parsers,
)


@pytest.mark.parametrize(
    "start",
    [
        None,
        True,
        False,
        "bogus",
        float("inf"),
        float("-inf"),
        float("nan"),
        -1,
        {},
        [],
        10**400,
    ],
)
def test_bad_start_salvages_valid_entry_and_strict_rejects(start):
    document = {
        "chapters": [{"startTime": start}, {"startTime": 61.5, "title": "Good"}]
    }
    result = parse_pci_chapters(document, source="feed", guid="episode")
    assert result.chapters == (ChapterData(61.5, "Good"),)
    assert result.issues[0].index == 0
    assert result.issues[0].field == "startTime"
    assert result.source == "feed"
    assert result.guid == "episode"
    assert extract_pci_chapters(document) == [Chapter(61, "Good")]
    with pytest.raises(ChapterParseError) as caught:
        parse_pci_chapters(document, strict=True, source="feed", guid="episode")
    assert caught.value.issues
    assert caught.value.guid == "episode"


def test_infinite_json_never_escapes_as_overflow():
    document = json.loads('{"chapters": [{"startTime": 1e999}]}')
    with pytest.raises(ChapterParseError):
        parse_pci_chapters(document)
    assert extract_pci_chapters(document) is None


@pytest.mark.parametrize(
    "document",
    [{}, {"chapters": None}, {"chapters": {}}, {"chapters": "bad"}, None, []],
)
def test_invalid_document_shape(document):
    with pytest.raises(ChapterParseError):
        parse_pci_chapters(document)


@pytest.mark.parametrize("entries", [[{}], [None], ["bad"], [{"startTime": "bad"}]])
def test_no_usable_structured_entries_is_failure(entries):
    with pytest.raises(ChapterParseError) as caught:
        parse_pci_chapters({"chapters": entries})
    assert caught.value.issues


def test_empty_chapters_is_successful_absence():
    assert not parse_pci_chapters({"chapters": []}).chapters
    assert not parse_psc_chapters(ElementTree.fromstring("<chapters/>")).chapters
    assert extract_pci_chapters({"chapters": []}) == []


def test_untitled_and_invalid_optional_fields():
    result = parse_pci_chapters(
        {
            "chapters": [
                {"startTime": 0},
                {
                    "startTime": 1,
                    "title": None,
                    "url": 12,
                    "img": [],
                    "toc": "false",
                    "endTime": -2,
                },
            ]
        }
    )
    assert result.chapters == (ChapterData(0), ChapterData(1))
    assert {i.field for i in result.issues} == {"title", "url", "img", "toc", "endTime"}
    assert all(i.index == 1 for i in result.issues)
    assert result.to_legacy() == [Chapter(0, ""), Chapter(1, "")]


def test_numeric_strings_are_reported_and_strict_rejects():
    document = {"chapters": [{"startTime": "61.5", "endTime": "70.25"}]}
    result = parse_pci_chapters(document)
    assert result.chapters[0] == ChapterData(61.5, end=70.25)
    assert [i.code for i in result.issues] == ["coerced_number", "coerced_number"]
    with pytest.raises(ChapterParseError):
        parse_pci_chapters(document, strict=True)


@pytest.mark.parametrize("end", [None, float("inf"), True, -1, 9])
def test_invalid_end_is_omitted(end):
    result = parse_pci_chapters({"chapters": [{"startTime": 10, "endTime": end}]})
    assert result.chapters[0].end is None
    assert result.issues[0].field == "endTime"


def test_metadata_roundtrip_and_legacy_marker_filter():
    document = {
        "chapters": [
            {"startTime": 0.25, "title": "Intro", "endTime": 61.5},
            {"startTime": 61.5, "toc": False, "img": "https://example.com/art"},
        ]
    }
    result = parse_pci_chapters(document)
    assert (
        parse_pci_chapters(json.loads(chapters_to_pci_json(result.chapters))).chapters
        == result.chapters
    )
    assert chapters_to_pci_dict(result.chapters)["chapters"] == document["chapters"]
    assert extract_pci_chapters(document) == [Chapter(0, "Intro")]
    assert extract_pci_chapters(document, include_non_toc=True) == [
        Chapter(0, "Intro"),
        Chapter(61, "", None, "https://example.com/art"),
    ]
    psc = parse_psc_chapters(
        ElementTree.fromstring(chapters_to_psc_xml(result.chapters))
    )
    assert psc.chapters == (ChapterData(0.25, "Intro"),)
    assert chapters_to_description(result.chapters) == "0:00.25 Intro"
    with pytest.raises(FrozenInstanceError):
        result.chapters[0].start = 20


def test_psc_recovers_others_but_requires_title():
    xml = '<chapters><chapter start="0:01.25" title="Good"/><chapter start="10"/><chapter start="bad" title="Bad"/></chapters>'
    element = ElementTree.fromstring(xml)
    result = parse_psc_chapters(element)
    assert result.chapters == (ChapterData(1.25, "Good"),)
    assert {i.field for i in result.issues} == {"title", "start"}
    assert extract_psc_chapters(element) == [Chapter(1, "Good")]
    with pytest.raises(ChapterParseError):
        parse_psc_chapters(element, strict=True)


@pytest.mark.parametrize(
    "element", [None, {}, "<chapters/>", ElementTree.Element("wrong")]
)
def test_psc_rejects_wrong_document_shape(element):
    with pytest.raises(ChapterParseError):
        parse_psc_chapters(element)


def test_psc_validates_hand_built_element_fields():
    root = ElementTree.Element("chapters")
    ElementTree.SubElement(root, "chapter", {"start": None, "title": "Bad"})
    ElementTree.SubElement(root, "chapter", {"start": "1", "title": None})
    ElementTree.SubElement(
        root, "chapter", {"start": "2.5", "title": "Good", "href": None}
    )
    result = parse_psc_chapters(root)
    assert result.chapters == (ChapterData(2.5, "Good"),)
    assert [(issue.index, issue.field) for issue in result.diagnostics] == [
        (0, "start"),
        (1, "title"),
        (2, "href"),
    ]
    with pytest.raises(ChapterParseError):
        parse_psc_chapters(root, strict=True)


@pytest.mark.parametrize(
    ("time", "seconds"),
    [
        ("35:12.250", 2112.25),
        ("37.125", 37.125),
        ("1:02:03.5", 3723.5),
        ("0:00.000001", 0.000001),
    ],
)
def test_fractional_time_helpers(time, seconds):
    assert parse_timestamp(time) == seconds
    assert parse_timestamp(format_timestamp(seconds)) == seconds


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf"), True])
def test_format_rejects_invalid_time(seconds):
    with pytest.raises(ValueError):
        format_timestamp(seconds)


def test_rich_normalization_retains_metadata():
    chapters = [
        ChapterData(3.5, "<b>B</b>", end=5, toc=False),
        ChapterData(0, None),
        ChapterData(3.5, "Duplicate"),
    ]
    result = normalize_chapter_data(chapters, strip_titles=True)
    assert result == [ChapterData(0), ChapterData(3.5, "B", end=5, toc=False)]
    assert normalize_chapter_data([ChapterData(float("inf"))]) == []


def test_feed_index_reuses_xml_and_episode_parses(monkeypatch):
    xml_parse = Mock(wraps=parsers.ElementTree.fromstring)
    psc_parse = Mock(wraps=parsers.parse_psc_chapters)
    monkeypatch.setattr(parsers.ElementTree, "fromstring", xml_parse)
    monkeypatch.setattr(parsers, "parse_psc_chapters", psc_parse)
    index = parse_feed_chapters(FEED_XML.encode(), source="feed")
    first = index.psc_for_guid("guid-1")
    for _ in range(200):
        assert index.psc_for_guid("guid-1") is first
    assert xml_parse.call_count == 1
    assert psc_parse.call_count == 1
    assert not index.psc_for_guid("missing").chapters
    assert index.pci_url_for_guid("missing") is None


def test_duplicate_and_bad_episode_are_isolated(tmp_path):
    xml = """<rss xmlns:psc="http://podlove.org/simple-chapters"><channel>
    <item><guid>bad</guid><psc:chapters><psc:chapter start="0"/></psc:chapters></item>
    <item><guid>good</guid><psc:chapters><psc:chapter start="1.25" title="First"/></psc:chapters></item>
    <item><guid>good</guid><psc:chapters><psc:chapter start="2" title="Duplicate"/></psc:chapters></item>
    </channel></rss>"""
    index = parse_feed_chapters(xml)
    assert index.guids == ("bad", "good")
    assert index.issues[0].code == "duplicate_guid"
    with pytest.raises(ChapterParseError):
        index.psc_for_guid("bad")
    assert index.psc_for_guid("good").chapters == (ChapterData(1.25, "First"),)
    path = tmp_path / "feed.xml"
    path.write_text(xml)
    assert extract_all_psc_chapters_from_file(path) == {"good": [Chapter(1, "First")]}


def test_feed_strict_lookup_reuses_tolerant_result():
    xml = '<rss xmlns:psc="http://podlove.org/simple-chapters"><channel><item><guid>g</guid><psc:chapters><psc:chapter start="0" title="A"/><psc:chapter start="1"/></psc:chapters></item></channel></rss>'
    index = parse_feed_chapters(xml)
    assert index.psc_for_guid("g").chapters
    with pytest.raises(ChapterParseError):
        index.psc_for_guid("g", strict=True)
    assert index.psc_for_guid("g").chapters


def test_namespace_alias_and_canonical_preference():
    xml = '<rss xmlns:old="https://github.com/Podcastindex-org/podcast-namespace/blob/main/docs/1.0.md" xmlns:new="https://podcastindex.org/namespace/1.0"><channel><item><guid>g</guid><old:chapters url="old"/><new:chapters url="new"/></item></channel></rss>'
    assert parse_feed_chapters(xml).pci_url_for_guid("g") == "new"
    assert (
        parse_feed_chapters(
            xml.replace('<new:chapters url="new"/>', "")
        ).pci_url_for_guid("g")
        == "old"
    )


@pytest.mark.parametrize("xml", ["bad <", "<rss/>", b"\xff"])
def test_feed_errors_are_typed(xml):
    with pytest.raises(ChapterParseError):
        parse_feed_chapters(xml)
