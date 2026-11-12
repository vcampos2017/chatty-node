"""
Bedtime wind-down: once an evening Chatty runs her late-night data desk.

    "Good evening from the Chatty data desk! The bedtime numbers are in. First,
     tomorrow. Tomorrow: sunny, with a high around 61 degrees. Tonight's low is 38,
     so that's a 23 degree swing. Twenty-three degrees! Rain chances top out at
     60 percent around 3 PM. Better than a coin flip, so the umbrella makes the team.
     Now, the node roll call! Greenhouse? Present! 58 degrees, soil at 52 percent.
     Rain gauge? Present, and dry. Lightning node? Present, though its sensor is
     still snoozing. Word clock? Present, and right on time. Naturally. That's
     4 for 4. Perfect attendance! And that's the board. Dimming the lights. Goodnight!"

Then the screen dims for the night (the face's `bedtime` message keeps it at the
night level until night mode ends in the morning) and she dozes off. She still
answers "Hey Chatty" unless CHATTY_BEDTIME_REST=1, which puts her to bed like
"goodnight" does (a tap wakes her).

Her delivery is an excited numbers-nerd election-night desk (Vincent asked for that
kind of charisma), in her own words: percentages, attendance, "big number!".

What's in it:
  - tomorrow's forecast (NWS, the same as "what's the weather tomorrow?"), the swing
    from tonight's low to tomorrow's high, a frost note below freezing, and the peak
    chance of rain tomorrow from the hourly forecast (the one rain_watch.py reads)
  - the node roll call from the MQTT node network (mesh.py): who answered, a reading
    or two from each, and an attendance score
  - a short version on the face as a notice (a tap clears it)

When: at CHATTY_BEDTIME (default 9:30 PM, half an hour before night mode), once an
evening, only while she's awake and free (if you're talking to her she waits, up to
CHATTY_BEDTIME_WINDOW minutes). It counts as the evening's one even after a
restart. If the homecoming watcher (homecoming.py) knows everyone's phone is away,
she doesn't talk to an empty room: only the notice goes on the face.

"Hey Chatty, wind down" / "bedtime routine" / "tuck me in" / "evening briefing" gives it
any time (in the evening it also counts as tonight's and dims the screen).
"Roll call" / "take attendance" gives just the node roll call.

Settings (in /etc/chatty/secrets.env):
    CHATTY_BEDTIME=21:30          when (9:30pm, 22, 21.45 all work; 0 = never on its own)
    CHATTY_BEDTIME_WINDOW=90      minutes after that she may still give it if she was busy
    CHATTY_BEDTIME_NODES          who's in the roll call (default greenhouse,rain,lightning,
                                  wordclock; "0" leaves the roll call out)
    CHATTY_BEDTIME_REST=1         after goodnight, rest until tapped (default: still listening)
    CHATTY_BEDTIME_SCREEN=0       no notice on her face

Try it on the Pi:  python3 src/bedtime.py   (prints tonight's wind-down, says nothing)
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

try:
    import morning_briefing
except ImportError:  # running from another folder
    from . import morning_briefing  # type: ignore

_RAW = os.getenv("CHATTY_BEDTIME", "21:30").strip()
ON = _RAW not in ("0", "off", "")
_NODES = os.getenv("CHATTY_BEDTIME_NODES", "greenhouse,rain,lightning,wordclock").strip()
NODES: List[str] = [] if _NODES in ("", "0") else [n.strip() for n in _NODES.split(",") if n.strip()]
REST = os.getenv("CHATTY_BEDTIME_REST", "0") == "1"
SCREEN = os.getenv("CHATTY_BEDTIME_SCREEN", "1") != "0"
try:
    WINDOW = max(10, min(240, int(os.getenv("CHATTY_BEDTIME_WINDOW", "90"))))
except ValueError:
    WINDOW = 90
STATE_FILE = Path(os.getenv("CHATTY_BEDTIME_STATE",
                            os.path.expanduser("~/.local/share/chatty/bedtime.json")))
SOIL_DRY = morning_briefing.SOIL_DRY

OPENERS = [
    "Good evening from the Chatty data desk! The bedtime numbers are in.",
    "Okay, it's wind-down time, and you know what that means. Let's go to the board!",
    "Stop the presses! It's bedtime, and the numbers just came in.",
    "Alright, final update of the night. Let's dig into the data!",
]
CLOSERS = [
    "And that's the board. Dimming the lights. Goodnight!",
    "My projection for you: a good night's sleep, and a hundred percent chance of sweet dreams. Goodnight!",
    "Final call of the night: I'll be right here in the morning. Ninety-nine point nine percent certain. Sleep well!",
    "That's all the numbers for tonight. Lights going down, data desk signing off. Goodnight!",
]
REST_TAIL = " Tap me if you need me."
NUMBER_WORDS = {
    10: "Ten", 11: "Eleven", 12: "Twelve", 13: "Thirteen", 14: "Fourteen", 15: "Fifteen",
    16: "Sixteen", 17: "Seventeen", 18: "Eighteen", 19: "Nineteen", 20: "Twenty",
    30: "Thirty", 40: "Forty", 50: "Fifty",
}
TITLES = {"greenhouse": "Greenhouse", "rain": "Rain gauge", "lightning": "Lightning node",
          "wordclock": "Word clock"}
TINY_LINES = [   # a kind little Easter egg now and then: Tiny is Vincent's tuxedo cat
    "And Tiny? Tiny does not answer roll calls. Tiny is a cat.",
    "Unofficial result: Tiny, present, on the warmest spot in the house.",
]
TINY_SHARE = 0.2


def start_minute() -> Optional[int]:
    """Minutes after midnight for the wind-down, or None when it's off."""
    if not ON:
        return None
    m = morning_briefing.parse_time(_RAW)
    if m is None:
        print(f"Bedtime: can't read CHATTY_BEDTIME={_RAW!r}, using 9:30 PM", flush=True)
        return 21 * 60 + 30
    return m


