import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx2
from loguru import logger

from .entities import (
    PCI,
    PSC,
    Chapter,
    _description_chapter,
    _re_url,
    _retry_description_chapter,
)
from .normalize import strip_html as _strip_html
from .timecodes import ts_to_secs

DEFAULT_TIMEOUT = 30.0

# Backwards-compatible alias for the pre-0.2 private helper.
_ts_to_secs = ts_to_secs


def extract_description_chapters(
    description: str,
    *,
    strip_html: bool = False,
) -> None | list[Chapter]:
    """Extract chapters from an episode description (plain text or HTML).

    Returns ``None`` when fewer than two chapters are found, since a single
    timestamp is more likely to be an incidental mention than a chapter list.
    Set ``strip_html`` to remove markup from chapter titles.
    """
    desc_chapters = _description_chapter.findall(description)
    chapters = _desc_matches_to_chapters(desc_chapters, strip_html=strip_html)
    if chapters is not None:
        return chapters
    if len(desc_chapters) == 1:
        retry_desc_chapters = _retry_description_chapter.findall(
            f"{desc_chapters[0][0]} {desc_chapters[0][1]}",
        )
        return _desc_matches_to_chapters(retry_desc_chapters, strip_html=strip_html)
    return None


def _desc_matches_to_chapters(
    matches: list[tuple[str, str]],
    *,
    strip_html: bool,
) -> None | list[Chapter]:
    if len(matches) < 2:  # noqa: PLR2004
        return None
    chapters = []
    for match in matches:
        try:
            chapters.append(_extract_desc_ts_and_title(match, strip_html=strip_html))
        except ValueError:
            logger.debug("Skipping invalid chapter timestamp: {}", match[0])
    return chapters if len(chapters) > 1 else None


def _extract_desc_ts_and_title(
    ts_title: tuple[str, str],
    *,
    strip_html: bool = False,
) -> Chapter:
    title = ts_title[1].strip()
    if "<a" in title and "</a>" not in title:
        title += "</a>"

    url = m[0] if (m := _re_url.search(title)) is not None else None
    if strip_html:
        title = _strip_html(title)

    return Chapter(ts_to_secs(ts_title[0]), title, url, None)


def extract_pci_chapters(chapters_json: dict[str, Any]) -> None | list[Chapter]:
    """Extract chapters from a parsed PodcastIndex chapters JSON document."""
    try:
        return [
            Chapter(int(c["startTime"]), c["title"], c.get("url"), c.get("img"))
            for c in chapters_json["chapters"]
        ]
    except (KeyError, ValueError, TypeError):
        logger.warning("Failed to extract PCI chapters from JSON document")
        return None


