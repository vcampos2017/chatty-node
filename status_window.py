import json
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path

STATUS_FILE = Path("/home/pi/chatty-node/status.json")
REFRESH_MS = 2000


def load_status():
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception as e:
        return {"error": str(e)}


def truncate(text, max_len=28):
    if text is None:
        return "n/a"

    text = str(text)

    if len(text) <= max_len:
        return text

    return text[: max_len - 3] + "..."


def format_lightning_status(last_strike):
    if not last_strike:
        return "None", "n/a"

    try:
        strike_dt = datetime.fromisoformat(last_strike.replace("Z", "+00:00"))
        age_minutes = (datetime.now(timezone.utc) - strike_dt).total_seconds() / 60

        if age_minutes < 10:
            return "ACTIVE", last_strike
        elif age_minutes < 60:
            return "Recent", last_strike
        else:
            return "Old", last_strike

    except Exception:
        return "Unknown", last_strike


def format_freshness(updated_raw):
    if not updated_raw:
        return "n/a"

    try:
        updated_dt = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
        age_seconds = (datetime.now(timezone.utc) - updated_dt).total_seconds()

        if age_seconds < 15:
            return "LIVE"
        elif age_seconds < 60:
            return f"{int(age_seconds)}s ago"
        else:
            return f"{int(age_seconds / 60)}m ago"

    except Exception:
        return "n/a"



def format_ts(ts):
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%b %d %I:%M %p")
    except Exception:
        return ts

def refresh():
    data = load_status()

    if "error" in data:
        text = f"🌱 Chatty Status\n\nError reading status:\n{data['error']}"
    else:
        now_local = datetime.now().strftime("%H:%M:%S")
        updated_raw = data.get("updated", "n/a")
        freshness = format_freshness(updated_raw)

        lightning_status, last_strike = format_lightning_status(
            data.get("last_lightning_ts")
        )

        noaa = data.get("noaa") or {}
        noaa_forecast = truncate(noaa.get("shortForecast", "n/a"), 28)
        noaa_temp = noaa.get("temperature", "?")
        noaa_unit = noaa.get("temperatureUnit", "")

        text = (
            "🌱 Chatty Status\n\n"
            f"🕒 {now_local}   {freshness}\n\n"
            f"Node: {data.get('node', 'unknown')}\n"
            f"Soil Moisture: {data.get('soil_moisture', 'n/a')}%\n\n"
            f"⚡ Lightning: {lightning_status}\n"
            f"Last Strike: {format_ts(last_strike)}\n\n"
            f"🌤 NOAA: {noaa_forecast}, {noaa_temp}°{noaa_unit}\n\n"
            f"Updated:\n{format_ts(updated_raw)}"
        )

    label.config(text=text)
    root.after(REFRESH_MS, refresh)


root = tk.Tk()
root.title("Chatty Status")
root.geometry("760x420")
root.configure(bg="#101820")

label = tk.Label(
    root,
    text="Loading...",
    font=("DejaVu Sans Mono", 22),
    fg="#2ecc71",
    bg="#101820",
    justify="left",
    anchor="nw",
    padx=24,
    pady=24,
)

label.pack(fill="both", expand=True)

refresh()
root.mainloop()
