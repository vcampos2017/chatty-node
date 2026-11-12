"""
"It rained, you can skip watering": a gentle tip for the outdoor hoses.

Vincent's garden hoses run on Diivoo smart water timers (Smart Life app). Chatty
NEVER touches them (nodes and gadgets stay read-only, see CLAUDE.md "Decisions"):
she only tells him when the rain already did the job, so he can skip a watering
himself.

How she knows: the rain gauge (chatty/nodes/rain/data on the node network) sends its
running total (rain_mm, or rain_in) about once a minute. Each rise is added to a
small rain log (last 48 h, ~/.local/share/chatty/watering_tip.json, survives
restarts). A reset of the gauge's total (new day, reboot) is just a new starting point.

When she says it:
  - Once a day at most, in the daytime (CHATTY_WATER_TIP_FROM..._UNTIL, 8-20), while
    she's free, after at least CHATTY_SKIP_WATER_IN (0.25 in) fell in the last 24 h
    and the rain has stopped for 30 min: "Good news for the garden: we got about half
    an inch of rain since yesterday. You can skip watering the outdoor plants today."
    The same words stay on her face as a notice.
  - Overnight rain is told in the morning briefing instead (and counts as today's tip).
  - "Should I water the garden?" / "do I need to water today?" answers any time, also
    with forecast rain ("rain is likely around 3 PM, so you could wait").

Free and local: only the rain gauge and the NWS forecast she already reads.

Settings (in /etc/chatty/secrets.env):
    CHATTY_WATER_TIP=0          turn this off
    CHATTY_WATER_TIP_SPEAK=0    face notice only, never say it on her own
    CHATTY_SKIP_WATER_IN        rain (inches, last 24 h) that means "skip it" (0.25)
    CHATTY_WATER_TIP_FROM / _UNTIL   hours she may bring it up on her own (8, 20)
Test on the Pi: python3 src/watering_tip.py
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

try:
    import quiet_hours
except ImportError:  # running from another folder
    from . import quiet_hours  # type: ignore

ENABLED = os.getenv("CHATTY_WATER_TIP", "1") != "0"
SPEAK = os.getenv("CHATTY_WATER_TIP_SPEAK", "1") != "0"
RAIN_NODE = os.getenv("CHATTY_SKY_RAIN_NODE", "rain").strip() or "rain"
MM_PER_IN = 25.4


def _num(name: str, default: float, low: float, high: float) -> float:
    try:
        return min(high, max(low, float(os.getenv(name, str(default)))))
    except ValueError:
        return default


SKIP_IN = _num("CHATTY_SKIP_WATER_IN", 0.25, 0.01, 5)
FROM_HOUR = int(_num("CHATTY_WATER_TIP_FROM", 8, 0, 23))
UNTIL_HOUR = int(_num("CHATTY_WATER_TIP_UNTIL", 20, 1, 24))
STOPPED = 30 * 60          # no rise for this long: the rain has stopped
KEEP = 48 * 3600           # how much of the rain log to keep
WINDOW = 24 * 3600         # "since yesterday"

STATE_FILE = Path(os.getenv("CHATTY_WATER_TIP_STATE",
                            os.path.expanduser("~/.local/share/chatty/watering_tip.json")))


def amount_words(inches: float) -> str:
    """0.27 -> 'about a quarter of an inch', 0.5 -> 'about half an inch', 1.3 -> 'about 1.3 inches'."""
    if inches < 0.05:
        return "just a sprinkle"
    if inches < 0.15:
        return "about a tenth of an inch"
    if inches < 0.35:
        return "about a quarter of an inch"
    if inches < 0.65:
        return "about half an inch"
    if inches < 0.9:
        return "about three quarters of an inch"
    if inches < 1.15:
        return "about an inch"
    return f"about {inches:.1f} inches"


def _total_mm(d: dict) -> Optional[float]:
    for key, scale in (("rain_mm", 1.0), ("rain_in", MM_PER_IN)):
        if d.get(key) is not None:
            try:
                return float(d[key]) * scale
            except (TypeError, ValueError):
                return None
    return None


def asked(prompt: str) -> bool:
    """'Should I water the garden?', 'do I need to water today?', 'can I skip watering?'"""
    p = (prompt or "").lower()
    if "greenhouse" in p:
        return False       # the greenhouse is under cover: rain doesn't count there (nodes.py answers)
    return bool(re.search(r"\b(should|do|must|can) i (still )?(need to )?(water|skip (the )?watering)\b|"
                          r"\bneed (to )?(water|watering)\b|\bwater the (garden|yard|lawn|hoses?)\b|"
                          r"\bskip (the )?watering\b|\b(is|are) the (garden|yard|lawn) (thirsty|dry)\b", p))


class WaterTip:
    """Feed it rain gauge readings with on_data(); the voice node asks due(mode)."""

    def __init__(self, notice: Optional[Callable[[str], None]] = None,
                 raining: Callable[[], bool] = lambda: False,
                 outlook: Callable[[], object] = lambda: None,
                 is_night: Callable[[float], bool] = quiet_hours.is_night,
                 clock: Callable[[], float] = time.time,
                 state_file: Optional[Path] = STATE_FILE):
        self.notice = notice or _face_notice
        self.raining, self.outlook, self.is_night, self.clock = raining, outlook, is_night, clock
        self.state_file = state_file
        self.lock = threading.Lock()
        self.log: List[Tuple[float, float]] = []    # (when, mm that fell)
        self.last_total: Optional[float] = None
        self.tipped_day = ""                         # "2026-11-12": already told today
        self._load()

    # ----- remembering -----
    def _load(self) -> None:
        if not self.state_file:
            return
        try:
            d = json.loads(self.state_file.read_text())
            self.log = [(float(t), float(mm)) for t, mm in d.get("log", [])]
            self.last_total = d.get("last_total")
            self.tipped_day = str(d.get("tipped_day") or "")
        except (OSError, ValueError, TypeError):
            pass

    def _save(self) -> None:
        if not self.state_file:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"log": self.log, "last_total": self.last_total,
                                       "tipped_day": self.tipped_day}))
            tmp.replace(self.state_file)
        except OSError as e:
            print("Watering tip: couldn't save:", repr(e), flush=True)

    # ----- input from the node network -----
    def on_data(self, name: str, body: dict, now: Optional[float] = None) -> None:
        if not ENABLED or name != RAIN_NODE or not isinstance(body, dict):
            return
        now = self.clock() if now is None else now
        total = _total_mm(body)
        if total is None:
            return
        with self.lock:
            last, self.last_total = self.last_total, total
            changed = last != total
            if last is not None and 0 < total - last < 200:   # a jump of 200 mm is a glitch
                self.log.append((now, round(total - last, 2)))
            self.log = [(t, mm) for t, mm in self.log if now - t < KEEP]
            if changed:
                self._save()

    # ----- what she knows -----
    def inches(self, now: Optional[float] = None, window: float = WINDOW) -> float:
        now = self.clock() if now is None else now
        with self.lock:
            return sum(mm for t, mm in self.log if 0 <= now - t < window) / MM_PER_IN

    def last_rain(self) -> Optional[float]:
        with self.lock:
            return self.log[-1][0] if self.log else None

    def _soaked(self, now: float) -> bool:
        return self.inches(now) >= SKIP_IN

    def _day(self, now: float) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(now))

    def tip_text(self, now: float) -> str:
        return (f"Good news for the garden: we got {amount_words(self.inches(now))} of rain since "
                "yesterday. You can skip watering the outdoor plants today.")

    # ----- for the voice node's main loop -----
    def due(self, mode: str, now: Optional[float] = None) -> Optional[str]:
        """The tip to say now (once a day, daytime, while she's free, after the rain stopped)."""
        if not ENABLED or mode != "sleep":
            return None
        now = self.clock() if now is None else now
        hour = time.localtime(now).tm_hour
        if not (FROM_HOUR <= hour < UNTIL_HOUR) or self.is_night(now):
            return None
        if self.tipped_day == self._day(now) or not self._soaked(now):
            return None
        last = self.last_rain()
        if last is None or now - last < STOPPED:
            return None            # still raining: wait until it's done
        try:
            if self.raining():
                return None
        except Exception:
            pass
        text = self.tip_text(now)
        with self.lock:
            self.tipped_day = self._day(now)
            self._save()
        print("Watering tip:", text, flush=True)
        try:
            self.notice(f"Rained {self.inches(now):.2f} in since yesterday: skip watering today")
        except Exception as e:
            print("Watering tip: couldn't show the notice:", repr(e), flush=True)
        return text if SPEAK else None

    # ----- the morning briefing -----
    def briefing_line(self, now: Optional[float] = None) -> str:
        """One sentence for the morning briefing (counts as today's tip), or ''."""
        if not ENABLED:
            return ""
        now = self.clock() if now is None else now
        if not self._soaked(now):
            return ""
        with self.lock:
            self.tipped_day = self._day(now)
            self._save()
        return (f"We got {amount_words(self.inches(now))} of rain since yesterday, "
                "so you can skip watering the outdoor plants today.")

    # ----- "Hey Chatty, should I water the garden?" -----
    def answer(self, now: Optional[float] = None) -> str:
        now = self.clock() if now is None else now
        got = self.inches(now)
        try:
            raining = bool(self.raining())
        except Exception:
            raining = False
        if got >= SKIP_IN:
            return (f"No need, I think. We got {amount_words(got)} of rain since yesterday, "
                    "so the outdoor plants should be fine today.")
        if raining:
            return "It's raining right now, so I'd wait and see how much we get before watering."
        o = None
        try:
            o = self.outlook()
        except Exception:
            pass
        if o is not None and getattr(o, "starts", None):
            mins = max(0, round((o.starts - now) / 60))
            when = "soon" if mins < 60 else f"in about {round(mins / 60)} hour{'s' if mins >= 90 else ''}"
            return (f"Maybe wait: rain is likely {when}, about a {o.chance} percent chance. "
                    "If it doesn't come, water later.")
        if got >= 0.05:
            return (f"We only got {amount_words(got)} of rain since yesterday, and none is expected "
                    "soon, so the outdoor plants could use their watering.")
        return ("No rain since yesterday and none expected soon, so yes, "
                "the outdoor plants could use their watering.")


def _face_notice(text: str) -> None:
    import face_link
    face_link.notice(text)


if __name__ == "__main__":
    w = WaterTip(notice=print, state_file=STATE_FILE)
    print("Watering tip is", "on" if ENABLED else "off (CHATTY_WATER_TIP=0)")
    print(f"Rain in the last 24 h: {w.inches():.2f} in (skip watering at {SKIP_IN:.2f} in)")
    print("Told today already:", w.tipped_day == w._day(time.time()))
    print("Answer:", w.answer())
