import pytest

from podcast_chapter_tools.timecodes import secs_to_ts, ts_to_secs


class TestTsToSecs:
    def test_seconds_only(self):
        assert ts_to_secs("42") == 42

    def test_minutes_seconds(self):
        assert ts_to_secs("1:02") == 62

    def test_hours_minutes_seconds(self):
        assert ts_to_secs("1:02:03") == 3723

    def test_fractional_seconds_truncated(self):
        assert ts_to_secs("0:01:30.500") == 90

    def test_fractional_seconds_only_allowed_in_final_segment(self):
        with pytest.raises(ValueError, match="final segment"):
            ts_to_secs("1.5:02")

    def test_fractional_seconds_must_be_numeric(self):
        with pytest.raises(ValueError):
            ts_to_secs("1:02.bad")

    def test_leading_zeros(self):
        assert ts_to_secs("00:00:00") == 0
        assert ts_to_secs("01:05") == 65

    def test_surrounding_whitespace(self):
        assert ts_to_secs(" 1:02 ") == 62

    def test_too_many_segments(self):
        with pytest.raises(ValueError):
            ts_to_secs("1:2:3:4")

    def test_non_numeric(self):
        with pytest.raises(ValueError):
            ts_to_secs("aa:10")
        with pytest.raises(ValueError):
            ts_to_secs("aa:10:10")

    def test_out_of_range_minutes(self):
        with pytest.raises(ValueError):
            ts_to_secs("1:61:00")

    def test_out_of_range_seconds(self):
        with pytest.raises(ValueError):
            ts_to_secs("1:00:99")

    def test_negative_segment(self):
        with pytest.raises(ValueError, match="Negative segment"):
            ts_to_secs("-5")


class TestSecsToTs:
    def test_under_a_minute(self):
        assert secs_to_ts(5) == "0:05"

    def test_minutes(self):
        assert secs_to_ts(62) == "1:02"

    def test_hours(self):
        assert secs_to_ts(3723) == "1:02:03"

    def test_zero(self):
        assert secs_to_ts(0) == "0:00"

    def test_negative(self):
        with pytest.raises(ValueError):
            secs_to_ts(-1)

    def test_roundtrip(self):
        for seconds in (0, 59, 60, 61, 3599, 3600, 3661, 86399):
            assert ts_to_secs(secs_to_ts(seconds)) == seconds
