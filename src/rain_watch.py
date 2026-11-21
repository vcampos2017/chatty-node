"""
Rain watch: "Hey, hey! Rain in about an hour. Close the windows!"

Every 15 minutes (in the background) Chatty reads the National Weather Service's
hour-by-hour forecast for her location (CHATTY_LAT / CHATTY_LON, the same as the
weather answers and alerts). When an hour in the next few hours has a good chance
of rain, she gives one heads-up before it arrives:

  - Daytime, while she's free: she says it ("Hey, hey! Rain is coming in about an
    hour. Close the windows!") and leaves a notice on her face, in case nobody
    was in the room.
  - At night (night mode, quiet_hours.py): only the notice on her face.

No nagging: after a heads-up she stays quiet until the forecast has been dry for
a couple of hours AND at least CHATTY_RAIN_WARN_GAP hours have passed, so one rainy
afternoon gets one heads-up, not one every 15 minutes. If the rain gauge already
feels rain (sky.py), there's nothing to warn about. What she last warned about is
remembered across restarts (~/.local/share/chatty/rain_watch.json).

The node network gets the news too. Each check is posted (retained) on MQTT:

    chatty/forecast/rain   {"rain_expected": true, "starts_ts": 1730900000,
                            "minutes": 55, "chance": 70, "kind": "rain",
                            "summary": "Chance Showers And Thunderstorms",
                            "hours_ahead": 3, "raining_now": false,
                            "ts": 1730896700, "source": "NWS hourly forecast"}

so the greenhouse node (or the word clock) can use it, e.g. skip a "thirsty"
alert when rain is on the way. It's news, never a command: Chatty doesn't open or
close anything. Treat a reading older than about an hour as stale ("ts").
kind is "rain", "storms" or "snow". When no rain is expected, rain_expected is
false and starts_ts is null.

Settings (in /etc/chatty/secrets.env):
    CHATTY_RAIN_WARN=0          turn this off (default on)
    CHATTY_RAIN_WARN_HOURS=3    how far ahead to look, in hours (1-12)
    CHATTY_RAIN_WARN_CHANCE=50  chance of rain (percent) that counts as "rain coming"
    CHATTY_RAIN_WARN_GAP=4      at least this many hours between heads-ups
    CHATTY_RAIN_WARN_SPEAK=0    show it on the face only, never say it
    CHATTY_RAIN_WARN_PHONE=1    also send it to the phone through IFTTT (default off)
    CHATTY_RAIN_WARN_EVERY=900  seconds between forecast checks

Try it on the Pi:  python3 src/rain_watch.py   (prints what she sees right now)
"""
from __future__ import annotations

import json
import storage  # safe JSON saves (atomic, owner-only)
import os
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

try:
    import quiet_hours
except ImportError:  # running from another folder
    from . import quiet_hours  # type: ignore


def _num(name: str, default: float, low: float, high: float) -> float:
    try:
        return min(high, max(low, float(os.getenv(name, str(default)))))
    except ValueError:
        return default


ENABLED = os.getenv("CHATTY_RAIN_WARN", "1") != "0"
HOURS = _num("CHATTY_RAIN_WARN_HOURS", 3, 1, 12)
CHANCE = _num("CHATTY_RAIN_WARN_CHANCE", 50, 10, 100)
GAP = _num("CHATTY_RAIN_WARN_GAP", 4, 1, 48) * 3600
SPEAK = os.getenv("CHATTY_RAIN_WARN_SPEAK", "1") != "0"
PHONE = os.getenv("CHATTY_RAIN_WARN_PHONE", "0") == "1"
EVERY = _num("CHATTY_RAIN_WARN_EVERY", 900, 300, 3600)
REARM_DRY = 2 * 3600       # forecast dry this long before a new heads-up is allowed
TOPIC = "chatty/forecast/rain"
STATE_FILE = Path(os.getenv("CHATTY_RAIN_WARN_STATE",
                            os.path.expanduser("~/.local/share/chatty/rain_watch.json")))


@dataclass
class Outlook:
    starts: float         # unix time the first rainy hour begins (may be now)
    chance: int           # percent
    kind: str             # "rain" | "storms" | "snow"
    summary: str          # NWS words, e.g. "Chance Showers And Thunderstorms"


def _ts(iso: Optional[str]) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _kind(summary: str) -> str:
    s = summary.lower()
    if "thunder" in s or "storm" in s:
        return "storms"
    if ("snow" in s or "flurr" in s or "sleet" in s) and "rain" not in s:
        return "snow"
    return "rain"


