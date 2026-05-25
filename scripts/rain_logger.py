import time
import requests
import os
from datetime import datetime

RAIN_URL = "http://rain-node:5000/status"

IFTTT_KEY = os.getenv("IFTTT_KEY")

LAST_TIP_COUNT = None
IS_RAINING = False
LAST_RAIN_TIME = 0
RAIN_TIMEOUT = 300  # 5 minutes


def send_ifttt():
    if not IFTTT_KEY:
        return

    url = f"https://maker.ifttt.com/trigger/rain_detected/with/key/{IFTTT_KEY}"

    try:
        requests.post(url, timeout=5)
    except Exception as e:
        print(f"IFTTT error: {e}")


print("Chatty rain logger started...")

while True:
    try:
        response = requests.get(RAIN_URL, timeout=5)
        data = response.json()

        rain_mm = float(data["rain_mm"])
        rate = float(data["rate_mm_hr"])
        tips = int(data["tip_count"])

        print(f"Rain: {rain_mm:.4f} mm, rate {rate:.2f} mm/hr")

        now = time.time()

        # First run initialization
        if LAST_TIP_COUNT is None:
            LAST_TIP_COUNT = tips
            LAST_RAIN_TIME = now

        # New tip detected
        elif tips > LAST_TIP_COUNT:
            LAST_RAIN_TIME = now

            if not IS_RAINING:
                print("🌧️ Rain started")
                send_ifttt()
                IS_RAINING = True
            else:
                print("🌧️ Rain continuing")

        # Rain stopped after timeout
        elif IS_RAINING and (now - LAST_RAIN_TIME > RAIN_TIMEOUT):
            print("☀️ Rain stopped")
            IS_RAINING = False

        LAST_TIP_COUNT = tips

    except Exception as e:
        print(f"Error: {e}")

    time.sleep(30)
