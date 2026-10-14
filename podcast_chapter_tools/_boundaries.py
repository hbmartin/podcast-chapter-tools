"""Shared physical line separators for parsing and description rendering."""

import re

LINE_BREAK_CHARACTERS = "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"
LINE_BREAK_PATTERN = r"\r\n|[" + re.escape(LINE_BREAK_CHARACTERS) + "]"
LINE_BREAKS = frozenset({"\r\n", *LINE_BREAK_CHARACTERS})


def is_line_break(text: str) -> bool:
    """Recognize short literal or decoded separators without hashing long text."""
    return len(text) <= 2 and text in LINE_BREAKS  # noqa: PLR2004 - CRLF is the only two-character separator.