def assess(periods: list, now: float, hours: float = HOURS, chance: float = CHANCE) -> Optional[Outlook]:
    """The first hour in the next `hours` with at least `chance` percent of rain, or None."""
    horizon = now + hours * 3600
    for p in periods or []:
        if not isinstance(p, dict):
            continue
        start, end = _ts(p.get("startTime")), _ts(p.get("endTime"))
        if not start:
            continue
        end = end or start + 3600
        if end <= now:
            continue            # already over
        if start >= horizon:
            break               # periods are in time order
        pop = (p.get("probabilityOfPrecipitation") or {}).get("value")
        try:
            pop = int(pop or 0)
        except (TypeError, ValueError):
            pop = 0
        if pop >= chance:
            summary = (p.get("shortForecast") or "").strip()
            return Outlook(starts=max(start, now), chance=pop, kind=_kind(summary), summary=summary)
    return None


def when_words(minutes: float) -> str:
    if minutes <= 15:
        return "any minute now"
    if minutes < 45:
        return "in less than an hour"
    if minutes < 90:
        return "in about an hour"
    return f"in about {round(minutes / 60)} hours"


_LINES = {
    "rain": ["Hey, hey! Rain is coming {when}. Close the windows!",
             "Hey, hey! Looks like rain {when}. Time to close the windows.",
             "Heads up! Rain {when}, so close the windows and bring in anything that shouldn't get wet."],
    "storms": ["Hey, hey! Thunderstorms are on the way, {when}. Close the windows, and bring in anything that shouldn't get wet.",
               "Heads up! Storms {when}. Close the windows!"],
    "snow": ["Hey, hey! Snow is coming {when}. Close the windows and bundle up!"],
}


def spoken(o: Outlook, now: float) -> str:
    when = when_words((o.starts - now) / 60)
    text = random.choice(_LINES.get(o.kind, _LINES["rain"])).format(when=when)
    if o.chance < 70:
        text += f" The chance is about {o.chance} percent."
    return text


def _clock(ts: float) -> str:
    d = time.localtime(ts)
    return f"{d.tm_hour % 12 or 12}:{d.tm_min:02d} {'AM' if d.tm_hour < 12 else 'PM'}"


def screen_text(o: Outlook, now: float) -> str:
    """Short line for the face, e.g. 'Rain likely around 3:00 PM (70%). Close the windows!'"""
    word = {"storms": "Storms", "snow": "Snow"}.get(o.kind, "Rain")
    when = "soon" if o.starts - now <= 15 * 60 else f"around {_clock(o.starts)}"
    return f"{word} likely {when} ({o.chance}%). Close the windows!"


def news(o: Optional[Outlook], now: float, raining_now: bool = False) -> dict:
    """What goes on the node network (chatty/forecast/rain)."""
    body = {"rain_expected": o is not None, "starts_ts": None, "minutes": None,
            "chance": 0, "kind": None, "summary": "", "hours_ahead": HOURS,
            "raining_now": bool(raining_now), "ts": int(now), "source": "NWS hourly forecast"}
    if o is not None:
        body.update(starts_ts=int(o.starts), minutes=max(0, round((o.starts - now) / 60)),
                    chance=o.chance, kind=o.kind, summary=o.summary)
    return body


def _default_fetch() -> list:
    import weather_lookup
    return weather_lookup.get_hourly()


def _face_notice(text: str) -> None:
    import face_link
    face_link.notice(text)


def _phone(text: str) -> None:
    import alerts
    alerts.send_phone_alert(text)


