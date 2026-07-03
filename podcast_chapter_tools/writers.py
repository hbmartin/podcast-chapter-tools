"""Serialize chapters to PCI JSON, PSC XML, and description-embed text."""

import json
from collections.abc import Iterable
from typing import Any
from xml.etree import ElementTree

from .entities import Chapter
from .timecodes import secs_to_ts

PCI_VERSION = "1.2.0"
PSC_VERSION = "1.2"
PSC_NAMESPACE = "http://podlove.org/simple-chapters"


def chapters_to_pci_dict(chapters: Iterable[Chapter]) -> dict[str, Any]:
    """Build a PodcastIndex chapters document as a dict."""
    pci_chapters = []
    for chapter in chapters:
        chapter_ = Chapter(*chapter)
        entry: dict[str, Any] = {"startTime": chapter_.start, "title": chapter_.title}
        if chapter_.url is not None:
            entry["url"] = chapter_.url
        if chapter_.image is not None:
            entry["img"] = chapter_.image
        pci_chapters.append(entry)
    return {"version": PCI_VERSION, "chapters": pci_chapters}


def chapters_to_pci_json(
    chapters: Iterable[Chapter],
    indent: int | None = None,
) -> str:
    """Serialize chapters to a PodcastIndex chapters JSON string."""
    return json.dumps(chapters_to_pci_dict(chapters), indent=indent)


def chapters_to_psc_element(chapters: Iterable[Chapter]) -> ElementTree.Element:
    """Build a ``<psc:chapters>`` element containing the given chapters."""
    ElementTree.register_namespace("psc", PSC_NAMESPACE)
    root = ElementTree.Element(
        f"{{{PSC_NAMESPACE}}}chapters",
        {"version": PSC_VERSION},
    )
    for chapter in chapters:
        chapter_ = Chapter(*chapter)
        attrib = {"start": secs_to_ts(chapter_.start), "title": chapter_.title}
        if chapter_.url is not None:
            attrib["href"] = chapter_.url
        if chapter_.image is not None:
            attrib["image"] = chapter_.image
        ElementTree.SubElement(root, f"{{{PSC_NAMESPACE}}}chapter", attrib)
    return root


def chapters_to_psc_xml(chapters: Iterable[Chapter]) -> str:
    """Serialize chapters to a Podlove Simple Chapters XML string."""
    return ElementTree.tostring(
        chapters_to_psc_element(chapters),
        encoding="unicode",
    )


def chapters_to_description(chapters: Iterable[Chapter]) -> str:
    """Serialize chapters to description-embed text (one chapter per line)."""
    lines = []
    for chapter in chapters:
        chapter_ = Chapter(*chapter)
        line = f"{secs_to_ts(chapter_.start)} {chapter_.title}"
        if chapter_.url is not None and chapter_.url not in chapter_.title:
            line += f" {chapter_.url}"
        lines.append(line)
    return "\n".join(lines)
