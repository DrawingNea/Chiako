"""
Parsing the dates people type, in the campaign's time zone, into unix timestamps.
Shown back with Discord timestamps (<t:...>), which every player sees in their own time zone.

Accepted:  2026-10-09 19:30 · 09.10.2026 19:30 · 9.10. 19:30 · 9.10 7:30pm · 19:30 Uhr
           today 19:30 · tomorrow 19:30 · fri 19:30 · friday 19:30
           heute 19:30 · morgen 19:30 · fr 19:30 · freitag 19:30
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from .helpers import UserError

WEEKDAYS = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
    # German
    "mo": 0, "montag": 0, "di": 1, "dienstag": 1, "mi": 2, "mittwoch": 2, "do": 3, "donnerstag": 3,
    "fr": 4, "freitag": 4, "sa": 5, "samstag": 5, "so": 6, "sonntag": 6,
}
TODAY = {"today", "tonight", "heute"}
TOMORROW = {"tomorrow", "morgen"}
HELP = ("Try `2026-10-09 19:30`, `09.10.2026 19:30`, `9.10. 19:30`, `tomorrow 19:30` or `fri 19:30` "
        "(times in the campaign's time zone, see `/campaign timezone`).")

_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", re.I)


_ZONES_LOWER: dict[str, str] = {}


def get_zone(name: str) -> ZoneInfo:
    """Find a time zone by name, ignoring capitalisation ('europe/berlin' works too)."""
    name = name.strip()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        pass
    if not _ZONES_LOWER:
        try:
            _ZONES_LOWER.update({z.lower(): z for z in available_timezones()})
        except Exception:  # no time zone database available
            pass
    real = _ZONES_LOWER.get(name.lower().replace(" ", "_"))
    if real:
        return ZoneInfo(real)
    raise UserError(f"Unknown time zone `{name}`. Use a name like `Europe/Berlin`, `America/New_York` or `UTC`.")


def _parse_time(text: str) -> time:
    m = _TIME_RE.match(text.strip())
    if not m:
        raise UserError(f"I can't read the time `{text}`. {HELP}")
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ampm:
        if not 1 <= hour <= 12:
            raise UserError(f"`{text}` isn't a valid time.")
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    elif m.group(2) is None:
        raise UserError(f"Please include minutes, e.g. `{hour}:00`. {HELP}")
    if hour > 23 or minute > 59:
        raise UserError(f"`{text}` isn't a valid time.")
    return time(hour, minute)


def parse_when(text: str, tz_name: str, now_ts: int) -> int:
    """Return the unix timestamp for `text`, which must be in the future."""
    tz = get_zone(tz_name)
    now = datetime.fromtimestamp(now_ts, tz)
    raw = " ".join(text.strip().lower().split())
    raw = re.sub(r"\s*uhr$", "", raw)  # "19:30 Uhr"
    if not raw:
        raise UserError(f"When? {HELP}")

    if m := re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})[ t]+(.+)$", raw):
        kind, day, rest = "absolute", _date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4)
    elif m := re.match(r"^(\d{1,2})\.(\d{1,2})\.?(\d{4})?\s+(.+)$", raw):
        if m.group(3):
            kind, day = "absolute", _date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        else:
            kind, day = "no_year", _date(now.year, int(m.group(2)), int(m.group(1)))
        rest = m.group(4)
    elif (m := re.match(r"^([a-z]+)\s+(.+)$", raw)) and m.group(1) in TODAY | TOMORROW:
        kind, rest = "relative", m.group(2)
        day = now.date() + timedelta(days=1 if m.group(1) in TOMORROW else 0)
    elif (m := re.match(r"^([a-z]+)\s+(.+)$", raw)) and m.group(1) in WEEKDAYS:
        kind, rest = "weekday", m.group(2)
        day = now.date() + timedelta(days=(WEEKDAYS[m.group(1)] - now.weekday()) % 7)
    else:
        raise UserError(f"I can't read `{text}`. {HELP}")

    when = datetime.combine(day, _parse_time(rest), tz)
    if when <= now:
        if kind == "no_year":      # 9.10. already passed this year -> next year
            when = datetime.combine(_date(now.year + 1, day.month, day.day), when.timetz())
        elif kind == "weekday":    # "fri 19:30" on a Friday evening -> next week
            when += timedelta(days=7)
        else:
            raise UserError("That's in the past. Pick a time in the future.")
    return int(when.timestamp())


def _date(y: int, m: int, d: int) -> date:
    try:
        return date(y, m, d)
    except ValueError:
        raise UserError(f"`{d}.{m}.{y}` isn't a real date.")


def fmt(ts: int) -> str:
    """Full date + relative time, rendered in each viewer's own time zone."""
    return f"<t:{ts}:F> (<t:{ts}:R>)"
