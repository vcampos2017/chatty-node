import requests
import os
import json
import time
from datetime import datetime, UTC

RAIN_URL = "http://rain-node:5000/status"

IFTTT_KEY = os.getenv("IFTTT_KEY")
LOG_FILE = "logs/rain_log.jsonl"
LAST_TIP_COUNT = None


def fetch_rain():
    try:
        r = requests.get(RAIN_URL, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def log_data(data):
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "rain-node",
        "data": data
    }

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def main():
    print("Chatty rain logger started...")

    while True:
        data = fetch_rain()

        LAST_TIP_COUNT = None

while True:
    data = fetch_rain()

    if "error" not in data:
        rain_mm = data.get("rain_mm", 0)
        rate = data.get("rate_mm_hr", 0)
        tips = data.get("tip_count", 0)

        print(f"Rain: {rain_mm} mm, rate {rate} mm/hr")

        # 🌧️ Detect new rain (new tip)
        if LAST_TIP_COUNT is not None and tips > LAST_TIP_COUNT:
            print("🌧️ Rain detected (new tip)")

        # ⚠️ Detect heavy rain
        if rate > 20:
            print("⚠️ Heavy rain detected")

        LAST_TIP_COUNT = tips

    else:
        print(f"Error: {data['error']}")

    log_data(data)

    time.sleep(30)

if __name__ == "__main__":
    main()
