"""
Timers and alarms, all on the Pi.

    "Hey Chatty, set a timer for ten minutes"      "start a 90 second timer"
    "timer for an hour and a half"                  "remind me in 5 minutes"
    "set an alarm for 7 am"   "wake me up at six thirty"   "alarm for 7:45 pm"
    "how much time is left?"  "what timers do I have?"
    "cancel the timer"        "cancel my alarm"     "cancel all timers"

When one is done she chimes and says so ("Your 10 minute timer is done!"),
even at night or while resting, since you asked for it. An alarm rings again
a minute later (three times at most) until you tap her or say "Hey Chatty".
The face shows the next one counting down in the top-right corner, and a
missed one stays on the face as a notice.

Timers survive a restart: they're kept in ~/.local/share/chatty/timers.json.

Settings (in /etc/chatty/secrets.env):
    CHATTY_TIMERS=0         turn timers and alarms off
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

ENABLED = os.getenv("CHATTY_TIMERS", "1") != "0"
FILE = Path(os.path.expanduser("~/.local/share/chatty/timers.json"))
MAX_ITEMS = 5
MAX_SECONDS = 24 * 3600
ALARM_RINGS = 3            # an alarm rings this many times, a minute apart
RING_GAP = 60

_ONES = {"zero": 0, "oh": 0, "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
         "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
         "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
         "seventeen": 17, "eighteen": 18, "nineteen": 19, "couple": 2, "few": 3}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_UNITS = {"second": 1, "seconds": 1, "sec": 1, "secs": 1,
          "minute": 60, "minutes": 60, "min": 60, "mins": 60,
          "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600}


def _words(text: str) -> List[str]:
    t = text.lower().replace("-", " ")
    t = re.sub(r"(\d)([a-z])", r"\1 \2", t)          # "10min" -> "10 min"
    return re.findall(r"\d+(?:\.\d+)?|[a-z]+|:", t)


def _number_at(words: List[str], i: int):
    """(value, next index) for a number starting at words[i], or (None, i)."""
    if i >= len(words):
        return None, i
    w = words[i]
    if re.fullmatch(r"\d+(?:\.\d+)?", w):
        return float(w), i + 1
    if w in _TENS:
        v, j = _TENS[w], i + 1
        if j < len(words) and words[j] in _ONES and 0 < _ONES[words[j]] < 10 and words[j] not in ("a", "an"):
            v, j = v + _ONES[words[j]], j + 1
        return float(v), j
    if w in _ONES:
        j = i + 1
        if w == "couple" and j < len(words) and words[j] == "of":
            j += 1
        return float(_ONES[w]), j
    return None, i


def parse_duration(text: str) -> Optional[int]:
    """Seconds in 'ten minutes', '1 hour 30 minutes', 'an hour and a half',
    'half an hour', '90 seconds', 'two and a half minutes'. None if there's none."""
    words = _words(text)
    total, found, i = 0.0, False, 0
    while i < len(words):
        if words[i] == "half" and i + 2 < len(words) and words[i + 1] in ("an", "a") and words[i + 2] in _UNITS:
            total += 0.5 * _UNITS[words[i + 2]]
            found, i = True, i + 3
            continue
        value, j = _number_at(words, i)
        if value is None:
            i += 1
            continue
        if j + 2 < len(words) and words[j] == "and" and words[j + 1] in ("a", "an") and words[j + 2] == "half":
            value, j = value + 0.5, j + 3
        if j < len(words) and words[j] in _UNITS:
            unit = _UNITS[words[j]]
            j += 1
            if j + 2 < len(words) and words[j] == "and" and words[j + 1] in ("a", "an") and words[j + 2] == "half":
                value, j = value + 0.5, j + 3
            total += value * unit
            found = True
        i = j
    return int(round(total)) if found and total > 0 else None


