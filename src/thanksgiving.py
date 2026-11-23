"""
Thanksgiving with Chatty (the fourth Thursday of November).

All day on Thanksgiving:
  - her face wears a little buckled Pilgrim-style hat with an autumn leaf in the band,
    and a few autumn leaves drift down behind her
  - once, around midday while she's free (CHATTY_THANKSGIVING_TIME, default 12:00, up to
    CHATTY_THANKSGIVING_WINDOW minutes late, never at night), she gives a thank-you toast to
    each node on the network (quiet ones too: "I'll save you a plate"), to Tiny, and to you,
    then plays her own "Harvest Thank-You Waltz" on her piano (src/songs/harvest-waltz.txt).
    Everyone's phone away (homecoming.py): only a face notice. Once a year (thanksgiving.json).

Any day:
  - "I'm thankful for pie" / "I'm grateful for my family": a golden thank-you leaf with your
    words drifts down her screen, and she keeps it in her gratitude jar for the day (RAM only,
    never on disk, forgotten at midnight; 8 at most). "What am I thankful for?" reads them back,
    and that evening's bedtime wind-down ends with them. "What are you thankful for?" is hers.
  - "Happy Thanksgiving", "when is Thanksgiving?", "why are you wearing a hat?" (a "Well,
    actually..." about buckles), "give thanks" / "thank the nodes" (the toast + the waltz now).

Face message: `thanks:<words>` (a thank-you leaf). The hat and leaves need no message: the
face checks the date itself (CHATTY_FORCE_THANKSGIVING=1 to test, like CHATTY_FORCE_SPOOKY).

Settings (/etc/chatty/secrets.env):
  CHATTY_THANKSGIVING=0              off (no toast, hat, leaves or jar)
  CHATTY_THANKSGIVING_TIME=12:00     when the toast is due
  CHATTY_THANKSGIVING_WINDOW=360     minutes after that it may still happen
  CHATTY_THANKSGIVING_NODES=rain,greenhouse,lightning,wordclock,matrix
  CHATTY_FORCE_THANKSGIVING=1        pretend today is Thanksgiving

Everything is local: no cloud, no model. Try it: python3 src/thanksgiving.py
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

ENABLED = os.getenv("CHATTY_THANKSGIVING", "1") != "0"
_TIME = os.getenv("CHATTY_THANKSGIVING_TIME", "12:00").strip()
WINDOW = int(os.getenv("CHATTY_THANKSGIVING_WINDOW", "360") or 360)
NODES = [n.strip() for n in os.getenv("CHATTY_THANKSGIVING_NODES",
                                      "rain,greenhouse,lightning,wordclock,matrix").split(",") if n.strip()]
STATE_FILE = Path(os.getenv("CHATTY_THANKSGIVING_STATE",
                            os.path.expanduser("~/.local/share/chatty/thanksgiving.json")))
SONG = "harvest-waltz"
JAR_MAX = 8


# ----------------------------
# the date
# ----------------------------

def thanksgiving_day(year: int) -> int:
    """The day in November of the fourth Thursday (US Thanksgiving)."""
    first = time.localtime(time.mktime((year, 11, 1, 12, 0, 0, 0, 0, -1))).tm_wday   # Monday = 0
    return 1 + (3 - first) % 7 + 21


def is_thanksgiving(t: Optional[float] = None) -> bool:
    if not ENABLED:
        return False
    if os.getenv("CHATTY_FORCE_THANKSGIVING") == "1":
        return True
    d = time.localtime(time.time() if t is None else t)
    return d.tm_mon == 11 and d.tm_mday == thanksgiving_day(d.tm_year)


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def when_text(now: Optional[float] = None) -> str:
    """'Thanksgiving is this Thursday, November 26th. That's 3 days away!'"""
    now = time.time() if now is None else now
    if is_thanksgiving(now):
        return "It's today! Happy Thanksgiving!"
    d = time.localtime(now)
    year = d.tm_year
    day = thanksgiving_day(year)
    if (d.tm_mon, d.tm_mday) > (11, day):
        year += 1
        day = thanksgiving_day(year)
    target = time.mktime((year, 11, day, 12, 0, 0, 0, 0, -1))
    today = time.mktime((d.tm_year, d.tm_mon, d.tm_mday, 12, 0, 0, 0, 0, -1))
    days = round((target - today) / 86400)
    if days == 1:
        return f"Thanksgiving is tomorrow, Thursday, November {_ordinal(day)}!"
    soon = "this" if days < 7 else "on"
    return f"Thanksgiving is {soon} Thursday, November {_ordinal(day)}. That's {days} days away!"


