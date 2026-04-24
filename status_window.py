import json
import tkinter as tk
from pathlib import Path

STATUS_FILE = Path("/home/pi/chatty-node/status.json")
REFRESH_MS = 2000


def load_status():
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception as e:
        return {"error": str(e)}


def refresh():
    data = load_status()

    if "error" in data:
        text = f"Chatty Status\n\nError reading status:\n{data['error']}"
    else:
        lightning = "Detected" if data.get("last_lightning_ts") else "None"
        text = (
            "🌱 Chatty Status\n\n"
            f"Node: {data.get('node', 'unknown')}\n"
            f"Soil Moisture: {data.get('soil_moisture', 'n/a')}%\n"
            f"⚡ Lightning: {lightning}\n"
            f"Last Strike: {data.get('last_lightning_ts') or 'n/a'}\n\n"
            f"Updated:\n{data.get('updated', 'n/a')}"
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
