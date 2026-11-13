"""
Morning briefing: once a day Chatty says good morning and gives a short rundown.

    "Good morning! It's Sunday, November 8th. Right now it's 45 degrees and cloudy.
     Today: Sunny, with a high near 62. Rain is likely around 3 PM, about a 70 percent
     chance, so an umbrella might be handy. All three nodes checked in. The greenhouse
     is 58 degrees and the soil is at 52 percent. Have a lovely day!"

What's in it:
  - the weather (the same words as "Hey Chatty, what's the weather?", local_skills.py)
  - the chance of rain for the rest of today, from the NWS hourly forecast (the
    same forecast rain_watch.py reads)
  - the node network (mesh.py): who checked in, who has gone quiet, the greenhouse
    reading, lightning strikes since midnight, and rain the gauge feels right now

When: at CHATTY_MORNING_TIME (default 7:30), or later if night mode is still on
(CHATTY_NIGHT_END) or she's busy. Only while she's awake and free, never after
noon, and once a day even if she restarts (it shares morning_weather.py's day
counter, so it's never said twice). A short version stays on her face as a
notice, in case nobody was in the room; a tap clears it.

"Hey Chatty, morning briefing" (or "brief me", "what's my briefing") gives it any time.

Settings (in /etc/chatty/secrets.env):
    CHATTY_MORNING_BRIEFING=0     back to the plain morning weather
    CHATTY_MORNING_WEATHER=0      no morning news at all (still works on request)
    CHATTY_MORNING_TIME=7:30      when to give it (7, 7:30, 07:45, 6:30am all work)
    CHATTY_MORNING_HOUR           older setting, used when CHATTY_MORNING_TIME isn't set
    CHATTY_MORNING_NODES          which nodes to report (default greenhouse,rain,lightning;
                                  "0" leaves the node network out)
    CHATTY_MORNING_SCREEN=0       don't leave the notice on her face

Try it on the Pi:  python3 src/morning_briefing.py   (prints today's briefing, says nothing)
"""
from __future__ import annotations

import os
import random
import re
import time
from typing import Callable, List, Optional, Tuple

try:
    import morning_weather
    import quiet_hours
except ImportError:  # running from another folder
    from . import morning_weather, quiet_hours  # type: ignore

ON = os.getenv("CHATTY_MORNING_BRIEFING", "1") != "0"
SCREEN = os.getenv("CHATTY_MORNING_SCREEN", "1") != "0"
_NODES = os.getenv("CHATTY_MORNING_NODES", "greenhouse,rain,lightning").strip()
NODES: List[str] = [] if _NODES in ("", "0") else [n.strip() for n in _NODES.split(",") if n.strip()]
RAIN_LIKELY = 50     # percent: "rain is likely"
RAIN_MAYBE = 20      # percent: "a small chance"
SOIL_DRY = float(os.getenv("CHATTY_SOIL_DRY", "35"))

CLOSERS = [
    "Have a lovely day!",
    "Have a wonderful day!",
    "Be kind out there, and have a good one!",
    "I'll keep an eye on things here. Have a great day!",
    "That's all from me. Go be awesome!",
]
NUMBERS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def parse_time(raw: str) -> Optional[int]:
    """'7:30', '6:30am', '21.45', '1:15 pm' -> minutes after midnight (None if unreadable)."""
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", (raw or "").strip().lower())
    if not m:
        return None
    h, mins = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3) and m.group(3).startswith("p") and h < 12:
        h += 12
    if m.group(3) and m.group(3).startswith("a") and h == 12:
        h = 0
    if 0 <= h <= 23 and 0 <= mins <= 59:
        return h * 60 + mins
    return None


def start_minute() -> int:
    """Minutes after midnight for the briefing (default 7:30)."""
    raw = os.getenv("CHATTY_MORNING_TIME", "").strip().lower()
    if not raw and os.getenv("CHATTY_MORNING_HOUR", "").strip():
        return morning_weather._start_minute()
    m = parse_time(raw)
    if m is not None:
        return m
    if raw:
        print(f"Morning briefing: can't read CHATTY_MORNING_TIME={raw!r}, using 7:30", flush=True)
    return 7 * 60 + 30


