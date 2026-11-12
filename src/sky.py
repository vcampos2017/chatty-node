"""
Sky watch: Chatty notices the weather the other nodes feel.

The rain and lightning nodes post their readings on the node network (see
mesh.py). This turns those readings into things she shows and says:

  Rain (chatty/nodes/rain/data: rain_in, rate_mm_hr, tip_count)
    - It "is raining" while rate_mm_hr is above 0, or the bucket tipped in the
      last RAIN_QUIET_MINUTES. Her face gets soft blue raindrops falling behind
      her, and her falling-code doodle turns into blue rain.
    - When it starts, she says so once (daytime, while she's free), at most
      once every few hours.

  Lightning (chatty/nodes/lightning/data: last_strike {ts, distance_mi, ...})
    - A new strike flashes her screen and she counts "one Mississippi, two
      Mississippi..." for as long as thunder would take to reach her (about
      5 seconds a mile), then shows how far away it was.
    - The first strike of a storm is said out loud in the daytime ("I just saw
      lightning, about 6 miles away"); at night it's a notice on her screen.

Face messages (UDP, see chatty_face.py): `sky:rain`, `sky:dry`, `sky:strike:<miles>`.

Settings (in /etc/chatty/secrets.env):
    CHATTY_SKY=0                 turn this off
    CHATTY_SKY_SPEAK=0           show only, never say it out loud
    CHATTY_SKY_RAIN_NODE         default "rain"
    CHATTY_SKY_LIGHTNING_NODE    default "lightning"
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, List, Optional

try:
    import quiet_hours
except ImportError:  # running from another folder
    from . import quiet_hours  # type: ignore

ENABLED = os.getenv("CHATTY_SKY", "1") != "0"
SPEAK = os.getenv("CHATTY_SKY_SPEAK", "1") != "0"
RAIN_NODE = os.getenv("CHATTY_SKY_RAIN_NODE", "rain").strip() or "rain"
LIGHTNING_NODE = os.getenv("CHATTY_SKY_LIGHTNING_NODE", "lightning").strip() or "lightning"
RAIN_QUIET_MINUTES = 20        # no tips for this long (and rate 0): the rain stopped
RAIN_SAY_GAP = 3 * 3600        # say "it's raining" at most this often
STORM_GAP = 30 * 60            # a strike after this long without one starts a new storm
STRIKE_MAX_AGE = 180           # ignore strikes older than this (e.g. replayed after a restart)


def _miles(strike: dict) -> Optional[float]:
    mi = strike.get("distance_mi")
    if mi is None and strike.get("distance_km") is not None:
        try:
            mi = float(strike["distance_km"]) * 0.621371
        except (TypeError, ValueError):
            return None
    try:
        return None if mi is None else max(0.0, float(mi))
    except (TypeError, ValueError):
        return None


def _distance_words(mi: Optional[float]) -> str:
    if mi is None:
        return "too far away to tell how far"
    if mi < 1:
        return "less than a mile away"
    n = round(mi)
    return f"about {n} mile{'s' if n != 1 else ''} away"


class SkyWatch:
    """Feed it node readings with on_data(); it tells the face and queues things to say.
    No networking in here, so it's easy to test."""

    def __init__(self, face: Optional[Callable[[str], None]] = None,
                 notice: Optional[Callable[[str], None]] = None,
                 is_night: Callable[[float], bool] = quiet_hours.is_night,
                 on_wet: Optional[Callable[[float], None]] = None):
        self.face = face or _face_send
        self.on_wet = on_wet          # e.g. rain_hold.note_wet: remember when it last rained
        self.notice = notice or _face_notice
        self.is_night = is_night
        self.lock = threading.Lock()
        self.raining = False
        self.last_tips: Optional[int] = None
        self.last_tip_at = 0.0
        self.rain_said_at = -1e12
        self.last_strike_ts = None
        self.last_strike_at = -1e12   # when we last saw a new strike (our clock)
        self.pending: List[str] = []  # things to say once she's free

    # ----- input from the node network -----
    def on_data(self, name: str, body: dict, now: Optional[float] = None) -> None:
        if not ENABLED or not isinstance(body, dict):
            return
        now = time.time() if now is None else now
        try:
            if name == RAIN_NODE:
                self._rain(body, now)
            elif name == LIGHTNING_NODE:
                self._lightning(body, now)
        except Exception as e:   # a strange reading must never stop the voice node
            print("Sky watch: bad reading from", name, repr(e), flush=True)

    def _rain(self, d: dict, now: float) -> None:
        try:
            rate = float(d.get("rate_mm_hr") or 0)
        except (TypeError, ValueError):
            rate = 0.0
        try:
            tips = int(d.get("tip_count")) if d.get("tip_count") is not None else None
        except (TypeError, ValueError):
            tips = None
        with self.lock:
            if tips is not None:
                if self.last_tips is not None and tips > self.last_tips:
                    self.last_tip_at = now
                self.last_tips = tips
            wet = rate > 0 or now - self.last_tip_at < RAIN_QUIET_MINUTES * 60
            started = wet and not self.raining
            self.raining = wet
        # every reading (about once a minute), so a restarted face catches up
        self.face("sky:rain" if wet else "sky:dry")
        if wet and self.on_wet:
            try:
                self.on_wet(now)
            except Exception as e:
                print("Sky watch: couldn't note the rain:", repr(e), flush=True)
        if started:
            print("Sky watch: it's raining", flush=True)
            if now - self.rain_said_at > RAIN_SAY_GAP:
                self.rain_said_at = now
                if SPEAK and not self.is_night(now):
                    self._say("Looks like it's raining! The rain gauge just felt the first drops.")

    def _lightning(self, d: dict, now: float) -> None:
        strike = d.get("last_strike")
        if not isinstance(strike, dict) or strike.get("ts") is None:
            return
        try:
            ts = float(strike["ts"])
        except (TypeError, ValueError):
            return
        with self.lock:
            if ts == self.last_strike_ts:
                return                     # the same strike again (heartbeat repeat)
            self.last_strike_ts = ts
            if now - ts > STRIKE_MAX_AGE:
                return                     # old news, e.g. retained from earlier today
            new_storm = now - self.last_strike_at > STORM_GAP
            self.last_strike_at = now
        mi = _miles(strike)
        print(f"Sky watch: lightning, {_distance_words(mi)}", flush=True)
        self.face("sky:strike:" + ("" if mi is None else f"{mi:.1f}"))
        if not new_storm:
            return
        text = f"I just saw lightning, {_distance_words(mi)}."
        if mi is not None and mi < 8:
            text += " If you're outside, it's a good time to come in."
        if SPEAK and not self.is_night(now):
            self._say(text)
        else:
            self.notice(f"Lightning {_distance_words(mi)} ({time.strftime('%I:%M %p', time.localtime(now)).lstrip('0')})")

    def _say(self, text: str) -> None:
        with self.lock:
            if len(self.pending) < 3:
                self.pending.append(text)

    # ----- for the voice node's main loop -----
    def due(self, mode: str) -> Optional[str]:
        """Something to say now, only while she's free (asleep, waiting for 'Hey Chatty')."""
        if mode != "sleep":
            return None
        with self.lock:
            return self.pending.pop(0) if self.pending else None


def _face_send(msg: str) -> None:
    import face_link
    face_link.send(msg)


def _face_notice(text: str) -> None:
    import face_link
    face_link.notice(text)
