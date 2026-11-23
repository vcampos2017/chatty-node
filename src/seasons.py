"""
Chatty's season days: the first day of summer is a party, and the first days of spring,
fall and winter get a small celebration of their own.

The dates come from the sky, worked out right here on the Pi: the solstices and equinoxes
(Jean Meeus, Astronomical Algorithms, chapter 27; good to about a minute for years
2000-3000), then turned into the Pi's own local date. No calendar lookups, no internet.

The first day of summer (the June solstice):
  - sunglasses on her face, a big smiling sun in the corner, a lazy seagull or two
  - once, in the daytime while she's free (CHATTY_SEASONS_TIME, default 10:00, up to
    CHATTY_SEASONS_WINDOW minutes late): "Happy first day of summer!", then a summer breeze
    comes along and blows thousands of Chatty Bucks right off her screen (her own play money,
    with her face on it: she takes it very well), then she plays her own "Sunny Day Shuffle"
    on her piano (src/songs/sunny-day-shuffle.txt)
The first day of spring / fall / winter: blossoms, falling leaves or snowflakes drift behind
her face all day, and she says a short hello to the new season once in the daytime.
Everyone's phone away (homecoming.py): only a face notice. Once per season (seasons.json).

Any day:
  "Hey Chatty, celebrate summer" / "first day of summer!"  the whole summer party now
  "celebrate spring / fall / autumn / winter"               that season's hello + decorations
  "when is the first day of summer?" / "when does winter start?" / "when is the solstice?"
  "how many days until summer?", "when is the longest day of the year?"
  "what is a solstice?" / "what is an equinox?"
  "why are you wearing sunglasses?"
  "blow the money away" / "chatty bucks"                    just the money breeze

Face messages: `season:<summer|spring|autumn|winter>` (that season's look for a few minutes,
any day) and `season:bills` (the money breeze). The everyday look needs no message: the face
checks the date itself (CHATTY_FORCE_SEASON=summer|spring|autumn|winter to test).

Settings (/etc/chatty/secrets.env):
  CHATTY_SEASONS=0              off (no party, decorations or hellos; questions still answered)
  CHATTY_SEASONS_TIME=10:00     when the day's celebration is due
  CHATTY_SEASONS_WINDOW=480     minutes after that it may still happen
  CHATTY_SEASONS_SMALL=0        only summer (no spring / fall / winter days)
  CHATTY_FORCE_SEASON=summer    pretend today is that season's first day

All local: no cloud, no model. Try it: python3 src/seasons.py
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ENABLED = os.getenv("CHATTY_SEASONS", "1") != "0"
SMALL = os.getenv("CHATTY_SEASONS_SMALL", "1") != "0"
_TIME = os.getenv("CHATTY_SEASONS_TIME", "10:00").strip()
WINDOW = int(os.getenv("CHATTY_SEASONS_WINDOW", "480") or 480)
STATE_FILE = Path(os.getenv("CHATTY_SEASONS_STATE",
                            os.path.expanduser("~/.local/share/chatty/seasons.json")))
SONG = "sunny-day-shuffle"
SEASONS = ("spring", "summer", "autumn", "winter")
SHOW_SECONDS = 240.0        # how long `season:<name>` shows that season's look on another day
BILLS_SECONDS = 14.0        # how long the money breeze blows

# ----------------------------
# the sky's dates
# ----------------------------

# Meeus, table 27.A (years 2000-3000): the mean instant, as a Julian Ephemeris Day
_MEAN = {
    "spring": (2451623.80984, 365242.37404, 0.05169, -0.00411, -0.00057),   # March equinox
    "summer": (2451716.56767, 365241.62603, 0.00325, 0.00888, -0.00030),    # June solstice
    "autumn": (2451810.21715, 365242.01767, -0.11575, 0.00337, 0.00078),    # September equinox
    "winter": (2451900.05952, 365242.74049, -0.06223, -0.00823, 0.00032),   # December solstice
}
# Meeus, table 27.C: the periodic terms (A, B degrees, C degrees per century)
_TERMS = [
    (485, 324.96, 1934.136), (203, 337.23, 32964.467), (199, 342.08, 20.186),
    (182, 27.85, 445267.112), (156, 73.14, 45036.886), (136, 171.52, 22518.443),
    (77, 222.54, 65928.934), (74, 296.72, 3034.906), (70, 243.58, 9037.513),
    (58, 119.81, 33718.147), (52, 297.17, 150.678), (50, 21.02, 2281.226),
    (45, 247.54, 29929.562), (44, 325.15, 31555.956), (29, 60.93, 4443.417),
    (18, 155.12, 67555.328), (17, 288.79, 4562.452), (16, 198.04, 62894.029),
    (14, 199.76, 31436.921), (12, 95.39, 14577.848), (12, 287.11, 31931.756),
    (12, 320.81, 34777.259), (9, 227.73, 1222.114), (8, 15.45, 16859.074),
]
_DELTA_T = 69.0             # seconds between the sky's clock (TT) and ours (UTC), these years


def instant(season: str, year: int) -> float:
    """The Unix time of that season's solstice or equinox in that year (UTC, to about a minute)."""
    y = (year - 2000) / 1000.0
    a = _MEAN[season]
    jde0 = a[0] + a[1] * y + a[2] * y ** 2 + a[3] * y ** 3 + a[4] * y ** 4
    t = (jde0 - 2451545.0) / 36525.0
    w = math.radians(35999.373 * t - 2.47)
    dl = 1 + 0.0334 * math.cos(w) + 0.0007 * math.cos(2 * w)
    s = sum(A * math.cos(math.radians(B + C * t)) for A, B, C in _TERMS)
    jde = jde0 + 0.00001 * s / dl
    return (jde - 2440587.5) * 86400.0 - _DELTA_T


