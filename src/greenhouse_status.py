"""
The greenhouse check that cron runs every 10 minutes on Chatty's Pi:
    */10 * * * * ~/chatty-wake-venv/bin/python3 ~/chatty-node/src/greenhouse_status.py

It reads the greenhouse node's /status, logs the reading (db.py), and sends an
IFTTT phone alert when the soil changes state (critically dry / moderate / good).
Read-only: it never sends the greenhouse a command. Until 2026-11-13 it sent
"water_on" / "water_off" to <node>/command, against the rule that other nodes are
read-only; that was removed.
"""
from datetime import datetime
import os
import requests

import settings  # reads /etc/chatty/secrets.env without python-dotenv

SECRETS = settings.SECRETS
# The cron job's venv (chatty-wake-venv) may not have python-dotenv: then
# CHATTY_GREENHOUSE_URL was never read and the check kept asking the greenhouse's
# old address. Settings already in the environment win.
_load_settings = settings.load


_load_settings()


from db import log_sensor, log_action, get_last_status

NODE_NAME = "greenhouse-1"
# Set CHATTY_GREENHOUSE_URL in /etc/chatty/secrets.env (shared with the face's pondering).
GREENHOUSE_STATUS_URL = os.getenv("CHATTY_GREENHOUSE_URL", "http://192.168.1.227:5000/status")
import soil as soil_mod  # how dry: the greenhouse's own label first
import phone  # the IFTTT phone buzz (needs IFTTT_KEY in /etc/chatty/secrets.env)


def send_alert(message: str):
    phone.send(message)


def fetch_greenhouse_metrics() -> tuple[float, float]:
    response = requests.get(GREENHOUSE_STATUS_URL, timeout=5)
    response.raise_for_status()
    data = response.json()

    soil_percent = float(data["metrics"]["soil_moisture_percent"])
    temp_f = float(data["metrics"]["air_temperature_f"])
    global _last_band
    _last_band = data["metrics"].get("soil_moisture_band")

    # A disconnected or unpowered probe usually reads 0%, which would look like
    # bone-dry soil. Treat it as "no data" instead of "thirsty".
    if not 0 < soil_percent <= 100:
        raise ValueError(f"no usable soil reading: {soil_percent}")
    return soil_percent, temp_f


_last_band = None     # the greenhouse's own label from the last reading


def classify_soil(soil: float, band=None) -> str:
    """The greenhouse node's own call (soil_moisture_band) when it sends one,
    else Chatty's old cut-offs (35% / 50%). See soil.py."""
    return {"dry": "critically dry", "okay": "moderate", "wet": "good"}[soil_mod.state(soil, band)]


def run_greenhouse_check() -> dict:
    try:
        soil, temp_f = fetch_greenhouse_metrics()
    except Exception as e:
        # Node offline or probe disconnected: say so, and don't alert on missing data.
        return {
            "node": NODE_NAME,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "soil": None,
            "temp_f": None,
            "status": "offline",
            "action": "none",
            "error": str(e),
            "message": "I can't get a reading from the greenhouse node right now, so I don't know how the soil is.",
        }

    status = classify_soil(soil, _last_band)
    previous_status = get_last_status()

    # Always log current reading
    log_sensor(NODE_NAME, soil, temp_f, status)

    action = "none"

    # Only alert if the state changed. Chatty never sends the greenhouse commands
    # (other nodes are read-only: no watering from here), she only tells you.
    if status != previous_status:
        if status == "critically dry":
            send_alert(f"⚠️ Greenhouse soil is dry ({soil:.0f}%). It may need water.")
        elif status == "good" and previous_status == "critically dry":
            send_alert(f"✅ Greenhouse soil is back to good ({soil:.0f}%).")
        else:
            send_alert(
                f"Greenhouse update: {previous_status} -> {status} "
                f"(Soil {soil:.0f}%, Temp {temp_f:.1f}F)"
            )

    return {
        "node": NODE_NAME,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "soil": soil,
        "temp_f": temp_f,
        "status": status,
        "action": action,
        "message": f"Soil: {soil:.0f}% | Temp: {temp_f:.1f} F | Status: {status} | Action: {action}",
    }


if __name__ == "__main__":
    result = run_greenhouse_check()
    print(result["message"])