def evening_of(now: float) -> str:
    """Which evening this is: 1 AM still belongs to the evening before."""
    return time.strftime("%Y-%m-%d", time.localtime(now - 6 * 3600))


def in_evening(now: float) -> bool:
    """5 PM to 6 AM: when asking for the wind-down counts as tonight's."""
    h = time.localtime(now).tm_hour
    return h >= 17 or h < 6


def _words(n: int) -> str:
    if n in NUMBER_WORDS:
        return NUMBER_WORDS[n]
    tens, ones = divmod(n, 10)
    if tens * 10 in NUMBER_WORDS and 0 < ones:
        ones_word = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"][ones]
        return f"{NUMBER_WORDS[tens * 10]}-{ones_word}"
    return str(n)


# ----------------------------
# tomorrow's numbers
# ----------------------------

def _ts(iso) -> float:
    import rain_watch
    return rain_watch._ts(iso)


def _local_day(ts: float) -> Tuple[int, int, int]:
    d = time.localtime(ts)
    return d.tm_year, d.tm_mon, d.tm_mday


def _midnight_after(ts: float) -> float:
    d = time.localtime(ts)
    return time.mktime((d.tm_year, d.tm_mon, d.tm_mday + 1, 0, 0, 0, 0, 0, -1))


def pick_periods(periods: list, now: float) -> Tuple[Optional[dict], Optional[dict]]:
    """(tonight, tomorrow): the next night period, and the daytime period after it."""
    tonight = None
    for p in periods or []:
        if not isinstance(p, dict):
            continue
        end = _ts(p.get("endTime"))
        if end and end <= now:
            continue
        if not p.get("isDaytime", True):
            if tonight is None:
                tonight = p
        elif tonight is not None:
            return tonight, p
    return tonight, None


def _day_label(p: dict, now: float) -> str:
    start = _ts(p.get("startTime"))
    if start and _local_day(start) == _local_day(now):
        return "today"           # after midnight, "tomorrow" is really today
    if start and _local_day(start) == _local_day(_midnight_after(now)):
        return "tomorrow"
    return p.get("name") or "tomorrow"


def outlook(periods: list, now: float) -> Tuple[List[str], str]:
    """(spoken sentences, screen) for tomorrow: headline, swing, frost."""
    import local_skills
    tonight, day = pick_periods(periods, now)
    if day is None:
        return [], ""
    label = _day_label(day, now)
    # leave the rain chance out of the headline: the hourly peak below says it better
    headline = dict(day, probabilityOfPrecipitation=None)
    said = [local_skills._period_line(headline, label)]
    try:
        high = int(day.get("temperature"))
    except (TypeError, ValueError):
        high = None
    try:
        low = int(tonight.get("temperature")) if tonight else None
    except (TypeError, ValueError):
        low = None
    if high is not None and low is not None and high >= low:
        swing = high - low
        if swing >= 20:
            said.append(f"Tonight's low is {low}, so that's a {swing} degree swing. "
                        f"{_words(swing)} degrees! That's a big number.")
        elif swing >= 10:
            said.append(f"Tonight's low is {low}, a {swing} degree climb by the afternoon.")
        else:
            said.append(f"Tonight's low is {low}, only a {swing} degree spread. Steady as she goes.")
    elif low is not None:
        said.append(f"Tonight's low is {low}.")
    if low is not None and low <= 32:
        said.append(f"Frost watch from the data desk: {low} is below freezing. Bundle up!")
    screen = f"{label.capitalize()}: {(day.get('shortForecast') or '').strip()}"
    if high is not None:
        screen += f" {high}°"
    return said, screen