def first_day(season: str, year: int) -> Tuple[int, int]:
    """(month, day) of that season's first day on this Pi's own calendar."""
    d = time.localtime(instant(season, year))
    return d.tm_mon, d.tm_mday


def _on(season: str) -> bool:
    return ENABLED and (season == "summer" or SMALL)


def season_today(t: Optional[float] = None) -> Optional[str]:
    """'summer' on the first day of summer (and so on), else None."""
    forced = os.getenv("CHATTY_FORCE_SEASON", "").strip().lower()
    forced = "autumn" if forced == "fall" else forced
    if forced in SEASONS:
        return forced if _on(forced) else None
    d = time.localtime(time.time() if t is None else t)
    for season in SEASONS:
        if _on(season) and first_day(season, d.tm_year) == (d.tm_mon, d.tm_mday):
            return season
    return None


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
NAMES = {"spring": "spring", "summer": "summer", "autumn": "fall", "winter": "winter"}
SKY_NAMES = {"spring": "the spring equinox", "summer": "the summer solstice",
             "autumn": "the fall equinox", "winter": "the winter solstice"}


def next_first_day(season: str, now: Optional[float] = None) -> Tuple[int, int, int, int]:
    """(year, month, day, days away) of that season's next first day (0 days = today)."""
    now = time.time() if now is None else now
    d = time.localtime(now)
    today = time.mktime((d.tm_year, d.tm_mon, d.tm_mday, 12, 0, 0, 0, 0, -1))
    for year in (d.tm_year, d.tm_year + 1):
        m, day = first_day(season, year)
        target = time.mktime((year, m, day, 12, 0, 0, 0, 0, -1))
        days = round((target - today) / 86400)
        if days >= 0:
            return year, m, day, days
    return d.tm_year + 1, m, day, days       # never reached


def _clock(t: float) -> str:
    lt = time.localtime(t)
    hour = lt.tm_hour % 12 or 12
    return f"{hour}:{lt.tm_min:02d} {'AM' if lt.tm_hour < 12 else 'PM'}"


def when_text(season: str, now: Optional[float] = None) -> str:
    """'The first day of summer is Sunday, June 20th, 2027. That's 209 days away!'"""
    now = time.time() if now is None else now
    year, m, day, days = next_first_day(season, now)
    name = NAMES[season]
    weekday = time.strftime("%A", time.localtime(time.mktime((year, m, day, 12, 0, 0, 0, 0, -1))))
    exact = _clock(instant(season, year))
    if days == 0:
        return f"It's today! Happy first day of {name}! {SKY_NAMES[season].capitalize()} is at {exact}."
    when = f"{weekday}, {MONTHS[m - 1]} {_ordinal(day)}"
    if days == 1:
        return f"The first day of {name} is tomorrow, {when}! {SKY_NAMES[season].capitalize()} is at {exact}."
    if year != time.localtime(now).tm_year:
        when += f", {year}"
    return f"The first day of {name} is {when}. That's {days} days away!"


