import os
import sqlite3
from datetime import datetime, UTC, timedelta
import time
import requests
import json
import subprocess
import urllib.request

def get_noaa_weather():
    try:
        lat = os.getenv("NOAA_LAT")
        lon = os.getenv("NOAA_LON")
        ua = os.getenv("NOAA_USER_AGENT")

        if not lat or not lon or not ua:
            return None

        headers = {"User-Agent": ua}

        # Step 1: get grid endpoint
        url = f"https://api.weather.gov/points/{lat},{lon}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.load(resp)

        forecast_url = data["properties"]["forecastHourly"]

        # Step 2: get hourly forecast
        req2 = urllib.request.Request(forecast_url, headers=headers)
        with urllib.request.urlopen(req2, timeout=5) as resp2:
            forecast = json.load(resp2)

        period = forecast["properties"]["periods"][0]

        return {
            "shortForecast": period["shortForecast"],
            "temperature": period["temperature"],
            "temperatureUnit": period["temperatureUnit"]
        }

    except Exception as e:
        print("NOAA error:", e)
        return None

def write_status(payload):
    try:
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"Status write error: {e}")

def get_last_lightning_ts():
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS chatty_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    row = c.execute(
        "SELECT value FROM chatty_state WHERE key = ?",
        ("last_lightning_ts",)
    ).fetchone()

    conn.close()
    return row[0] if row else None


def set_last_lightning_ts(ts):
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    c.execute("""
        INSERT OR REPLACE INTO chatty_state (key, value)
        VALUES (?, ?)
    """, ("last_lightning_ts", ts))

    conn.commit()
    conn.close()

def get_latest_lightning_event():
    try:
        result = subprocess.run(
            ["ssh", "pi@lightning-node", "tail -n 1 ~/Lightning-Node/lightning_telemetry.jsonl"],
            capture_output=True,
            text=True,
            timeout=5
        )


        line = result.stdout.strip()
        if not line:
            return None

        data = json.loads(line)

        if data.get("event") != "strike":
            print("DEBUG: Not a strike event")
            return None

        return {
            "node_id": data.get("node_id"),
            "distance_mi": data.get("distance_mi"),
            "energy": data.get("energy"),
            "ts": data.get("ts_iso")
        }

    except Exception as e:
        print(f"⚡ Lightning read error: {e}")
        return None

#Constants Start	

GREENHOUSE_URL = "http://greenhouse-pi.local:5000/status"  # adjust if needed

CHECK_INTERVAL = 30  # seconds
LAST_SUMMARY = None

STATUS_PATH = "/home/pi/chatty-node/status.json"

# Constants End

def get_latest_soil_moisture():
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    row = c.execute("""
        SELECT moisture_percent
        FROM soil_readings
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    conn.close()

    return row[0] if row else None

def send_ifttt_alert(message):
    key = os.getenv("IFTTT_KEY")
    url = f"https://maker.ifttt.com/trigger/chatty_alert/with/key/{key}"

    try:
        requests.post(url, json={"value1": message}, timeout=5)
        print("📡 IFTTT alert sent")
    except Exception as e:
        print(f"IFTTT error: {e}")


def init_db():
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS soil_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            moisture_percent INTEGER
        )
    """)

    conn.commit()
    conn.close()