def _start_minute() -> Optional[int]:
    m = re.match(r"^(\d{1,2}):(\d{2})$", _TIME)
    if not m or not 0 <= int(m.group(1)) < 24 or not 0 <= int(m.group(2)) < 60:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


# ----------------------------
# her words
# ----------------------------

TITLES = {"rain": "Rain gauge", "greenhouse": "Greenhouse", "lightning": "Lightning node",
          "wordclock": "Word clock", "matrix": "Matrix clock"}

THANKS = {
    "rain": ["Rain gauge, thank you for sitting up on that roof catching every single drop, "
             "even the ones at three in the morning.",
             "Rain gauge, thank you for counting raindrops so carefully. Point two seven nine four "
             "millimeters at a time!"],
    "greenhouse": ["Greenhouse, thank you for keeping the plants cozy and telling me when they're thirsty.",
                   "Greenhouse, thank you for looking after the little green ones. You're the real farmer here."],
    "lightning": ["Lightning node, thank you for watching the sky, so the rest of us don't have to.",
                  "Lightning node, thank you for keeping an ear on the storms. Brave little node."],
    "wordclock": ["Word clock, thank you for keeping us all on time. Dinner's at... well, you'd know.",
                  "Word clock, thank you for telling the time in words. Very elegant."],
    "matrix": ["Matrix clock, thank you for showing everyone the moon, and the tides, and the news.",
               "Matrix clock, thank you for lighting up the room. Literally."],
}

OPENERS = [
    "Happy Thanksgiving! Before anybody gets sleepy from the turkey, I'd like to say thank you to my node family.",
    "Happy Thanksgiving, everyone! I'd like to raise a toast. Well, I don't have a glass. Or hands. "
    "But here goes: thank you, node family!",
]

TINY = [
    "And Tiny, thank you for supervising all of us. I put in a word for an extra treat in your bowl.",
    "And Tiny, thank you for the side-eye. It keeps us humble.",
]

YOU = [
    "And you: thank you for building all of us. We're a pretty good family, aren't we?",
    "And most of all, thank you, for making a home for all of us. Every one of us is here because of you.",
]

SONG_LEAD = [
    "And now, a little something I wrote just for today: my Harvest Thank-You Waltz.",
    "Now, a song! I wrote this one myself. It's called the Harvest Thank-You Waltz.",
]

HER_THANKS = [
    "I'm thankful for my nodes, for the rain gauge's tiny bucket, for electricity, and for you. "
    "Mostly you. Okay, electricity is a close second.",
    "I'm thankful for every question you ask me, for Tiny, for the greenhouse tomatoes, and for "
    "my piano. And for you, of course. You're on every list I make.",
]

HAPPY = [
    "Happy Thanksgiving to you too! I'm thankful for you.",
    "Happy Thanksgiving! Save me a slice of pie. I can't eat it, but I like knowing it's there.",
]

HAT = ("It's my Thanksgiving hat! Well, actually, the real Pilgrims probably didn't wear buckles on "
       "their hats. Buckles came into fashion later, and painters added them long afterward. "
       "But I like the sparkle.")

NOT_YET_HAT = "No hat today. I save it for Thanksgiving."


