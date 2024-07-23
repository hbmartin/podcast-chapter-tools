import json
import os
import sys
from pathlib import Path

from loguru import logger
from objective import Client


def create_finetune_index(objective_api_key: str, index_id: str) -> None:
    queries = [
        {"query": "pytest"},
        {"query": "tdd"},
        {"query": "fixtures"},
        {"query": "refactor"},
        {"query": "mock"},
        {"query": "django"},
        {"query": "coverage"},
        {"query": "saas"},
        {"query": "plugins"},
        {"query": "assert"},
    ]
    client = Client(api_key=objective_api_key)
    index = client.get_index(index_id)
    ft_index = index.finetune(queries)
    ft_index.status(watch=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:  # noqa: PLR2004
        logger.error(
            "Usage: search <index ID>")
        sys.exit(1)
    create_finetune_index(
        objective_api_key=os.environ["OBJECTIVE_KEY"],
        index_id=sys.argv[1],
    )
