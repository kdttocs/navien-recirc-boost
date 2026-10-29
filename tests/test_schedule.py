import pytest

from custom_components.navien_recirc_boost.schedule import (
    ScheduleError,
    build_day,
    day_number,
    day_windows,
    describe,
    parse_windows,
)

from .conftest import SCHEDULE


def test_describe_sample_schedule():
    d = describe(SCHEDULE)
    assert d["sunday"] == "07:00-09:00, 14:00-21:00"
    assert d["monday"] == "04:00-08:00, 15:30-21:00"
    assert d["friday"] == "04:00-08:00, 15:30-22:00"
    assert d["saturday"] == "07:00-22:00"


def test_round_trip():
    w = parse_windows("15:30-21:00, 4:00-08:00")
    assert w == [(4, 0, 8, 0), (15, 30, 21, 0)]
    day = build_day(2, w)
    assert day == SCHEDULE[1]
    assert day_windows(day) == w


@pytest.mark.parametrize("text", ["5-9", "08:00-04:00", "04:00-08:00, 07:00-09:00",
                                  "24:00-25:00", "0:00-1:00,2:00-3:00,4:00-5:00,6:00-7:00,8:00-09:00"])
def test_bad(text):
    with pytest.raises(ScheduleError):
        parse_windows(text)


def test_off_and_days():
    assert parse_windows("off") == []
    assert build_day(1, []) == {"day": 1, "schdCnt": 0, "schdList": []}
    assert day_number("Monday") == 2 and day_number("sat") == 7 and day_number(1) == 1
    with pytest.raises(ScheduleError):
        day_number("funday")


def test_friendly_round_trip():
    from custom_components.navien_recirc_boost.schedule import format_friendly
    for text in ["6am-8am, 5:30pm-9pm", "7am-9:30am, 2pm-12am", "off"]:
        assert format_friendly(parse_windows(text)) == text
    assert parse_windows("6-8am") == [(6, 0, 8, 0)]
    assert parse_windows("11-1pm") == [(11, 0, 13, 0)]