class RainWatch:
    """Checks the hourly forecast in a background thread. The voice node calls
    due(mode) from its main loop to get a heads-up to say now (or None)."""

    def __init__(self, fetch: Callable[[], list] = _default_fetch,
                 publish: Optional[Callable[[str, dict], object]] = None,
                 raining: Callable[[], bool] = lambda: False,
                 notice: Callable[[str], None] = _face_notice,
                 phone: Callable[[str], None] = _phone,
                 is_night: Callable[[float], bool] = quiet_hours.is_night,
                 clock: Callable[[], float] = time.time,
                 state_file: Optional[Path] = STATE_FILE,
                 on_outlook: Optional[Callable[[Optional[float], float], None]] = None):
        self.fetch, self.publish, self.raining = fetch, publish, raining
        self.on_outlook = on_outlook   # e.g. rain_hold.note_forecast(starts or None, now)
        self.notice, self.phone, self.is_night, self.clock = notice, phone, is_night, clock
        self.state_file = state_file
        self.lock = threading.Lock()
        self.armed = True
        self.warned_at = -1e12
        self.dry_since: Optional[float] = None
        self.pending: Optional[Outlook] = None
        self.latest: Optional[Outlook] = None
        self.ok = False
        self._load()

    # ----- remembering across restarts -----
    def _load(self) -> None:
        if not self.state_file:
            return
        try:
            d = json.loads(self.state_file.read_text())
            self.armed = bool(d.get("armed", True))
            self.warned_at = float(d.get("warned_at", -1e12))
            self.dry_since = d.get("dry_since")
        except (OSError, ValueError, TypeError):
            pass

    def _save(self) -> None:
        if not self.state_file:
            return
        try:
            storage.save_json(self.state_file, {"armed": self.armed, "warned_at": self.warned_at,
                                                "dry_since": self.dry_since})
        except OSError as e:
            print("Rain watch: couldn't save state:", repr(e), flush=True)

    # ----- one look at the forecast -----
    def check_once(self, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        try:
            periods = self.fetch()
            self.ok = True
        except Exception as e:
            self.ok = False
            print("Rain watch: forecast check failed:", repr(e), flush=True)
            return
        try:
            wet_now = bool(self.raining())
        except Exception:
            wet_now = False
        o = assess(periods, now)
        warn = None
        with self.lock:
            before = (self.armed, self.warned_at, self.dry_since)
            self.latest = o
            if o is None and not wet_now:
                if self.dry_since is None:
                    self.dry_since = now
                if not self.armed and now - self.dry_since >= REARM_DRY:
                    self.armed = True          # the last rain is well past: ready for the next
            else:
                self.dry_since = None
                if wet_now:
                    self.armed = False         # the gauge already feels it: nothing to warn about
                    self.pending = None
                elif self.armed and now - self.warned_at >= GAP:
                    self.armed = False
                    self.warned_at = now
                    warn = o
            if (self.armed, self.warned_at, self.dry_since) != before:
                self._save()
        if self.on_outlook:
            try:
                self.on_outlook(o.starts if o else None, now)
            except Exception as e:
                print("Rain watch: couldn't note the outlook:", repr(e), flush=True)
        if self.publish:
            try:
                self.publish(TOPIC, news(o, now, wet_now))
            except Exception as e:
                print("Rain watch: couldn't post the forecast:", repr(e), flush=True)
        if warn:
            self._warn(warn, now)

    def _warn(self, o: Outlook, now: float) -> None:
        print(f"Rain watch: {o.kind} likely in {round((o.starts - now) / 60)} min "
              f"({o.chance}%, {o.summary})", flush=True)
        try:
            self.notice(screen_text(o, now))
        except Exception as e:
            print("Rain watch: couldn't show the notice:", repr(e), flush=True)
        if PHONE:
            try:
                self.phone(f"Chatty: {screen_text(o, now)}")
            except Exception as e:
                print("Rain watch: phone alert failed:", repr(e), flush=True)
        if SPEAK and not self.is_night(now):
            with self.lock:
                self.pending = o

    def run_forever(self) -> None:
        time.sleep(30)     # give the node network a moment to connect first
        while True:
            self.check_once()
            time.sleep(EVERY)

    def start(self) -> None:
        if ENABLED:
            threading.Thread(target=self.run_forever, daemon=True, name="rain-watch").start()

    # ----- for the voice node's main loop -----
    def due(self, mode: str, now: Optional[float] = None) -> Optional[str]:
        """The heads-up to say now, only while she's free ('sleep' = waiting for her name)."""
        if mode != "sleep":
            return None
        now = self.clock() if now is None else now
        with self.lock:
            o = self.pending
            if o is None:
                return None
            self.pending = None
        if self.is_night(now) or now > o.starts + 30 * 60:
            return None        # it got late, or the rain is long here: the notice says it
        try:
            if self.raining():
                return None    # already raining: "close the windows" is old news
        except Exception:
            pass
        return spoken(o, now)

    # ----- "Hey Chatty, is rain coming?" -----
    def answer(self, now: Optional[float] = None) -> str:
        now = self.clock() if now is None else now
        if not self.ok and self.latest is None:
            return "I can't reach the weather service right now, so I'm not sure."
        o = self.latest
        if o is None:
            return f"No rain in the forecast for the next {int(HOURS)} hours."
        word = {"storms": "Thunderstorms", "snow": "Snow"}.get(o.kind, "Rain")
        return f"{word} {when_words((o.starts - now) / 60)}, about a {o.chance} percent chance."


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from dotenv import load_dotenv
        load_dotenv("/etc/chatty/secrets.env")
    except ImportError:
        pass
    import weather_lookup
    now = time.time()
    found = assess(weather_lookup.get_hourly(), now)
    print(f"Looking {HOURS:g} hours ahead for a {CHANCE:g}%+ chance of rain:")
    if found:
        print(" Face:", screen_text(found, now))
        print(" Says:", spoken(found, now))
    else:
        print(" No rain expected.")
    print(" Node network:", json.dumps(news(found, now)))
