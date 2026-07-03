"""Command-line interface: extract chapters from any source, emit any format.

Examples::

    podcast-chapters from-description shownotes.txt --to pci
    podcast-chapters from-psc feed.xml --guid abc123 --to description
    podcast-chapters from-pci https://example.com/chapters.json
    podcast-chapters from-id3 episode.mp3 --to psc
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from .entities import Chapter
from .extractors import (
    extract_description_chapters,
    extract_pci_chapters,
    extract_psc_chapters_from_file,
    extract_psc_chapters_from_url,
    get_and_extract_pci_chapters,
)
from .normalize import normalize_chapters
from .writers import (
    chapters_to_description,
    chapters_to_pci_json,
    chapters_to_psc_xml,
)

FORMATS = ("pci", "psc", "description")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="podcast-chapters",
        description="Extract and convert podcast chapter information.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
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


def _extract(args: argparse.Namespace) -> None | list[Chapter]:  # noqa: PLR0911
    if args.command == "from-description":
        return extract_description_chapters(
            args.file.read_text(),
            strip_html=args.strip_html,
        )
    if args.command == "from-psc":
        if args.feed.startswith(("http://", "https://")):
            return extract_psc_chapters_from_url(args.feed, args.guid)
        return extract_psc_chapters_from_file(Path(args.feed), args.guid)
    if args.command == "from-pci":
        if args.source.startswith(("http://", "https://")):
            return get_and_extract_pci_chapters(args.source)
        return extract_pci_chapters(json.loads(Path(args.source).read_text()))
    if args.command == "from-id3":
        # Imported lazily so the optional mutagen dependency is only
        # required for the from-id3 command.
        from .id3 import extract_id3_chapters  # noqa: PLC0415

        return extract_id3_chapters(args.file)
    return None


def _emit(chapters: list[Chapter], fmt: str, indent: int) -> str:
    if fmt == "pci":
        return chapters_to_pci_json(chapters, indent=indent)
    if fmt == "psc":
        return chapters_to_psc_xml(chapters)
    return chapters_to_description(chapters)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    chapters = _extract(args)
    if not chapters:
        print("No chapters found.", file=sys.stderr)
        return 1

    if args.normalize:
        chapters = normalize_chapters(chapters, strip_titles=True)

    rendered = _emit(chapters, args.to, args.indent)
    if args.output is not None:
        args.output.write_text(rendered + "\n")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
