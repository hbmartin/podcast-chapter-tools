import json
import os
import sys
from pathlib import Path

from loguru import logger
from objective import Client

from podcast_transcript_tools.file_utils import list_files


def _read_json_and_map_id(file_path: str) -> dict[str, str]:
    data = json.loads(Path(file_path).read_text())
    data["id"] = data["metadata"]["guid"]
    return data


def main(source_path: str, objective_api_key: str) -> None:
    client = Client(api_key=objective_api_key)
    files = list_files(source_path, [])
    logger.info(f"Reading {len(files)} files")
    objects = [_read_json_and_map_id(file) for file in files]
    logger.info("Uploading objects")
    batch_results = client.object_store.upsert_objects(objects)
    logger.info(batch_results)
    Path("batch_results.json").write_text(json.dumps(batch_results, indent=4))


if __name__ == "__main__":
    if len(sys.argv) == 1:
        logger.error(
            "Usage: up_obj <source dir>\n"
            "OBJECTIVE_KEY env var must be set to your API key.",
        )
        sys.exit(1)

    main(
        source_path=sys.argv[1],
        objective_api_key=os.getenv("OBJECTIVE_KEY")
        or sys.exit("Error: OBJECTIVE_KEY not provided"),
    )