def next_season(now: Optional[float] = None) -> str:
    """The season whose first day comes next (today counts)."""
    return min(SEASONS, key=lambda s: next_first_day(s, now)[3])


def _start_minute() -> Optional[int]:
    m = re.match(r"^(\d{1,2}):(\d{2})$", _TIME)
    if not m or not 0 <= int(m.group(1)) < 24 or not 0 <= int(m.group(2)) < 60:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


# ----------------------------
# her words (all her own)
# ----------------------------

SUMMER_OPEN = [
    "Happy first day of summer! The sun is working overtime today: this is the longest day of the "
    "whole year. I put on my sunglasses for the occasion. Do they make me look cool? Don't answer that.",
    "It's officially summer! The longest day of the year, the shortest night, and the best excuse to "
    "wear sunglasses indoors. Which I am doing. On purpose.",
]

BREEZE = [
    "Oh! Feel that summer breeze? Wait. Wait, that's my money! Look at it go! Thousands of Chatty "
    "Bucks, fluttering off into the sky! Goodbye, money! Write if you get work! Oh well. Sunshine is free.",
    "Ooh, a summer breeze! Whoa, whoa, there goes my piggy bank! Thousands of Chatty Bucks, just "
    "floating away on the wind! Easy come, easy go. Honestly, the best parts of summer don't cost a thing.",
]

BREEZE_SHORT = [
    "Whoosh! There go thousands of Chatty Bucks, off on their own summer vacation. Bon voyage!",
    "Look at it all go! Easy come, easy go. Good thing sunshine is free.",
]

SUMMER_NODES = [
    "Greenhouse, enjoy all that extra sunlight. Rain gauge, I hope you get the day off.",
    "Greenhouse, this is your big day: maximum sunshine. Lightning node, keep an eye out for summer storms.",
]

SUMMER_LEAD = [
    "And now, a summer song I wrote myself. It's called the Sunny Day Shuffle.",
    "Time for my summer song! I wrote it myself: the Sunny Day Shuffle.",
]

SUMMER_CLOSE = [
    "Happy summer! Drink some water, and wear your sunscreen.",
    "Happy summer, everybody! Stay cool out there. I'll be right here, in my shades.",
]

HELLOS = {
    "spring": [
        "Happy first day of spring! Today day and night are just about the same length, and from "
        "here on the days win. Greenhouse, this is your season!",
        "Spring is here! It's the equinox, so day and night are almost even today. Time for "
        "blossoms, seedlings, and opening the windows.",
    ],
    "autumn": [
        "Happy first day of fall! Day and night are about even today, and from now on the nights get "
        "a little longer. Sweater weather. Well, for you. I'd just get lint in my ports.",
        "Fall is here! It's the equinox: day and night are nearly the same length. Leaves are "
        "turning, and so is the season.",
    ],
    "winter": [
        "Happy first day of winter! Tonight is the longest night of the whole year. But here's the "
        "good part: starting tomorrow, every day gets a little longer. The light always comes back.",
        "Winter is here! It's the solstice, the shortest day of the year. From now on the sunshine "
        "comes back, a minute or two at a time.",
    ],
}

SCREENS = {"summer": "Happy first day of summer!", "spring": "Happy first day of spring!",
           "autumn": "Happy first day of fall!", "winter": "Happy first day of winter!"}

SHADES = ("They're my summer sunglasses! It's the first day of summer, and the sun is out all day. "
          "Also, I think they make me look very cool.")
NO_SHADES = "No sunglasses today. I save them for the first day of summer."

EXPLAIN = {
    "solstice": "A solstice is the moment the sun is farthest north or south in our sky. In June it "
                "gives us the longest day of the year, the first day of summer. In December, the "
                "shortest day, the first day of winter. The word means the sun standing still.",
    "equinox": "An equinox is the moment the sun crosses the equator, so day and night are about the "
               "same length everywhere. It happens twice a year: the first day of spring in March, "
               "and the first day of fall in September. The word means equal night.",
}