def parse_clock(text: str, now: float) -> Optional[float]:
    """When the next 'seven am', '6:30', 'six thirty pm', 'half past seven', 'noon' is."""
    t = text.lower()
    hour = minute = None
    ampm = None
    if re.search(r"\bnoon\b", t):
        hour, minute, ampm = 12, 0, "pm"
    elif re.search(r"\bmidnight\b", t):
        hour, minute, ampm = 0, 0, "am"
    m = re.search(r"\b(a\s?m|p\s?m|in the morning|in the evening|tonight|at night|in the afternoon)\b", t)
    if m:
        ampm = "am" if m.group(1).replace(" ", "") in ("am", "inthemorning") else "pm"
    if hour is None:
        tail = re.split(r"\b(?:alarm|at|for|wake me up|wake me)\b", t)[-1]
        words = _words(tail)
        m2 = re.search(r"\b(\d{1,2}):(\d{2})\b", tail)
        if m2:
            hour, minute = int(m2.group(1)), int(m2.group(2))
        elif "past" in words or "to" in words and "quarter" in words:
            k = words.index("past") if "past" in words else words.index("to")
            mins = 30 if "half" in words[:k] else 15 if "quarter" in words[:k] else None
            if mins is None:
                mins_v, _ = _number_at(words, 0)
                mins = int(mins_v) if mins_v is not None else None
            hv, _ = _number_at(words, k + 1)
            if mins is not None and hv is not None:
                hour, minute = int(hv), mins
                if words[k] == "to":
                    hour, minute = (hour - 1) % 24, 60 - mins
        else:
            for i in range(len(words)):
                hv, j = _number_at(words, i)
                if hv is None or words[i] in ("a", "an") or not 0 <= hv <= 23:
                    continue
                hour, minute = int(hv), 0
                if j < len(words) and words[j] == "oh":
                    mv, j2 = _number_at(words, j + 1)
                    minute = int(mv) if mv is not None and mv < 10 else 0
                else:
                    mv, j2 = _number_at(words, j)
                    if mv is not None and 0 <= mv < 60 and words[j] not in ("a", "an"):
                        minute = int(mv)
                break
    if hour is None or minute is None or not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    base = datetime.fromtimestamp(now)
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    candidates = [hour] if ampm or hour > 12 or hour == 0 else [hour, (hour + 12) % 24]
    best = None
    for h in candidates:
        when = base.replace(hour=h, minute=minute, second=0, microsecond=0)
        if when.timestamp() <= now + 5:
            when += timedelta(days=1)
        if best is None or when < best:
            best = when
    return best.timestamp()


def spoken_duration(seconds: int) -> str:
    """600 -> '10 minute', 90 -> '90 second', 5400 -> '1 hour 30 minute' (for 'a ... timer')."""
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    if h == 0 and m == 0:
        return f"{s} second"
    if h == 0 and s == 0:
        return f"{m} minute"
    if h == 0 and m < 2:
        return f"{m * 60 + s} second"
    parts = []
    if h:
        parts.append(f"{h} hour")
    if m:
        parts.append(f"{m} minute")
    if s and not h:
        parts.append(f"{s} second")
    return " ".join(parts)


