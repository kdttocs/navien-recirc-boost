"""Helpers for the heater's weekly schedule format.

The heater stores, per day (1 = Sunday ... 7 = Saturday), a list of numbered
on/off points: ``{"num": 1, "hh": 5, "mm": 0, "flag": 1}`` where flag 1 means
"recirculation starts" and flag 2 means "recirculation stops". These helpers
turn that into readable windows such as ``06:00-08:00`` and back.
"""

from __future__ import annotations

import re
from typing import Any

from .const import DAY_NAMES, MAX_WINDOWS_PER_DAY

_TIME = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a|p)?"
_WINDOW_RE = re.compile(rf"^\s*{_TIME}\s*(?:-|–|—|to)\s*{_TIME}\s*$")


class ScheduleError(ValueError):
    """The text could not be turned into a valid day schedule."""


def day_windows(day: dict[str, Any]) -> list[tuple[int, int, int, int]]:
    """Return a day's windows as (start_h, start_m, stop_h, stop_m) tuples."""
    items = sorted(day.get("schdList", []), key=lambda s: s.get("num", 0))
    windows: list[tuple[int, int, int, int]] = []
    start: tuple[int, int] | None = None
    for item in items:
        hm = (int(item.get("hh", 0)), int(item.get("mm", 0)))
        if item.get("flag") == 1:
            start = hm
        elif item.get("flag") == 2 and start is not None:
            windows.append((*start, *hm))
            start = None
    return windows


def format_windows(windows: list[tuple[int, int, int, int]]) -> str:
    """Return windows as text, e.g. ``06:00-08:00, 17:30-21:00`` or ``off``."""
    if not windows:
        return "off"
    return ", ".join(f"{a:02d}:{b:02d}-{c:02d}:{d:02d}" for a, b, c, d in windows)


def describe(schedule: list[dict[str, Any]]) -> dict[str, str]:
    """Return {"sunday": "08:00-10:00, 15:00-22:00", ...} for every day."""
    by_day = {d.get("day"): d for d in schedule}
    return {
        name: format_windows(day_windows(by_day[num])) if num in by_day else "off"
        for num, name in DAY_NAMES.items()
    }


def parse_windows(text: str) -> list[tuple[int, int, int, int]]:
    """Parse ``6am-8am, 5:30pm-9pm`` or ``06:00-08:00, 17:30-21:00`` (or ``off``) into windows.

    Raises ScheduleError when a window is malformed, ends before it starts,
    overlaps another, or there are too many.
    """
    text = (text or "").strip().lower()
    if text in ("", "off", "none"):
        return []
    windows: list[tuple[int, int, int, int]] = []
    for part in re.split(r"[,;]", text):
        if not part.strip():
            continue
        match = _WINDOW_RE.match(part)
        if not match:
            raise ScheduleError(f"'{part.strip()}' is not like 6am-8am or 06:00-08:00")
        a, b, c, d = _window(part.strip(), *match.groups())
        windows.append((a, b, c, d))
    windows.sort()
    for prev, cur in zip(windows, windows[1:], strict=False):
        if (cur[0], cur[1]) < (prev[2], prev[3]):
            raise ScheduleError("Two windows overlap")
    if len(windows) > MAX_WINDOWS_PER_DAY:
        raise ScheduleError(f"At most {MAX_WINDOWS_PER_DAY} windows per day")
    return windows


def _window(
    part: str, h1: str, m1: str | None, ap1: str | None, h2: str, m2: str | None, ap2: str | None
) -> tuple[int, int, int, int]:
    """Turn one matched window (24-hour or am/pm) into (start_h, start_m, stop_h, stop_m)."""
    ap1 = ap1[0] if ap1 else None
    ap2 = ap2[0] if ap2 else None
    a, b, c, d = int(h1), int(m1 or 0), int(h2), int(m2 or 0)
    if ((ap1 is None and m1 is None) or (ap2 is None and m2 is None)) and not (ap1 or ap2):
        raise ScheduleError(f"'{part}' needs am/pm or minutes, like 6am-8am or 06:00-08:00")

    def to24(h: int, ap: str | None) -> int:
        if ap is None:
            return h
        if not 1 <= h <= 12:
            raise ScheduleError(f"'{part}' has an impossible time")
        return h % 12 + (12 if ap == "p" else 0)

    if ap1 is None and ap2 is not None and a <= 12:
        # "6-8am": the start takes the end's am/pm unless that would put it after the end.
        guess = to24(a, ap2)
        ap1 = ap2 if (guess, b) < (to24(c, ap2) or 24, d) else ("a" if ap2 == "p" else "p")
    a, c = to24(a, ap1), to24(c, ap2)
    if (c, d) == (0, 0):
        c, d = 23, 59  # "to midnight"
    if not (0 <= a <= 23 and 0 <= c <= 23 and 0 <= b <= 59 and 0 <= d <= 59):
        raise ScheduleError(f"'{part}' has an impossible time")
    if (c, d) <= (a, b):
        raise ScheduleError(f"'{part}' ends before it starts")
    return a, b, c, d


def _hm12(h: int, m: int) -> str:
    if (h, m) == (23, 59):
        return "12am"  # midnight; read back as 23:59
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{ap}" if m else f"{h12}{ap}"


def format_friendly(windows: list[tuple[int, int, int, int]]) -> str:
    """Return windows as ``6am-8am, 5:30pm-9pm`` (or ``off``); parse_windows reads it back."""
    if not windows:
        return "off"
    return ", ".join(f"{_hm12(a, b)}-{_hm12(c, d)}" for a, b, c, d in windows)


def build_day(day: int, windows: list[tuple[int, int, int, int]]) -> dict[str, Any]:
    """Return one day in the heater's format."""
    items: list[dict[str, int]] = []
    for a, b, c, d in windows:
        items.append({"num": len(items) + 1, "hh": a, "mm": b, "flag": 1})
        items.append({"num": len(items) + 1, "hh": c, "mm": d, "flag": 2})
    return {"day": day, "schdCnt": len(items), "schdList": items}


def day_number(name_or_number: str | int) -> int:
    """Accept 'monday', 'Mon', or 2 and return the heater's day number."""
    if isinstance(name_or_number, int) or str(name_or_number).isdigit():
        num = int(name_or_number)
        if num in DAY_NAMES:
            return num
        raise ScheduleError(f"Day must be 1 (Sunday) to 7 (Saturday), not {num}")
    key = str(name_or_number).strip().lower()
    for num, name in DAY_NAMES.items():
        if name == key or name[:3] == key[:3] and len(key) >= 3:
            return num
    raise ScheduleError(f"Unknown day '{name_or_number}'")