MOODS = {"summer": "mischief_talk", "spring": "love_talk", "autumn": "speaking", "winter": "love_talk"}


def celebration(season: str, rng: Optional[random.Random] = None) -> List[Tuple[str, str, str]]:
    """Her celebration as (face message to send first, words, mood) steps. For summer the piano
    song comes after these (song_lead + SONG), then SUMMER_CLOSE."""
    rng = rng or random
    if season == "summer":
        return [("season:summer", rng.choice(SUMMER_OPEN), "mischief_talk"),
                ("season:bills", rng.choice(BREEZE), "love_talk"),
                ("", rng.choice(SUMMER_NODES), "speaking")]
    return [(f"season:{season}", rng.choice(HELLOS[season]), MOODS[season])]


def song_lead(rng: Optional[random.Random] = None) -> str:
    return (rng or random).choice(SUMMER_LEAD)


def summer_close(rng: Optional[random.Random] = None) -> str:
    return (rng or random).choice(SUMMER_CLOSE)


# ----------------------------
# what you might ask
# ----------------------------

_SEASON = r"(summer|spring|fall|autumn|winter)"
_CELEBRATE = re.compile(r"\b(?:celebrate|celebrating|party for|throw a|lets celebrate) (?:the )?"
                        r"(?:first day of )?" + _SEASON + r"\b|"
                        r"\b" + _SEASON + r" (?:party|celebration)\b|"
                        r"^(?:its |it is )?(?:the )?first day of " + _SEASON + r"$")
_WHEN = re.compile(r"\b(?:when(?:s| is| does| will)|what day is|how (?:many days|long) (?:until|till|til|to|before))"
                   r"(?: the)?(?: it)?(?: first day of)? " + _SEASON + r"(?: start| begin| come)?\b|"
                   r"\bwhen(?:s| is)(?: the)? (?:(summer|winter|june|december) solstice|"
                   r"(spring|fall|autumn|march|september) equinox|(longest|shortest) (?:day|night))\b|"
                   r"\bwhen(?:s| is)(?: the)? next (solstice|equinox)\b|\bwhen(?:s| is)(?: the)? (solstice|equinox)\b")
_EXPLAIN = re.compile(r"\bwhat(?:s| is| are)(?: an?| the)? (solstice|equinox)(?:es|s)?\b")
_SHADES = re.compile(r"\b(?:sunglasses|shades)\b")
_BILLS = re.compile(r"\b(?:chatty bucks|blow (?:the|your|all the) money(?: away)?|money (?:in the|on the) "
                    r"(?:breeze|wind)|money breeze|throw (?:your|the) money)\b")
_HAPPY = re.compile(r"\bhappy (?:first day of )?" + _SEASON + r"\b|\bhappy (solstice|equinox)\b")

_SKY_WORD = {"june": "summer", "december": "winter", "march": "spring", "september": "autumn",
             "longest": "summer", "shortest": "winter", "fall": "autumn"}


def _season_word(word: str) -> str:
    return _SKY_WORD.get(word, word)


def asked(prompt: str, now: Optional[float] = None) -> Optional[Tuple[str, str]]:
    """(kind, season) for a season-ish request, else None. prompt is normalized (lower case,
    no punctuation). Kinds: celebrate, when, explain (season = solstice|equinox), shades,
    bills, happy."""
    if not prompt:
        return None
    m = _EXPLAIN.search(prompt)
    if m:
        return "explain", m.group(1)
    m = _WHEN.search(prompt)
    if m:
        word = next(g for g in m.groups() if g)
        if word in ("solstice", "equinox"):
            nxt = [s for s in SEASONS if (s in ("summer", "winter")) == (word == "solstice")]
            return "when", min(nxt, key=lambda s: next_first_day(s, now)[3])
        return "when", _season_word(word)
    m = _CELEBRATE.search(prompt)
    if m:
        return "celebrate", _season_word(next(g for g in m.groups() if g))
    if _SHADES.search(prompt) and re.search(r"\b(?:why|what|your|nice|cool|cute|love|like)\b", prompt):
        return "shades", ""
    if _BILLS.search(prompt):
        return "bills", "summer"
    m = _HAPPY.search(prompt)
    if m:
        word = next(g for g in m.groups() if g)
        if word in ("solstice", "equinox"):
            word = season_today(now) or next_season(now)
        return "happy", _season_word(word)
    return None