def spoken_left(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if s and not h and m < 5:
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " and ".join(parts) or "a moment"


def clock_text(ts: float) -> str:
    d = time.localtime(ts)
    return f"{d.tm_hour % 12 or 12}:{d.tm_min:02d} {'AM' if d.tm_hour < 12 else 'PM'}"


# ----------------------------
# understanding what was asked
# ----------------------------

CANCEL = re.compile(r"\b(cancel|stop|delete|clear|remove|turn off|never mind)\b.*\b(timers?|alarms?)\b")
LEFT = re.compile(r"\b(how (much|long)\b.*\b(left|remaining|to go)|time left|time remaining|"
                  r"what timers|which timers|any timers|my timers|what alarms|any alarms|my alarms|"
                  r"when is my alarm|whats my alarm|is my alarm set)\b")
ALARM = re.compile(r"\b(alarm|wake me( up)?)\b")
TIMER = re.compile(r"\b(timer|remind me in|count down|countdown)\b")


def understand(prompt: str, now: float) -> Optional[dict]:
    """What a timer/alarm request means, or None if it isn't one."""
    if not ENABLED:
        return None
    p = prompt.lower()
    if CANCEL.search(p):
        what = "alarm" if re.search(r"\balarms?\b", p) else "timer"
        return {"do": "cancel", "kind": what, "all": bool(re.search(r"\b(all|every)\b", p))}
    if LEFT.search(p):
        return {"do": "left"}
    if ALARM.search(p) and re.search(r"\b(set|for|at|make|wake)\b", p):
        secs = parse_duration(p) if re.search(r"\bin\b", p) else None
        when = now + secs if secs else parse_clock(p, now)   # "wake me up in 20 minutes"
        return {"do": "alarm", "when": when}
    if TIMER.search(p):
        return {"do": "timer", "seconds": parse_duration(p)}
    return None


# ----------------------------
# the timers themselves
# ----------------------------

class Timers:
    def __init__(self, path: Path = None, clock=time.time, face=None):
        self.path = path or FILE
        self.clock = clock
        self.face = face            # callable(msg) for the countdown on the screen
        self.items: List[dict] = self._load()
        self.lock = threading.Lock()
        self.ringing: List[dict] = []   # alarms that will ring again
        self.next_id = max([i["id"] for i in self.items] + [0]) + 1
        self.shown = None

    def _load(self) -> List[dict]:
        try:
            items = json.loads(self.path.read_text())
            return [i for i in items if isinstance(i, dict) and "end" in i and "kind" in i][:MAX_ITEMS]
        except (OSError, ValueError):
            return []

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.items))
            os.chmod(tmp, 0o600)
            tmp.replace(self.path)
        except OSError as e:
            print("Timers: couldn't save:", repr(e), flush=True)

    def add_timer(self, seconds: int) -> dict:
        return self._add("timer", self.clock() + seconds, spoken_duration(seconds))

    def add_alarm(self, when: float) -> dict:
        return self._add("alarm", when, clock_text(when))

    def _add(self, kind: str, end: float, label: str) -> dict:
        with self.lock:
            item = {"id": self.next_id, "kind": kind, "end": end, "label": label}
            self.next_id += 1
            self.items.append(item)
            self.items.sort(key=lambda i: i["end"])
            self._save()
        self.show()
        return item

    def full(self) -> bool:
        return len(self.items) >= MAX_ITEMS

    def cancel(self, kind: str, everything: bool = False) -> List[dict]:
        """Cancel the soonest of this kind (or all of them); returns what was cancelled."""
        with self.lock:
            mine = [i for i in self.items if i["kind"] == kind]
            gone = mine if everything else mine[:1]
            self.items = [i for i in self.items if i not in gone]
            if kind == "alarm":
                self.ringing = []
            self._save()
        self.show()
        return gone

    def due(self) -> Optional[dict]:
        """The next thing that should ring now, or None."""
        now = self.clock()
        with self.lock:
            for r in self.ringing:
                if r["again"] <= now:
                    r["again"] = now + RING_GAP
                    r["rings"] += 1
                    if r["rings"] >= ALARM_RINGS:
                        self.ringing.remove(r)
                    return dict(r["item"], again=True)
            if self.items and self.items[0]["end"] <= now:
                item = self.items.pop(0)
                self._save()
                if item["kind"] == "alarm":
                    self.ringing.append({"item": item, "again": now + RING_GAP, "rings": 1})
            else:
                return None
        self.show()
        return item

    def silence(self) -> bool:
        """She was woken (tap or 'Hey Chatty'): stop any alarm that's still ringing."""
        with self.lock:
            had = bool(self.ringing)
            self.ringing = []
        return had

    def summary(self) -> str:
        now = self.clock()
        with self.lock:
            items = list(self.items)
        if not items:
            return "You don't have any timers or alarms right now."
        parts = []
        for i in items:
            if i["kind"] == "timer":
                parts.append(f"your {i['label']} timer has {spoken_left(i['end'] - now)} left")
            else:
                parts.append(f"your alarm is set for {clock_text(i['end'])}")
        text = "; ".join(parts)
        return text[0].upper() + text[1:] + "."

    def show(self) -> None:
        """Tell the face about the next one ('timer:<end>:<kind>:<label>', or 'timer:' for none)."""
        with self.lock:
            nxt = self.items[0] if self.items else None
        msg = f"timer:{nxt['end']:.0f}:{nxt['kind']}:{nxt['label']}" if nxt else "timer:"
        self.shown = msg
        if self.face:
            try:
                self.face(msg)
            except Exception:
                pass


def ring_text(item: dict) -> str:
    if item["kind"] == "alarm":
        if item.get("again"):
            return f"It's {clock_text(time.time())}. Your alarm is still going. Tap me or say Hey Chatty to stop it."
        return f"Good {'morning' if time.localtime().tm_hour < 12 else 'day'}! It's {item['label']}, time for your alarm."
    return f"Ding! Your {item['label']} timer is done."


def done_notice(item: dict) -> str:
    what = "Alarm" if item["kind"] == "alarm" else f"{item['label'].capitalize()} timer"
    return f"{what} went off"
