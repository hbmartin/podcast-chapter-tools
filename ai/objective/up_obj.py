import json
import os
import sys
from collections.abc import Generator
from pathlib import Path

from loguru import logger
from objective import Client, Object
from podcast_transcript_convert.file_utils import list_files


def _read_json_and_map_id(file_path: str) -> Generator[Object, None, None]:
    data = json.loads(Path(file_path).read_text())
    guid = data["metadata"]["guid"]
    title = data["metadata"]["title"]
    for i, item in enumerate(data["segments"]):
        if "speaker" in item:
            yield Object(
                id=f"{guid}_{i}",
                object={
                    "body": item["body"],
                    "speaker": item["speaker"],
                    "title": title,
                },
            )
        else:
            yield Object(
                id=f"{guid}_{i}",
                object={
                    "body": item["body"],
                    "title": title,
                },
            )


def upload_from_source_directory(source_path: str, objective_api_key: str) -> None:
    client = Client(api_key=objective_api_key)
    files = [f for f in list_files(source_path, []) if f.endswith(".json")]
    for file in files:
        logger.info(f"Reading {file}")
        objects = list(_read_json_and_map_id(file))
        logger.info(f"Uploading {len(objects)}")
        batch_results = client.object_store.upsert_objects(objects)
        if len(objects) != len(batch_results.success):
            logger.error(batch_results)
        else:
            logger.info(batch_results)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        logger.error(
            "Usage: up_obj <source dir>\n"
            "OBJECTIVE_KEY env var must be set to your API key.",
        )
        sys.exit(1)

    logger.add(f"{os.getcwd()}/upload_{sys.argv[1]}.log")

    upload_from_source_directory(
        source_path=sys.argv[1],
        objective_api_key=os.getenv("OBJECTIVE_KEY")
        or sys.exit("Error: OBJECTIVE_KEY not provided"),
    )