def rain_tomorrow(hourly: list, day: Optional[dict], now: float) -> Tuple[str, str]:
    """(spoken, screen) for the peak chance of rain during the next day."""
    import rain_watch
    start = _ts(day.get("startTime")) if day else 0.0
    if not start or start < now:
        start = now
    end = _midnight_after(start)
    top, top_at, kind = -1, 0.0, "rain"
    for p in hourly or []:
        if not isinstance(p, dict):
            continue
        s = _ts(p.get("startTime"))
        if not s or s < start - 1 or s >= end:
            continue
        try:
            pop = int((p.get("probabilityOfPrecipitation") or {}).get("value") or 0)
        except (TypeError, ValueError):
            pop = 0
        if pop > top:
            top, top_at = pop, s
            kind = rain_watch._kind(p.get("shortForecast") or "")
    if top < 0:     # no hourly numbers: the day's own chance, if it has one
        try:
            top = int(((day or {}).get("probabilityOfPrecipitation") or {}).get("value") or 0)
        except (TypeError, ValueError):
            return "", ""
        top_at = 0.0
    what = {"storms": "Storm", "snow": "Snow"}.get(kind, "Rain")
    when = f" around {morning_briefing._clock(top_at)}" if top_at else ""
    if top >= 70:
        said = (f"{what} chances peak at {top} percent{when}. At {top} percent, that's not a maybe. "
                + ("Bundle up!" if kind == "snow" else "Umbrella, front and center."))
    elif top >= 50:
        said = (f"{what} chances top out at {top} percent{when}. Better than a coin flip, "
                + ("so the warm boots make the team." if kind == "snow" else "so the umbrella makes the team."))
    elif top >= 20:
        said = f"{what} chances max out at {top} percent. A long shot, but it's on the board."
    elif top > 0:
        said = f"Rain chances stay at {top} percent or less all day. That's a dry day, folks."
    else:
        said = "Zero percent chance of rain, all day. Zero! I love a clean number."
    return said, (f"{what} {top}%" if top >= 20 else "Dry")


# ----------------------------
# the node roll call
# ----------------------------

def _title(name: str) -> str:
    if name in TITLES:
        return TITLES[name]
    import mesh
    return mesh.title_for(name)


def _num(d: dict, key: str) -> Optional[float]:
    try:
        return float(d[key]) if d.get(key) is not None else None
    except (TypeError, ValueError):
        return None


def _greenhouse(d: dict) -> str:
    m = d.get("metrics") if isinstance(d.get("metrics"), dict) else d
    temp, soil, volts = _num(m, "air_temperature_f"), _num(m, "soil_moisture_percent"), _num(m, "soil_voltage")
    bits = []
    if temp is not None:
        bits.append(f"{temp:.0f} degrees")
    if volts is not None and abs(volts) < 0.05:
        bits.append("but the soil probe isn't reporting")      # about 0 V = unplugged, not wet
    elif soil is not None:
        bits.append(f"soil at {soil:.0f} percent" + (", a little thirsty. That's a job for the morning"
                                                      if soil < SOIL_DRY else ""))
    if not bits:
        return "Greenhouse? Present!"
    text = ", ".join(bits)
    return "Greenhouse? Present! " + text[0].upper() + text[1:] + "."


def _lightning(d: dict) -> str:
    if str(d.get("sensor", "ok")).lower() == "missing":
        return "Lightning node? Present, though its sensor is still snoozing."
    try:
        n = int(d.get("strikes_today") or 0)
    except (TypeError, ValueError):
        n = 0
    if n > 0:
        return (f"Lightning node? Present, with {n} strike{'s' if n != 1 else ''} since midnight."
                + (f" {_words(n)}!" if n >= 10 else ""))
    return "Lightning node? Present. Zero strikes today, a quiet sky."


