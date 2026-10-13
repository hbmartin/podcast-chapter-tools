"""Shared, bounded recognition of chapter-line prefixes."""

from unicodedata import category

_PREFIX_LABEL = "chapters:"
_PREFIX_PADDING = frozenset(
    {"leading", "blockquote", "after_label", "after_marker", "after_number"}
)
_PREFIX_LIST = frozenset({"leading", "blockquote", "after_label"})


class _ChapterPrefix:
    """Recognize a visible prefix incrementally without retaining its text."""

    def __init__(self) -> None:
        """Start at a fresh visible line boundary."""
        self.reset()

    def reset(self, offset: int = 0) -> None:
        """Reuse the recognizer at a new line or absolute source offset."""
        self.state = "leading"
        self.label_index = 0
        self.delimiter = ""
        self.chapter = False
        self.numeric_start: int | None = None
        self.offset = offset

    def _padding(self, char: str) -> None:
        """Consume optional prefixes or enter the numeric timestamp run."""
        state = self.state
        if char.isspace() or (state == "leading" and category(char) == "Cf"):
            return
        if state == "leading" and char == ">":
            self.state = "blockquote"
        elif state in {"leading", "blockquote"} and char.lower() == "c":
            self.state, self.label_index = "label", 1
        elif state in _PREFIX_LIST and char in "-*+•":
            self.state = "marker_gap"
        elif char in "([":
            self.state = "wrapped"
        elif char.isdigit():
            self.numeric_start = self.offset
            self.state = "number" if state in _PREFIX_LIST else "time"
        else:
            self.state = "done"

    def _character(self, char: str) -> None:
        """Advance the finite prefix states by one visible character."""
        if char in "\r\n":
            self.state = "done"
        elif self.state in _PREFIX_PADDING:
            self._padding(char)
        elif self.state == "label":
            if char.lower() != _PREFIX_LABEL[self.label_index]:
                self.state = "done"
            else:
                self.label_index += 1
                if self.label_index == len(_PREFIX_LABEL):
                    self.state = "after_label"
        elif self.state == "marker_gap":
            self.state = "after_marker" if char.isspace() else "done"
        elif self.state == "wrapped":
            self.state = "time" if char.isdigit() else "done"
            if char.isdigit():
                self.numeric_start = self.offset
        elif self.state == "delimiter":
            self._number_delimiter(char)
        else:
            self._numeric(char)

    def _number_delimiter(self, char: str) -> None:
        """Resolve numbered-list padding without losing decimal timestamp offsets."""
        if char.isspace():
            self.state = "after_number"
            self.numeric_start = None
        elif self.delimiter == ".":
            self.state = "time"
            self._numeric(char)
        else:
            self.state = "done"

    def _numeric(self, char: str) -> None:
        """Recognize a colon or distinguish numbered markers from timestamp dots."""
        if char == ":":
            self.chapter, self.state = True, "done"
        elif self.state == "number" and char in ".)":
            self.delimiter, self.state = char, "delimiter"
        elif not (char.isdigit() or (self.state == "time" and char == ".")):
            self.state = "done"

    def feed(self, text: str, start: int = 0) -> None:
        """Consume each prefix character once, stopping after its classification."""
        for index in range(start, len(text)):
            if self.state == "done":
                break
            self._character(text[index])
            self.offset += 1


def line_timestamp_start(text: str, index: int = 0) -> int | None:
    """Return the numeric start after an optional chapter-list prefix."""
    prefix = _ChapterPrefix()
    prefix.reset(index)
    prefix.feed(text, index)
    return prefix.numeric_start


def chapter_timestamp_end(text: str, index: int) -> int | None:
    """Return a recognized candidate's end for bounded continuation scanning."""
    start = line_timestamp_start(text, index)
    if start is None:
        return None
    end = start
    while end < len(text) and (text[end].isdigit() or text[end] in ":."):
        end += 1
    return end if ":" in text[start:end] else None
