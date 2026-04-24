import json
import time
import os

STATUS_FILE = "/home/pi/chatty-node/status.json"

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

        print("\n----------------------")
        print(f"Updated: {data['updated']}")

    except Exception as e:
        print("Error reading status:", e)

    time.sleep(2)