def init_event_table():
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            event_type TEXT,
            description TEXT
        )
    """)

    conn.commit()
    conn.close()

def log_event(event_type, description):
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    c.execute(
        "INSERT INTO events (timestamp, event_type, description) VALUES (?, ?, ?)",
        (datetime.now(UTC).isoformat(), event_type, description)
    )

    conn.commit()
    conn.close()

def log_soil(moisture):
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    c.execute(
        "INSERT INTO soil_readings (timestamp, moisture_percent) VALUES (?, ?)",
        (datetime.now(UTC).isoformat(), moisture)
    )

    conn.commit()
    conn.close()

def get_last_summary():
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS chatty_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    row = c.execute(
        "SELECT value FROM chatty_state WHERE key = ?",
        ("last_summary",)
    ).fetchone()

    conn.commit()
    conn.close()

    return row[0] if row else None

def set_last_summary(summary):
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS chatty_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    c.execute(
        "INSERT OR REPLACE INTO chatty_state (key, value) VALUES (?, ?)",
        ("last_summary", summary)
    )

    conn.commit()
    conn.close()

def get_last_soil_status():
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS chatty_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    row = c.execute(
        "SELECT value FROM chatty_state WHERE key = ?",
        ("last_soil_status",)
    ).fetchone()

    conn.commit()
    conn.close()

    return row[0] if row else None

def set_last_soil_status(status):
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS chatty_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    c.execute(
        "INSERT OR REPLACE INTO chatty_state (key, value) VALUES (?, ?)",
        ("last_soil_status", status)
    )

    conn.commit()
    conn.close()

def get_moisture_trend():
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    rows = c.execute("""
        SELECT moisture_percent
        FROM soil_readings
        ORDER BY id DESC
        LIMIT 3
    """).fetchall()

    conn.close()

    values = [row[0] for row in rows]

    if len(values) < 3:
        return "insufficient data"

    newest, previous, oldest = values[0], values[1], values[2]

    delta = newest - oldest

    if delta >= 3:
        return "getting wetter"
    elif delta <= -3:
        return "drying"
    else:
        return "stable"

def trend_summary(trend):
    if trend == "getting wetter":
        return "Soil moisture has increased over the last few readings."
    elif trend == "drying":
        return "Soil moisture has decreased over the last few readings."
    elif trend == "stable":
        return "Soil moisture has stayed steady over the last few readings."
    else:
        return "Not enough data yet to determine a moisture trend."

def check_greenhouse():
    try:
        r = requests.get(GREENHOUSE_URL, timeout=5)
        data = r.json()

        soil = data.get("metrics", {}).get("soil_moisture_percent")

        if soil is None:
            print("No soil data")
            return

        print(f"Soil moisture: {soil}%")
        log_soil(soil)
        trend = get_moisture_trend()

        summary = trend_summary(trend)
        last_summary = get_last_summary()

        if summary != last_summary:
            print(f"📝 Chatty Summary: {summary}")
            set_last_summary(summary)

        if soil < 35:
            soil_status = "critical"
            status_message = "🌱 Chatty: Soil is critically dry — recommend watering."
        elif soil < 50:
            soil_status = "dry"
            status_message = "🌱 Chatty: Soil is getting dry."
        else:
            soil_status = "good"
            status_message = "🌱 Chatty: Soil moisture is good."

        last_soil_status = get_last_soil_status()

        # Only log event if we have a real previous value
        if last_soil_status is not None and soil_status != last_soil_status:
            log_event("soil_status_changed", f"Soil status changed from {last_soil_status} to {soil_status}")
            print(f"⚡ Event: Soil status changed from {last_soil_status} to {soil_status}")

        # ALERT TRIGGERS
        if soil_status == "dry":
            print("🚨 ALERT: Soil is getting dry — consider watering soon.")
            if alert_allowed():
                send_ifttt_alert("Soil is getting dry — consider watering soon.")
                set_last_alert_time(datetime.now(UTC))
            else:
                print("⏳ Alert suppressed by cooldown.")
        elif soil_status == "critical":
            print("🚨 ALERT: Soil is critically dry — watering recommended immediately!")
            if alert_allowed():
                send_ifttt_alert("Soil is critically dry — watering recommended immediately!")
                set_last_alert_time(datetime.now(UTC))
            else:
                print("⏳ Alert suppressed by cooldown.")

        # Always persist current state (critical fix)
        set_last_soil_status(soil_status)

        print(status_message)

    except Exception as e:
        print(f"Error checking greenhouse: {e}")

def get_last_alert_time():
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS chatty_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    row = c.execute(
        "SELECT value FROM chatty_state WHERE key = ?",
        ("last_alert_time",)
    ).fetchone()

    conn.commit()
    conn.close()

    if row and row[0]:
        return datetime.fromisoformat(row[0])

    return None


def set_last_alert_time(ts):
    conn = sqlite3.connect("/home/pi/chatty-node/chatty.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS chatty_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    c.execute(
        "INSERT OR REPLACE INTO chatty_state (key, value) VALUES (?, ?)",
        ("last_alert_time", ts.isoformat())
    )

    conn.commit()
    conn.close()


def alert_allowed(cooldown_minutes=60):
    last_alert = get_last_alert_time()

    if last_alert is None:
        return True

    return datetime.now(UTC) - last_alert >= timedelta(minutes=cooldown_minutes)

def main_loop():
    print("Chatty Core Loop started")
    init_db()
    init_event_table()

    # Ensure soil status is initialized once
    if get_last_soil_status() is None:
        print("🔧 Initializing soil status state")

    while True:
        check_greenhouse()

        lightning = get_latest_lightning_event()

        if lightning:
            last_ts = get_last_lightning_ts()
            current_ts = lightning["ts"]

            if last_ts != current_ts:
                print(f"⚡ NEW Lightning: {lightning}")
                log_event("lightning_strike", f"Lightning at {lightning['distance_mi']} mi")
                send_ifttt_alert(f"⚡ Lightning detected {lightning['distance_mi']} miles away!")
                set_last_lightning_ts(current_ts)
            else:
                print("⏳ Duplicate lightning event ignored")

        noaa = get_noaa_weather()

        write_status({
            "node": "chatty-node",
            "soil_moisture": get_latest_soil_moisture(),
            "last_lightning_ts": get_last_lightning_ts(),
            "noaa": noaa,
            "updated": datetime.now(UTC).isoformat()
        })

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main_loop()

