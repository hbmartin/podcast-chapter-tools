import os
import sys

from loguru import logger
from objective import Client


def objective_search(objective_api_key: str, index_id: str, query: str) -> None:
    client = Client(api_key=objective_api_key)
    index = client.get_index(index_id)
    results = index.search(query=query, object_fields="body")
    logger.info(results)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        logger.error(
            "Usage: search <index ID> <query>\n"
            "OBJECTIVE_KEY env var must be set to your API key.",
        )
        sys.exit(1)
    logger.info(f"Searching index '{sys.argv[1]}' for '{sys.argv[2]}'")
    objective_search(
        objective_api_key=os.environ["OBJECTIVE_KEY"],
        index_id=sys.argv[1],
        query=sys.argv[2],
    )
