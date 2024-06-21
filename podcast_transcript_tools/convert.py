import sys
from os import walk
from pathlib import Path
from sys import argv

from loguru import logger  # type: ignore[import-not-found]

from podcast_transcript_tools.xml_to_json import xml_file_to_json_file

from .file_utils import _identify_file_types
from .html_to_json import html_file_to_json_file
from .json_to_json import json_file_to_json_file
from .srt_to_json import srt_file_to_json_file
from .vtt_to_json import vtt_file_to_json_file


def list_files(directory: str, ignore: list[str]) -> list[str]:
    file_paths: list[str] = []  # List to store file paths
    for root, _, filenames in walk(directory):
        dirpath = Path(root)
        file_paths.extend(
            str(dirpath / filename)
            for filename in filenames
            if filename not in ignore
            and not filename.startswith(".")
            and not filename.endswith(".pdf")
            and not filename.endswith(".octet-stream")
        )
    return file_paths


def _destination_path(file_path: str, destination_dir: str) -> str:
    file_path = Path(file_path)
    parent = Path(destination_dir) / file_path.parts[-2]
    parent.mkdir(parents=True, exist_ok=True)
    return str(parent / (".".join(file_path.parts[-1].split(".")[:-1]) + ".json"))


def main(transcript_path: str, destination_path: str, ignore: list[str]) -> None:
    file_paths = list_files(transcript_path, ignore)
    html_files, json_files, srt_files, vtt_files, xml_files, unknown_pods = (
        _identify_file_types(
            file_paths,
        )
    )
    logger.info(f"Found {len(vtt_files)} VTT files")
    logger.info(f"Found {len(srt_files)} SRT files")
    logger.info(f"Found {len(html_files)} HTML files")
    logger.info(f"Found {len(json_files)} JSON files")
    logger.info(f"Found {len(xml_files)} XML files")
    if len(unknown_pods) > 0:
        logger.warning(f"Unknown: {unknown_pods}")
    for vtt_file in vtt_files:
        vtt_file_to_json_file(vtt_file, _destination_path(vtt_file, destination_path))
    logger.info("Finished VTT conversion")
    for srt_file in srt_files:
        srt_file_to_json_file(srt_file, _destination_path(srt_file, destination_path))
    logger.info("Finished SRT conversion")
    for html_file in html_files:
        html_file_to_json_file(
            html_file,
            _destination_path(html_file, destination_path),
        )
    logger.info("Finished HTML conversion")
    for xml_file in xml_files:
        xml_file_to_json_file(
            xml_file,
            _destination_path(xml_file, destination_path),
        )
    logger.info("Finished XML conversion")
    for json_file in json_files:
        json_file_to_json_file(
            json_file,
            _destination_path(json_file, destination_path),
        )
    logger.info("Finished JSON conversion")


if __name__ == "__main__":
    if len(argv) < 3:  # noqa: PLR2004
        logger.error(
            "Usage: convert <source directory> <output directory> <opt. ignore file>",
        )
        sys.exit(1)

    transcript_ignore_path = Path.cwd() / ".transcriptignore"
    ignore = (
        (
            []
            if not transcript_ignore_path.exists()
            else transcript_ignore_path.read_text().split("\n")
        )
        if len(argv) == 3  # noqa: PLR2004
        else Path(argv[3]).read_text().split("\n")
    )
    Path(argv[2]).mkdir(parents=True, exist_ok=True)
    main(transcript_path=argv[1], destination_path=argv[2], ignore=ignore)
