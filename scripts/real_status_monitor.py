from src.db import init_db, log_sensor, log_action, get_last_status
from src.event_bus import EventBus
import json
import urllib.request

GREENHOUSE_STATUS_URL = "http://greenhouse-pi:5000/status"

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