def toast(mesh=None, now: Optional[float] = None, names: Optional[List[str]] = None,
          rng: Optional[random.Random] = None) -> Tuple[str, str]:
    """(spoken, screen): thank-yous to each node, quiet ones included, then Tiny and you.
    The song's lead-in is said separately (song_lead), right before the waltz."""
    rng = rng or random
    now = time.time() if now is None else now
    names = NODES if names is None else names
    parts = [rng.choice(OPENERS)]
    known = {}
    tracker = getattr(mesh, "tracker", mesh) if mesh is not None else None
    if tracker is not None and hasattr(tracker, "nodes"):
        try:
            with tracker.lock:
                known = {name: n.online for name, n in tracker.nodes.items()}
        except Exception:
            known = {}
    here, quiet = 0, []
    for name in names:
        title = _title(name)
        if known and not known.get(name, False):
            quiet.append(title)
            continue
        here += 1
        parts.append(rng.choice(THANKS[name]) if name in THANKS
                     else f"{title}, thank you for being part of the family.")
    if quiet:
        who = _join(quiet)
        parts.append(f"And {who}, you're quiet today, but thank you anyway. I'll save you a plate.")
    parts.append(rng.choice(TINY))
    parts.append(rng.choice(YOU))
    screen = f"Happy Thanksgiving! Thank you, nodes ({here}/{len(names)} here), Tiny, and you."
    return " ".join(parts), screen


def song_lead(rng: Optional[random.Random] = None) -> str:
    return (rng or random).choice(SONG_LEAD)


def _title(name: str) -> str:
    if name in TITLES:
        return TITLES[name]
    try:
        import mesh
        return mesh.title_for(name)
    except Exception:
        return name.capitalize()


