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

A TORNADO WARNING for her spot is different: it turns on Red Alert (red_alert.py):
red face at full brightness, her own alarm tone, "Red alert! Red alert!...", a phone
buzz, repeated until someone taps her or says "Hey Chatty". A Tornado Watch is not.

New alerts also show up right away as an amber notice on her face (day or night,
until someone taps the screen), and urgent warnings are sent to your phone through
IFTTT (the same `chatty_alert` event the greenhouse and SSH alerts use).

The node network gets the list too. After every check, what's in effect is posted
(retained) on MQTT, so the e-ink word clock can show a small note:

    chatty/alerts/active   {"alerts": [{"event": "Tornado Warning", "kind": "urgent",
                                        "expires_ts": 1730900000}],
                            "ts": 1730896700, "source": "NWS alerts"}

kind is "urgent", "amber" or "info"; expires_ts is null when unknown. An empty list
means nothing is in effect. Only names and times, no descriptions. It's news, never
a command. Treat it as stale after about 20 minutes ("ts").

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
    CHATTY_ALERT_STALE_MINUTES=30  no good check for this long: a face notice says so
    CHATTY_LAT / CHATTY_LON  location (default: same as the weather skill)
    CHATTY_ALERTS_SCREEN=0   don't show new alerts on the face
    CHATTY_ALERTS_PHONE      which alerts go to the phone: "urgent" (default:
                             tornado, severe thunderstorm, flash flood and other
                             warnings), "tornado" (tornado warnings only), "all", or "off"
    CHATTY_ALERTS_IFTTT_EVENT  IFTTT Webhooks event (default chatty_alert)
    IFTTT_KEY                your IFTTT Webhooks key
