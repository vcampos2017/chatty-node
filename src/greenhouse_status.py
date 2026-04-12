from datetime import datetime
import requests


from db import log_sensor, log_action, get_last_status

NODE_NAME = "greenhouse-1"
GREENHOUSE_STATUS_URL = "http://192.168.1.227:5000/status"
GREENHOUSE_COMMAND_URL = "http://192.168.1.227:5000/command"
IFTTT_WEBHOOK_URL = "https://maker.ifttt.com/trigger/chatty_alert/with/key/fadGQ2jfX8LDoAx01ljWIEHyFkqCX5MI6T5oIsFi4nm"

def send_alert(message: str):
    try:
        requests.post(
            IFTTT_WEBHOOK_URL,
            json={"value1": message},
            timeout=5
        )
    except Exception:
        pass


def send_command(action: str) -> dict:
    response = requests.post(
        GREENHOUSE_COMMAND_URL,
        json={"action": action},
        timeout=5
    )
    response.raise_for_status()
    return response.json()


def fetch_greenhouse_metrics() -> tuple[float, float]:
    response = requests.get(GREENHOUSE_STATUS_URL, timeout=5)
    response.raise_for_status()
    data = response.json()

    soil_percent = float(data["metrics"]["soil_moisture_percent"])
    temp_f = float(data["metrics"]["air_temperature_f"])
    return soil_percent, temp_f


def classify_soil(soil: float) -> str:
    if soil < 35:
        return "critically dry"
    if soil < 50:
        return "moderate"
    return "good"


def run_greenhouse_check() -> dict:
    soil, temp_f = fetch_greenhouse_metrics()
    status = classify_soil(soil)
    previous_status = get_last_status()

    # Always log current reading
    log_sensor(NODE_NAME, soil, temp_f, status)

    action = "none"

    # Only act and alert if state changed
    if status != previous_status:
        if status == "critically dry":
            result = send_command("water_on")
            action = "watering_on"
            log_action(
                NODE_NAME,
                "watering",
                result.get("status", "ok"),
                result.get("message", "Water ON")
            )
            send_alert(f"⚠️ Soil critically dry — watering started. ({soil:.0f}%)")

        elif status == "good":
            result = send_command("water_off")
            action = "watering_off"
            log_action(
                NODE_NAME,
                "watering",
                result.get("status", "ok"),
                result.get("message", "Water OFF")
            )
            send_alert(f"✅ Soil recovered — watering stopped. ({soil:.0f}%)")

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
