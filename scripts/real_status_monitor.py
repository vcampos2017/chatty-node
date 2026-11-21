"""
The soil monitor the chatty-soil-monitor.timer runs every 5 minutes on Chatty's Pi
(`python3 -m scripts.real_status_monitor` from ~/chatty-node). It reads the
greenhouse node's own soil_moisture_band, logs it (src/db.py), and when the soil
turns dry Chatty says so in her own voice; at night it is only a notice on her face.
(Until 2026-11-13 it spoke with espeak at any hour.)
"""
from src.db import init_db, log_sensor, log_action, get_last_status
from src.event_bus import EventBus
import json
import os
import socket
import urllib.request

from src import settings, quiet_hours, face_link

settings.load()   # night hours (CHATTY_NIGHT_*), the greenhouse address

GREENHOUSE_STATUS_URL = os.getenv("CHATTY_GREENHOUSE_URL", "http://greenhouse-pi:5000/status")
VOICE_ADDR = ("127.0.0.1", int(os.getenv("CHATTY_VOICE_PORT", "47475")))
DRY_TEXT = "The greenhouse soil is dry. The plants could use some water."


def tell_her(text):
    """Have Chatty say it in her own voice (the voice node speaks 'notify:'
    messages once she's free), and put it on her face as a notice. At night
    (quiet_hours: 10 pm to 7 am by default) it is only the notice: no sound.
    Returns "said" or "notice"."""
    face_link.notice(text)
    if quiet_hours.is_night():
        return "notice"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(f"notify:{text}".encode("utf-8"), VOICE_ADDR)
    except OSError:
        pass        # voice node not running: the notice is still on her face
    return "said"

def fetch_current_metrics():
    try:
        with urllib.request.urlopen(GREENHOUSE_STATUS_URL, timeout=5) as response:
            data = json.loads(response.read().decode())

        metrics = data.get("metrics", {})

        return {
            "status": metrics.get("soil_moisture_band", "unknown"),
            "soil_moisture": metrics.get("soil_moisture_percent"),
            "temperature": metrics.get("air_temperature_f"),
            "online": True,
            "error": None,
        }

    except Exception as exc:
        print(f"[ERROR] Could not reach greenhouse node: {exc}")

        return {
            "status": "offline",
            "soil_moisture": None,
            "temperature": None,
            "online": False,
            "error": str(exc),
        }

def handle_soil_status_changed(payload):
    node = payload.get("node", "greenhouse-node")
    soil = payload.get("soil_moisture")
    temp = payload.get("temperature")
    status = payload.get("status", "unknown")

    print(f"[EVENT] Soil status changed on {node}: {status}")
        
    if status == "dry":
        print(f"[ALERT] {tell_her(DRY_TEXT)}: {DRY_TEXT}")

    log_sensor(
        node=node,
        soil=soil,
        temp=temp,
        status=status,
    )

    online = payload.get("online")
    error = payload.get("error")

    if online is False:
        action_notes = f"greenhouse-node offline: {error}"
    elif status == "offline":
        action_notes = "greenhouse-node offline"
    else:
        action_notes = (
            f"greenhouse-node status: {status}; "
            f"soil_moisture={soil}%; "
            f"temperature={temp}°F"
        )

    log_action(
        node=node,
        action="soil.status.changed",
        result="event_emitted",
        notes=action_notes,
    )


def main():
    init_db()

    previous_status = get_last_status(offset=0)

    print(f"[STATE] Previous: {previous_status}")
    current_metrics = fetch_current_metrics()
    current_status = current_metrics["status"]
    print(f"[STATE] Current: {current_status}")
    print(f"[LIVE] Soil moisture: {current_metrics['soil_moisture']}%")
    print(f"[LIVE] Air temperature: {current_metrics['temperature']}°F")

    bus = EventBus()
    bus.subscribe("soil.status.changed", handle_soil_status_changed)

    if previous_status != current_status:
        errors = bus.publish(
            "soil.status.changed",
            {
                "node": "greenhouse-node",
                "soil_moisture": current_metrics["soil_moisture"],
                "temperature": current_metrics["temperature"],
                "status": current_status,
                "online": current_metrics["online"],
                "error": current_metrics["error"],
            },
        )

        if errors:
            print(f"[ERROR] {len(errors)} handler error(s): {errors}")
            raise SystemExit(1)

    else:
        print("[STATE] No status change detected")


if __name__ == "__main__":
    main()
