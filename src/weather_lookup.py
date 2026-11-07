"""
Weather from the free National Weather Service API (no key needed).

Location comes from CHATTY_LAT / CHATTY_LON (set in /etc/chatty/secrets.env,
the same ones the weather alerts use). Without them it falls back to
San Antonio, TX.

  get_forecast()  12-hour forecast periods ("Today", "Tonight", "Friday", ...)
  get_hourly()    hour-by-hour forecast (chance of rain each hour), for rain_watch.py
  get_current()   the latest reading from the nearest weather station
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any, Dict, Optional, Tuple


DEFAULT_LAT = 29.4241
DEFAULT_LON = -98.4936
USER_AGENT = os.getenv("CHATTY_NWS_AGENT", "ChattyNode/0.2 (home voice assistant)")

# the points lookup (which forecast office and stations serve us) almost never
# changes, so it is fetched once and kept for a day
_points: Dict[Tuple[float, float], Tuple[float, Dict[str, Any]]] = {}


def location() -> Tuple[float, float]:
    try:
        return float(os.getenv("CHATTY_LAT", DEFAULT_LAT)), float(os.getenv("CHATTY_LON", DEFAULT_LON))
    except ValueError:
        return DEFAULT_LAT, DEFAULT_LON


def _get_json(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/geo+json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _point(lat: Optional[float], lon: Optional[float]) -> Dict[str, Any]:
    if lat is None or lon is None:
        lat, lon = location()
    key = (round(lat, 4), round(lon, 4))
    hit = _points.get(key)
    if hit and time.time() - hit[0] < 86400:
        return hit[1]
    props = _get_json(f"https://api.weather.gov/points/{key[0]},{key[1]}")["properties"]
    _points[key] = (time.time(), props)
    return props


def get_forecast(lat: Optional[float] = None, lon: Optional[float] = None) -> Dict[str, Any]:
    """Forecast periods for a lat/lon (default: Chatty's location)."""
    return _get_json(_point(lat, lon)["forecast"])


def get_hourly(lat: Optional[float] = None, lon: Optional[float] = None) -> list:
    """Hourly forecast periods: startTime, endTime, shortForecast, probabilityOfPrecipitation."""
    return _get_json(_point(lat, lon)["forecastHourly"])["properties"]["periods"]


def place_name(lat: Optional[float] = None, lon: Optional[float] = None) -> str:
    """'San Antonio' for Chatty's location, or '' if unknown."""
    try:
        rel = _point(lat, lon).get("relativeLocation", {}).get("properties", {})
        return rel.get("city", "") or ""
    except Exception:
        return ""


def _value(props: Dict[str, Any], name: str) -> Optional[float]:
    v = (props.get(name) or {}).get("value")
    return float(v) if v is not None else None


def get_current(lat: Optional[float] = None, lon: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """
    Latest reading from the nearest station that has one:
    {"temp_f", "feels_like_f", "description", "humidity", "wind_mph", "station"}.
    None if no nearby station has a recent temperature.
    """
    stations = _get_json(_point(lat, lon)["observationStations"]).get("features", [])
    for station in stations[:3]:
        sid = station["properties"]["stationIdentifier"]
        try:
            obs = _get_json(f"https://api.weather.gov/stations/{sid}/observations/latest")["properties"]
        except Exception:
            continue
        temp_c = _value(obs, "temperature")
        if temp_c is None:
            continue
        feels_c = _value(obs, "heatIndex")
        if feels_c is None:
            feels_c = _value(obs, "windChill")
        wind_kmh = _value(obs, "windSpeed")
        return {
            "temp_f": temp_c * 9 / 5 + 32,
            "feels_like_f": feels_c * 9 / 5 + 32 if feels_c is not None else None,
            "description": (obs.get("textDescription") or "").strip(),
            "humidity": _value(obs, "relativeHumidity"),
            "wind_mph": wind_kmh * 0.621371 if wind_kmh is not None else None,
            "station": sid,
        }
    return None


def summarize_forecast(day: str = "today", lat: Optional[float] = None, lon: Optional[float] = None) -> str:
    """
    Return a short spoken forecast summary for 'today' or 'tomorrow'.
    """
    forecast = get_forecast(lat=lat, lon=lon)
    periods = forecast["properties"]["periods"]

    if not periods:
        return "I couldn't find a forecast right now."

    target = None

    if day.lower() == "tomorrow":
        for period in periods:
            if "tomorrow" in period["name"].lower():
                target = period
                break
        if target is None:
            target = periods[min(2, len(periods) - 1)]
    else:
        target = periods[0]

    name = target["name"]
    forecast_text = target["shortForecast"]
    temp = target["temperature"]
    temp_unit = target["temperatureUnit"]
    wind = target["windSpeed"]

    return f"{name}: {forecast_text}, temperature {temp} degrees {temp_unit}, wind {wind}."


if __name__ == "__main__":
    print("Location:", location(), place_name())
    print("Now:", get_current())
    print("Today:", summarize_forecast("today"))
    print("Tomorrow:", summarize_forecast("tomorrow"))
