"""Clock helpers for the Matrix node: UTC <-> local time, daylight saving, H:MM.

CircuitPython has no time zones, so the board keeps its clock (RTC) on UTC and
this works out the local time from a zone name in secrets.py:

    "timezone": "America/New_York"   (US and EU zones below, with daylight saving)
    "timezone": "-07:00"             (a fixed offset, no daylight saving)

Unknown names fall back to UTC. Pure Python, no hardware: tested on a computer.
"""

# name: (standard offset in hours, daylight saving rule)
ZONES = {
    "UTC": (0, None), "Etc/UTC": (0, None), "GMT": (0, None),
    "America/New_York": (-5, "us"), "US/Eastern": (-5, "us"),
    "America/Detroit": (-5, "us"),
    "America/Chicago": (-6, "us"), "US/Central": (-6, "us"),
    "America/Denver": (-7, "us"), "US/Mountain": (-7, "us"),
    "America/Phoenix": (-7, None), "US/Arizona": (-7, None),
    "America/Los_Angeles": (-8, "us"), "US/Pacific": (-8, "us"),
    "America/Anchorage": (-9, "us"), "US/Alaska": (-9, "us"),
    "Pacific/Honolulu": (-10, None), "US/Hawaii": (-10, None),
    "America/Puerto_Rico": (-4, None),
    "Europe/London": (0, "eu"), "Europe/Dublin": (0, "eu"), "Europe/Lisbon": (0, "eu"),
    "Europe/Paris": (1, "eu"), "Europe/Berlin": (1, "eu"), "Europe/Madrid": (1, "eu"),
    "Europe/Rome": (1, "eu"), "Europe/Amsterdam": (1, "eu"),
    "Europe/Athens": (2, "eu"), "Europe/Helsinki": (2, "eu"),
}


def is_leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def days_from_civil(y, m, d):
    """Days since 1970-01-01 for a calendar date (any year, integers only)."""
    if m <= 2:
        y -= 1
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    """(year, month, day) for days since 1970-01-01."""
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return (y + 1 if m <= 2 else y, m, d)


def epoch(y, mo, d, hh=0, mm=0, ss=0):
    """Seconds since 1970-01-01 00:00:00 for a date and time (no zone)."""
    return days_from_civil(y, mo, d) * 86400 + hh * 3600 + mm * 60 + ss


def weekday(y, mo, d):
    """0 = Monday .. 6 = Sunday."""
    return (days_from_civil(y, mo, d) + 3) % 7


def _days_in_month(y, m):
    if m == 2:
        return 29 if is_leap(y) else 28
    return 30 if m in (4, 6, 9, 11) else 31


def nth_sunday(y, mo, n):
    """Day of the month of the nth Sunday (n = -1: the last one)."""
    if n > 0:
        return 1 + (6 - weekday(y, mo, 1)) % 7 + 7 * (n - 1)
    last = _days_in_month(y, mo)
    return last - (weekday(y, mo, last) - 6) % 7


def _dst_window(rule, y, std):
    """(start, end) of daylight saving as UTC epoch seconds, or None."""
    if rule == "us":   # 2nd Sunday in March 2:00 standard .. 1st Sunday in Nov 2:00 daylight
        return (epoch(y, 3, nth_sunday(y, 3, 2), 2) - std * 3600,
                epoch(y, 11, nth_sunday(y, 11, 1), 2) - (std + 1) * 3600)
    if rule == "eu":   # last Sunday in March .. last Sunday in October, 01:00 UTC
        return (epoch(y, 3, nth_sunday(y, 3, -1), 1), epoch(y, 10, nth_sunday(y, 10, -1), 1))
    return None


def parse_fixed(zone):
    """'-07:00' / '+5:30' / '-7' -> offset in seconds, or None."""
    if not isinstance(zone, str) or len(zone) < 2 or zone[0] not in "+-":
        return None
    try:
        parts = zone[1:].split(":")
        secs = int(parts[0]) * 3600 + (int(parts[1]) * 60 if len(parts) > 1 else 0)
    except ValueError:
        return None
    if secs > 14 * 3600:
        return None
    return -secs if zone[0] == "-" else secs


def known(zone):
    return zone in ZONES or parse_fixed(zone) is not None


def offset(zone, utc):
    """Seconds to add to UTC for local time in `zone` at the moment `utc`."""
    fixed = parse_fixed(zone)
    if fixed is not None:
        return fixed
    std, rule = ZONES.get(zone, (0, None))
    if rule:
        y = civil_from_days(utc // 86400)[0]
        start, end = _dst_window(rule, y, std)
        if start <= utc < end:
            return (std + 1) * 3600
    return std * 3600


def parts(secs):
    """(year, month, day, hour, minute, second, weekday) for epoch seconds."""
    days, rest = divmod(int(secs), 86400)
    y, mo, d = civil_from_days(days)
    return (y, mo, d, rest // 3600, rest % 3600 // 60, rest % 60, (days + 3) % 7)


def local_midnight(zone, utc):
    """UTC epoch seconds of the local midnight that starts the day `utc` falls in."""
    off = offset(zone, utc)
    start = (utc + off) // 86400 * 86400 - off
    # a daylight saving change during the night: use the offset at midnight itself
    off2 = offset(zone, start)
    return (utc + off) // 86400 * 86400 - off2


def hh_mm(hour, minute, twelve=True):
    """'3:05' / '12:00' (12-hour) or '15:05' (24-hour)."""
    if twelve:
        h = hour % 12 or 12
        return str(h) + ":" + "{:02d}".format(minute)
    return "{:02d}:{:02d}".format(hour, minute)


def short_hour(hour, minute=0):
    """'3P', '11A', '3:30P': a time in four or five characters for a 32-pixel screen."""
    h = hour % 12 or 12
    tail = "A" if hour < 12 else "P"
    if minute:
        return str(h) + ":" + "{:02d}".format(minute) + tail
    return str(h) + tail


def parse_iso_utc(text):
    """'2026-02-17T05:12:34Z' (or with +00:00) -> UTC epoch seconds, or None."""
    try:
        s = text.strip()
        date, clock = s.split("T")
        sign, off = 1, 0
        for ch in "+-":
            if ch in clock:
                clock, tz = clock.split(ch, 1)
                hh, mm = (tz.split(":") + ["0"])[:2]
                off = (int(hh) * 3600 + int(mm) * 60) * (1 if ch == "+" else -1)
                break
        clock = clock.rstrip("Z")
        y, mo, d = [int(x) for x in date.split("-")]
        hms = [int(float(x)) for x in clock.split(":")]
        while len(hms) < 3:
            hms.append(0)
        return epoch(y, mo, d, hms[0], hms[1], hms[2]) - sign * off
    except (ValueError, IndexError, AttributeError):
        return None
