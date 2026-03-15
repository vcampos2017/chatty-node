from __future__ import annotations

import json
import urllib.request
from typing import Dict, Any


DEFAULT_LAT = 29.4241
DEFAULT_LON = -98.4936
USER_AGENT = "ChattyNode/0.1 (vincent local test)"


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


def get_forecast(lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON) -> Dict[str, Any]:
    """
    Fetch NWS forecast metadata and the forecast periods for a lat/lon.
    Default location is San Antonio, TX.
    """
    points_url = f"https://api.weather.gov/points/{lat},{lon}"
    points_data = _get_json(points_url)

    forecast_url = points_data["properties"]["forecast"]
    forecast_data = _get_json(forecast_url)

    return forecast_data


def summarize_forecast(day: str = "today", lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON) -> str:
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
    print("Today:")
    print(summarize_forecast("today"))
    print()
    print("Tomorrow:")
    print(summarize_forecast("tomorrow"))