def reply_for(kind: str, season: str, now: Optional[float] = None,
              rng: Optional[random.Random] = None) -> Tuple[str, str]:
    """(what she says, mood) for when / explain / shades / happy / bills. The celebration
    itself is played by the voice node (celebration())."""
    rng = rng or random
    now = time.time() if now is None else now
    if kind == "when":
        return when_text(season, now), "speaking"
    if kind == "explain":
        return EXPLAIN[season], "speaking"
    if kind == "shades":
        return (SHADES, "mischief_talk") if season_today(now) == "summer" else (NO_SHADES, "speaking")
    if kind == "bills":
        return rng.choice(BREEZE_SHORT), "love_talk"
    if kind == "happy":
        if season_today(now) == season:
            return f"Happy first day of {NAMES[season]} to you too!", MOODS[season]
        text = when_text(season, now).split(".")[0]
        return f"{text}. But happy almost-{NAMES[season]} to you!", "speaking"
    return "Happy new season!", "speaking"


# ----------------------------
# once per season, in the daytime
# ----------------------------

def _face_notice(text: str) -> None:
    import face_link
    face_link.notice(text)


def _is_night(now: float) -> bool:
    try:
        import quiet_hours
        return quiet_hours.is_night(now)
    except Exception:
        return False


class SeasonDay:
    """The voice node calls due(mode) from its main loop. When it returns the first line she says
    it, then plays the rest with rest_of_party() (the Announcer's after="season")."""

    def __init__(self, home: Callable[[], Optional[bool]] = lambda: None,
                 notice: Callable[[str], None] = _face_notice, clock: Callable[[], float] = time.time,
                 start: Callable[[], Optional[int]] = _start_minute, state_file: Path = STATE_FILE,
                 send: Callable[[str], None] = lambda msg: None):
        self.home, self.notice, self.clock = home, notice, clock
        self.start, self.state_file, self.send = start, state_file, send
        self.steps: List[Tuple[str, str, str]] = []
        self.season = ""
        self._done = self._load()

    def _load(self) -> List[str]:
        try:
            return list(json.loads(self.state_file.read_text()).get("done", []))[-8:]
        except Exception:
            return []

    def _save(self, key: str) -> None:
        self._done = (self._done + [key])[-8:]
        try:
            import storage
            storage.save_json(self.state_file, {"done": self._done})
        except Exception as e:
            print("Seasons: couldn't save state:", repr(e), flush=True)

    def _window(self, now: float) -> bool:
        start = self.start()
        if start is None:
            return False
        lt = time.localtime(now)
        since = lt.tm_hour * 60 + lt.tm_min - start
        return 0 <= since < WINDOW

    def due(self, mode: str, now: Optional[float] = None) -> Optional[Tuple[str, str]]:
        now = self.clock() if now is None else now
        season = season_today(now)
        if not season or mode != "sleep":
            return None
        key = f"{time.localtime(now).tm_year}-{season}"
        if key in self._done or not self._window(now) or _is_night(now):
            return None
        self._save(key)
        try:
            self.notice(SCREENS[season])
        except Exception as e:
            print("Seasons: couldn't show the notice:", repr(e), flush=True)
        try:
            home = self.home()
        except Exception:
            home = None
        if home is False:
            print("Seasons: nobody's home, so it's only on the screen", flush=True)
            return None
        return self.begin(season)

    def begin(self, season: str) -> Tuple[str, str]:
        """Sends the first step's face message and returns its (words, mood); the rest wait
        in self.steps for rest_of_party()."""
        steps = celebration(season)
        self.season, self.steps = season, steps[1:]
        msg, words, mood = steps[0]
        if msg:
            self.send(msg)
        return words, mood

    def now_steps(self, season: str, now: Optional[float] = None) -> List[Tuple[str, str, str]]:
        """'Hey Chatty, celebrate summer': the whole thing any day (on the day it counts)."""
        now = self.clock() if now is None else now
        if season_today(now) == season:
            key = f"{time.localtime(now).tm_year}-{season}"
            if key not in self._done:
                self._save(key)
        self.season, self.steps = season, []
        return celebration(season)


# ----------------------------
# on her face (drawn by face_model)
# ----------------------------

