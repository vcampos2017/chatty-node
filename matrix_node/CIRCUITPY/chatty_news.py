"""What the node network is saying, boiled down to little cards for a 64x32 panel.

The Matrix node listens (read-only, like every node) to:

    chatty/alerts/active          NWS alerts Chatty found (names and end times only)
    chatty/forecast/rain          her rain outlook for the next hours
    chatty/nodes/+/status         everyone's heartbeat: who is online
    chatty/nodes/rain/data        the rain gauge (rate_mm_hr, rain_in, tip_count)
    chatty/nodes/lightning/data   the lightning node (last_strike: ts, distance_mi)
    chatty/nodes/greenhouse/data  the greenhouse (air_temperature_f, soil_moisture_band)

and turns them into cards: a small picture plus up to three words of five letters
or less (the panel stands on its side, 32 pixels wide), or one line of scrolling
text for weather alerts. A Tornado Warning is not a card: tornado() says when the
whole panel should turn into a red TAKE SHELTER sign.

Old news is dropped: alerts after 30 minutes without an update from Chatty (she
checks every 3), the rain outlook after 90, readings after 30. Pure Python, no
hardware: tested on a computer.
"""
import json

RED = 0xFF0000
ORANGE = 0xFF6000
AMBER = 0xFFA000
YELLOW = 0xFFE040
GREEN = 0x00D040
BLUE = 0x2080FF
CYAN = 0x00C0FF
WHITE = 0xC0C0C0
PURPLE = 0xA040FF

ALERTS_STALE = 30 * 60
FORECAST_STALE = 90 * 60
READING_STALE = 30 * 60
RAIN_QUIET = 20 * 60        # no tips for this long (and rate 0): the rain stopped
STRIKE_FRESH = 3 * 60       # a strike newer than this flashes the panel
STRIKE_CARD = 30 * 60       # ...and gets a card for this long
NODE_QUIET = 3 * 60 + 30    # 3 missed heartbeats (plus a little) = quiet


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def soil_band(metrics):
    """'dry' / 'ok' / 'wet' / None from the greenhouse's own label, else its percent."""
    band = str(metrics.get("soil_moisture_band") or "").lower()
    for word, out in (("dry", "dry"), ("thirsty", "dry"), ("parched", "dry"), ("low", "dry"),
                      ("critical", "dry"), ("wet", "wet"), ("soak", "wet"), ("satur", "wet"),
                      ("ok", "ok"), ("moist", "ok"), ("good", "ok"), ("ideal", "ok")):
        if word in band:
            return out
    volts = _num(metrics.get("soil_voltage"))
    if volts is not None and volts < 0.05:
        return None                     # about 0 V: the probe is unplugged, not soaked
    pct = _num(metrics.get("soil_moisture_percent"))
    if pct is None:
        return None
    return "dry" if pct < 35 else ("ok" if pct < 50 else "wet")


def short_name(name):
    """'greenhouse' -> 'GRN', 'wordclock' -> 'CLOK': four letters (plus a '?') for the panel."""
    special = {"greenhouse": "GRN", "wordclock": "CLOK", "lightning": "ZAP",
               "chatty": "CHAT", "rain": "RAIN"}
    key = name.lower().replace("-node", "").replace("_node", "").replace("-", "")
    return special.get(key, key.upper()[:4])


def _card(icon, color, lines, seconds=5):
    return {"icon": icon, "color": color, "lines": [str(x)[:5] for x in lines][:3],
            "scroll": None, "seconds": seconds}


def _scroll(icon, color, text):
    return {"icon": icon, "color": color, "lines": [], "scroll": text.upper(), "seconds": 0}


def _is_tornado(alert):
    return "tornado warning" in str(alert.get("event", "")).lower()


