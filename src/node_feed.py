"""
Node feed: small news Chatty posts for the display nodes that can't fetch it themselves.

The Matrix node (an Adafruit Matrix Portal M4, vcampos2017/matrix-node) has very little
memory: loading a web library for HTTPS leaves it too little to talk MQTT. So Chatty
does the web part on the Pi and posts the answers on her MQTT board:

    chatty/tides   (retained, every CHATTY_TIDE_EVERY hours, default 6)
                   {"station": "1234567", "units": "english",
                    "events": [[1763520780, 1.91, "H"], [1763544060, 0.40, "L"], ...],
                    "ts": 1763500000, "source": "NOAA CO-OPS"}
                   three days of high (H) and low (L) tides from yesterday on, from NOAA's
                   free tides service (https://api.tidesandcurrents.noaa.gov, no key).
                   Heights in feet ("english") or meters ("metric"), times UTC epoch.

    chatty/clock   (not retained, every minute) {"ts": 1763500000}
                   the time, for a node whose WiFi chip can't reach a time server.

Only the station number is sent to NOAA (never her location). News only: nothing here
is a command.

Settings (in /etc/chatty/secrets.env):
    CHATTY_TIDE_STATION=1234567   NOAA station number (tidesandcurrents.noaa.gov). Empty: no tides.
    CHATTY_TIDE_UNITS=english     or metric
    CHATTY_TIDE_EVERY=6           hours between tide fetches (a failed one is retried in 15 min)
    CHATTY_NODE_CLOCK=0           don't post chatty/clock

Try it on the Pi:  python3 src/node_feed.py   (prints the tides it would post)
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
STATION = "".join(ch for ch in os.environ.get("CHATTY_TIDE_STATION", "") if ch.isalnum())[:12]
UNITS = "metric" if os.environ.get("CHATTY_TIDE_UNITS", "").lower() == "metric" else "english"
CLOCK = os.environ.get("CHATTY_NODE_CLOCK", "1") != "0"
RETRY = 15 * 60
try:
    EVERY = max(1.0, min(float(os.environ.get("CHATTY_TIDE_EVERY", "6")), 24.0)) * 3600
except ValueError:
    EVERY = 6 * 3600


def url(station: str, now: float, units: str = UNITS) -> str:
    start = datetime.fromtimestamp(now, timezone.utc) - timedelta(days=1)
    return (f"{API}?product=predictions&application=chatty_node_feed"
            f"&begin_date={start:%Y%m%d}&range=72&datum=MLLW&station={station}"
            f"&time_zone=gmt&units={units}&interval=hilo&format=json")


def parse(body) -> List[list]:
    """NOAA's answer -> [[utc, height, "H"|"L"], ...] oldest first ([] for an error)."""
    if not isinstance(body, dict) or not isinstance(body.get("predictions"), list):
        return []
    out = []
    for item in body["predictions"]:
        try:
            when = datetime.strptime(str(item["t"]), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            kind = str(item.get("type", "")).upper()[:1]
            if kind in ("H", "L"):
                out.append([int(when.timestamp()), round(float(item["v"]), 2), kind])
        except (KeyError, ValueError, TypeError):
            continue
    out.sort()
    return out[:16]


def _fetch(address: str) -> dict:
    req = urllib.request.Request(address, headers={"User-Agent": "chatty-node (tides)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Feed:
    def __init__(self, publish: Callable[..., bool], station: str = STATION,
                 fetch: Callable[[str], dict] = _fetch, clock: Callable[[], float] = time.time):
        self.publish, self.station, self.fetch, self.clock = publish, station, fetch, clock
        self.next_tides = 0.0
        self.events: List[list] = []

    def tides_once(self, now: Optional[float] = None) -> bool:
        now = self.clock() if now is None else now
        try:
            events = parse(self.fetch(url(self.station, now)))
        except Exception as e:
            print("Node feed: no tides this time:", repr(e), flush=True)
            events = []
        if not events:
            self.next_tides = now + RETRY
            return False
        self.events = events
        ok = self.publish("chatty/tides", {"station": self.station, "units": UNITS,
                                           "events": events, "ts": int(now),
                                           "source": "NOAA CO-OPS"})
        self.next_tides = now + (EVERY if ok else RETRY)
        return ok

    def step(self, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        if CLOCK:
            self.publish("chatty/clock", {"ts": int(now)}, retain=False)
        if self.station and now >= self.next_tides:
            self.tides_once(now)

    def run_forever(self) -> None:
        time.sleep(20)          # give the node network a moment to connect
        while True:
            try:
                self.step()
            except Exception as e:
                print("Node feed:", repr(e), flush=True)
            time.sleep(60)

    def start(self) -> None:
        if self.station or CLOCK:
            threading.Thread(target=self.run_forever, daemon=True, name="node-feed").start()


if __name__ == "__main__":
    if not STATION:
        print("Set CHATTY_TIDE_STATION in /etc/chatty/secrets.env first.")
    else:
        rows = parse(_fetch(url(STATION, time.time())))
        for ts, height, kind in rows:
            print(datetime.fromtimestamp(ts).strftime("%a %I:%M %p"), "HIGH" if kind == "H" else "LOW ",
                  height, "ft" if UNITS == "english" else "m")
        print(len(rows), "tides")
