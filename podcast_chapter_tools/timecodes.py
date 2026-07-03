"""Conversions between ``HH:MM:SS``-style timestamps and seconds."""

_SECS_PER_MINUTE = 60
_SECS_PER_HOUR = 3600
_MAX_TIME_PARTS = 3


def ts_to_secs(time_string: str) -> int:
    """Convert a timestamp string (``[[HH:]MM:]SS[.fff]``) to whole seconds.

    Fractional seconds are truncated. Raises ``ValueError`` for strings that
    are not valid timestamps (non-numeric parts, too many segments, or
    minutes/seconds >= 60 when a larger unit is present).
    """
    raw_time = time_string.strip()
    whole_seconds, separator, fractional_seconds = raw_time.partition(".")
    if separator:
        if ":" in fractional_seconds:
            msg = f"Fractional seconds must be in final segment: {time_string!r}"
            raise ValueError(msg)
        if not fractional_seconds.isdigit():
            msg = f"Non-numeric fractional seconds in timestamp: {time_string!r}"
            raise ValueError(msg)

    time_parts = whole_seconds.split(":")
    if len(time_parts) > _MAX_TIME_PARTS:
        msg = f"Too many segments in timestamp: {time_string!r}"
        raise ValueError(msg)

    try:
        values = [int(part) for part in time_parts]
    except ValueError:
        msg = f"Non-numeric segment in timestamp: {time_string!r}"
        raise ValueError(msg) from None

    if any(value < 0 for value in values):
        msg = f"Negative segment in timestamp: {time_string!r}"
        raise ValueError(msg)
    if any(value >= _SECS_PER_MINUTE for value in values[1:]):
        msg = f"Minutes/seconds must be < 60: {time_string!r}"
        raise ValueError(msg)

    seconds = values[-1]
    if len(values) > 1:
        seconds += _SECS_PER_MINUTE * values[-2]
    if len(values) > 2:  # noqa: PLR2004
        seconds += _SECS_PER_HOUR * values[-3]
    return seconds


def secs_to_ts(seconds: int) -> str:
    """Convert whole seconds to a timestamp (``M:SS``, or ``H:MM:SS`` >= 1h)."""
    if seconds < 0:
        msg = f"Seconds must be non-negative: {seconds!r}"
        raise ValueError(msg)
    hours, remainder = divmod(seconds, _SECS_PER_HOUR)
    minutes, secs = divmod(remainder, _SECS_PER_MINUTE)
    if hours:
        return f"{hours}:{minutes:02}:{secs:02}"
    return f"{minutes}:{secs:02}"
