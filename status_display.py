import json
import time
import os
import requests

STATUS_FILE = "/home/pi/chatty-node/status.json"
RAIN_URL = os.getenv("RAIN_URL", "http://rain-node:5000/status")


def get_rain_status():
    try:
        response = requests.get(RAIN_URL, timeout=2)
        response.raise_for_status()
        data = response.json()
        return (
            f"🌧️ Rain: {float(data.get('rain_in', 0)):.3f} in "
            f"({float(data.get('rain_mm', 0)):.1f} mm)"
        )
    except Exception:
        return "🌧️ Rain: unavailable"

def clear():
    print("\033[2J\033[H", end="")

while True:
    clear()

    try:
        with open(STATUS_FILE) as f:
            data = json.load(f)

        print("🌱 Chatty Status\n")

        print(f"Node: {data['node']}")
        print(f"Soil Moisture: {data['soil_moisture']}%")

        if data["last_lightning_ts"]:
            print(f"⚡ Lightning: detected")
            print(f"Last Strike: {data['last_lightning_ts']}")
        else:
            print("⚡ Lightning: none")

        print(get_rain_status())

        print("\n----------------------")
        print(f"Updated: {data['updated']}")

    except Exception as e:
        print("Error reading status:", e)

    time.sleep(2)
