"""Shared, bounded recognition of chapter-line prefixes."""

from unicodedata import category


def _padding_end(text: str, index: int, *, leading: bool = False) -> int:
    """Skip line-local padding and optionally leading format marks."""
    while index < len(text) and text[index] not in "\r\n":
        if not (text[index].isspace() or (leading and category(text[index]) == "Cf")):
            break
        index += 1
    return index


def line_timestamp_start(text: str, index: int = 0) -> int | None:
    """Return the numeric start after an optional chapter-list prefix."""
    index = _padding_end(text, index, leading=True)
    if text[index : index + 1] == ">":
        index = _padding_end(text, index + 1)
    if text[index : index + 9].lower() == "chapters:":
        index = _padding_end(text, index + 9)
    if text[index : index + 1] in {"-", "*", "+", "•"}:
        end = _padding_end(text, index + 1)
        if end == index + 1:
            return None
        index = end
    else:
        end = index
        while end < len(text) and text[end].isdigit():
            end += 1
        if end > index and text[end : end + 1] in {".", ")"}:
            padded = _padding_end(text, end + 1)
            if padded > end + 1:
                index = padded
    if text[index : index + 1] in {"(", "["}:
        index += 1
    return index if index < len(text) and text[index].isdigit() else None


def begins_chapter_line(text: str, index: int) -> bool:
    """Detect a timestamp candidate without scanning past its numeric run."""
    return chapter_timestamp_end(text, index) is not None


def chapter_timestamp_end(text: str, index: int) -> int | None:
    """Return a recognized candidate's end for bounded continuation scanning."""
    start = line_timestamp_start(text, index)
    if start is None:
        return None
    end = start
    while end < len(text) and (text[end].isdigit() or text[end] in ":."):
        end += 1
    return end if ":" in text[start:end] else None
