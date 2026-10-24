"""
Asking the other nodes how they're doing (read-only).

Each node is a small web service that answers GET /status with JSON. Chatty only
ever READS from them: she never sends commands (no watering, no switches).

Settings (in /etc/chatty/secrets.env):
    CHATTY_GREENHOUSE_URL   greenhouse status   (default http://192.168.1.227:5000/status)
    CHATTY_RAIN_URL         rain gauge status   (default http://rain-node:5000/status)
    CHATTY_NODES            which ones she asks (default "greenhouse,rain")
    CHATTY_SOIL_DRY         soil % she worries about (default 35)

Tailscale names work too, e.g. CHATTY_GREENHOUSE_URL=http://greenhouse-pi:5000/status
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

TIMEOUT = float(os.getenv("CHATTY_NODE_TIMEOUT", "4"))
SOIL_DRY = float(os.getenv("CHATTY_SOIL_DRY", "35"))
SOIL_OK = 50.0


@dataclass
class Reading:
    node: str                     # "greenhouse"
    ok: bool                      # did the node answer?
    big: str = ""                 # the headline number, e.g. "42%"
    label: str = ""               # what the number is, e.g. "soil moisture"
    detail: str = ""              # a second fact, e.g. "78 F inside"
    comment: str = ""             # Chatty's reaction
    mood: str = "happy"           # happy / puzzled / worried
    spoken: str = ""              # said out loud only when it matters (alert)
    raw: dict = field(default_factory=dict)


def get_json(url: str, timeout: float = TIMEOUT) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "chatty-node"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


# ----------------------------
# greenhouse
# ----------------------------

def greenhouse_url() -> str:
    return os.getenv("CHATTY_GREENHOUSE_URL", "http://192.168.1.227:5000/status")


def read_greenhouse(fetch: Optional[Callable[[str], dict]] = None) -> Reading:
    fetch = fetch or get_json
    try:
        m = fetch(greenhouse_url()).get("metrics", {})
        soil = float(m["soil_moisture_percent"])
    except Exception as e:
        print("Greenhouse didn't answer:", repr(e), flush=True)
        return Reading("greenhouse", False, comment="No answer. Maybe the greenhouse is napping.",
                       mood="puzzled")
    temp = m.get("air_temperature_f")
    detail = f"{float(temp):.0f} F inside" if temp is not None else ""
    volts = m.get("soil_voltage")
    if volts is not None and abs(float(volts)) < 0.05:
        # 0 volts reads as "100% wet", but really means the soil probe isn't connected
        big = f"{float(temp):.0f} F" if temp is not None else "?"
        return Reading("greenhouse", True, big=big, label="inside the greenhouse",
                       detail="soil probe: no signal",
                       comment="I can't feel the soil. Is the probe unplugged?", mood="puzzled", raw=m)
    r = Reading("greenhouse", True, big=f"{soil:.0f}%", label="soil moisture", detail=detail, raw=m)
    if soil < SOIL_DRY:
        r.comment, r.mood = "The plants are thirsty!", "worried"
        r.spoken = (f"Just so you know, the greenhouse soil is down to {soil:.0f} percent. "
                    "The plants are thirsty.")
    elif soil < SOIL_OK:
        r.comment = "Doing okay. Water soon?"
    else:
        r.comment = "Nice and damp. Happy plants."
    if temp is not None and float(temp) >= 100:
        r.comment, r.mood = "It's really hot in there!", "worried"
        r.spoken = r.spoken or f"Heads up, it's {float(temp):.0f} degrees in the greenhouse."
    return r


# ----------------------------
# rain gauge
# ----------------------------

def rain_url() -> str:
    return os.getenv("CHATTY_RAIN_URL", "http://rain-node:5000/status")


def read_rain(fetch: Optional[Callable[[str], dict]] = None) -> Reading:
    fetch = fetch or get_json
    try:
        d = fetch(rain_url())
        rain_in = float(d.get("rain_in", 0))
        rate = float(d.get("rate_mm_hr", 0))
    except Exception as e:
        print("Rain gauge didn't answer:", repr(e), flush=True)
        return Reading("rain", False, comment="No answer from the rain gauge. Dozing, maybe?",
                       mood="puzzled")
    r = Reading("rain", True, big=f'{rain_in:.2f}"', label="of rain", raw=d)
    if rate > 0:
        r.detail = f"{rate:.1f} mm/hr right now"
        r.comment = "It's raining! Good for the garden."
    elif rain_in > 0:
        r.comment = "We got some rain."
    else:
        r.comment = "Dry so far."
    return r


# ----------------------------
# which nodes, and what she wonders about each
# ----------------------------

NODES: Dict[str, dict] = {
    "greenhouse": dict(read=read_greenhouse, title="Greenhouse", icon="sprout",
                       asking="Asking the greenhouse...",
                       questions=["What's the soil moisture in the greenhouse?",
                                  "I wonder how the plants are doing...",
                                  "Is the greenhouse thirsty?"]),
    "rain": dict(read=read_rain, title="Rain gauge", icon="rain",
                 asking="Asking the rain gauge...",
                 questions=["Did it rain today?", "I wonder if it's raining..."]),
}


def enabled() -> List[str]:
    names = [n.strip() for n in os.getenv("CHATTY_NODES", "greenhouse,rain").split(",")]
    return [n for n in names if n in NODES]


def read(node: str) -> Reading:
    try:
        return NODES[node]["read"]()
    except Exception as e:  # never let a node crash the face
        print(f"Node {node} check failed:", repr(e), flush=True)
        return Reading(node, False, comment="Hmm, something went wrong asking.", mood="puzzled")