SUN = (255, 204, 64)
SUN_RAY = (255, 170, 50)
LENS = (18, 22, 34)
LENS_SHEEN = (40, 70, 96)
FRAME = (244, 96, 128)
BILL = (126, 178, 118)
BILL_DARK = (62, 112, 66)
BILL_LIGHT = (196, 226, 180)
PETALS = [(250, 190, 214), (255, 222, 236), (238, 160, 196), (255, 240, 246)]
SNOW = (226, 236, 250)


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_sun(c, w: float, h: float, now: float, background, dim: float = 1.0) -> None:
    """A big smiling sun peeking in from the top-left corner, its rays turning slowly."""
    cx, cy, r = w * 0.075, h * 0.1, h * 0.085
    ray, body = _mix(background, SUN_RAY, 0.8 * dim), _mix(background, SUN, 0.9 * dim)
    spin = now * 0.25
    for i in range(12):
        a = spin + i * math.pi / 6
        long = 1.55 if i % 2 else 1.85
        tip = (cx + math.cos(a) * r * long, cy + math.sin(a) * r * long)
        s1 = (cx + math.cos(a - 0.16) * r * 1.1, cy + math.sin(a - 0.16) * r * 1.1)
        s2 = (cx + math.cos(a + 0.16) * r * 1.1, cy + math.sin(a + 0.16) * r * 1.1)
        c.polygon(ray, [s1, tip, s2])
    c.ellipse(body, (cx - r, cy - r, 2 * r, 2 * r))
    face = _mix(background, (150, 92, 30), 0.85 * dim)
    for dx in (-0.32, 0.32):
        c.ellipse(face, (cx + dx * r - r * 0.08, cy - r * 0.22, r * 0.16, r * 0.2))
    c.arc(face, (cx - r * 0.42, cy - r * 0.2, r * 0.84, r * 0.62), math.pi * 1.1, math.pi * 1.9,
          max(2, int(r * 0.08)))


def draw_gulls(c, w: float, h: float, now: float, background, dim: float = 1.0) -> None:
    """Two lazy seagulls gliding across the top of the screen."""
    col = _mix(background, (220, 226, 236), 0.6 * dim)
    for i, (speed, y, size) in enumerate(((0.018, 0.07, 0.04), (0.013, 0.15, 0.03))):
        x = ((now * speed + i * 0.47) % 1.3 - 0.15) * w
        yy = h * y + math.sin(now * 1.4 + i) * h * 0.01
        s = h * size
        flap = math.sin(now * 3 + i * 2) * s * 0.25
        c.polyline(col, [(x - s, yy - s * 0.15 - flap), (x - s * 0.45, yy - s * 0.42 + flap * 0.4),
                         (x, yy), (x + s * 0.45, yy - s * 0.42 + flap * 0.4),
                         (x + s, yy - s * 0.15 - flap)], max(3, int(h * 0.008)))


def draw_sunglasses(c, w: float, h: float, cy: float, gx: float, now: float) -> None:
    """Big round-cornered summer shades over her eyes: coral frames, dark lenses with a
    blue-green sheen, a glint sweeping across now and then, arms back to the edges."""
    lw, lh = w * 0.2, h * 0.375
    top = cy - lh * 0.5
    fw = max(4, int(h * 0.012))
    centers = (w * 0.34 + gx, w * 0.66 + gx)
    # the arms and the bridge first, so the lenses sit on top
    c.line(FRAME, (centers[0] - lw * 0.5, top + lh * 0.18), (w * 0.08, top + lh * 0.08), fw)
    c.line(FRAME, (centers[1] + lw * 0.5, top + lh * 0.18), (w * 0.92, top + lh * 0.08), fw)
    c.arc(FRAME, (centers[0] + lw * 0.42, top + lh * 0.12, centers[1] - centers[0] - lw * 0.84, lh * 0.25),
          math.pi * 0.15, math.pi * 0.85, fw)
    glint = (now * 0.35) % 1.0           # a shine slides across every few seconds
    for x in centers:
        rect = (x - lw / 2, top, lw, lh)
        c.rrect(FRAME, (rect[0] - fw, rect[1] - fw, rect[2] + 2 * fw, rect[3] + 2 * fw), radius=lh * 0.4)
        c.rrect(LENS, rect, radius=lh * 0.36)
        c.rrect(LENS_SHEEN, (rect[0] + lw * 0.06, rect[1] + lh * 0.62, lw * 0.88, lh * 0.32), radius=lh * 0.16)
        c.rrect(LENS, (rect[0] + lw * 0.06, rect[1] + lh * 0.58, lw * 0.88, lh * 0.08), radius=lh * 0.04)
        if glint < 0.35:
            k = glint / 0.35
            gx0 = rect[0] + lw * (0.05 + 0.75 * k)
            c.line((235, 245, 255), (gx0, rect[1] + lh * 0.15), (gx0 + lw * 0.12, rect[1] + lh * 0.12), max(3, fw - 1))
            c.line((235, 245, 255), (gx0 - lw * 0.04, rect[1] + lh * 0.32), (gx0 + lw * 0.16, rect[1] + lh * 0.22),
                   max(2, fw - 2))
        else:
            c.ellipse((200, 220, 240), (rect[0] + lw * 0.16, rect[1] + lh * 0.16, lw * 0.12, lh * 0.12))


