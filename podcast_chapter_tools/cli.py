"""Command-line interface: extract chapters from any source, emit any format.

Examples::

    podcast-chapters from-description shownotes.txt --to pci
    podcast-chapters from-psc feed.xml --guid abc123 --to description
    podcast-chapters from-pci https://example.com/chapters.json
    podcast-chapters from-id3 episode.mp3 --to psc
"""

import argparse
import json
import sys
from pathlib import Path

from loguru import logger

from .description import parse_description_chapters
from .entities import ChapterData, ChapterParseResult
from .errors import ChapterFetchError, ChapterParseError
from .extractors import (
    _fetch_feed_index,
    _log_result,
    _read_feed_index,
    fetch_pci_chapters,
)
from .normalize import normalize_chapter_data
from .parsers import parse_pci_chapters
from .writers import (
    chapters_to_description,
    chapters_to_pci_json,
    chapters_to_psc_xml,
)

FORMATS = ("pci", "psc", "description")


def _build_parser() -> argparse.ArgumentParser:
    """Build the command parser with shared output options."""
    parser = argparse.ArgumentParser(
        prog="podcast-chapters",
        description="Extract and convert podcast chapter information.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        """Add format, normalization, and output options to a subcommand."""
        sub.add_argument("--to", choices=FORMATS, default="pci")
        sub.add_argument("--normalize", action="store_true")
        sub.add_argument("--indent", type=int, default=2)
        sub.add_argument("--output", "-o", type=Path, default=None)

    desc = subparsers.add_parser(
        "from-description",
        help="Extract from a description text/HTML file",
    )
    desc.add_argument("file", type=Path)
    desc.add_argument("--strip-html", action="store_true")
    desc.add_argument(
        "--description-mode", choices=("strict", "lenient"), default="strict"
    )
    add_common(desc)

    psc = subparsers.add_parser(
        "from-psc",
        help="Extract PSC chapters from an RSS feed file or URL",
    )
    psc.add_argument("feed", help="Path or URL of the podcast RSS feed")
    psc.add_argument("--guid", required=True, help="Episode GUID")
    add_common(psc)

    pci = subparsers.add_parser(
        "from-pci",
        help="Extract from a PodcastIndex chapters JSON file or URL",
    )
    pci.add_argument("source", help="Path or URL of the chapters JSON document")
    add_common(pci)

    id3 = subparsers.add_parser(
        "from-id3",
        help="Extract from ID3 CHAP frames of an MP3 file",
    )
    id3.add_argument("file", type=Path)
    add_common(id3)

    return parser


def _extract(args: argparse.Namespace) -> ChapterParseResult | None:
    """Read the selected source into a rich chapter result."""
    if args.command == "from-description":
        return parse_description_chapters(
            args.file.read_text(encoding="utf-8-sig"),
            strip_html=args.strip_html,
            mode=args.description_mode,
            source=str(args.file),
        )
    if args.command == "from-psc":
        if args.feed.startswith(("http://", "https://")):
            index = _fetch_feed_index(args.feed)
        else:
            index = _read_feed_index(Path(args.feed))
        _log_result(ChapterParseResult(issues=index.issues, source=index.source))
        return index.psc_for_guid(args.guid)
    if args.command == "from-pci":
        if args.source.startswith(("http://", "https://")):
            return fetch_pci_chapters(args.source)
        return parse_pci_chapters(
            json.loads(Path(args.source).read_bytes()),
            source=args.source,
        )
    if args.command == "from-id3":
        # Imported lazily so the optional mutagen dependency is only
        # required for the from-id3 command.
        from .id3 import extract_id3_chapters  # noqa: PLC0415

        chapters = extract_id3_chapters(args.file) or []
        return ChapterParseResult(
            tuple(ChapterData(c.start, c.title, c.url, c.image) for c in chapters),
            source=str(args.file),
        )
    return None


def _emit(chapters: list[ChapterData], fmt: str, indent: int) -> str:
    """Serialize rich chapters in the requested output format."""
    if fmt == "pci":
        return chapters_to_pci_json(chapters, indent=indent)
    if fmt == "psc":
        return chapters_to_psc_xml(chapters)
    return chapters_to_description(chapters)


def main(argv: list[str] | None = None) -> int:
    """Run chapter conversion and return a command exit status."""
    args = _build_parser().parse_args(argv)
    logger.enable("podcast_chapter_tools")
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if args.verbose else "WARNING",
        format="{level} {name}: {message}",
    )

    try:
        result = _extract(args)
        if result is not None:
            _log_result(result)
        if result is None or not result.chapters:
            print("No chapters found.", file=sys.stderr)
            return 1

        chapters = list(result.chapters)
        if args.normalize:
            chapters = normalize_chapter_data(chapters, strip_titles=True)

        rendered = _emit(chapters, args.to, args.indent)
        if args.output is not None:
            args.output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
    except (OSError, ValueError, ImportError, ChapterFetchError) as exc:
        if isinstance(exc, ChapterParseError):
            _log_result(
                ChapterParseResult(issues=exc.issues, source=exc.source, guid=exc.guid)
            )
        logger.error("{}: {}", type(exc).__name__, exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