def get_and_extract_pci_chapters(
    url: str,
    headers: dict | None = None,
    archive_path_json: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> None | list[Chapter]:
    """Fetch a PodcastIndex chapters JSON document and extract its chapters.

    When ``archive_path_json`` is given, the raw JSON is read from (or written
    to) that path so repeated calls do not refetch the document.
    """
    if archive_path_json is not None and archive_path_json.exists():
        try:
            chapters_json = json.loads(archive_path_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Failed to read archived PCI chapters {}", archive_path_json)
            return None
    else:
        try:
            response = httpx2.get(
                url,
                headers=headers or {},
                timeout=timeout,
                follow_redirects=True,
            )
        except httpx2.RequestError as exc:
            logger.error("Error fetching chapters {}: {}", url, exc)
            return None
        if not response.is_success:
            logger.error(
                "Error {} fetching chapters {}",
                response.status_code,
                url,
            )
            return None
        try:
            chapters_json = response.json()
        except ValueError:
            logger.warning("Failed to decode PCI chapters JSON {}", url)
            return None
        if archive_path_json:
            try:
                archive_path_json.write_text(
                    json.dumps(chapters_json),
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning(
                    "Failed to write archived PCI chapters {}: {}",
                    archive_path_json,
                    exc,
                )

    chapters = extract_pci_chapters(chapters_json)
    if chapters is None:
        logger.warning("Failed to extract PCI for {} @ {}", url, archive_path_json)
    return chapters


def _iter_feed_items(root: ElementTree.Element) -> Iterator[ElementTree.Element]:
    channel = root.find("./channel")
    if channel is None:
        return
    for element in channel:
        if element.tag == "item":
            yield element


def _parse_feed(feed_xml: str, source: str) -> ElementTree.Element | None:
    try:
        root = ElementTree.fromstring(feed_xml)
    except ElementTree.ParseError:
        logger.warning("Failed to parse podcast feed {}", source)
        return None
    if root.find("./channel") is None:
        logger.warning("Failed to find channel in podcast feed {}", source)
        return None
    return root


def _read_feed_file(feed_file: Path) -> str | None:
    try:
        return feed_file.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        logger.error("Failed to read feed file {}: {}", feed_file, exc)
        return None


def extract_psc_chapters_from_file(feed_file: Path, guid: str) -> None | list[Chapter]:
    """Extract PSC chapters for the episode with ``guid`` from a feed file."""
    if not feed_file.exists():
        logger.error("File not found {}", feed_file)
        return None
    feed_content = _read_feed_file(feed_file)
    if feed_content is None:
        return None
    root = _parse_feed(feed_content, str(feed_file))
    if root is None:
        return None
    return _extract_psc_chapters_for_guid(root, guid, str(feed_file))


def extract_psc_chapters_from_url(
    feed_url: str,
    guid: str,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> None | list[Chapter]:
    """Fetch a podcast feed and extract PSC chapters for ``guid``."""
    try:
        response = httpx2.get(
            feed_url,
            headers=headers or {},
            timeout=timeout,
            follow_redirects=True,
        )
    except httpx2.RequestError as exc:
        logger.error("Error fetching feed {}: {}", feed_url, exc)
        return None
    if not response.is_success:
        logger.error("Error {} fetching feed {}", response.status_code, feed_url)
        return None
    root = _parse_feed(response.text, feed_url)
    if root is None:
        return None
    return _extract_psc_chapters_for_guid(root, guid, feed_url)


def _extract_psc_chapters_for_guid(
    root: ElementTree.Element,
    guid: str,
    source: str,
) -> None | list[Chapter]:
    for item in _iter_feed_items(root):
        found_guid = item.find("guid")
        if found_guid is not None and found_guid.text == guid:
            if (psc_chapters := item.find(f"./{PSC}chapters")) is not None:
                return extract_psc_chapters(psc_chapters)
            logger.info("Failed PSC chapters for episode {} in {}", guid, source)
            return None
    return None


def extract_all_psc_chapters_from_file(
    feed_file: Path,
) -> None | dict[str, list[Chapter]]:
    """Extract PSC chapters for every episode in a feed file, keyed by GUID."""
    if not feed_file.exists():
        logger.error("File not found {}", feed_file)
        return None
    feed_content = _read_feed_file(feed_file)
    if feed_content is None:
        return None
    root = _parse_feed(feed_content, str(feed_file))
    if root is None:
        return None

    all_chapters: dict[str, list[Chapter]] = {}
    for item in _iter_feed_items(root):
        found_guid = item.find("guid")
        if found_guid is None or found_guid.text is None:
            continue
        if (psc_chapters := item.find(f"./{PSC}chapters")) is not None:
            chapters = extract_psc_chapters(psc_chapters)
            if chapters is not None:
                all_chapters[found_guid.text] = chapters
    return all_chapters


def extract_psc_chapters(psc_chapters: ElementTree.Element) -> None | list[Chapter]:
    """Extract PSC chapters from XML.

    psc_chapters: ElementTree.Element is the element <psc:chapters>.
    """
    try:
        return [
            Chapter(
                ts_to_secs(c.attrib["start"]),
                c.attrib["title"],
                c.attrib.get("href"),
                c.attrib.get("image"),
            )
            for c in psc_chapters
        ]
    except (KeyError, ValueError, TypeError):
        logger.warning("Failed to extract PSC chapters {}", psc_chapters)
        return None


def find_pci_chapters_url(feed_file: Path, guid: str) -> str | None:
    """Find the ``<podcast:chapters>`` URL for the episode with ``guid``.

    Returns the URL declared in the feed's Podcasting 2.0 namespace, ready to
    pass to ``get_and_extract_pci_chapters``, or ``None`` if not declared.
    """
    if not feed_file.exists():
        logger.error("File not found {}", feed_file)
        return None
    feed_content = _read_feed_file(feed_file)
    if feed_content is None:
        return None
    root = _parse_feed(feed_content, str(feed_file))
    if root is None:
        return None
    for item in _iter_feed_items(root):
        found_guid = item.find("guid")
        if found_guid is not None and found_guid.text == guid:
            if (pci_chapters := item.find(f"./{PCI}chapters")) is not None:
                return pci_chapters.attrib.get("url")
            return None
    return None
