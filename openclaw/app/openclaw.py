#!/usr/bin/env python3
import os, json, urllib.request, urllib.error, shutil
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8081

RELAY_URL = os.getenv("CHATTY_RELAY_URL", "http://127.0.0.1:8000/chat")
CHATTY_TOKEN = os.getenv("CHATTY_TOKEN")

DATA_DIR = Path("/opt/openclaw/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_FILE = DATA_DIR / "memory.json"

STATS_FILE = DATA_DIR / "stats.json"

def load_stats():
    try:
        if STATS_FILE.exists():
            return json.loads(STATS_FILE.read_text())
    except Exception:
        pass
    return {"local": 0, "relay": 0}

def save_stats(stats: dict):
    STATS_FILE.write_text(json.dumps(stats, indent=2))

def inc_stat(which: str):
    stats = load_stats()
    stats[which] = int(stats.get(which, 0)) + 1
    stats[f"last_{which}_iso"] = datetime.now().isoformat(timespec="seconds")
    save_stats(stats)


class ReuseHTTPServer(HTTPServer):
    allow_reuse_address = True

def now_payload():
    dt = datetime.now()
    return {
        "iso": dt.isoformat(timespec="seconds"),
        "pretty": dt.strftime("%a, %b %d, %Y %I:%M %p"),
    }

def load_memory():
    if MEMORY_FILE.exists():
        return json.loads(MEMORY_FILE.read_text())
    return []

def save_memory(data):
    MEMORY_FILE.write_text(json.dumps(data, indent=2))

def relay_chat(text: str) -> dict:
    if not CHATTY_TOKEN:
        return {"reply": "Server misconfigured: CHATTY_TOKEN missing"}

    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        RELAY_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Chatty-Token": CHATTY_TOKEN,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return {"reply": "Relay error", "detail": repr(e)}


def fetch_weather(loc: str) -> dict:
    """
    Fetch current + today's forecast via Open-Meteo.
    Returns: {source, location, query, current, today} or {error, ...}
    """
    from urllib.parse import quote
    try:
        # Geocode
        def geocode(name: str) -> dict:
            url = "https://geocoding-api.open-meteo.com/v1/search?count=10&name=" + quote(name)
            with urllib.request.urlopen(url, timeout=10) as r:
                return json.loads(r.read().decode())

        loc = (loc or "").strip()
        if not loc:
            return {"error": "location required"}

        geo = geocode(loc)

        # fallback: if "City, ST" fails, try city-only
        if not geo.get("results") and "," in loc:
            city_only = loc.split(",")[0].strip()
            if city_only:
                geo = geocode(city_only)

        if not geo.get("results"):
            return {"error": "location not found", "query": loc}

        results = geo["results"]

        # prefer US, then Texas, else first result
        preferred = None
        for r0 in results:
            if r0.get("country_code") == "US":
                preferred = r0
                if (r0.get("admin1") or "").lower() == "texas":
                    break
        g = preferred or results[0]

        lat = g["latitude"]
        lon = g["longitude"]
        resolved = f"{g.get('name','')}, {g.get('admin1','')}, {g.get('country','')}"

        # Forecast
        wx_url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            "&current_weather=true&temperature_unit=fahrenheit&timezone=auto"
        )
        with urllib.request.urlopen(wx_url, timeout=10) as r:
            wx = json.loads(r.read().decode())

        return {
            "source": "open-meteo",
            "location": resolved,
            "query": loc,
            "current": wx.get("current_weather", {}),
            "today": {
                "high_f": wx["daily"]["temperature_2m_max"][0],
                "low_f": wx["daily"]["temperature_2m_min"][0],
                "precip_chance_pct": wx["daily"]["precipitation_probability_max"][0],
            },
        }
    except Exception as e:
        return {"error": "weather fetch failed", "detail": str(e), "query": loc}

