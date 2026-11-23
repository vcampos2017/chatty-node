"""
Weather trends: "Heads up, the air pressure is dropping" and "the greenhouse is cooling fast".

Vincent asked (2026-11-23) for trend advisories, like temperatures or pressure dropping.
All local and free: the greenhouse node already sends its BME280 readings over the node
network about once a minute (chatty/nodes/greenhouse/data: air_temperature_f,
air_humidity, air_pressure_hpa). Chatty keeps one reading every ~5 minutes for the last
6 hours and looks at how they change:

  pressure   falling CHATTY_TREND_PRESSURE (3) millibars (hPa) or more in 3 hours: a storm
             or rain is often on the way. 6+ is "falling fast". The BME280 sits in the
             greenhouse box, which is fine: a box doesn't change the pressure.
             No pressure from the greenhouse (sensor off, node quiet)? She reads the
             nearest NWS station's last few hours instead (free, no key), at most every
             30 minutes.
  frost      the greenhouse is at CHATTY_TREND_FROST_AT (40 F) or below and cooling 2+
             degrees an hour, on its way to freezing within 3 hours (or already 34 F or
             below and still dropping).
  cold snap  the greenhouse dropped CHATTY_TREND_TEMP_DROP (15 F) or more in 2 hours.
  humidity   rising 15+ points in 3 hours: only added to a pressure heads-up (and to the
             answer), never said on its own. The box often reads 100%, so it rarely moves.

How she tells you (quiet, like rain_watch.py):
  - each kind once, then not again until it has been back to normal for an hour AND
    CHATTY_TREND_GAP (6) hours have passed;
  - a short notice on her face every time (it dims and glows red at night like any notice);
  - said aloud only in the daytime, while she's free, not after the bedtime wind-down, and
    only within 45 minutes (an old heads-up stays a notice);
  - the phone only if CHATTY_TREND_PHONE says so (frost / all; default off).
Red Alert is separate (red_alert.py) and always wins: spoken extras wait while it's on.

"Is the pressure dropping?", "what's the barometer?", "weather trends", "is it getting
colder in the greenhouse?", "is a storm coming?" answer any time.

The trends go on the node network too (retained, at most every 5 minutes), for the Matrix
clock or anyone else; news only, never a command:

    chatty/trends  {"pressure_hpa": 1012.4, "pressure_3h": -3.6, "pressure_source": "greenhouse",
                    "temp_f": 41.2, "temp_1h": -2.5, "temp_2h": -4.8, "humidity": 82,
                    "humidity_3h": 6, "advisories": ["pressure"], "ts": 1763860000}

Remembered across restarts (readings and "already told"): ~/.local/share/chatty/trends.json.

Settings (in /etc/chatty/secrets.env):
    CHATTY_TRENDS=0             turn this off
    CHATTY_TREND_SPEAK=0        face notice only, never say it on her own
    CHATTY_TREND_PRESSURE=3     millibars in 3 hours that count as "dropping" (fast = twice that)
    CHATTY_TREND_FROST_AT=40    greenhouse temperature (F) where the frost watch starts
    CHATTY_TREND_TEMP_DROP=15   degrees F in 2 hours that count as a cold snap
    CHATTY_TREND_GAP=6          hours between two heads-ups of the same kind
    CHATTY_TREND_PHONE=off      frost | all | off
    CHATTY_TREND_NWS=0          never use the NWS station for pressure
    CHATTY_TREND_NODE=greenhouse   the node whose readings are used
Try it on the Pi:  python3 src/trends.py
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import storage

try:
    import quiet_hours
except ImportError:  # running from another folder
    from . import quiet_hours  # type: ignore


def _num(name: str, default: float, low: float, high: float) -> float:
    try:
        return min(high, max(low, float(os.getenv(name, str(default)))))
    except ValueError:
        return default


ENABLED = os.getenv("CHATTY_TRENDS", "1") != "0"
SPEAK = os.getenv("CHATTY_TREND_SPEAK", "1") != "0"
USE_NWS = os.getenv("CHATTY_TREND_NWS", "1") != "0"
PHONE = os.getenv("CHATTY_TREND_PHONE", "off").strip().lower()
NODE = os.getenv("CHATTY_TREND_NODE", "greenhouse").strip() or "greenhouse"
PRESSURE_DROP = _num("CHATTY_TREND_PRESSURE", 3, 0.5, 20)
FROST_AT = _num("CHATTY_TREND_FROST_AT", 40, 33, 60)
TEMP_DROP = _num("CHATTY_TREND_TEMP_DROP", 15, 3, 60)
GAP = _num("CHATTY_TREND_GAP", 6, 1, 48) * 3600

SAMPLE_EVERY = 240        # keep a reading at most every 4 minutes
KEEP = 6 * 3600           # how much history to keep
SLACK = 15 * 60           # "3 hours ago" may be off by this much
FRESH = 20 * 60           # the newest reading must be this new to count
CLEAR_FOR = 3600          # back to normal this long before the same kind can come again
SAY_WITHIN = 45 * 60      # a heads-up older than this stays a notice
NWS_EVERY = 30 * 60
SAVE_EVERY = 15 * 60
PUBLISH_EVERY = 5 * 60
HUMID_RISE = 15
FREEZING = 32.0
TOPIC = "chatty/trends"
STATE_FILE = Path(os.getenv("CHATTY_TRENDS_STATE",
                            os.path.expanduser("~/.local/share/chatty/trends.json")))

Series = List[Tuple[float, float]]     # (when, value), oldest first
FIELDS = {"temp": ("air_temperature_f", -40, 140),
          "humidity": ("air_humidity", 0, 100),
          "pressure": ("air_pressure_hpa", 800, 1100)}


def _reading(d: dict, key: str, low: float, high: float) -> Optional[float]:
    try:
        v = float(d.get(key))
    except (TypeError, ValueError):
        return None
    return v if low <= v <= high else None      # a sensor glitch is not a trend


def _mean(vals: List[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def change(series: Series, now: float, window: float) -> Optional[float]:
    """How much it moved over the last `window` seconds (newest minus then), or None.

    Both ends are averages of the readings within 15 minutes, so one noisy reading
    can't fake a trend; None without a fresh reading or without one from back then."""
    if not series or now - series[-1][0] > FRESH:
        return None
    end = series[-1][0]
    late = _mean([v for t, v in series if end - t <= 10 * 60])
    early = _mean([v for t, v in series if abs((end - window) - t) <= SLACK])
    if late is None or early is None:
        return None
    return late - early