def _present(name: str, d: dict, raining: bool) -> str:
    if name == "greenhouse":
        return _greenhouse(d) if d else "Greenhouse? Present!"
    if name == "lightning":
        return _lightning(d) if d else "Lightning node? Present."
    if name == "rain":
        return ("Rain gauge? Present, and working overtime. It's raining right now!" if raining
                else "Rain gauge? Present, and dry.")
    if name == "wordclock":
        return "Word clock? Present, and right on time. Naturally."
    return f"{_title(name)}? Present."


def roll_call(mesh, raining: bool = False, now: Optional[float] = None,
              names: Optional[List[str]] = None, tiny: Optional[bool] = None) -> Tuple[str, str]:
    """(spoken, screen) roll call of the nodes from the MQTT node network."""
    names = NODES if names is None else names
    if not names:
        return "", ""
    now = time.time() if now is None else now
    if mesh is None or getattr(mesh, "client", True) is None:
        return "My node network isn't running, so no roll call tonight.", ""
    tracker = getattr(mesh, "tracker", mesh)
    with tracker.lock:
        known = {name: (n.online, n.last_seen) for name, n in tracker.nodes.items()}
    lines, here = [], 0
    for name in names:
        title = _title(name)
        if name not in known:
            lines.append(f"{title}? No answer tonight.")
            continue
        up, seen = known[name]
        if not up:
            since = f" Quiet since {morning_briefing._clock(seen)}." if seen else " Quiet."
            lines.append(f"{title}? ... {title}?{since} I'll leave the porch light on for it.")
            continue
        here += 1
        d = tracker.latest(name, max_age=3 * 3600, now=now) or {}
        lines.append(_present(name, d, raining))
    total = len(names)
    if not getattr(mesh, "connected", True):
        lines.insert(0, "I can't reach my message board right now, so this is from the last numbers I had.")
    if total == 1:
        score = ""
    elif here == total:
        score = f"That's {here} for {here}. Perfect attendance!"
    elif here == 0:
        score = f"That's zero for {total}. Everybody's quiet. I'll keep listening."
    else:
        score = f"That's {here} of {total}, {round(100 * here / total)} percent attendance."
    if score:
        lines.append(score)
    if tiny is None:
        tiny = random.random() < TINY_SHARE
    if tiny:
        lines.append(random.choice(TINY_LINES))
    return " ".join(lines), f"Nodes {here}/{total}"


# ----------------------------
# putting it together
# ----------------------------

def _forecast() -> list:
    import weather_lookup
    return weather_lookup.get_forecast()["properties"]["periods"]


def _hourly() -> list:
    import weather_lookup
    return weather_lookup.get_hourly()


def _face_notice(text: str) -> None:
    import face_link
    face_link.notice(text)


