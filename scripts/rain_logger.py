import requests
import json
import time
from datetime import datetime, UTC

RAIN_URL = "http://rain-node:5000/status"
LOG_FILE = "logs/rain_log.jsonl"


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

        if "error" not in data:
            print(f"Rain: {data['rain_mm']} mm, rate {data['rate_mm_hr']} mm/hr")
        else:
            print(f"Error: {data['error']}")

        log_data(data)

        time.sleep(30)  # every 30 seconds


if __name__ == "__main__":
    main()
