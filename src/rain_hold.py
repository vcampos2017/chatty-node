"""
Rain hold: no "the plants are thirsty" nag right after rain, or just before it.

If the rain gauge felt rain a few hours ago, the greenhouse soil may still be
soaking it up (the probe is slow to notice). If the forecast says rain is about to
come, the sky is about to do the watering. Either way, asking Vincent to water is
a nag, so she holds it back. The reading itself is never hidden: the face card and
"is the greenhouse thirsty?" still say the soil is dry, and add why she isn't worried
("but it rained about 2 hours ago").

Who writes, who reads (one small file, so every process on the Pi shares it, and it
survives restarts):
    sky.py        note_wet()       the rain gauge says it's raining (about once a minute)
    rain_watch.py note_forecast()  each forecast check (every 15 min): rain due or not
    nodes.py / local_skills.py / morning_briefing.py / chatty_core.py   reason()

Free and local: only the rain node's readings and the NWS forecast Chatty already
fetches. Nothing is sent anywhere.

OFF by default: Vincent's greenhouse soil is under cover, so rain doesn't water it
(decided 2026-11-12). Turn it on for a bed that the rain does reach.

Settings (in /etc/chatty/secrets.env):
    CHATTY_RAIN_HOLD=1               turn this on (default 0: the soil is under a roof)
    CHATTY_RAIN_HOLD_HOURS           hold the nag this long after the last rain (default 6)
    CHATTY_RAIN_HOLD_FORECAST=0      don't hold it for forecast rain, only for real rain
    CHATTY_RAIN_HOLD_FORECAST_MAX    stop trusting a forecast that keeps promising rain
                                     that doesn't come after this many hours (default 6)
"""
from __future__ import annotations

import json
import storage  # safe JSON saves (atomic, owner-only)
import os
import threading
import time
from pathlib import Path
from typing import Optional

ENABLED = os.getenv("CHATTY_RAIN_HOLD", "0") == "1"
FORECAST = os.getenv("CHATTY_RAIN_HOLD_FORECAST", "1") != "0"


def _hours(name: str, default: float) -> float:
    try:
        return min(48.0, max(0.0, float(os.getenv(name, str(default)))))
    except ValueError:
        return default


HOLD_HOURS = _hours("CHATTY_RAIN_HOLD_HOURS", 6)
FORECAST_MAX_HOURS = _hours("CHATTY_RAIN_HOLD_FORECAST_MAX", 6)
FORECAST_FRESH = 60 * 60       # a forecast note older than this is ignored (checks are every 15 min)
WRITE_EVERY = 5 * 60           # while it rains, save the time at most this often

STATE_FILE = Path(os.getenv("CHATTY_RAIN_HOLD_STATE",
                            os.path.expanduser("~/.local/share/chatty/rain_hold.json")))

_lock = threading.Lock()


def _read(path: Optional[Path] = None) -> dict:
    try:
        d = json.loads((path or STATE_FILE).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d: dict, path: Optional[Path] = None) -> None:
    path = path or STATE_FILE
    try:
        storage.save_json(path, d)
    except OSError as e:
        print("Rain hold: couldn't save:", repr(e), flush=True)


def _num(d: dict, key: str) -> Optional[float]:
    try:
        v = d.get(key)
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


# ----- writers -----
def note_wet(now: Optional[float] = None, path: Optional[Path] = None) -> None:
    """The rain gauge feels rain right now."""
    now = time.time() if now is None else now
    with _lock:
        d = _read(path)
        last = _num(d, "last_wet") or 0.0
        if now - last < WRITE_EVERY:
            return
        d["last_wet"] = now
        _write(d, path)


def note_forecast(starts: Optional[float], now: Optional[float] = None,
                  path: Optional[Path] = None) -> None:
    """One forecast check: `starts` is when rain is due (None: no rain in the window)."""
    now = time.time() if now is None else now
    with _lock:
        d = _read(path)
        if starts is None:
            d["rain_due"] = None
            d["due_since"] = None
        else:
            d["rain_due"] = float(starts)
            if _num(d, "due_since") is None:
                d["due_since"] = now
        d["forecast_ts"] = now
        _write(d, path)


# ----- readers -----
def _ago_words(seconds: float) -> str:
    minutes = max(0, round(seconds / 60))
    if minutes < 50:
        return "less than an hour ago" if minutes > 5 else "just now"
    hours = round(minutes / 60)
    return "about an hour ago" if hours <= 1 else f"about {hours} hours ago"


def _until_words(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes <= 15:
        return "any minute now"
    if minutes < 50:
        return "within the hour"
    hours = round(minutes / 60)
    return "in about an hour" if hours <= 1 else f"in about {hours} hours"


def reason(now: Optional[float] = None, path: Optional[Path] = None) -> Optional[str]:
    """Why a "please water" nag should wait, as words that follow "but",
    e.g. "it rained about 2 hours ago". None: no reason, nag as usual."""
    if not ENABLED:
        return None
    now = time.time() if now is None else now
    d = _read(path)
    last = _num(d, "last_wet")
    if last is not None and 0 <= now - last < HOLD_HOURS * 3600:
        if now - last < 10 * 60:
            return "it's raining right now"
        return "it rained " + _ago_words(now - last)
    if not FORECAST:
        return None
    due, since, ts = _num(d, "rain_due"), _num(d, "due_since"), _num(d, "forecast_ts")
    if due is None or ts is None or now - ts > FORECAST_FRESH:
        return None
    if since is not None and now - since > FORECAST_MAX_HOURS * 3600:
        return None       # it's been "coming" for hours and never came: back to normal
    return "rain is on the way " + _until_words(max(0.0, due - now))


def soaking_words(why: str) -> str:
    """The rest of the sentence after "the plants are thirsty, but ...". """
    if why.startswith("rain is on the way"):
        return f"{why}, so the sky may do the watering."
    if why.startswith("it's raining"):
        return f"{why}, so they're getting a drink."
    return f"{why}, so it may still be soaking in."


if __name__ == "__main__":
    print("Rain hold is", "on" if ENABLED else "off (CHATTY_RAIN_HOLD=1 turns it on)")
    print("Saved:", _read())
    why = reason()
    print("Holding the thirsty nag:", ("yes, " + why) if why else "no")