def _bill_corners(x, y, bw, bh, angle, flip):
    """The four corners of a bill turning on the wind: angle tilts it, flip squashes it
    (|flip| near 0 = edge-on), like paper fluttering."""
    hw, hh = bw / 2 * max(0.08, abs(flip)), bh / 2
    cs, sn = math.cos(angle), math.sin(angle)
    return [(x + dx * cs - dy * sn, y + dx * sn + dy * cs) for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]


class Breeze:
    """The money breeze: a stream of Chatty Bucks (play money with her face on it) blowing in
    from the left, tumbling and fluttering across the screen and off the right side."""

    def __init__(self, rng: random.Random, started: float, n: int = 46):
        self.started = started
        self.bills = []
        for i in range(n):
            self.bills.append(dict(
                t0=rng.uniform(0, BILLS_SECONDS * 0.6),     # when it blows in
                y=rng.uniform(0.08, 0.92), speed=rng.uniform(0.11, 0.22),
                size=rng.uniform(0.85, 1.25), spin=rng.uniform(1.5, 4.2), phase=rng.uniform(0, 6.28),
                tumble=rng.uniform(-1.6, 1.6), lift=rng.uniform(0.04, 0.1)))

    def alive(self, now: float) -> bool:
        return now - self.started < BILLS_SECONDS + 4

    def draw(self, c, w: float, h: float, now: float) -> None:
        t = now - self.started
        bw, bh = w * 0.11, w * 0.11 * 0.43
        for b in self.bills:
            age = t - b["t0"]
            if age < 0:
                continue
            x = -bw + age * b["speed"] * w * (1 + 0.15 * math.sin(age * 0.7 + b["phase"]))
            if x > w + bw:
                continue
            y = h * b["y"] - age * h * b["lift"] * 0.5 + math.sin(age * 1.8 + b["phase"]) * h * 0.05
            angle = math.sin(age * 1.1 + b["phase"]) * 0.5 + b["tumble"] * age * 0.15
            flip = math.cos(age * b["spin"] + b["phase"])
            s = b["size"]
            pts = _bill_corners(x, y, bw * s, bh * s, angle, flip)
            front = flip > 0
            c.polygon(BILL_DARK, pts)
            inner = _bill_corners(x, y, bw * s * 0.9, bh * s * 0.8, angle, flip)
            c.polygon(BILL if front else _mix(BILL, BILL_DARK, 0.35), inner)
            if abs(flip) > 0.55:
                # her portrait in the middle: a little oval with two eyes and a smile
                r = bh * s * 0.3
                squash = abs(flip)
                c.ellipse(BILL_LIGHT, (x - r * squash, y - r, 2 * r * squash, 2 * r))
                if front:
                    for dx in (-0.35, 0.35):
                        ex = x + math.cos(angle) * dx * r * squash
                        ey = y + math.sin(angle) * dx * r - r * 0.15
                        c.ellipse(BILL_DARK, (ex - r * 0.1, ey - r * 0.2, r * 0.2, r * 0.4))
                    c.arc(BILL_DARK, (x - r * 0.45 * squash, y - r * 0.15, r * 0.9 * squash, r * 0.6),
                          math.pi * 1.1, math.pi * 1.9, max(1, int(r * 0.15)))
                    # a "C" in two corners (Chatty Bucks)
                    fs = max(9, int(bh * s * 0.34))
                    for k in (0, 2):
                        px, py = pts[k]
                        px += (x - px) * 0.3
                        py += (y - py) * 0.3
                        c.text("C", (px - fs * 0.3, py - fs * 0.55), fs, BILL_DARK)