class WindDown:
    """Builds the wind-down in the background each evening. The voice node calls
    due(mode) from its main loop, says what comes back, then tucks her in."""

    def __init__(self, mesh=None, raining: Callable[[], bool] = lambda: False,
                 home: Callable[[], Optional[bool]] = lambda: None,
                 forecast: Callable[[], list] = _forecast, hourly: Callable[[], list] = _hourly,
                 notice: Callable[[str], None] = _face_notice,
                 clock: Callable[[], float] = time.time,
                 start: Callable[[], Optional[int]] = start_minute,
                 state_file: Path = STATE_FILE, rest: bool = REST):
        self.mesh, self.raining, self.home = mesh, raining, home
        self.forecast, self.hourly, self.notice = forecast, hourly, notice
        self.clock, self.start, self.state_file, self.rest = clock, start, state_file, rest
        self.screen = ""
        self._ready: Optional[Tuple[str, str]] = None
        self._fetching = False
        self._tries = 0
        self._last_try = -1e12
        self._done = self._load()

    # ----- once an evening -----
    def _load(self) -> str:
        try:
            return json.loads(self.state_file.read_text()).get("evening", "")
        except Exception:
            return ""

    def _save(self, evening: str) -> None:
        self._done = evening
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps({"evening": evening}))
        except Exception as e:
            print("Bedtime: couldn't save state:", repr(e), flush=True)

    def _raining(self) -> bool:
        try:
            return bool(self.raining())
        except Exception:
            return False

    # ----- the words -----
    def build(self, now: Optional[float] = None) -> Tuple[str, str]:
        """(spoken, screen) for right now. Never raises: missing pieces are left out."""
        now = self.clock() if now is None else now
        parts, screen = [random.choice(OPENERS)], []
        day = None
        try:
            periods = self.forecast()
            said, short = outlook(periods, now)
            day = pick_periods(periods, now)[1]
            if said:
                parts.append("First, the outlook.")
                parts.extend(said)
                screen.append(short)
        except Exception as e:
            print("Bedtime: forecast failed:", repr(e), flush=True)
            parts.append("The weather service isn't answering, so tomorrow stays a mystery for now.")
        try:
            hourly = self.hourly()
        except Exception as e:
            print("Bedtime: hourly forecast failed:", repr(e), flush=True)
            hourly = []
        if day is not None or hourly:
            said, short = rain_tomorrow(hourly, day, now)
            if said:
                parts.append(said)
                screen.append(short)
        try:
            said, short = roll_call(self.mesh, raining=self._raining(), now=now)
            if said:
                parts.append("Now, the node roll call!")
                parts.append(said)
                if short:
                    screen.append(short)
        except Exception as e:
            print("Bedtime: roll call failed:", repr(e), flush=True)
        parts.append(random.choice(CLOSERS) + (REST_TAIL if self.rest else ""))
        text = " ".join(p.strip() for p in parts if p and p.strip())
        return text, ("Goodnight! " + " · ".join(screen)) if screen else ""

    def _fetch(self) -> None:
        try:
            self._ready = self.build()
        except Exception as e:
            print("Bedtime: couldn't build the wind-down:", repr(e), flush=True)
        finally:
            self._fetching = False

    def _window(self, now: float) -> bool:
        start = self.start()
        if start is None:
            return False
        lt = time.localtime(now)
        since = (lt.tm_hour * 60 + lt.tm_min - start) % (24 * 60)
        return since < WINDOW

    def due(self, mode: str, now: Optional[float] = None) -> Optional[str]:
        """The wind-down to say now, or None. Call from the main loop."""
        now = self.clock() if now is None else now
        evening = evening_of(now)
        if self._done == evening:
            return None
        if not self._window(now):
            self._ready, self._tries = None, 0
            return None
        if self._ready is None:
            # build it in the background so she never freezes on the network
            if not self._fetching and self._tries < 4 and now - self._last_try > 300:
                self._fetching = True
                self._tries += 1
                self._last_try = now
                threading.Thread(target=self._fetch, daemon=True).start()
            return None
        if mode != "sleep":          # "sleep" = awake and waiting for her name
            return None
        (text, self.screen), self._ready = self._ready, None
        self._save(evening)
        self._show()
        try:
            home = self.home()
        except Exception:
            home = None
        if home is False:
            print("Bedtime: nobody's home, so the wind-down is only on the screen", flush=True)
            return None
        return text

    def _show(self) -> None:
        if SCREEN and self.screen:
            try:
                self.notice(self.screen[:300])
            except Exception as e:
                print("Bedtime: couldn't show the notice:", repr(e), flush=True)

    # ----- on request -----
    def answer(self, now: Optional[float] = None) -> Tuple[str, bool]:
        """'Hey Chatty, wind down.' (text, tuck_in): in the evening it counts as tonight's."""
        now = self.clock() if now is None else now
        text, self.screen = self.build(now)
        tonight = in_evening(now)
        if tonight:
            self._save(evening_of(now))
            self._ready = None
        return text, tonight

    def roll_call(self, now: Optional[float] = None) -> str:
        """'Hey Chatty, roll call.'"""
        now = self.clock() if now is None else now
        said, _ = roll_call(self.mesh, raining=self._raining(), now=now, names=NODES or None)
        return said or "There's nobody on my roll call list."


ASK = re.compile(r"\bwind(ing)? (it )?down\b|\bbedtime (routine|report|rundown|briefing|numbers|update)\b|"
                 r"\b(night|nightly|evening|bedtime) (briefing|report|rundown|update|numbers)\b|"
                 r"\btuck (me|yourself|you) in\b")
ROLL = re.compile(r"\broll ?call\b|\btake (the )?attendance\b")


def asked(prompt: str) -> bool:
    return bool(ASK.search(prompt or ""))


def asked_roll_call(prompt: str) -> bool:
    return bool(ROLL.search(prompt or "")) and not asked(prompt)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from dotenv import load_dotenv
        load_dotenv("/etc/chatty/secrets.env")
    except ImportError:
        pass
    import mesh as mesh_mod
    m = start_minute()
    print("Wind-down time:", f"{m // 60}:{m % 60:02d}" if m is not None else "off (on request only)")
    net = mesh_mod.Mesh(on_events=lambda events: None)
    net.start()
    if net.client is not None:
        print("Listening to the node network for 10 seconds...")
        time.sleep(10)
    w = WindDown(mesh=net)
    spoken, screen = w.build()
    print(" Says:", spoken)
    print(" Face:", screen)