def _clock(ts: float) -> str:
    d = time.localtime(ts)
    if d.tm_min == 0:
        return f"{d.tm_hour % 12 or 12} {'AM' if d.tm_hour < 12 else 'PM'}"
    return f"{d.tm_hour % 12 or 12}:{d.tm_min:02d} {'AM' if d.tm_hour < 12 else 'PM'}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def greeting(now: float, on_request: bool = False) -> str:
    d = time.localtime(now)
    part = "Good morning" if 4 <= d.tm_hour < 12 else ("Good afternoon" if d.tm_hour < 17 else "Good evening")
    day = time.strftime("%A, %B ", d) + _ordinal(d.tm_mday)
    if on_request:
        return f"{part}! Here's your briefing for {day}."
    return f"{part}! It's {day}."


# ----------------------------
# rain for the rest of today
# ----------------------------

def _end_of_day(now: float) -> float:
    d = time.localtime(now)
    midnight = time.mktime((d.tm_year, d.tm_mon, d.tm_mday + 1, 0, 0, 0, 0, 0, -1))
    return max(midnight, now + 6 * 3600)     # late starts still look a few hours ahead


def rain_today(periods: list, now: float) -> Tuple[str, str]:
    """(spoken, screen) about the chance of rain from now to the end of the day."""
    import rain_watch
    hours = (_end_of_day(now) - now) / 3600
    likely = rain_watch.assess(periods, now, hours=hours, chance=RAIN_LIKELY)
    if likely:
        word = {"storms": "Thunderstorms are", "snow": "Snow is"}.get(likely.kind, "Rain is")
        short = {"storms": "Storms", "snow": "Snow"}.get(likely.kind, "Rain")
        if likely.starts - now <= 30 * 60:
            when, when_short = "soon", "soon"
        else:
            when, when_short = f"around {_clock(likely.starts)}", f"~{_clock(likely.starts)}"
        tip = "so bundle up" if likely.kind == "snow" else "so an umbrella might be handy"
        return (f"{word} likely {when}, about a {likely.chance} percent chance, {tip}.",
                f"{short} {likely.chance}% {when_short}")
    top = 0
    horizon = now + hours * 3600
    for p in periods or []:
        if not isinstance(p, dict):
            continue
        start, end = rain_watch._ts(p.get("startTime")), rain_watch._ts(p.get("endTime"))
        if not start or (end or start + 3600) <= now:
            continue
        if start >= horizon:
            break
        try:
            top = max(top, int((p.get("probabilityOfPrecipitation") or {}).get("value") or 0))
        except (TypeError, ValueError):
            pass
    if top >= RAIN_MAYBE:
        return f"There's a small chance of rain today, up to {top} percent.", f"Rain {top}% at most"
    return "No rain expected today.", "No rain today"


# ----------------------------
# the node network
# ----------------------------

def _title(name: str) -> str:
    return {"greenhouse": "greenhouse", "rain": "rain gauge", "lightning": "lightning node"}.get(
        name, name.replace("-", " ").replace("_", " ") + " node")


