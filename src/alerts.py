"""
Local alerts: severe weather and AMBER alerts from the National Weather Service.

Every few minutes (in the background) Chatty asks the free NWS alerts API what is
active for her location: https://api.weather.gov/alerts/active?point=LAT,LON

  - Urgent  (tornado / flash flood / severe thunderstorm WARNINGS, "Extreme" or
             "Severe" warnings, evacuation and shelter-in-place orders):
             said right away, with an attention chime, even at night or while
             she's resting (turn that off with CHATTY_ALERTS_NIGHT=0).
  - AMBER   ("Child Abduction Emergency"): said with the details (who/what vehicle
             to look for) when she's awake, 7am-11pm.
  - Other   (watches, advisories, special weather statements): said once, briefly,
             when she's awake and it's daytime.

Each alert is announced ONCE (updates to the same alert aren't repeated), and the
ones she's already announced are remembered across restarts.

A note on AMBER alerts: the NWS feed only carries the ones law enforcement sends
through the NWS / NOAA Weather Radio. Many go straight to phones (Wireless Emergency
Alerts) instead, so Chatty may miss some. Keep phone alerts on; she's a bonus, not
a replacement.

Settings (in /etc/chatty/secrets.env):
    CHATTY_ALERTS=0          turn alerts off (default on)
    CHATTY_ALERTS_AMBER=0    no AMBER / civil alerts (default on)
    CHATTY_ALERTS_NIGHT=0    don't speak even urgent warnings at night (default: speak)
    CHATTY_ALERT_EVERY=180   seconds between checks
    CHATTY_LAT / CHATTY_LON  location (default: same as the weather skill)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

ENABLED = os.getenv("CHATTY_ALERTS", "1") != "0"
AMBER = os.getenv("CHATTY_ALERTS_AMBER", "1") != "0"
NIGHT = os.getenv("CHATTY_ALERTS_NIGHT", "1") != "0"
EVERY = max(60.0, float(os.getenv("CHATTY_ALERT_EVERY", "180")))
USER_AGENT = os.getenv("CHATTY_NWS_AGENT", "ChattyNode/0.2 (home voice assistant)")
SEEN_FILE = Path(os.getenv("CHATTY_ALERTS_SEEN",
                           os.path.expanduser("~/.local/share/chatty/alerts_seen.json")))


def location():
    try:
        from weather_lookup import DEFAULT_LAT, DEFAULT_LON
    except ImportError:
        DEFAULT_LAT, DEFAULT_LON = 29.4241, -98.4936
    return (float(os.getenv("CHATTY_LAT", DEFAULT_LAT)), float(os.getenv("CHATTY_LON", DEFAULT_LON)))


# Events that are about people's safety rather than weather.
AMBER_EVENTS = {"child abduction emergency"}
CIVIL_URGENT = {"evacuation immediate", "shelter in place warning", "civil danger warning",
                "nuclear power plant warning", "radiological hazard warning",
                "hazardous materials warning", "fire warning", "law enforcement warning",
                "911 telephone outage emergency"}
CIVIL_INFO = {"blue alert", "civil emergency message", "local area emergency"}
# Weather warnings that should never wait, whatever their listed severity.
WEATHER_URGENT = {"tornado warning", "flash flood warning", "severe thunderstorm warning",
                  "extreme wind warning", "hurricane warning", "tropical storm warning",
                  "flash flood emergency", "storm surge warning", "dust storm warning",
                  "ice storm warning", "blizzard warning"}


@dataclass
class Alert:
    id: str
    event: str            # "Tornado Warning"
    kind: str             # "urgent" | "amber" | "info"
    spoken: str           # what Chatty says
    details: str          # longer text for "Hey Chatty, alert details"
    expires: float        # unix time (0 = unknown)
    references: tuple = ()


# ----------------------------
# reading the NWS feed
# ----------------------------

def fetch_features(lat: float, lon: float, timeout: float = 10) -> list:
    url = f"https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/geo+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore")).get("features", [])


def _ts(iso: Optional[str]) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _spoken_time(ts: float) -> str:
    d = time.localtime(ts)
    hour = d.tm_hour % 12 or 12
    ampm = "a m" if d.tm_hour < 12 else "p m"
    minute = "" if d.tm_min == 0 else f":{d.tm_min:02d}"
    day = "" if time.strftime("%Y%m%d", d) == time.strftime("%Y%m%d") else f" {time.strftime('%A', d)}"
    return f"{hour}{minute} {ampm}{day}"


def _sentences(text: str, limit: int) -> str:
    """The first sentences of a long NWS text, cleaned up for speaking."""
    text = re.sub(r"\s+", " ", (text or "").replace("...", ", ")).strip()
    text = re.sub(r"^\*\s*", "", text)
    text = re.sub(r"\*\s*(WHAT|WHERE|WHEN|IMPACTS|HAZARD|SOURCE|IMPACT)\s*,?", r"\1:", text)
    out = ""
    for s in re.split(r"(?<=[.!?])\s+", text):
        if len(out) + len(s) > limit and out:
            break
        out = (out + " " + s).strip()
    return out[:limit]


def classify(event: str, severity: str) -> Optional[str]:
    e = event.lower()
    if e in AMBER_EVENTS:
        return "amber" if AMBER else None
    if e in CIVIL_URGENT:
        return "urgent" if AMBER else None
    if e in CIVIL_INFO:
        return "info" if AMBER else None
    if e in WEATHER_URGENT or (e.endswith(("warning", "emergency")) and severity in ("Extreme", "Severe")):
        return "urgent"
    if e.startswith("test") or e.endswith("test"):
        return None
    return "info"


def parse(feature: dict) -> Optional[Alert]:
    p = feature.get("properties", {})
    if p.get("status") != "Actual" or p.get("messageType") == "Cancel":
        return None   # skip tests, exercises and cancellations
    event = (p.get("event") or "").strip()
    kind = classify(event, p.get("severity") or "")
    if not event or not kind:
        return None
    expires = _ts(p.get("ends") or p.get("expires"))
    until = f" until {_spoken_time(expires)}" if expires else ""
    article = "an" if event[:1].lower() in "aeiou" else "a"
    if kind == "amber":
        event = "AMBER Alert"
        desc = _sentences(p.get("description") or p.get("headline") or "", 420)
        spoken = f"AMBER Alert for our area. {desc} If you see them, call 9 1 1."
    elif kind == "urgent":
        spoken = f"Attention! The National Weather Service has issued {article} {event} for our area{until}."
        instr = _sentences(p.get("instruction") or "", 160)
        if instr:
            spoken += " " + instr
    else:
        spoken = f"Heads up: there's {article} {event} for our area{until}."
    details = _sentences(p.get("description") or p.get("headline") or "", 500)
    refs = tuple(r.get("identifier") or r.get("@id") or "" for r in (p.get("references") or []))
    return Alert(id=p.get("id") or feature.get("id") or "", event=event, kind=kind,
                 spoken=spoken, details=details, expires=expires, references=refs)


# ----------------------------
# remembering what's been announced
# ----------------------------

def _load_seen() -> dict:
    try:
        return json.loads(SEEN_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_seen(seen: dict) -> None:
    try:
        SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SEEN_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(seen))
        tmp.replace(SEEN_FILE)
    except OSError as e:
        print("Couldn't save seen alerts:", repr(e), flush=True)


class Watcher:
    """Checks the feed in a background thread. The voice node calls due(mode) from
    its main loop to get an alert that should be spoken now (or None)."""

    def __init__(self, fetch: Optional[Callable[[], list]] = None, clock=time.time):
        lat, lon = location()
        self.fetch = fetch or (lambda: fetch_features(lat, lon))
        self.clock = clock
        self.seen = _load_seen()          # alert id -> expiry
        self.pending: List[Alert] = []
        self.active: List[Alert] = []     # everything currently in effect (for questions)
        self.lock = threading.Lock()
        self.ok = False                   # last check worked?

    def check_once(self) -> None:
        try:
            features = self.fetch()
            self.ok = True
        except Exception as e:
            self.ok = False
            print("Alert check failed:", repr(e), flush=True)
            return
        now = self.clock()
        alerts = [a for a in (parse(f) for f in features) if a]
        with self.lock:
            self.active = alerts
            changed = False
            for a in alerts:
                if a.id in self.seen:
                    continue
                # an update of an alert already announced: remember it quietly
                repeat = any(r in self.seen for r in a.references)
                self.seen[a.id] = a.expires or now + 12 * 3600
                changed = True
                if not repeat:
                    print(f"New alert ({a.kind}): {a.event}", flush=True)
                    self.pending.append(a)
            # forget old ones so the file stays small
            for k in [k for k, exp in self.seen.items() if exp < now - 86400]:
                del self.seen[k]
                changed = True
            self.pending = [a for a in self.pending if not a.expires or a.expires > now]
            self.pending.sort(key=lambda a: {"urgent": 0, "amber": 1, "info": 2}[a.kind])
        if changed:
            _save_seen(self.seen)

    def run_forever(self) -> None:
        while True:
            self.check_once()
            time.sleep(EVERY)

    def start(self) -> None:
        if ENABLED:
            threading.Thread(target=self.run_forever, daemon=True, name="alerts").start()

    def due(self, mode: str) -> Optional[Alert]:
        """The next alert to say now, given the voice node's mode
        ('sleep' = awake and free, 'resting' = put to bed, others = busy)."""
        hour = time.localtime(self.clock()).tm_hour
        with self.lock:
            for a in self.pending:
                if a.kind == "urgent":
                    ok = mode == "sleep" or (mode == "resting" and NIGHT)
                elif a.kind == "amber":
                    ok = mode == "sleep" and 7 <= hour < 23
                else:
                    ok = mode == "sleep" and 8 <= hour < 22
                if ok:
                    self.pending.remove(a)
                    return a
        return None

    # ----- questions: "any weather alerts?" -----
    def summary(self) -> str:
        with self.lock:
            active = list(self.active)
        if not active:
            if not self.ok:
                return "I can't reach the weather service right now, so I'm not sure about alerts."
            return "No alerts for our area right now."
        names = []
        for a in active:
            if a.event not in names:
                names.append(a.event)
        if len(names) == 1:
            return f"There's {'an' if names[0][:1].lower() in 'aeiou' else 'a'} {names[0]} in effect. Ask me for alert details to hear more."
        return "Active alerts: " + ", ".join(names[:-1]) + f", and {names[-1]}. Ask me for alert details to hear more."

    def details(self) -> str:
        with self.lock:
            active = list(self.active)
        if not active:
            return "There are no alerts for our area right now."
        a = sorted(active, key=lambda a: {"urgent": 0, "amber": 1, "info": 2}[a.kind])[0]
        return f"{a.event}. {a.details}" if a.details else a.spoken