def latest(series: Series, now: float) -> Optional[float]:
    if not series or now - series[-1][0] > FRESH:
        return None
    return series[-1][1]


def _clock(ts: float) -> str:
    d = time.localtime(ts)
    return f"{d.tm_hour % 12 or 12}:{d.tm_min:02d} {'AM' if d.tm_hour < 12 else 'PM'}"


def _hours(h: float) -> str:
    return "an hour" if round(h) <= 1 else f"{round(h)} hours"


class Trends:
    """Feed it node readings with on_data(); the voice node asks due(mode)."""

    def __init__(self, notice: Optional[Callable[[str], None]] = None,
                 publish: Optional[Callable[[str, dict], object]] = None,
                 phone: Optional[Callable[[str], object]] = None,
                 nws: Optional[Callable[[], Series]] = None,
                 is_night: Callable[[float], bool] = quiet_hours.is_night,
                 tucked_in: Callable[[float], bool] = lambda now: False,
                 clock: Callable[[], float] = time.time,
                 state_file: Optional[Path] = STATE_FILE):
        self.notice = notice or _face_notice
        self.publish, self.phone = publish, phone or _phone
        self.nws = nws if nws is not None else (_nws_pressure if USE_NWS else None)
        self.is_night, self.tucked_in, self.clock = is_night, tucked_in, clock
        self.state_file = state_file
        self.lock = threading.Lock()
        self.series: Dict[str, Series] = {k: [] for k in FIELDS}
        self.nws_series: Series = []
        self.nws_at = -1e12
        self.told: Dict[str, float] = {}         # kind -> when it was last told
        self.clear_since: Dict[str, float] = {}  # kind -> when it went back to normal
        self.pending: Optional[Tuple[str, str, float]] = None   # (kind, words, when)
        self.saved_at = -1e12
        self.published_at = -1e12
        self._fetching = False
        self._load()

    # ----- remembering -----
    def _load(self) -> None:
        if not self.state_file:
            return
        d = storage.load_json(self.state_file, {}) or {}
        try:
            for k in FIELDS:
                self.series[k] = [(float(t), float(v)) for t, v in d.get("series", {}).get(k, [])]
            self.told = {str(k): float(v) for k, v in d.get("told", {}).items()}
            self.clear_since = {str(k): float(v) for k, v in d.get("clear_since", {}).items()}
        except (TypeError, ValueError, AttributeError):
            self.series = {k: [] for k in FIELDS}

    def _save(self, now: float) -> None:
        self.saved_at = now
        if not self.state_file:
            return
        try:
            storage.save_json(self.state_file, {"series": self.series, "told": self.told,
                                                "clear_since": self.clear_since})
        except OSError as e:
            print("Trends: couldn't save:", repr(e), flush=True)

    # ----- input from the node network -----
    def on_data(self, name: str, body: dict, now: Optional[float] = None) -> None:
        if not ENABLED or name != NODE or not isinstance(body, dict):
            return
        now = self.clock() if now is None else now
        m = body.get("metrics") if isinstance(body.get("metrics"), dict) else body
        with self.lock:
            added = False
            for k, (key, low, high) in FIELDS.items():
                v = _reading(m, key, low, high)
                s = self.series[k]
                if v is None or (s and now - s[-1][0] < SAMPLE_EVERY):
                    continue
                s.append((now, v))
                self.series[k] = [(t, x) for t, x in s if now - t <= KEEP]
                added = True
        if added:
            self.check(now)

    def pressure_series(self, now: float) -> Tuple[Series, str]:
        """The greenhouse's own pressure when it has one, else the NWS station's."""
        own = self.series["pressure"]
        if own and now - own[-1][0] <= FRESH:
            return own, "greenhouse"
        return self.nws_series, "weather station"

    def _maybe_nws(self, now: float) -> None:
        """No pressure from the greenhouse: read the NWS station (in the background)."""
        if not self.nws or self._fetching or now - self.nws_at < NWS_EVERY:
            return
        own = self.series["pressure"]
        if own and now - own[-1][0] <= FRESH:
            return
        self.nws_at, self._fetching = now, True

        def fetch():
            try:
                got = sorted(self.nws() or [])
                with self.lock:
                    self.nws_series = [(float(t), float(v)) for t, v in got if 800 <= v <= 1100]
                self.check(self.clock(), fetch=False)
            except Exception as e:
                print("Trends: no pressure from the weather station:", repr(e), flush=True)
            finally:
                self._fetching = False
        threading.Thread(target=fetch, daemon=True, name="trends-nws").start()

    # ----- what she sees -----
    def snapshot(self, now: Optional[float] = None) -> dict:
        now = self.clock() if now is None else now
        with self.lock:
            ps, source = self.pressure_series(now)
            if source == "weather station":     # NWS readings come hourly and are ~1 h late
                p = ps[-1][1] if ps and now - ps[-1][0] <= 2 * 3600 else None
                p3 = change(ps, ps[-1][0], 3 * 3600) if p is not None else None
            else:
                p, p3 = latest(ps, now), change(ps, now, 3 * 3600)
            t, h = self.series["temp"], self.series["humidity"]
            return {"pressure_hpa": p, "pressure_3h": p3,
                    "pressure_source": source if p is not None else None,
                    "temp_f": latest(t, now), "temp_1h": change(t, now, 3600),
                    "temp_2h": change(t, now, 2 * 3600),
                    "humidity": latest(h, now), "humidity_3h": change(h, now, 3 * 3600)}

    def advisories(self, s: dict, now: Optional[float] = None) -> Dict[str, Tuple[str, str]]:
        """kind -> (what she says, the face notice) for each trend that's off right now."""
        now = self.clock() if now is None else now
        out = {}
        p3 = s["pressure_3h"]
        if p3 is not None and p3 <= -PRESSURE_DROP:
            fast = p3 <= -2 * PRESSURE_DROP
            mb = round(-p3)
            humid = s["humidity_3h"] is not None and s["humidity_3h"] >= HUMID_RISE
            said = (f"Heads up: the air pressure is falling fast, about {mb} millibars in 3 hours. "
                    "A storm may be on the way, so keep an eye on the sky." if fast else
                    f"Heads up: the air pressure is dropping, about {mb} millibars in the last 3 hours. "
                    "That often means rain or a storm is on the way.")
            if humid:
                said += " The air is getting more humid too."
            out["pressure"] = (said, f"Pressure {'falling fast' if fast else 'dropping'}: "
                                     f"-{mb} mb in 3 h" + (", humidity rising" if humid else ""))
        temp, t1, t2 = s["temp_f"], s["temp_1h"], s["temp_2h"]
        if temp is not None and t1 is not None and t1 <= -2 and temp <= FROST_AT:
            rate = -t1
            if temp <= FREEZING + 2:
                out["frost"] = (f"Brr! The greenhouse is down to {temp:.0f} degrees and still dropping. "
                                "Frost watch for the plants.",
                                f"Greenhouse {temp:.0f}°F and dropping: frost watch")
            else:
                hours = (temp - FREEZING) / rate
                if hours <= 3:
                    at = _clock(now + hours * 3600)
                    out["frost"] = (f"Heads up: the greenhouse is cooling fast. It's {temp:.0f} degrees and "
                                    f"dropping about {rate:.0f} degrees an hour, so it could reach freezing "
                                    f"around {at}.",
                                    f"Greenhouse {temp:.0f}°F, -{rate:.0f}°/h: could freeze ~{at}")
        if temp is not None and t2 is not None and t2 <= -TEMP_DROP and "frost" not in out:
            out["cold"] = (f"Whoa, the greenhouse dropped {-t2:.0f} degrees in the last 2 hours. "
                           f"It's {temp:.0f} now. A cold front, maybe?",
                           f"Greenhouse -{-t2:.0f}°F in 2 h (now {temp:.0f}°F)")
        return out

    # ----- deciding -----
    def check(self, now: Optional[float] = None, fetch: bool = True) -> None:
        now = self.clock() if now is None else now
        if fetch:
            self._maybe_nws(now)
        s = self.snapshot(now)
        found = self.advisories(s, now)
        fire = []
        with self.lock:
            for kind in ("pressure", "frost", "cold"):
                if kind not in found:
                    self.clear_since.setdefault(kind, now)
                    continue
                cleared = self.clear_since.pop(kind, None)
                last = self.told.get(kind)
                ready = last is None or (cleared is not None and now - cleared >= CLEAR_FOR
                                         and now - last >= GAP)
                if ready:
                    self.told[kind] = now
                    fire.append(kind)
            if fire or now - self.saved_at >= SAVE_EVERY:
                self._save(now)
            publish = self.publish and now - self.published_at >= PUBLISH_EVERY
            if publish:
                self.published_at = now
        for kind in fire:
            self._tell(kind, *found[kind], now=now)
        if publish:
            body = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in s.items()}
            body.update(advisories=sorted(found), ts=int(now))
            try:
                self.publish(TOPIC, body)
            except Exception as e:
                print("Trends: couldn't post the trends:", repr(e), flush=True)

    def _tell(self, kind: str, said: str, screen: str, now: float) -> None:
        print(f"Trends: {kind}: {screen}", flush=True)
        try:
            self.notice(screen)
        except Exception as e:
            print("Trends: couldn't show the notice:", repr(e), flush=True)
        if PHONE == "all" or (PHONE == "frost" and kind == "frost"):
            try:
                self.phone(f"Chatty: {screen}")
            except Exception as e:
                print("Trends: phone alert failed:", repr(e), flush=True)
        if SPEAK:
            with self.lock:
                if self.pending is None or kind == "frost":    # frost matters most to the plants
                    self.pending = (kind, said, now)

    def run_forever(self) -> None:
        time.sleep(60)          # give the node network a moment first
        while True:
            try:
                self.check()    # also when the greenhouse is quiet (then the NWS station's pressure)
            except Exception as e:
                print("Trends: check failed:", repr(e), flush=True)
            time.sleep(300)

    def start(self) -> None:
        if ENABLED:
            threading.Thread(target=self.run_forever, daemon=True, name="trends").start()

    # ----- for the voice node's main loop -----
    def due(self, mode: str, now: Optional[float] = None) -> Optional[str]:
        """The heads-up to say now: daytime, while she's free, not after the wind-down."""
        if not ENABLED or mode != "sleep":
            return None
        now = self.clock() if now is None else now
        with self.lock:
            got = self.pending
            if got is None:
                return None
            if now - got[2] > SAY_WITHIN:
                self.pending = None        # too old: the notice says it
                return None
        if self.is_night(now) or self.tucked_in(now):
            with self.lock:
                self.pending = None        # evening quiet: the notice is enough
            return None
        with self.lock:
            self.pending = None
        return got[1]

    # ----- "Hey Chatty, is the pressure dropping?" -----
    def answer(self, prompt: str = "", now: Optional[float] = None) -> str:
        now = self.clock() if now is None else now
        s = self.snapshot(now)
        p = (prompt or "").lower()
        about_temp = bool(re.search(r"\b(colder|warmer|cooling|warming|temperature|frost|freez)", p))
        parts = []
        if s["pressure_hpa"] is not None:
            inhg = s["pressure_hpa"] * 0.02953
            where = "in the greenhouse" if s["pressure_source"] == "greenhouse" else "at the weather station"
            p3 = s["pressure_3h"]
            if p3 is None:
                how = "I don't have 3 hours of readings yet to see which way it's going"
            elif p3 <= -2 * PRESSURE_DROP:
                how = f"and it's falling fast, down {-p3:.0f} millibars in 3 hours. A storm may be coming"
            elif p3 <= -PRESSURE_DROP:
                how = f"and it's dropping, down {-p3:.0f} millibars in 3 hours, so rain or a storm could be on the way"
            elif p3 <= -1:
                how = "and it's slowly dropping"
            elif p3 >= PRESSURE_DROP:
                how = f"and it's rising, up {p3:.0f} millibars in 3 hours. That usually means clearing skies"
            elif p3 >= 1:
                how = "and it's slowly rising"
            else:
                how = "and it's holding steady"
            parts.append(f"The air pressure {where} is {s['pressure_hpa']:.0f} millibars, "
                         f"about {inhg:.2f} inches, {how}.")
        elif not about_temp:
            parts.append("I'm not getting an air pressure reading right now.")
        temp, t1, t2 = s["temp_f"], s["temp_1h"], s["temp_2h"]
        if temp is not None and (about_temp or (t2 is not None and abs(t2) >= 5)):
            if t2 is None:
                parts.append(f"The greenhouse is {temp:.0f} degrees.")
            elif t2 <= -1:
                parts.append(f"The greenhouse is {temp:.0f} degrees, down {-t2:.0f} in the last 2 hours"
                             + (", cooling fast" if t1 is not None and t1 <= -2 else "") + ".")
            elif t2 >= 1:
                parts.append(f"The greenhouse is {temp:.0f} degrees, up {t2:.0f} in the last 2 hours.")
            else:
                parts.append(f"The greenhouse is holding steady at {temp:.0f} degrees.")
        elif about_temp:
            parts.append("I'm not getting the greenhouse temperature right now.")
        h3 = s["humidity_3h"]
        if h3 is not None and abs(h3) >= HUMID_RISE:
            parts.append(f"Humidity is {'up' if h3 > 0 else 'down'} {abs(h3):.0f} points in 3 hours.")
        return " ".join(parts)


