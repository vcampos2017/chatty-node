import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import local_skills  # noqa: E402
import weather_lookup  # noqa: E402

PERIODS = [
    {"name": "This Afternoon", "isDaytime": True, "temperature": 81, "shortForecast": "Mostly Sunny",
     "windSpeed": "5 to 10 mph", "probabilityOfPrecipitation": {"value": None}},
    {"name": "Tonight", "isDaytime": False, "temperature": 62, "shortForecast": "Partly Cloudy",
     "windSpeed": "5 mph", "probabilityOfPrecipitation": {"value": 20}},
    {"name": "Saturday", "isDaytime": True, "temperature": 75, "shortForecast": "Chance Showers",
     "windSpeed": "10 mph", "probabilityOfPrecipitation": {"value": 40}},
    {"name": "Saturday Night", "isDaytime": False, "temperature": 58, "shortForecast": "Clear",
     "windSpeed": "5 mph", "probabilityOfPrecipitation": {"value": None}},
    {"name": "Sunday", "isDaytime": True, "temperature": 79, "shortForecast": "Sunny",
     "windSpeed": "5 mph", "probabilityOfPrecipitation": {"value": None}},
]
NOW = {"temp_f": 72.4, "feels_like_f": None, "description": "Partly Cloudy",
       "humidity": 60, "wind_mph": 6, "station": "KSAT"}


def setup_function(_):
    local_skills._cache.clear()
    weather_lookup.get_forecast = lambda *a, **k: {"properties": {"periods": PERIODS}}
    weather_lookup.get_current = lambda *a, **k: NOW


def test_whats_the_weather_gives_now_and_today():
    r = local_skills.handle("Hey Chatty, what's the weather?")
    assert r.startswith("Right now it's 72 degrees and partly cloudy.")
    assert "this afternoon: mostly sunny, with a high around 81 degrees" in r.lower()


def test_how_hot_is_it():
    r = local_skills.handle("how hot is it outside")
    assert "72 degrees" in r


def test_tonight_and_weekend():
    assert local_skills.handle("what's the weather tonight").startswith("Tonight: partly cloudy, with a low around 62")
    r = local_skills.handle("what's the weather this weekend")
    assert "Saturday: chance showers" in r and "Sunday: sunny" in r and "40 percent" in r


def test_news_offers_the_weather():
    r = local_skills.handle("what's the news for San Antonio, Texas?")
    assert "news" in r and "Right now it's 72 degrees" in r


def test_service_down():
    def boom(*a, **k):
        raise OSError("no network")
    weather_lookup.get_forecast = boom
    assert "couldn't reach the weather" in local_skills.handle("what's the forecast")


def test_location_from_env(monkeypatch):
    monkeypatch.setenv("CHATTY_LAT", "30.1")
    monkeypatch.setenv("CHATTY_LON", "-97.5")
    assert weather_lookup.location() == (30.1, -97.5)