"""
from __future__ import annotations

import json
import storage  # safe JSON saves (atomic, owner-only)
import os
import re
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

try:
    import red_alert
except ImportError:  # running from another folder
    from . import red_alert  # type: ignore

ENABLED = os.getenv("CHATTY_ALERTS", "1") != "0"
AMBER = os.getenv("CHATTY_ALERTS_AMBER", "1") != "0"
NIGHT = os.getenv("CHATTY_ALERTS_NIGHT", "1") != "0"
EVERY = max(60.0, float(os.getenv("CHATTY_ALERT_EVERY", "180")))
STALE = max(5.0, float(os.getenv("CHATTY_ALERT_STALE_MINUTES", "30"))) * 60
STALE_NOTICE = "I can't reach the weather service for alerts right now. I'll keep trying."
BACK_NOTICE = "I can check weather alerts again."
SCREEN = os.getenv("CHATTY_ALERTS_SCREEN", "1") != "0"
PHONE = os.getenv("CHATTY_ALERTS_PHONE", "urgent").strip().lower()
IFTTT_EVENT = os.getenv("CHATTY_ALERTS_IFTTT_EVENT", "chatty_alert").strip()
USER_AGENT = os.getenv("CHATTY_NWS_AGENT", "ChattyNode/0.2 (home voice assistant)")
TOPIC = "chatty/alerts/active"
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
    red: bool = False     # a Tornado Warning: Red Alert (red_alert.py)


# ----------------------------
# reading the NWS feed
# ----------------------------

def fetch_features(lat: float, lon: float, timeout: float = 10) -> list:
    url = f"https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/geo+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "ignore"))
    features = data.get("features") if isinstance(data, dict) else None
    return features if isinstance(features, list) else []


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


def parse_all(features) -> List[Alert]:
    """Every alert in the feed. One odd entry is skipped, never the whole list
    (an error here used to stop the alert checker for good, Red Alert included)."""
    out = []
    for f in features or []:
        try:
            a = parse(f)
        except Exception as e:
            print("Skipped an alert I couldn't read:", repr(e)[:200], flush=True)
            continue
        if a:
            out.append(a)
    return out


def parse(feature: dict) -> Optional[Alert]:
    p = feature.get("properties") or {}
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
    refs = tuple((r.get("identifier") or r.get("@id") or "") if isinstance(r, dict) else str(r)
                 for r in (p.get("references") or []))
    return Alert(id=p.get("id") or feature.get("id") or "", event=event, kind=kind,
                 spoken=spoken, details=details, expires=expires, references=refs,
                 red=kind == "urgent" and red_alert.is_red(event))


# ----------------------------
# on the screen and on the phone (right away, day or night)
# ----------------------------

def _written_time(ts: float) -> str:
    d = time.localtime(ts)
    text = f"{d.tm_hour % 12 or 12}:{d.tm_min:02d} {'AM' if d.tm_hour < 12 else 'PM'}"
    if time.strftime("%Y%m%d", d) != time.strftime("%Y%m%d"):
        text += time.strftime(" %a", d)
    return text


def screen_text(a: Alert) -> str:
    """Short line for the face, e.g. 'WEATHER ALERT: Tornado Warning until 6:45 PM'."""
    if a.kind == "amber":
        return "AMBER Alert for our area. Ask me for alert details."
    until = f" until {_written_time(a.expires)}" if a.expires else ""
    label = "WEATHER ALERT" if a.kind == "urgent" else "Heads up"
    if a.red:
        label = "RED ALERT"
    return f"{label}: {a.event}{until}"


def phone_wanted(a: Alert, mode: str = None) -> bool:
    mode = PHONE if mode is None else mode
    if mode == "all":
        return True
    if mode == "urgent":
        return a.kind in ("urgent", "amber")
    if mode == "tornado":
        return a.event.lower().startswith("tornado") and a.kind == "urgent"
    return False


def send_phone_alert(text: str) -> None:
    """IFTTT phone buzz (phone.py); kept under this name for the many callers."""
    import phone
    phone.send(text, IFTTT_EVENT)


def show_and_send(a: Alert, show=None, send=None) -> None:
    """What happens the moment a new alert arrives."""
    if SCREEN:
        try:
            if show is None:
                import face_link
                show = face_link.notice
            show(screen_text(a))
        except Exception as e:
            print("Couldn't show alert on the face:", repr(e), flush=True)
    if a.red:
        if PHONE != "off":    # Red Alert always buzzes the phone (unless phone alerts are off)
            (send or send_phone_alert)(red_alert.phone_text(a.expires))
    elif phone_wanted(a):
        (send or send_phone_alert)(f"Chatty: {screen_text(a)}. {a.spoken}"[:500])


def news(active: List[Alert], now: float) -> dict:
    """What goes on the node network (chatty/alerts/active): names and times only."""
    order = {"urgent": 0, "amber": 1, "info": 2}
    items, names = [], set()
    for a in sorted(active, key=lambda a: order[a.kind]):
        if a.event in names:         # the same warning for two zones: once is enough
            continue
        names.add(a.event)
        items.append({"event": a.event, "kind": a.kind,
                      "expires_ts": int(a.expires) if a.expires else None})
    return {"alerts": items[:5], "ts": int(now), "source": "NWS alerts"}


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
        storage.save_json(SEEN_FILE, seen)
    except OSError as e:
        print("Couldn't save seen alerts:", repr(e), flush=True)


class Watcher:
    """Checks the feed in a background thread. The voice node calls due(mode) from
    its main loop to get an alert that should be spoken now (or None)."""

    def __init__(self, fetch: Optional[Callable[[], list]] = None, clock=time.time,
                 on_new: Optional[Callable[[Alert], None]] = None,
                 publish: Optional[Callable[[str, dict], object]] = None,
                 notice: Optional[Callable[[str], None]] = None):
        lat, lon = location()
        self.publish = publish
        self.on_new = on_new if on_new is not None else show_and_send
        self.fetch = fetch or (lambda: fetch_features(lat, lon))
        self.clock = clock
        self.seen = _load_seen()          # alert id -> expiry
        self.pending: List[Alert] = []
        self.active: List[Alert] = []     # everything currently in effect (for questions)
        self.lock = threading.Lock()
        self.ok = False                   # last check worked?
        self.notice = notice              # face notice (default: face_link.notice)
        self.last_ok_at = clock()         # last good check (counting from start)
        self.stale_shown = False          # "I can't reach the weather service" is up

    def _show(self, text: str) -> None:
        if not SCREEN:
            return
        try:
            show = self.notice
            if show is None:
                import face_link
                show = face_link.notice
            show(text)
        except Exception as e:
            print("Couldn't show a notice on the face:", repr(e), flush=True)

    def stale(self, now: Optional[float] = None) -> bool:
        """True when no check has worked for CHATTY_ALERT_STALE_MINUTES."""
        now = self.clock() if now is None else now
        return now - self.last_ok_at >= STALE

    def check_once(self) -> None:
        try:
            features = self.fetch()
            if not isinstance(features, list):     # a garbled answer: keep the last list
                raise ValueError(f"unexpected feed: {type(features).__name__}")
            self.ok = True
        except Exception as e:
            self.ok = False
            print("Alert check failed:", repr(e), flush=True)
            if self.stale() and not self.stale_shown:
                self.stale_shown = True
                print("Alerts: no good check for a while; telling the face", flush=True)
                self._show(STALE_NOTICE)
            return
        now = self.clock()
        self.last_ok_at = now
        if self.stale_shown:
            self.stale_shown = False
            self._show(BACK_NOTICE)
        alerts = parse_all(features)
        fresh = []
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
                    print(f"New alert ({'RED ALERT' if a.red else a.kind}): {a.event}", flush=True)
                    if not a.red:         # red ones are said by the Red Alert (red_alert.py)
                        self.pending.append(a)
                    fresh.append(a)
            # forget old ones so the file stays small
            for k in [k for k, exp in self.seen.items() if exp < now - 86400]:
                del self.seen[k]
                changed = True
            self.pending = [a for a in self.pending if not a.expires or a.expires > now]
            self.pending.sort(key=lambda a: {"urgent": 0, "amber": 1, "info": 2}[a.kind])
        if changed:
            _save_seen(self.seen)
        if self.publish:
            try:
                self.publish(TOPIC, news(alerts, now))
            except Exception as e:
                print("Couldn't post alerts to the node network:", repr(e), flush=True)
        for a in fresh:
            try:
                self.on_new(a)
            except Exception as e:
                print("Alert hand-off failed:", repr(e), flush=True)

    def run_forever(self) -> None:
        while True:
            try:
                self.check_once()
            except Exception as e:   # never let one bad check stop the checker
                print("Alert checker hiccup (still running):", repr(e), flush=True)
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

    def red_warning(self) -> Optional[Alert]:
        """The Tornado Warning in effect here right now (Red Alert), or None.
        When the feed can't be reached, the last list is kept."""
        now = self.clock()
        with self.lock:
            red = [a for a in self.active if a.red and (not a.expires or a.expires > now)]
        return max(red, key=lambda a: a.expires or now + 3600) if red else None

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


if __name__ == "__main__":
    # Try it on the Pi:  python3 src/alerts.py --test   (fake tornado warning: face + phone)
    #                    python3 src/alerts.py          (what's active right now)
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from dotenv import load_dotenv
        load_dotenv("/etc/chatty/secrets.env")
    except ImportError:
        pass
    if "--test" in sys.argv:
        fake = Alert(id="test", event="Tornado Warning (TEST)", kind="urgent",
                     spoken="This is only a test of Chatty's weather alerts.",
                     details="", expires=time.time() + 1800)
        show_and_send(fake)
        print("Shown on the face:", screen_text(fake))
    else:
        lat, lon = location()
        found = [a for a in (parse(f) for f in fetch_features(lat, lon)) if a]
        print(f"Location {lat}, {lon}: {len(found)} active alert(s)")
        for a in found:
            print(" -", screen_text(a))
