import sys
from pathlib import Path

import tiktoken
from loguru import logger
from podcast_transcript_tools.ai import (
    complete,
    prompt_transcript_to_chapters,
)
from podcast_transcript_tools.json2simple import json_file_to_simple_file


def create_chapters(transcript: str) -> dict[str, tuple[str | None, Exception | None]]:
    # TODO: #21 estimate token count and split into multiple prompts if needed
    # https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb
    return complete(
        prompts=prompt_transcript_to_chapters(transcript),
    )


if __name__ == "__main__":
    if sys.argv[1].endswith(".simple"):
        source_path = Path(sys.argv[1])
    elif sys.argv[1].endswith(".json"):
        logger.info("Converting to simple format")
        source_path = Path(sys.argv[1].replace(".json", ".simple"))
        json_file_to_simple_file(sys.argv[1], source_path)
    else:
        print("Please provide a simple transcript file")
        sys.exit(1)

    encoder = tiktoken.encoding_for_model("gpt-4o")
    encoding = encoder.encode(source_path.read_text())
    logger.info(f"Document tokens: {len(encoding)}")

    chapters = create_chapters(Path(sys.argv[1]).read_text())
    for model_name, suggestion in chapters.items():
        logger.warning(model_name)
        if suggestion[1]:
            logger.error(suggestion[1])
            continue
        Path(
            str(source_path).replace(
                ".simple",
                f".{model_name.replace('.', '-')}.chapters",
            ),
        ).write_text(
            suggestion[0],
        )
        logger.info(suggestion[0])
    # TODO: write out suggestions to DB
