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
        self.state = "leading"
        self.label_index = 0
        self.delimiter = ""
        self.chapter = False

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
            self.state = "number" if state in _PREFIX_LIST else "time"
        else:
            self.state = "done"

    def _character(self, char: str) -> None:
        """Advance the finite prefix states by one visible character."""
        if self.state in _PREFIX_PADDING:
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
        elif self.state == "delimiter":
            if char.isspace():
                self.state = "after_number"
            elif self.delimiter == ".":
                self.state = "time"
                self._numeric(char)
            else:
                self.state = "done"
        else:
            self._numeric(char)

    def _numeric(self, char: str) -> None:
        """Recognize a colon or distinguish numbered markers from timestamp dots."""
        if char == ":":
            self.chapter, self.state = True, "done"
        elif self.state == "number" and char in ".)":
            self.delimiter, self.state = char, "delimiter"
        elif not (char.isdigit() or (self.state == "time" and char == ".")):
            self.state = "done"

    def feed(self, text: str) -> None:
        """Consume each prefix character once, stopping after its classification."""
        for char in text:
            if self.state == "done":
                break
            self._character(char)


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
