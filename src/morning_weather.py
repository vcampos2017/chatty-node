"""
Morning weather: once a day, after night mode ends, Chatty says the weather.

She only speaks while she's awake and free (not mid-conversation, not put to
bed), so if she's busy at 7 she says it a little later. It is said at most once
a day, even if she restarts, and not after noon.

Settings (environment or /etc/chatty/secrets.env):

  CHATTY_MORNING_WEATHER   "0" to turn it off (default on)
  CHATTY_MORNING_HOUR      earliest hour to say it, 0-23 (default: when night
                           mode ends, CHATTY_NIGHT_END, which defaults to 7)
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import quiet_hours

ON = os.getenv("CHATTY_MORNING_WEATHER", "1") != "0"
LAST_HOUR = 12  # too late to call it "morning" after this
STATE_FILE = Path(os.getenv("CHATTY_MORNING_STATE",
                            os.path.expanduser("~/.local/share/chatty/morning_weather.json")))

OPENERS = [
    "Good morning! Here's the weather.",
    "Morning! Here's what it's like out there.",
    "Good morning! Your weather for today.",
]


def _start_hour() -> int:
    try:
        h = int(os.getenv("CHATTY_MORNING_HOUR", ""))
        if 0 <= h <= 23:
            return h
    except ValueError:
        pass
    return quiet_hours.night_hours()[1]


def _default_report() -> str:
    import local_skills
    return local_skills.weather_report("full")


class Morning:
    def __init__(self, report: Callable[[], str] = _default_report, state_file: Path = STATE_FILE):
        self.report = report
        self.state_file = state_file
        self._ready: Optional[str] = None
        self._fetching = False
        self._tries = 0
        self._last_try = 0.0
        self._done_day = self._load()

    def _load(self) -> str:
        try:
            return json.loads(self.state_file.read_text()).get("day", "")
        except Exception:
            return ""

    def _save(self, day: str) -> None:
        self._done_day = day
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps({"day": day}))
        except Exception as e:
            print("Morning weather: couldn't save state:", repr(e), flush=True)

    def _fetch(self) -> None:
        try:
            self._ready = random.choice(OPENERS) + " " + self.report()
        except Exception as e:
            print("Morning weather lookup failed:", repr(e), flush=True)
        finally:
            self._fetching = False

    def due(self, mode: str, now: Optional[float] = None) -> Optional[str]:
        """The morning weather to say now, or None. Call from the main loop."""
        if not ON:
            return None
        now = time.time() if now is None else now
        lt = time.localtime(now)
        day = time.strftime("%Y-%m-%d", lt)
        if self._done_day == day:
            return None
        if not (_start_hour() <= lt.tm_hour < LAST_HOUR) or quiet_hours.is_night(now):
            self._ready = None
            self._tries = 0
            return None
        if self._ready is None:
            # look it up in the background so she never freezes waiting on the network;
            # retry every 5 minutes, and give up for the day after 6 tries
            if not self._fetching and self._tries < 6 and now - self._last_try > 300:
                self._fetching = True
                self._tries += 1
                self._last_try = now
                threading.Thread(target=self._fetch, daemon=True).start()
            return None
        if mode != "sleep":  # "sleep" = awake and waiting for her name
            return None
        text, self._ready = self._ready, None
        self._save(day)
        return text
