"""The moon, worked out on the board itself: phase, how much is lit, moonrise and moonset.

The original Moon Phase Clock asked a web service for this, which meant sending the
location out and breaking whenever that service changed. This needs no internet at
all, only the time (and, for rise and set, a latitude and longitude kept in
secrets.py, which never leave the board).

Low-precision formulas (the same ones the suncalc library uses, from "Astronomy
Answers" by Aphrodite Teunissen): good to a few minutes for rise and set and well
under a percent for the lit part, plenty for a clock. CircuitPython's floats are
small (about 7 digits), so the big "degrees per day" angles are split into a
whole-day part and a fraction to keep their precision.

phase: 0 = new moon, 0.25 = first quarter, 0.5 = full, 0.75 = last quarter.
Pure Python, no hardware: tested on a computer.
"""
import math

RAD = math.pi / 180
J2000 = 946728000          # 2000-01-01 12:00 UTC as epoch seconds
OBLIQUITY = RAD * 23.4397
RISE_ALT = 0.125 * RAD     # moon's centre at the horizon, after parallax and refraction
SUN_KM = 149598000


def _days(utc):
    """Days since J2000 as (whole days, fraction)."""
    secs = int(utc) - J2000
    di = secs // 86400
    return di, (secs - di * 86400) / 86400


def _angle(base, rate, di, df, frac=None):
    """(base + rate * days) in radians, accurate even with small floats. `frac` is the
    part of the rate after the decimal point, for rates too big to hold it exactly."""
    whole = int(rate)
    if frac is None:
        frac = rate - whole
    deg = base + (whole * di) % 360 + (frac * di) % 360 + rate * df
    return (deg % 360) * RAD


def _equatorial(lon, lat):
    ra = math.atan2(math.sin(lon) * math.cos(OBLIQUITY) - math.tan(lat) * math.sin(OBLIQUITY),
                    math.cos(lon))
    dec = math.asin(math.sin(lat) * math.cos(OBLIQUITY)
                    + math.cos(lat) * math.sin(OBLIQUITY) * math.sin(lon))
    return ra, dec


def sun(utc):
    """(right ascension, declination) of the sun in radians."""
    di, df = _days(utc)
    m = _angle(357.5291, 0.98560028, di, df)
    c = RAD * (1.9148 * math.sin(m) + 0.02 * math.sin(2 * m) + 0.0003 * math.sin(3 * m))
    lon = m + c + RAD * 102.9372 + math.pi
    return _equatorial(lon, 0.0)


def moon(utc):
    """(right ascension, declination, distance in km) of the moon."""
    di, df = _days(utc)
    l = _angle(218.316, 13.176396, di, df)
    m = _angle(134.963, 13.064993, di, df)
    f = _angle(93.272, 13.229350, di, df)
    lon = l + RAD * 6.289 * math.sin(m)
    lat = RAD * 5.128 * math.sin(f)
    ra, dec = _equatorial(lon, lat)
    return ra, dec, 385001 - 20905 * math.cos(m)


def illumination(utc):
    """(phase 0..1, lit fraction 0..1). Phase 0 = new, 0.5 = full."""
    sra, sdec = sun(utc)
    mra, mdec, mdist = moon(utc)
    phi = math.acos(max(-1.0, min(1.0, math.sin(sdec) * math.sin(mdec)
                                  + math.cos(sdec) * math.cos(mdec) * math.cos(sra - mra))))
    inc = math.atan2(SUN_KM * math.sin(phi), mdist - SUN_KM * math.cos(phi))
    angle = math.atan2(math.cos(sdec) * math.sin(sra - mra),
                       math.sin(sdec) * math.cos(mdec)
                       - math.cos(sdec) * math.sin(mdec) * math.cos(sra - mra))
    sign = -1 if angle < 0 else 1
    phase = (0.5 + 0.5 * inc * sign / math.pi) % 1.0
    return phase, (1 + math.cos(inc)) / 2


def altitude(utc, lat, lon):
    """The moon's height above the horizon, radians (centre, geocentric)."""
    di, df = _days(utc)
    ra, dec, _ = moon(utc)
    sidereal = _angle(280.16, 360.9856235, di, df, 0.9856235) + lon * RAD
    hour_angle = sidereal - ra
    phi = lat * RAD
    return math.asin(math.sin(phi) * math.sin(dec)
                     + math.cos(phi) * math.cos(dec) * math.cos(hour_angle))


def rise_set(day_start, lat, lon):
    """(rise, set) as UTC epoch seconds within the 24 hours from day_start, each
    None if it doesn't happen that day (the moon skips one rise and one set a month)."""
    rise = sets = None
    h0 = altitude(day_start, lat, lon) - RISE_ALT
    for hour in range(1, 25, 2):
        h1 = altitude(day_start + hour * 3600, lat, lon) - RISE_ALT
        h2 = altitude(day_start + (hour + 1) * 3600, lat, lon) - RISE_ALT
        # a parabola through the three points, looking for where it crosses zero
        a = (h0 + h2) / 2 - h1
        b = (h2 - h0) / 2
        xe = -b / (2 * a) if a else 0
        ye = (a * xe + b) * xe + h1
        d = b * b - 4 * a * h1
        roots, x1, x2 = 0, 0, 0
        if d >= 0 and a:
            dx = math.sqrt(d) / (abs(a) * 2)
            x1, x2 = xe - dx, xe + dx
            if abs(x1) <= 1:
                roots += 1
            if abs(x2) <= 1:
                roots += 1
            if x1 < -1:
                x1 = x2
        elif a == 0 and b:
            x1 = -h1 / b
            roots = 1 if abs(x1) <= 1 else 0
        if roots == 1:
            when = day_start + int((hour + x1) * 3600)
            if h0 < 0:
                rise = rise if rise is not None else when
            else:
                sets = sets if sets is not None else when
        elif roots == 2:
            first = day_start + int((hour + x1) * 3600)
            second = day_start + int((hour + x2) * 3600)
            if ye < 0:      # up then down: sets first, rises after
                sets = sets if sets is not None else first
                rise = rise if rise is not None else second
            else:
                rise = rise if rise is not None else first
                sets = sets if sets is not None else second
        if rise is not None and sets is not None:
            break
        h0 = h2
    return rise, sets


def next_event(now, days):
    """From [(rise, set), ...] for today and tomorrow: (when, 'rise' | 'set') of the
    next one after `now`, or (None, None)."""
    best, kind = None, None
    for rise, sets in days:
        for when, what in ((rise, "rise"), (sets, "set")):
            if when is not None and when >= now and (best is None or when < best):
                best, kind = when, what
    return best, kind


def name(phase):
    """'New moon', 'Waxing crescent', ... for a phase 0..1."""
    names = ("New moon", "Waxing crescent", "First quarter", "Waxing gibbous",
             "Full moon", "Waning gibbous", "Last quarter", "Waning crescent")
    return names[int((phase * 8 + 0.5) % 8)]