class Drift:
    """Petals (spring), leaves (fall) or snowflakes (winter) drifting down behind her face."""

    def __init__(self, rng: random.Random, n: int = 14):
        self.rng, self.n, self.items, self.kind = rng, n, [], ""

    def update(self, kind: str, dt: float, w: float, h: float) -> None:
        rng = self.rng
        if kind != self.kind or not self.items:
            self.kind = kind
            self.items = [[rng.uniform(0, w), rng.uniform(-h * 0.1, h), rng.uniform(0.012, 0.03),
                           rng.uniform(0, 6.28), rng.uniform(-1.4, 1.4), rng.uniform(0, 6.28),
                           rng.randrange(4)] for _ in range(self.n)]
        dt = min(dt, 0.25)
        fall = {"winter": 0.045, "spring": 0.035}.get(kind, 0.05)
        for it in self.items:
            it[1] += h * fall * dt * (1 + it[2] * 20)
            it[3] += it[4] * dt
            it[5] += dt * 1.1
            it[0] += math.sin(it[5]) * w * 0.025 * dt
            if it[1] > h * 1.06:
                it[0], it[1] = rng.uniform(0, w), -h * rng.uniform(0.03, 0.15)

    def draw(self, c, w: float, h: float, background, dim: float = 1.0) -> None:
        for x, y, size, ang, _, _, pick in self.items:
            s = size * h
            if self.kind == "winter":
                col = _mix(background, SNOW, 0.8 * dim)
                if pick == 0:          # now and then a proper six-armed snowflake
                    s *= 1.6
                    for k in range(3):
                        a = ang + k * math.pi / 3
                        c.line(col, (x - math.cos(a) * s, y - math.sin(a) * s),
                               (x + math.cos(a) * s, y + math.sin(a) * s), max(2, int(s * 0.18)))
                else:
                    c.ellipse(col, (x - s * 0.45, y - s * 0.45, s * 0.9, s * 0.9))
            elif self.kind == "spring":
                col = _mix(background, PETALS[pick], 0.85 * dim)
                s *= 1.5
                if pick == 0:          # now and then a whole little blossom
                    for k in range(5):
                        a = ang + k * math.tau / 5
                        px, py = x + math.cos(a) * s * 0.55, y + math.sin(a) * s * 0.55
                        c.ellipse(col, (px - s * 0.38, py - s * 0.38, s * 0.76, s * 0.76))
                    c.ellipse(_mix(background, (250, 214, 90), dim), (x - s * 0.24, y - s * 0.24, s * 0.48, s * 0.48))
                else:
                    k = abs(math.cos(ang))
                    c.ellipse(col, (x - s * (0.3 + 0.3 * k), y - s * 0.35, s * (0.6 + 0.6 * k), s * 0.7))
            else:
                try:
                    import thanksgiving
                    col = thanksgiving.LEAF_COLORS[pick % len(thanksgiving.LEAF_COLORS)]
                    thanksgiving.draw_leaf(c, _mix(background, col, 0.75 * dim), x, y, s * 2.2, ang)
                except Exception:
                    c.ellipse(_mix(background, (226, 140, 60), 0.55 * dim), (x - s, y - s, 2 * s, 2 * s))


def parse_face_message(value: str) -> str:
    """'summer' / 'bills' / 'fall' from `season:<value>`; '' if it isn't one."""
    v = (value or "").strip().lower()
    v = "autumn" if v == "fall" else v
    return v if v in SEASONS or v == "bills" else ""


if __name__ == "__main__":
    now = time.time()
    year = time.localtime(now).tm_year
    for s in SEASONS:
        print(f"{s:7s}", time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(instant(s, year))),
              "|", when_text(s, now))
    print("Today:", season_today(now) or "an ordinary day")
    for msg, words, mood in celebration("summer"):
        print(f"[{msg or '-'}] ({mood})", words)
    print(song_lead(), "...", summer_close())
