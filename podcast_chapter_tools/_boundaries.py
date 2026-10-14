"""Shared physical line separators for parsing and description rendering."""

LINE_BREAK_PATTERN = r"\r\n|[\r\n\v\f\x1c-\x1e\x85\u2028\u2029]"
HARD_BREAKS = frozenset({"\r", "\n", "\r\n"})
