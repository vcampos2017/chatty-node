import sqlite3
from datetime import datetime, UTC
import time
import requests

GREENHOUSE_URL = "http://greenhouse-pi.local:5000/status"  # adjust if needed

CHECK_INTERVAL = 30  # seconds
LAST_SUMMARY = None

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
            print("🌱 Chatty: Soil is critically dry — recommend watering.")
        elif soil < 50:
            print("🌱 Chatty: Soil is getting dry.")
        else:
            print("🌱 Chatty: Soil moisture is good.")

    except Exception as e:
        print(f"Error checking greenhouse: {e}")


def main_loop():
    print("Chatty Core Loop started")
    init_db()

    while True:
        check_greenhouse()
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main_loop()