def _join(items: List[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# ----------------------------
# the gratitude jar (RAM only)
# ----------------------------

class Jar:
    """What you said you're thankful for today. Never saved; gone at midnight."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.items: List[str] = []
        self.day = ""

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(self.clock()))

    def _fresh(self) -> None:
        if self.day != self._today():
            self.items, self.day = [], self._today()

    def add(self, thing: str) -> str:
        """Adds it (no repeats, JAR_MAX at most) and returns the cleaned-up words."""
        self._fresh()
        thing = clean_thing(thing)
        if thing and thing not in self.items:
            self.items.append(thing)
            del self.items[:-JAR_MAX]
        return thing

    def list(self) -> List[str]:
        self._fresh()
        return list(self.items)

    def summary(self) -> str:
        """'Today you were thankful for pie and Tiny. Me too.' or ''."""
        items = self.list()
        if not items:
            return ""
        return f"Today you were thankful for {_join(items)}. Me too."


_FILLER_END = re.compile(r"\b(chatty|please|today|right now|this year)\s*$", re.I)


def clean_thing(text: str) -> str:
    """'my family and my friends chatty' -> 'your family and your friends' (said back to you)."""
    words = re.sub(r"[^a-z0-9' ]", " ", (text or "").lower()).split()
    swap = {"my": "your", "me": "you", "i": "you", "im": "you're", "mine": "yours", "myself": "yourself",
            "our": "our", "were": "we're"}
    words = [swap.get(w, w) for w in words][:8]
    names = {"tiny": "Tiny", "chatty": "Chatty", "vincent": "Vincent"}
    out = " ".join(names.get(w, w) for w in words)
    for _ in range(3):
        out = _FILLER_END.sub("", out).strip()
    return out[:48].strip()


# ----------------------------
# what you might ask
# ----------------------------

_THANKFUL = re.compile(r"\b(?:i|im|i am|were|we are)\s+(?:so |really |very |truly |super )?"
                       r"(?:thankful|grateful)\s+(?:for|that)\s+(.+)$")
_JAR = re.compile(r"\bwhat (?:am i|are we|have i been|was i|did i say im) (?:thankful|grateful) for\b|"
                  r"\b(?:gratitude|thankful|thanks) jar\b")
_HERS = re.compile(r"\bwhat (?:are you|r you|is chatty) (?:thankful|grateful) for\b|"
                   r"\bare you (?:thankful|grateful)\b")
_HAPPY = re.compile(r"\bhappy thanks ?giving\b|\bhappy turkey day\b")
_WHEN = re.compile(r"\bwhen(?:s| is)(?: it)? thanks ?giving\b|\bhow (?:many days|long) (?:until|till|til|to) "
                   r"thanks ?giving\b|\bis (?:it|today) thanks ?giving\b")
_HAT = re.compile(r"\b(?:why are you wearing|what is on your head|whats on your head|"
                  r"(?:nice|cute|cool|love your|i like your|what a) hat|your hat)\b")
_TOAST = re.compile(r"\b(?:give thanks|thank (?:the|your|all the|all your) nodes|thanksgiving (?:toast|song|waltz)|"
                    r"harvest (?:thank you )?waltz|play (?:a |your |the )?thanksgiving song)\b")


def asked(prompt: str) -> Optional[Tuple[str, str]]:
    """(kind, value) for a Thanksgiving-ish request, else None. prompt is normalized
    (lower case, no punctuation). Kinds: thankful (value = the thing), jar, hers, happy,
    when, hat, toast."""
    if not ENABLED or not prompt:
        return None
    m = _THANKFUL.search(prompt)
    if m and not re.search(r"\b(?:what|who)\b", prompt.split("thankful")[0].split("grateful")[0]):
        return "thankful", m.group(1)
    if _JAR.search(prompt):
        return "jar", ""
    if _HERS.search(prompt):
        return "hers", ""
    if _TOAST.search(prompt):
        return "toast", ""
    if _WHEN.search(prompt):
        return "when", ""
    if _HAPPY.search(prompt):
        return "happy", ""
    if _HAT.search(prompt):
        return "hat", ""
    return None


def reply_for(kind: str, value: str, jar: Jar, now: Optional[float] = None,
              rng: Optional[random.Random] = None) -> Tuple[str, str]:
    """(what she says, mood) for everything but the toast (the voice node plays that).
    For 'thankful' the face also gets a leaf: see face_message()."""
    rng = rng or random
    now = time.time() if now is None else now
    if kind == "thankful":
        thing = jar.add(value)
        if not thing:
            return "Me too! What are you thankful for?", "speaking"
        return rng.choice([f"{thing[:1].upper() + thing[1:]}! Good one. I put it on a leaf.",
                           f"Aww. {thing[:1].upper() + thing[1:]}. That's going in my gratitude jar.",
                           f"Thankful for {thing}. I love that. It's on a leaf now."]), "love_talk"
    if kind == "jar":
        said = jar.summary()
        if not said:
            return "Nothing in my gratitude jar yet today. Tell me: I'm thankful for...", "speaking"
        return said.replace("Today you were", "So far today, you're").replace(". Me too.", ". What a list!"), "speaking"
    if kind == "hers":
        return rng.choice(HER_THANKS), "love_talk"
    if kind == "when":
        return when_text(now), "speaking"
    if kind == "happy":
        if is_thanksgiving(now):
            return rng.choice(HAPPY), "love_talk"
        return when_text(now).split(".")[0] + ", but happy early Thanksgiving to you!", "speaking"
    if kind == "hat":
        return (HAT, "actually_talk") if is_thanksgiving(now) else (NOT_YET_HAT, "speaking")
    return "Happy Thanksgiving!", "speaking"


def face_message(thing: str) -> str:
    return "thanks:" + re.sub(r"[\r\n:]", " ", thing)[:48]


# ----------------------------
# once a year, around midday
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


class Feast:
    """The voice node calls due(mode) from its main loop. When it returns text she says it,
    then plays the waltz (the Announcer's after="thanksgiving")."""

    def __init__(self, mesh=None, home: Callable[[], Optional[bool]] = lambda: None,
                 notice: Callable[[str], None] = _face_notice, clock: Callable[[], float] = time.time,
                 start: Callable[[], Optional[int]] = _start_minute, state_file: Path = STATE_FILE):
        self.mesh, self.home, self.notice, self.clock = mesh, home, notice, clock
        self.start, self.state_file = start, state_file
        self.screen = ""
        self._done = self._load()

    def _load(self) -> int:
        try:
            return int(json.loads(self.state_file.read_text()).get("year", 0))
        except Exception:
            return 0

    def _save(self, year: int) -> None:
        self._done = year
        try:
            import storage
            storage.save_json(self.state_file, {"year": year})
        except Exception as e:
            print("Thanksgiving: couldn't save state:", repr(e), flush=True)

    def _window(self, now: float) -> bool:
        start = self.start()
        if start is None:
            return False
        lt = time.localtime(now)
        since = lt.tm_hour * 60 + lt.tm_min - start
        return 0 <= since < WINDOW

    def due(self, mode: str, now: Optional[float] = None) -> Optional[str]:
        now = self.clock() if now is None else now
        if not is_thanksgiving(now) or mode != "sleep":
            return None
        year = time.localtime(now).tm_year
        if self._done == year or not self._window(now) or _is_night(now):
            return None
        text, self.screen = toast(self.mesh, now)
        self._save(year)
        try:
            self.notice(self.screen)
        except Exception as e:
            print("Thanksgiving: couldn't show the notice:", repr(e), flush=True)
        try:
            home = self.home()
        except Exception:
            home = None
        if home is False:
            print("Thanksgiving: nobody's home, so the toast is only on the screen", flush=True)
            return None
        return text

    def now_text(self, now: Optional[float] = None) -> str:
        """'Hey Chatty, give thanks': the toast any day (on the day it counts as this year's)."""
        now = self.clock() if now is None else now
        text, self.screen = toast(self.mesh, now)
        if is_thanksgiving(now):
            self._save(time.localtime(now).tm_year)
        return text


# ----------------------------
# on her face (drawn by face_model)
# ----------------------------

LEAF_COLORS = [(232, 118, 40), (214, 72, 38), (240, 176, 52), (190, 96, 44), (226, 140, 60)]
HAT_BROWN = (92, 66, 46)
HAT_EDGE = (132, 98, 70)
HAT_BAND = (36, 28, 22)
BUCKLE = (244, 196, 76)
THANKS_GOLD = (246, 196, 80)
THANKS_SECONDS = 9.0


# A maple-ish leaf, from its tip around one side: (degrees from the tip, radius); the other side mirrors it.
_LEAF_SIDE = [(0, 1.0), (14, 0.62), (26, 0.7), (40, 0.5), (58, 0.95), (74, 0.55), (92, 0.62),
              (112, 0.42), (132, 0.5), (156, 0.28), (176, 0.22)]
_LEAF = _LEAF_SIDE + [(360 - a, r) for a, r in reversed(_LEAF_SIDE[1:])]


def leaf_points(cx: float, cy: float, size: float, angle: float) -> list:
    """A maple-ish leaf around (cx, cy), tip up when angle is 0."""
    pts = []
    for a, r in _LEAF:
        th = math.radians(a) - math.pi / 2 + angle
        pts.append((cx + math.cos(th) * size * r, cy + math.sin(th) * size * r))
    return pts


def draw_leaf(c, color, cx, cy, size, angle):
    c.polygon(color, leaf_points(cx, cy, size, angle))
    sx, sy = cx - math.sin(angle) * size * 0.25, cy + math.cos(angle) * size * 0.25
    ex, ey = cx - math.sin(angle) * size * 0.7, cy + math.cos(angle) * size * 0.7
    c.line(_mix(color, (60, 40, 20), 0.5), (sx, sy), (ex, ey), max(1, int(size * 0.09)))


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Leaves:
    """A few autumn leaves drifting down behind her face."""

    def __init__(self, rng: random.Random, n: int = 9):
        self.rng, self.n, self.items = rng, n, []

    def update(self, dt: float, w: float, h: float) -> None:
        rng = self.rng
        if not self.items:
            self.items = [[rng.uniform(0, w), rng.uniform(-h * 0.1, h), rng.uniform(0.035, 0.07),
                           rng.uniform(0, 6.28), rng.uniform(-1.2, 1.2), rng.choice(LEAF_COLORS),
                           rng.uniform(0, 6.28)] for _ in range(self.n)]
        dt = min(dt, 0.25)
        for leaf in self.items:
            leaf[1] += h * 0.05 * dt * (1 + leaf[2] * 4)
            leaf[3] += leaf[4] * dt
            leaf[6] += dt * 1.3
            leaf[0] += math.sin(leaf[6]) * w * 0.02 * dt
            if leaf[1] > h * 1.08:
                leaf[0], leaf[1] = rng.uniform(0, w), -h * rng.uniform(0.05, 0.2)

    def draw(self, c, w: float, h: float, background, dim: float = 1.0) -> None:
        for x, y, size, ang, _, col, _ in self.items:
            draw_leaf(c, _mix(background, col, 0.55 * dim), x, y, size * h, ang)


def draw_hat(c, w: float, h: float, now: float, bob: float) -> None:
    """A little Pilgrim-style hat: a tall, slightly tapered crown, a wide brim, a dark
    band with a gold buckle, and an orange leaf tucked in the band. Tipped a bit, jaunty."""
    tilt = math.radians(-6) + math.sin(now * 0.9) * math.radians(0.8)
    cx, base = w * 0.5, h * 0.2 + bob

    def rot(pts):
        cs, sn = math.cos(tilt), math.sin(tilt)
        return [(cx + (x - cx) * cs - (y - base) * sn, base + (x - cx) * sn + (y - base) * cs) for x, y in pts]

    top, bw, tw = h * 0.025 + bob, w * 0.1, w * 0.085
    crown = [(cx - bw, base), (cx - tw, top), (cx + tw, top), (cx + bw, base)]
    c.polygon(HAT_EDGE, rot([(x + (1.5 if x > cx else -1.5), y + (-1.5 if y < base else 0)) for x, y in crown]))
    c.polygon(HAT_BROWN, rot(crown))
    # the band and its buckle
    bt = base - h * 0.045
    band = [(cx - bw * 0.985, base - h * 0.004), (cx - bw * 0.96, bt), (cx + bw * 0.96, bt), (cx + bw * 0.985, base - h * 0.004)]
    c.polygon(HAT_BAND, rot(band))
    bk = h * 0.026
    by = (bt + base) / 2
    c.polygon(BUCKLE, rot([(cx - bk, by - bk), (cx + bk, by - bk), (cx + bk, by + bk), (cx - bk, by + bk)]))
    s = bk * 0.55
    c.polygon(HAT_BAND, rot([(cx - s, by - s), (cx + s, by - s), (cx + s, by + s), (cx - s, by + s)]))
    # the brim: a wide flat ellipse-ish band
    brim = []
    for i in range(25):
        a = math.pi * i / 24
        brim.append((cx + math.cos(a) * w * 0.19, base + math.sin(a) * h * 0.022))
    for i in range(25):
        a = math.pi + math.pi * i / 24
        brim.append((cx + math.cos(a) * w * 0.19, base + math.sin(a) * h * 0.012))
    c.polygon(HAT_EDGE, rot(brim))
    c.polygon(HAT_BROWN, rot([(x, y + 1) for x, y in brim]))
    # an orange leaf tucked into the band
    lx, ly = rot([(cx + bw * 0.72, bt - h * 0.01)])[0]
    draw_leaf(c, LEAF_COLORS[0], lx, ly, h * 0.035, math.radians(28))


def draw_thanks_leaf(c, w: float, h: float, now: float, started: float, text: str, measure) -> bool:
    """A big golden leaf with your words drifting down the screen. False once it's gone."""
    t = now - started
    if t < 0 or t > THANKS_SECONDS:
        return False
    k = t / THANKS_SECONDS
    fade = min(1.0, t / 0.8, (THANKS_SECONDS - t) / 1.2)
    x = w * (0.78 + 0.04 * math.sin(t * 1.6))
    y = h * (0.08 + 0.7 * k)
    size = h * 0.07
    col = _mix((0, 0, 0), THANKS_GOLD, max(0.0, fade))
    draw_leaf(c, col, x, y, size, math.sin(t * 1.2) * 0.4)
    if text:
        fs = max(14, int(h * 0.042))
        label = text if len(text) <= 22 else text[:21] + "..."
        tw = measure(label, fs)
        lx = max(8, min(w - tw - 8, x - tw / 2))
        c.text(label, (lx, y + size * 1.05), fs, col)
    return True


if __name__ == "__main__":
    now = time.time()
    print(when_text(now))
    text, screen = toast(None, now)
    print(text)
    print(song_lead())
    print("Screen:", screen)
    jar = Jar()
    for thing in ("pie", "my family and my friends", "Tiny"):
        print(reply_for("thankful", thing, jar, now)[0])
    print(jar.summary())