class News:
    def __init__(self, me="matrix"):
        self.me = me
        self.alerts, self.alerts_ts, self.alerts_got = [], None, None
        self.forecast, self.forecast_got = None, None
        self.rain, self.rain_got = None, None
        self.last_tips, self.last_tip_at = None, None
        self.lightning, self.lightning_got = None, None
        self.strike_ts, self.strike_at, self.strike_miles = None, None, None
        self.greenhouse, self.greenhouse_got = None, None
        self.nodes = {}

    # ---------------------------------------------------------------- input

    def message(self, topic, text, utc, mono):
        """Take one MQTT message. Returns events for the screen: [("strike", miles)]."""
        try:
            body = json.loads(text) if text else {}
        except (ValueError, TypeError):
            return []
        if not isinstance(body, dict):
            return []
        if topic == "chatty/alerts/active":
            items = body.get("alerts") if isinstance(body.get("alerts"), list) else []
            self.alerts = [a for a in items if isinstance(a, dict)][:5]
            self.alerts_ts, self.alerts_got = _num(body.get("ts")), mono
            return []
        if topic == "chatty/forecast/rain":
            self.forecast, self.forecast_got = body, mono
            return []
        parts = topic.split("/")
        if len(parts) != 4 or parts[0] != "chatty" or parts[1] != "nodes":
            return []
        name, kind = parts[2], parts[3]
        if kind == "status":
            if name != self.me:
                state = str(body.get("state", "online")).lower()
                node = self.nodes.get(name) or {}
                node.update({"online": state != "offline", "got": mono,
                             "every": _num(body.get("every")) or 60})
                self.nodes[name] = node
            return []
        if kind != "data":
            return []
        if name == "rain":
            return self._rain(body, mono)
        if name == "lightning":
            return self._lightning(body, utc, mono)
        if name == "greenhouse":
            metrics = body.get("metrics") if isinstance(body.get("metrics"), dict) else body
            self.greenhouse, self.greenhouse_got = metrics, mono
        return []

    def _rain(self, body, mono):
        self.rain, self.rain_got = body, mono
        tips = _num(body.get("tip_count"))
        if tips is not None:
            if self.last_tips is not None and tips > self.last_tips:
                self.last_tip_at = mono
            self.last_tips = tips
        return []

    def _lightning(self, body, utc, mono):
        self.lightning, self.lightning_got = body, mono
        strike = body.get("last_strike")
        if not isinstance(strike, dict) or strike.get("ts") is None:
            return []
        ts = _num(strike.get("ts"))
        if ts is None or ts == self.strike_ts:
            return []
        first = self.strike_ts is None
        self.strike_ts = ts
        miles = _num(strike.get("distance_mi"))
        if miles is None and _num(strike.get("distance_km")) is not None:
            miles = _num(strike.get("distance_km")) / 1.609
        self.strike_miles = miles
        age = (utc - ts) if utc else None
        if age is not None and age > STRIKE_CARD:
            return []                       # an old one, replayed by the broker
        self.strike_at = mono - (age if age and age > 0 else 0)
        if age is None and first:
            return []                       # no clock yet: can't tell if it's new
        if age is None or age <= STRIKE_FRESH:
            return [("strike", miles)]
        return []

    # ---------------------------------------------------------------- reading

    def _fresh(self, got, mono, limit):
        return got is not None and mono - got <= limit

    def active_alerts(self, utc, mono):
        if not self._fresh(self.alerts_got, mono, ALERTS_STALE):
            return []
        if utc and self.alerts_ts and utc - self.alerts_ts > ALERTS_STALE:
            return []
        out = []
        for a in self.alerts:
            ends = _num(a.get("expires_ts"))
            if utc and ends and ends < utc:
                continue
            out.append(a)
        return out

    def tornado(self, utc, mono):
        """The Tornado Warning in effect (a dict with event / expires_ts), or None."""
        for a in self.active_alerts(utc, mono):
            if _is_tornado(a):
                return a
        return None

    def raining(self, mono):
        if not self._fresh(self.rain_got, mono, READING_STALE):
            return False
        rate = _num(self.rain.get("rate_mm_hr")) or 0
        recent = self.last_tip_at is not None and mono - self.last_tip_at < RAIN_QUIET
        return rate > 0 or recent

    def online(self, mono):
        """(online, total) of the other nodes heard from."""
        up = 0
        for node in self.nodes.values():
            late = mono - node["got"] > max(NODE_QUIET, 3.5 * node.get("every", 60))
            if node["online"] and not late:
                up += 1
        return up, len(self.nodes)

    def quiet_nodes(self, mono):
        out = []
        for name in sorted(self.nodes):
            node = self.nodes[name]
            if not node["online"] or mono - node["got"] > max(NODE_QUIET, 3.5 * node.get("every", 60)):
                out.append(name)
        return out

    def cards(self, utc, mono, local_hm):
        """The cards to show between moon screens, most important first.
        local_hm(utc) -> (hour, minute) in local time."""
        out = []
        for a in self.active_alerts(utc, mono):
            if _is_tornado(a):
                continue                       # that one takes over the whole panel
            kind = str(a.get("kind", "info"))
            color = ORANGE if kind == "urgent" else (AMBER if kind == "amber" else YELLOW)
            text = str(a.get("event", "Weather alert"))[:60]
            ends = _num(a.get("expires_ts"))
            if ends and utc:
                h, m = local_hm(int(ends))
                text += " til " + _hm(h, m)
            out.append(_scroll("warn", color, text))
        if self.strike_at is not None and mono - self.strike_at <= STRIKE_CARD:
            mins = int((mono - self.strike_at) // 60)
            miles = self.strike_miles
            where = (str(int(miles + 0.5)) + "mi") if miles is not None else "near"
            out.append(_card("bolt", YELLOW, [where, (str(mins) + "m" if mins else "now"),
                                               "ago" if mins else "!"]))
        if self.raining(mono):
            total = _num(self.rain.get("rain_in"))
            lines = ["RAIN", "NOW"]
            if total:
                lines.append("{:.2f}".format(total)[:4] + '"')
            out.append(_card("drop", BLUE, lines))
        elif self._fresh(self.forecast_got, mono, FORECAST_STALE) and self.forecast.get("rain_expected"):
            start = _num(self.forecast.get("starts_ts"))
            if not (utc and self.forecast.get("ts") and utc - _num(self.forecast.get("ts")) > FORECAST_STALE):
                kind = str(self.forecast.get("kind") or "rain").lower()
                word = {"storms": "STORM", "snow": "SNOW"}.get(kind, "RAIN")
                chance = _num(self.forecast.get("chance"))
                lines = [word, (str(int(chance)) + "%") if chance is not None else "SOON"]
                if start and utc and start > utc:
                    h, _ = local_hm(int(start))
                    lines.append(_short_hour(h))
                out.append(_card("cloud" if word != "SNOW" else "snow", CYAN, lines))
        if self._fresh(self.greenhouse_got, mono, READING_STALE):
            temp = _num(self.greenhouse.get("air_temperature_f"))
            band = soil_band(self.greenhouse)
            lines = []
            if temp is not None:
                lines.append(str(int(temp + 0.5)) + "F")
            if band:
                lines.append({"dry": "DRY", "ok": "OK", "wet": "WET"}[band])
            if lines:
                color = ORANGE if band == "dry" else GREEN
                out.append(_card("leaf", color, ["PLANT"] + lines if len(lines) < 3 else lines))
        up, total = self.online(mono)
        if total:
            lines = ["NODES", str(up) + "/" + str(total)]
            quiet = self.quiet_nodes(mono)
            if quiet:
                lines.append(short_name(quiet[0])[:4] + "?")
            out.append(_card("nodes", GREEN if not quiet else AMBER, lines))
        return out


def _hm(h, m):
    return str(h % 12 or 12) + (":" + "{:02d}".format(m) if m else "") + ("AM" if h < 12 else "PM")


def _short_hour(h):
    return str(h % 12 or 12) + ("A" if h < 12 else "P")
