"""
How dry is the greenhouse soil? One answer for all of Chatty: the greenhouse
node's own label (`soil_moisture_band` in its /status) when it sends one, and
her old percentage cut-offs only when it doesn't (Vincent, 2026-11-13: "use the
greenhouse's logical decision"; before, Chatty called 30% "critically dry" while
the greenhouse itself said "moderate").

    soil.state(31, "moderate")  -> "okay"
    soil.state(20, None)        -> "dry"       (no label: below CHATTY_SOIL_DRY, 35)
    soil.state(80, "wet")       -> "wet"

"dry" = the plants are thirsty (alerts and nags), "okay" = could use water soon,
"wet" = happy plants. Plain Python, no packages (the cron job's venv uses it).
"""
from __future__ import annotations

import os
import re
from typing import Optional

SOIL_DRY = float(os.getenv("CHATTY_SOIL_DRY", "35"))     # fallback cut-offs, only without a label
SOIL_OK = float(os.getenv("CHATTY_SOIL_OK", "50"))

_DRY = re.compile(r"\b(dry|parched|thirsty|low|critical)\b")
_OKAY = re.compile(r"\b(moderate|medium|ok|okay|fair|average|mid|normal)\b")
_WET = re.compile(r"\b(wet|moist|damp|good|ideal|optimal|saturated|high|soggy|great)\b")


def from_band(band) -> Optional[str]:
    """The greenhouse's label as 'dry' / 'okay' / 'wet', or None if there's none we know."""
    text = str(band or "").strip().lower().replace("_", " ").replace("-", " ")
    if not text or text in ("unknown", "none", "n/a", "error"):
        return None
    if re.search(r"\b(not|no longer)\s+dry\b", text):
        return "okay"
    if _DRY.search(text):
        return "dry"
    if _OKAY.search(text):
        return "okay"
    if _WET.search(text):
        return "wet"
    return None


def from_percent(soil: float) -> str:
    return "dry" if soil < SOIL_DRY else ("okay" if soil < SOIL_OK else "wet")


def state(soil: Optional[float], band=None) -> Optional[str]:
    """The greenhouse's own call when it makes one, else the percentage."""
    by_band = from_band(band)
    if by_band:
        return by_band
    if soil is None:
        return None
    return from_percent(float(soil))


def of(metrics: dict) -> Optional[str]:
    """state() straight from a /status 'metrics' dict."""
    m = metrics or {}
    soil = m.get("soil_moisture_percent")
    try:
        soil = float(soil) if soil is not None else None
    except (TypeError, ValueError):
        soil = None
    return state(soil, m.get("soil_moisture_band"))