def local_command(text: str):
    t = (text or "").strip()
    low = t.lower()

    # memory
    if low.startswith("/remember "):
        entry = t[10:].strip()
        mem = load_memory()
        mem.append({"time": now_payload()["iso"], "text": entry})
        save_memory(mem)
        return {"reply": f"Stored memory ({len(mem)} items total).", "_served_by": "openclaw-local"}

    if low in ("/recall", "recall"):
        return {"reply": load_memory(), "_served_by": "openclaw-local"}

    if low in ("/clear", "clear"):
        save_memory([])
        return {"reply": "Memory cleared.", "_served_by": "openclaw-local"}

    # metrics
    if low in ("/metrics", "metrics", "system status"):
        try:
            load1, load5, load15 = os.getloadavg()
        except Exception:
            load1 = load5 = load15 = None
        disk = shutil.disk_usage("/")
        return {
            "reply": "System metrics",
            "load_avg": {"1m": load1, "5m": load5, "15m": load15},
            "disk": {
                "total_gb": round(disk.total / 1e9, 2),
                "used_gb": round(disk.used / 1e9, 2),
            },
            "time": now_payload(),
        }

    if low in ("/time", "time"):
        return {"reply": now_payload()["pretty"], "time": now_payload(), "_served_by": "openclaw-local"}


    # weather (local shortcut)
    if low.startswith("/weather"):
        loc = t[len("/weather"):].strip()
        if not loc:
            loc = os.getenv("CHATTY_DEFAULT_LOC", "")
        wx = fetch_weather(loc)
        if wx.get("error"):
            return {"reply": f"I couldn't get weather for {loc}: {wx.get('error')}", "weather": wx}
        cur = wx.get("current", {})
        today = wx.get("today", {})
        reply = (
            f"Weather for {wx.get('location', loc)}: "
            f"currently {cur.get('temperature')}°F, wind {cur.get('windspeed')} mph. "
            f"Today: high {today.get('high_f')}°F / low {today.get('low_f')}°F, "
            f"precip chance {today.get('precip_chance_pct')}%."
        )
        return {"reply": reply, "weather": wx, "_served_by": "openclaw-local"}

    # natural language trigger: contains 'weather'
    if "weather" in low:
        loc = os.getenv("CHATTY_DEFAULT_LOC", "")
        if " in " in low:
            loc = t.split(" in ", 1)[1].strip(" ?.")
        if not loc:
            loc = "San Antonio, TX"
        wx = fetch_weather(loc)
        if wx.get("error"):
            return {"reply": f"I couldn't get weather for {loc}: {wx.get('error')}", "weather": wx}
        cur = wx.get("current", {})
        today = wx.get("today", {})
        reply = (
            f"Weather for {wx.get('location', loc)}: "
            f"currently {cur.get('temperature')}°F, wind {cur.get('windspeed')} mph. "
            f"Today: high {today.get('high_f')}°F / low {today.get('low_f')}°F, "
            f"precip chance {today.get('precip_chance_pct')}%."
        )
        return {"reply": reply, "weather": wx, "_served_by": "openclaw-local"}

    if low.startswith("ping"):
        return {"reply": "pong (local)", "_served_by": "openclaw-local"}

    return None

class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict):
        b = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok", "relay": RELAY_URL})
            return


        if self.path.startswith("/weather"):
            try:
                from urllib.parse import urlparse, parse_qs, quote
                import urllib.request, json

                qs = parse_qs(urlparse(self.path).query)
                loc = qs.get("loc", [os.getenv("CHATTY_DEFAULT_LOC", "")])[0].strip()

                if not loc:
                    self._json(400, {"error": "location required", "hint": "use ?loc=San%20Antonio%2C%20TX"})
                    return

                def geocode(name: str):
                    url = "https://geocoding-api.open-meteo.com/v1/search?count=10&name=" + quote(name)
                    with urllib.request.urlopen(url, timeout=10) as r:
                        return json.loads(r.read().decode())

                geo = geocode(loc)

                # fallback: if "City, ST" fails, try city-only
                if not geo.get("results") and "," in loc:
                    city_only = loc.split(",")[0].strip()
                    if city_only:
                        geo = geocode(city_only)

                if not geo.get("results"):
                    self._json(404, {"error": "location not found", "query": loc})
                    return

                results = geo["results"]

                # prefer US, then Texas, else first result
                preferred = None
                for r0 in results:
                    if r0.get("country_code") == "US":
                        preferred = r0
                        if (r0.get("admin1") or "").lower() == "texas":
                            break
                g = preferred or results[0]

                lat = g["latitude"]
                lon = g["longitude"]
                resolved = f"{g.get('name','')}, {g.get('admin1','')}, {g.get('country','')}"

                wx_url = (
                    "https://api.open-meteo.com/v1/forecast"
                    f"?latitude={lat}&longitude={lon}"
                    "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
                    "&current_weather=true&temperature_unit=fahrenheit&timezone=auto"
                )

                with urllib.request.urlopen(wx_url, timeout=10) as r:
                    wx = json.loads(r.read().decode())

                self._json(200, {
                    "_served_by": "openclaw-local",
                    "source": "open-meteo",
                    "location": resolved,
                    "query": loc,
                    "current": wx.get("current_weather", {}),
                    "today": {
                        "high_f": wx["daily"]["temperature_2m_max"][0],
                        "low_f": wx["daily"]["temperature_2m_min"][0],
                        "precip_chance_pct": wx["daily"]["precipitation_probability_max"][0]
                    }
                })
            except Exception as e:
                self._json(502, {"error": "weather fetch failed", "detail": str(e)})
            return

        if self.path == "/whoami":
            self._json(200, {
                "service": "openclaw",
                "bind": f"{HOST}:{PORT}",
                "relay": RELAY_URL,
                "has_chatty_token": bool(CHATTY_TOKEN),
                "user": os.getenv("USER") or "openclaw",
                "uid": os.getuid(),
                "gid": os.getgid(),
            })
            return

        if self.path == "/stats":

            self._json(200, load_stats())

            return


        self._json(404, {"error": "not found"})
    def do_POST(self):
        if self.path != "/chat":
            self._json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body or b"{}")
        except Exception:
            data = {}

        text = (data.get("text") or "").strip()

        local = local_command(text)
        if local is not None:
            inc_stat("local")
            self._json(200, local)
            return

        inc_stat("relay")


        rel = relay_chat(text)
        reply = rel.get("reply") if isinstance(rel, dict) else None
        self._json(200, {"reply": reply or "No reply", "relay_raw": rel, "_served_by": "openclaw->relay"})

if __name__ == "__main__":
    server = ReuseHTTPServer((HOST, PORT), Handler)
    server.serve_forever()
