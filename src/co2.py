"""Greenhouse CO2 in words (the greenhouse node's SCD-40 sensor, 2026-11-21).

The greenhouse node sends co2_ppm and its own co2_band ("low" / "normal" /
"high") with its other readings, and leaves them out when it has no CO2
sensor. Like soil.py, the node's own label wins; CHATTY_CO2_LOW / _HIGH
(350 / 1500 ppm) only when it sends no label.

    low     the plants used up the CO2 (a sunny day with the vents shut)
    normal  outside air is about 420 ppm
    high    stuffy: open a vent

Used by the greenhouse answer ("what's the CO2 in the greenhouse?"), the face's
greenhouse card and the morning briefing (only when it isn't normal).
Read-only like everything else: Chatty never opens a vent herself.
"""
from __future__ import annotations

import os
import re
from typing import Optional

LOW = float(os.getenv("CHATTY_CO2_LOW", "350"))
HIGH = float(os.getenv("CHATTY_CO2_HIGH", "1500"))

# What speech recognition makes of "CO2" after normalize() (lowercase, no punctuation)
_QUESTION = re.compile(r"\b(co2|co 2|c o 2|c o two|co two|see oh two|carbon dioxide)\b")


def is_question(text: str) -> bool:
    return bool(_QUESTION.search(text or ""))


def reading(metrics: dict) -> tuple[Optional[int], Optional[str]]:
    """(ppm, 'low' / 'normal' / 'high'), or (None, None) without a sensor."""
    try:
        ppm = int(round(float(metrics.get("co2_ppm"))))
    except (TypeError, ValueError, AttributeError):
        return None, None
    if ppm <= 0:
        return None, None
    band = str(metrics.get("co2_band") or "").strip().lower()
    if band not in ("low", "normal", "high"):
        band = "low" if ppm < LOW else "high" if ppm > HIGH else "normal"
    return ppm, band


def sentence(metrics: dict) -> str:
    """'The CO2 in there is 640 parts per million. That's normal.' or ''."""
    ppm, band = reading(metrics)
    if ppm is None:
        return ""
    how = {"low": "That's low: the plants have used it up. A little fresh air would help.",
           "high": "That's high. It's stuffy in there, so maybe open a vent.",
           "normal": "That's normal. Outside air is about 420."}[band]
    return f"The CO2 in there is {ppm} parts per million. {how}"


def answer(metrics: dict) -> str:
    """For a CO2 question."""
    return (sentence(metrics) or
            "I'm not getting a CO2 reading from the greenhouse. Is the CO2 sensor plugged in?")


def short(metrics: dict) -> str:
    """For the face card: 'CO2 640' (or '' without a sensor)."""
    ppm, band = reading(metrics)
    if ppm is None:
        return ""
    return f"CO2 {ppm}" + ("" if band == "normal" else f" {band}")


def briefing(metrics: dict) -> str:
    """A morning-briefing note, only when the CO2 isn't normal."""
    ppm, band = reading(metrics)
    if band == "high":
        return f"The greenhouse CO2 is high, {ppm} parts per million, so maybe open a vent."
    if band == "low":
        return f"The greenhouse CO2 is low, {ppm} parts per million. The plants could use some fresh air."
    return ""