def _join(items: List[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _greenhouse_line(d: dict) -> str:
    m = d.get("metrics") if isinstance(d.get("metrics"), dict) else d
    try:
        temp = float(m["air_temperature_f"]) if m.get("air_temperature_f") is not None else None
    except (TypeError, ValueError):
        temp = None
    try:
        soil = float(m["soil_moisture_percent"]) if m.get("soil_moisture_percent") is not None else None
    except (TypeError, ValueError):
        soil = None
    try:
        unplugged = m.get("soil_voltage") is not None and abs(float(m["soil_voltage"])) < 0.05
    except (TypeError, ValueError):
        unplugged = False
    warm = f"The greenhouse is {temp:.0f} degrees" if temp is not None else ""
    if unplugged:
        # about 0 volts means the probe is unplugged, not 100% wet
        return (warm + ", but I can't feel the soil probe." if warm
                else "I can't feel the greenhouse soil probe. Is it unplugged?")
    if soil is None:
        return warm + "." if warm else ""
    soil_words = f"the soil is at {soil:.0f} percent"
    import soil as soil_mod   # the greenhouse's own label first
    if soil_mod.state(soil, m.get("soil_moisture_band")) == "dry":
        soil_words += ", so the plants are thirsty"
        try:
            import rain_hold
            why = rain_hold.reason()
        except Exception:
            why = None
        if why:   # rain just fell or is coming: no need to rush out with the watering can
            soil_words += ", but " + why
    if warm:
        return f"{warm} and {soil_words}."
    return soil_words[:1].upper() + soil_words[1:] + " in the greenhouse."


def _lightning_line(d: dict) -> str:
    if str(d.get("sensor", "ok")).lower() == "missing":
        return "The lightning node is up, but its sensor still isn't answering."
    try:
        n = int(d.get("strikes_today") or 0)
    except (TypeError, ValueError):
        n = 0
    if n > 0:
        return f"The lightning node counted {n} strike{'s' if n != 1 else ''} since midnight."
    return ""


def node_report(mesh, raining: bool = False, now: Optional[float] = None,
                names: Optional[List[str]] = None) -> Tuple[str, str]:
    """(spoken, screen) about the nodes, from the MQTT node network. ('', '') if it's off."""
    names = NODES if names is None else names
    if not names or mesh is None:
        return "", ""
    now = time.time() if now is None else now
    if getattr(mesh, "client", True) is None:
        return "", ""        # the node network isn't running on this Pi
    tracker = getattr(mesh, "tracker", mesh)
    with tracker.lock:
        known = {name: (n.online, n.last_seen) for name, n in tracker.nodes.items()}
    online, lines = [], []
    for name in names:
        if name not in known:
            lines.append(f"I haven't heard from the {_title(name)} yet.")
            continue
        up, seen = known[name]
        if not up:
            lines.append(f"The {_title(name)} has been quiet since {_clock(seen)}." if seen
                         else f"The {_title(name)} is quiet.")
            continue
        online.append(name)
    if not getattr(mesh, "connected", True):
        lead = "I can't reach my message board right now, but last I knew"
        if online:
            lines.insert(0, f"{lead}, the {_join([_title(n) for n in online])} "
                            f"{'was' if len(online) == 1 else 'were'} fine.")
    elif online and len(online) == len(names):
        lines.insert(0, "All {} nodes checked in.".format(NUMBERS.get(len(names), len(names)))
                     if len(names) > 1 else f"The {_title(online[0])} checked in.")
    elif online:
        lines.insert(0, f"The {_join([_title(n) for n in online])} "
                        f"{'is' if len(online) == 1 else 'are'} online.")
    # a little news from the ones that are up
    for name in online:
        d = tracker.latest(name, max_age=3600, now=now) or {}
        if name == "greenhouse" and d:
            line = _greenhouse_line(d)
        elif name == "lightning" and d:
            line = _lightning_line(d)
        elif name == "rain" and raining:
            line = "The rain gauge says it's raining right now."
        else:
            line = ""
        if line:
            lines.append(line)
    screen = f"Nodes {len(online)}/{len(names)} online"
    return " ".join(lines), screen


# ----------------------------
# putting it together
# ----------------------------

def _weather() -> str:
    import local_skills
    return local_skills.weather_report("full")


def _hourly() -> list:
    import weather_lookup
    return weather_lookup.get_hourly()


def _today_short() -> str:
    """'Sunny, 62°' for the face."""
    import weather_lookup
    periods = weather_lookup.get_forecast()["properties"]["periods"]
    p = next((p for p in periods if p.get("isDaytime", True)), periods[0])
    return f"{p.get('shortForecast', '').strip()}, {p.get('temperature')}°".strip(", ")


def _face_notice(text: str) -> None:
    import face_link
    face_link.notice(text)


class Briefing:
    """Builds the briefing in the background each morning. The voice node calls
    due(mode) from its main loop and says what comes back."""

    def __init__(self, mesh=None, raining: Callable[[], bool] = lambda: False,
                 weather: Callable[[], str] = _weather, hourly: Callable[[], list] = _hourly,
                 today_short: Callable[[], str] = _today_short,
                 notice: Callable[[str], None] = _face_notice,
                 clock: Callable[[], float] = time.time,
                 state_file=morning_weather.STATE_FILE):
        self.mesh, self.raining = mesh, raining
        self.weather, self.hourly, self.today_short = weather, hourly, today_short
        self.notice, self.clock = notice, clock
        self.screen = ""
        self._weather_fails = 0
        if ON:
            self.morning = morning_weather.Morning(report=self._scheduled, state_file=state_file,
                                                   start=start_minute, openers=[])
        else:  # the plain morning weather, as before
            self.morning = morning_weather.Morning(state_file=state_file)

    def _raining(self) -> bool:
        try:
            return bool(self.raining())
        except Exception:
            return False

    def build(self, now: Optional[float] = None, on_request: bool = False,
              need_weather: bool = False) -> Tuple[str, str]:
        """(spoken, screen) for right now. Never raises unless need_weather and the
        weather service can't be reached."""
        now = self.clock() if now is None else now
        parts, screen = [greeting(now, on_request)], []
        try:
            parts.append(self.weather())
            try:
                screen.append(self.today_short())
            except Exception:
                pass
        except Exception as e:
            print("Morning briefing: weather lookup failed:", repr(e), flush=True)
            if need_weather:
                raise
            parts.append("I couldn't reach the weather service just now.")
        if self._raining():
            screen.append("Raining now")
        else:
            try:
                said, short = rain_today(self.hourly(), now)
                parts.append(said)
                screen.append(short)
            except Exception as e:
                print("Morning briefing: hourly forecast failed:", repr(e), flush=True)
        try:
            said, short = node_report(self.mesh, raining=self._raining(), now=now)
            if said:
                parts.append(said)
                screen.append(short)
        except Exception as e:
            print("Morning briefing: node report failed:", repr(e), flush=True)
        parts.append(random.choice(CLOSERS))
        text = " ".join(p.strip() for p in parts if p and p.strip())
        if not screen:
            return text, ""
        return text, ("Good morning! " if not on_request else "") + " · ".join(screen)

    def _scheduled(self) -> str:
        # retry a couple of times (5 minutes apart) if the weather service is down,
        # then give the rest of the briefing without it
        try:
            text, self.screen = self.build(need_weather=self._weather_fails < 2)
        except Exception:
            self._weather_fails += 1
            raise
        return text

    def due(self, mode: str, now: Optional[float] = None) -> Optional[str]:
        """The briefing to say now, or None. Leaves the short version on the face."""
        text = self.morning.due(mode, now)
        if text and ON and SCREEN and self.screen:
            try:
                self.notice(self.screen[:300])
            except Exception as e:
                print("Morning briefing: couldn't show the notice:", repr(e), flush=True)
        return text

    def answer(self) -> str:
        """'Hey Chatty, morning briefing.'"""
        return self.build(on_request=True)[0]


ASK = re.compile(r"\b(morning|daily) (briefing|brief|report|rundown|update)\b|\bbrief me\b|"
                 r"\b(my|the|a|your|today'?s) briefing\b")


def asked(prompt: str) -> bool:
    return bool(ASK.search(prompt or ""))


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
    print(f"Briefing time: {m // 60}:{m % 60:02d} (after night mode ends)")
    net = mesh_mod.Mesh(on_events=lambda events: None)
    net.start()
    if net.client is not None:
        print("Listening to the node network for 10 seconds...")
        time.sleep(10)
    b = Briefing(mesh=net)
    spoken, screen = b.build()
    print(" Says:", spoken)
    print(" Face:", screen)