def asked(prompt: str) -> bool:
    """'Is the pressure dropping?', 'barometer', 'weather trends', 'is it getting colder
    in the greenhouse?', 'is a storm coming?'"""
    p = (prompt or "").lower()
    if "blood pressure" in p:
        return False
    return bool(re.search(
        r"\b(air|barometric|atmospheric) pressure\b|\bbarometer\b|\bpressure (dropping|falling|rising|doing|trend)|"
        r"\bwhat'?s the pressure\b|\bis the pressure\b|\b(weather|temperature|pressure) trends?\b|"
        r"\b(is|are) (a |any )?storms? (coming|on the way|brewing)\b|"
        r"\bgetting (colder|warmer) in the greenhouse\b|\bgreenhouse (getting|cooling|warming) ", p))


def _face_notice(text: str) -> None:
    import face_link
    face_link.notice(text)


def _phone(text: str) -> None:
    import phone
    phone.send(text)


def _nws_pressure() -> Series:
    import weather_lookup
    return weather_lookup.get_pressure_history()


if __name__ == "__main__":
    import json
    w = Trends(notice=print, publish=None, state_file=STATE_FILE)
    print("Weather trends are", "on" if ENABLED else "off (CHATTY_TRENDS=0)")
    print("Readings kept:", {k: len(v) for k, v in w.series.items()})
    if not w.series["pressure"] and USE_NWS:
        try:
            w.nws_series = sorted(_nws_pressure())
            print("Weather station pressure readings:", len(w.nws_series))
        except Exception as e:
            print("Weather station:", repr(e))
    snap = w.snapshot()
    print("Now:", json.dumps(snap))
    print("Advisories:", {k: v[1] for k, v in w.advisories(snap).items()} or "none")
    print("Answer:", w.answer("is the pressure dropping"))
