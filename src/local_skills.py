"""
Local skills: questions Chatty answers on the Pi itself, with no AI service.

Anything handled here is instant and free. handle() returns a spoken reply,
or None to let the question go to the AI relay as usual.
"""
from __future__ import annotations

import random
import re
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

# ----------------------------
# helpers
# ----------------------------

_cache: dict = {}


def _cached(key: str, seconds: float, fn: Callable[[], str]) -> str:
    """Reuse a recent answer so repeated questions don't refetch."""
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < seconds:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


def _has(text: str, *phrases: str) -> bool:
    return any(re.search(rf"\b{p}\b", text) for p in phrases)


def _spoken_time(dt: datetime) -> str:
    hour = dt.strftime("%I").lstrip("0")
    minute = dt.minute
    ampm = "AM" if dt.hour < 12 else "PM"
    if minute == 0:
        return f"{hour} o'clock {ampm}" if dt.hour not in (0, 12) else ("midnight" if dt.hour == 0 else "noon")
    return f"{hour}:{minute:02d} {ampm}"


def _day_part(dt: datetime) -> str:
    h = dt.hour
    if h < 5:
        return "the middle of the night"
    if h < 12:
        return "the morning"
    if h < 17:
        return "the afternoon"
    if h < 21:
        return "the evening"
    return "night"


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ----------------------------
# skills
# ----------------------------

def _time(text: str) -> Optional[str]:
    if not (_has(text, "what time", "time is it", "the time", "current time")):
        return None
    now = datetime.now()
    t = _spoken_time(now)
    return random.choice([
        f"It's {t}.",
        f"It's {t} right now.",
        f"Right now it's {t}.",
    ])


def _date(text: str) -> Optional[str]:
    if not _has(text, "what day", "what date", "the date", "todays date", "what is today",
                "whats today", "day of the week", "day is it", "date is it"):
        return None
    now = datetime.now()
    if _has(text, "tomorrow"):
        d = now + timedelta(days=1)
        return f"Tomorrow is {d:%A}, {d:%B} {_ordinal(d.day)}."
    return f"Today is {now:%A}, {now:%B} {_ordinal(now.day)}."


def _speakable_forecast(text: str) -> str:
    """'85 F', '5 to 10 mph' -> words the voice reads nicely."""
    text = re.sub(r"(\d+)\s*mph", r"\1 miles per hour", text)
    return text


def _weather(text: str) -> Optional[str]:
    if not _has(text, "weather", "forecast", "rain", "raining", "temperature", "hot",
                "cold", "sunny", "cloudy", "storm", "storms", "umbrella", "jacket"):
        return None
    # leave greenhouse temperature questions to the greenhouse skill
    if _has(text, "greenhouse", "plants", "soil"):
        return None

    from weather_lookup import get_forecast  # free National Weather Service API

    want_tomorrow = _has(text, "tomorrow")
    want_tonight = _has(text, "tonight")

    def fetch() -> str:
        periods = get_forecast()["properties"]["periods"]
        if not periods:
            return "I couldn't find a forecast right now."
        target = periods[0]
        if want_tomorrow:
            day_name = (datetime.now() + timedelta(days=1)).strftime("%A").lower()
            target = next((p for p in periods[1:] if p["name"].lower() == day_name
                           or "tomorrow" in p["name"].lower()), periods[min(2, len(periods) - 1)])
        elif want_tonight:
            target = next((p for p in periods if "night" in p["name"].lower()), periods[0])

        name = target["name"]
        if want_tomorrow:
            when = "tomorrow"
        elif name.lower() in ("today", "tonight", "this afternoon", "this morning", "overnight"):
            when = name.lower()
        else:
            when = name
        forecast = target["shortForecast"].lower()
        temp = target["temperature"]
        is_night = not target.get("isDaytime", True)
        temp_word = "a low around" if is_night else "a high around"
        wind = _speakable_forecast(target.get("windSpeed", ""))
        rain = (target.get("probabilityOfPrecipitation") or {}).get("value")

        reply = f"{when[0].upper() + when[1:]}: {forecast}, with {temp_word} {temp} degrees"
        if rain:
            reply += f", and about a {rain} percent chance of rain"
        reply += "."
        if wind and not wind.startswith("0"):
            reply += f" Wind {wind}."
        return reply

    key = "tomorrow" if want_tomorrow else ("tonight" if want_tonight else "now")
    try:
        return _cached(f"weather:{key}", 600, fetch)
    except Exception as e:
        print("Weather lookup failed:", repr(e), flush=True)
        return "Hmm, I couldn't reach the weather service just now."


def _greenhouse(text: str) -> Optional[str]:
    if not _has(text, "greenhouse", "plants", "plant", "soil", "garden"):
        return None
    # Read-only: never toggles watering or sends alerts from a voice question.
    from greenhouse_status import fetch_greenhouse_metrics, classify_soil
    try:
        soil, temp_f = fetch_greenhouse_metrics()
    except Exception as e:
        print("Greenhouse lookup failed:", repr(e), flush=True)
        return "I can't reach the greenhouse node right now. It might be offline."
    status = classify_soil(soil)
    mood = {
        "critically dry": "The plants are thirsty!",
        "moderate": "They're doing okay, but could use water soon.",
        "good": "The plants look happy.",
    }.get(status, "")
    return (f"The greenhouse soil is at {soil:.0f} percent moisture, "
            f"and it's {temp_f:.0f} degrees in there. {mood}").strip()


SKILLS = [_time, _date, _greenhouse, _weather]


def handle(text: str) -> Optional[str]:
    """Return a local spoken answer, or None to ask the AI instead."""
    t = re.sub(r"[^a-z0-9\s]", "", (text or "").lower())
    # Longer, open-ended requests ("tell me about the history of weather
    # forecasting") are better answered by the AI.
    if len(t.split()) > 12 or _has(t, "explain", "why", "how does", "how do", "history",
                                    "tell me about", "what causes"):
        return None
    for skill in SKILLS:
        reply = skill(t)
        if reply:
            return reply
    return None
