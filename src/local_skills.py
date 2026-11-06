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


_WEATHER_WORDS = ("weather", "forecast", "rain", "raining", "temperature", "hot", "cold",
                  "sunny", "cloudy", "storm", "storms", "umbrella", "jacket", "outside",
                  "windy", "humid", "chilly")
_NOW_WORDS = ("right now", "currently", "outside", "at the moment", "is it", "how hot",
              "how cold", "how warm")


def _period_line(p: dict, when: str = "") -> str:
    """One forecast period as a short spoken sentence."""
    when = when or p["name"]
    temp_word = "a high around" if p.get("isDaytime", True) else "a low around"
    line = f"{when[0].upper() + when[1:]}: {p['shortForecast'].lower()}, with {temp_word} {p['temperature']} degrees"
    rain = (p.get("probabilityOfPrecipitation") or {}).get("value")
    if rain:
        line += f", and about a {rain} percent chance of rain"
    return line + "."


def _now_line(now: Optional[dict]) -> str:
    if not now:
        return ""
    line = f"Right now it's {now['temp_f']:.0f} degrees"
    if now.get("description"):
        line += f" and {now['description'].lower()}"
    feels = now.get("feels_like_f")
    if feels is not None and abs(feels - now["temp_f"]) >= 4:
        line += f", but it feels like {feels:.0f}"
    return line + "."


def _weather_reply(want: str) -> str:
    from weather_lookup import get_current, get_forecast  # free National Weather Service API

    periods = get_forecast()["properties"]["periods"]
    if not periods:
        return "I couldn't find a forecast right now."

    if want == "tomorrow":
        day_name = (datetime.now() + timedelta(days=1)).strftime("%A").lower()
        target = next((p for p in periods[1:] if p["name"].lower() == day_name
                       or "tomorrow" in p["name"].lower()), periods[min(2, len(periods) - 1)])
        return _period_line(target, "tomorrow")

    if want == "tonight":
        target = next((p for p in periods if not p.get("isDaytime", True)), periods[0])
        return _period_line(target, "tonight")

    if want in ("week", "weekend"):
        days = [p for p in periods if p.get("isDaytime", True)]
        if want == "weekend":
            days = [p for p in days if p["name"].lower() in ("saturday", "sunday")] or days[:2]
        else:
            days = days[:4]
        return " ".join(_period_line(p) for p in days)

    # "what's the weather" / "how hot is it": what it's like now, plus the rest of today
    try:
        now = get_current()
    except Exception as e:
        print("Current conditions failed:", repr(e), flush=True)
        now = None
    first = periods[0]
    when = first["name"].lower() if first["name"].lower() in (
        "today", "tonight", "this afternoon", "this morning", "overnight") else first["name"]
    reply = (_now_line(now) + " " + _period_line(first, when)).strip()
    if want == "full":
        wind = _speakable_forecast(first.get("windSpeed", ""))
        if wind and not wind.startswith("0"):
            reply += f" Wind {wind}."
    return reply


def weather_report(want: str = "full") -> str:
    """Spoken weather for 'full', 'now', 'tonight', 'tomorrow', 'weekend' or 'week'.
    Raises if the weather service can't be reached."""
    return _cached(f"weather:{want}", 600, lambda: _weather_reply(want))


def _weather(text: str) -> Optional[str]:
    if not _has(text, *_WEATHER_WORDS):
        return None
    # leave greenhouse temperature questions to the greenhouse skill
    if _has(text, "greenhouse", "plants", "soil"):
        return None

    if _has(text, "tomorrow"):
        want = "tomorrow"
    elif _has(text, "tonight"):
        want = "tonight"
    elif _has(text, "weekend"):
        want = "weekend"
    elif _has(text, "this week", "the week", "next few days", "coming days", "week"):
        want = "week"
    elif _has(text, *_NOW_WORDS) and not _has(text, "weather", "forecast"):
        want = "now"
    else:
        want = "full"

    try:
        return weather_report(want)
    except Exception as e:
        print("Weather lookup failed:", repr(e), flush=True)
        return "Hmm, I couldn't reach the weather service just now."


def _news(text: str) -> Optional[str]:
    """No news feed yet, so offer the weather instead of a shrug."""
    if not _has(text, "news", "headlines"):
        return None
    if _has(text, "good news", "bad news"):
        return None
    try:
        weather = weather_report("full")
    except Exception as e:
        print("Weather lookup failed:", repr(e), flush=True)
        return "I can't read the news yet, and I couldn't reach the weather service either. Sorry!"
    return random.choice([
        "I can't read the news yet, but I can tell you the weather. ",
        "No news feed for me yet, but here's the weather. ",
    ]) + weather


def _greenhouse(text: str) -> Optional[str]:
    if not _has(text, "greenhouse", "plants", "plant", "soil", "garden"):
        return None
    # Read-only: never toggles watering or sends alerts from a voice question.
    import nodes
    r = nodes.read_greenhouse()
    if not r.ok:
        return "I can't reach the greenhouse node right now. It might be offline."
    temp = r.raw.get("air_temperature_f")
    warmth = f"It's {float(temp):.0f} degrees in there." if temp is not None else ""
    if r.detail.startswith("soil probe"):
        return f"{warmth} But I'm not getting a reading from the soil probe. It might be unplugged.".strip()
    soil = float(r.raw["soil_moisture_percent"])
    mood = ("The plants are thirsty!" if soil < nodes.SOIL_DRY else
            "They're doing okay, but could use water soon." if soil < nodes.SOIL_OK else
            "The plants look happy.")
    return f"The greenhouse soil is at {soil:.0f} percent moisture. {warmth} {mood}".replace("  ", " ").strip()


SKILLS = [_time, _date, _greenhouse, _weather, _news]


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
