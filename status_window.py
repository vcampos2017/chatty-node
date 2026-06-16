import json
import os
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path

import requests

STATUS_FILE = Path("/home/pi/chatty-node/status.json")
RAIN_URL = os.getenv("RAIN_URL", "http://rain-node:5000/status")
REFRESH_MS = 2000


def load_status():
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception as e:
        return {"error": str(e)}


def truncate(text, max_len=24):
    if text is None:
        return "n/a"
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def format_ts(ts):
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.strftime("%b %d %I:%M %p")
    except Exception:
        return str(ts) if ts else "n/a"


def format_freshness(updated_raw):
    if not updated_raw:
        return "n/a"

    try:
        updated_dt = datetime.fromisoformat(str(updated_raw).replace("Z", "+00:00"))
        age_seconds = (datetime.now(timezone.utc) - updated_dt).total_seconds()

        if age_seconds < 15:
            return "LIVE"
        if age_seconds < 60:
            return f"{int(age_seconds)}s ago"
        return f"{int(age_seconds / 60)}m ago"

    except Exception:
        return "n/a"


def format_lightning_status(last_strike):
    if not last_strike:
        return "None", "n/a"

    try:
        strike_dt = datetime.fromisoformat(str(last_strike).replace("Z", "+00:00"))
        age_minutes = (datetime.now(timezone.utc) - strike_dt).total_seconds() / 60

        if age_minutes < 10:
            return "ACTIVE", last_strike
        if age_minutes < 60:
            return "Recent", last_strike
        return "Old", last_strike

    except Exception:
        return "Unknown", last_strike


def get_rain_data():
    try:
        response = requests.get(RAIN_URL, timeout=2)
        response.raise_for_status()
        data = response.json()
        return {
            "ok": True,
            "rain_in": float(data.get("rain_in", 0)),
            "rain_mm": float(data.get("rain_mm", 0)),
            "rate": float(data.get("rate_mm_hr", 0)),
            "tips": int(data.get("tip_count", 0)),
        }
    except Exception:
        return {"ok": False}


def set_text(widget, value):
    widget.config(text=value)


def refresh():
    data = load_status()
    now_local = datetime.now().strftime("%H:%M:%S")

    if "error" in data:
        set_text(header_value, "ERROR")
        set_text(fresh_value, "status.json")
        set_text(node_value, "unavailable")
        set_text(soil_value, "--")
        set_text(lightning_value, "--")
        set_text(strike_value, data["error"])
        set_text(rain_value, "--")
        set_text(rain_sub_value, "")
        set_text(noaa_value, "--")
        set_text(updated_value, "--")
        root.after(REFRESH_MS, refresh)
        return

    updated_raw = data.get("updated", "n/a")
    freshness = format_freshness(updated_raw)
    lightning_status, last_strike = format_lightning_status(data.get("last_lightning_ts"))

    noaa = data.get("noaa") or {}
    noaa_forecast = truncate(noaa.get("shortForecast", "n/a"), 24)
    noaa_temp = noaa.get("temperature", "?")
    noaa_unit = noaa.get("temperatureUnit", "")

    rain = get_rain_data()
    if rain.get("ok"):
        rain_main = f'{rain["rain_in"]:.3f} in'
        rain_sub = f'{rain["rain_mm"]:.1f} mm · {rain["rate"]:.2f} mm/hr'
    else:
        rain_main = "unavailable"
        rain_sub = "rain-node offline"

    set_text(header_value, now_local)
    set_text(fresh_value, freshness)
    set_text(node_value, data.get("node", "unknown"))
    set_text(soil_value, f'{data.get("soil_moisture", "n/a")}%')
    set_text(lightning_value, lightning_status)
    set_text(strike_value, format_ts(last_strike))
    set_text(rain_value, rain_main)
    set_text(rain_sub_value, rain_sub)
    set_text(noaa_value, f"{noaa_forecast} · {noaa_temp}°{noaa_unit}")
    set_text(updated_value, format_ts(updated_raw))

    root.after(REFRESH_MS, refresh)


BG = "#101820"
PANEL = "#162331"
GREEN = "#2ecc71"
DIM = "#8fd9a8"
WHITE = "#e8fff0"
YELLOW = "#f1c40f"

root = tk.Tk()
root.title("Chatty Status")
root.geometry("800x480")
root.configure(bg=BG)

main = tk.Frame(root, bg=BG, padx=18, pady=14)
main.pack(fill="both", expand=True)

header = tk.Frame(main, bg=BG)
header.pack(fill="x")

title = tk.Label(
    header,
    text="🌱 CHATTY STATUS",
    font=("DejaVu Sans Mono", 24, "bold"),
    fg=GREEN,
    bg=BG,
    anchor="w",
)
title.pack(side="left")

header_value = tk.Label(
    header,
    text="--:--:--",
    font=("DejaVu Sans Mono", 22, "bold"),
    fg=WHITE,
    bg=BG,
    anchor="e",
)
header_value.pack(side="right")

fresh_value = tk.Label(
    main,
    text="loading",
    font=("DejaVu Sans Mono", 15),
    fg=YELLOW,
    bg=BG,
    anchor="e",
)
fresh_value.pack(fill="x", pady=(0, 8))


grid = tk.Frame(main, bg=BG)
grid.pack(fill="both", expand=True)

for i in range(2):
    grid.columnconfigure(i, weight=1, uniform="cols")


def card(parent, row, col, title_text):
    frame = tk.Frame(parent, bg=PANEL, padx=14, pady=10)
    frame.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)

    label = tk.Label(
        frame,
        text=title_text,
        font=("DejaVu Sans Mono", 14, "bold"),
        fg=DIM,
        bg=PANEL,
        anchor="w",
    )
    label.pack(fill="x")

    value = tk.Label(
        frame,
        text="--",
        font=("DejaVu Sans Mono", 21, "bold"),
        fg=WHITE,
        bg=PANEL,
        anchor="w",
    )
    value.pack(fill="x")

    sub = tk.Label(
        frame,
        text="",
        font=("DejaVu Sans Mono", 13),
        fg=DIM,
        bg=PANEL,
        anchor="w",
    )
    sub.pack(fill="x")

    return value, sub


node_value, _ = card(grid, 0, 0, "NODE")
soil_value, _ = card(grid, 0, 1, "SOIL MOISTURE")
lightning_value, strike_value = card(grid, 1, 0, "LIGHTNING")
rain_value, rain_sub_value = card(grid, 1, 1, "RAIN")
noaa_value, _ = card(grid, 2, 0, "NOAA")
updated_value, _ = card(grid, 2, 1, "UPDATED")

refresh()
root.mainloop()
