import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CHATTY_NIGHT_END", "7")
import mesh  # noqa: E402
import morning_briefing as mb  # noqa: E402


def _at(hour, minute=0, day=8):
    return time.mktime((2026, 11, day, hour, minute, 0, 0, 0, -1))


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _hours(chances, start, summary="Chance Showers"):
    return [{"startTime": _iso(start + i * 3600), "endTime": _iso(start + (i + 1) * 3600),
             "shortForecast": summary, "probabilityOfPrecipitation": {"value": c}}
            for i, c in enumerate(chances)]


class FakeMesh:
    def __init__(self, now, connected=True):
        self.tracker = mesh.Tracker()
        self.client = object()
        self.connected = connected
        self.now = now

    def hear(self, name, status=None, data=None, at=None):
        at = self.now if at is None else at
        if status is not None:
            self.tracker.message(f"chatty/nodes/{name}/status", json.dumps(status).encode(), at)
        if data is not None:
            self.tracker.message(f"chatty/nodes/{name}/data", json.dumps(data).encode(), at)


def _all_online(now):
    m = FakeMesh(now)
    beat = {"state": "online", "every": 60, "ts": now}
    m.hear("greenhouse", beat, {"metrics": {"air_temperature_f": 58.2, "soil_moisture_percent": 52,
                                            "soil_voltage": 1.4}})
    m.hear("rain", beat, {"rain_in": 0, "rate_mm_hr": 0, "tip_count": 3})
    m.hear("lightning", beat, {"sensor": "ok", "strikes_today": 0, "last_strike": None})
    return m


def _briefing(m=None, weather=lambda: "Right now it's 45 degrees and cloudy. Today: Sunny, with a high near 62.",
              hourly=None, raining=False, notes=None, now=None):
    state = Path(tempfile.mkdtemp()) / "m.json"
    notes = [] if notes is None else notes
    return mb.Briefing(mesh=m, raining=lambda: raining, weather=weather,
                       hourly=hourly or (lambda: _hours([0, 10, 0, 5], now or _at(7, 30))),
                       today_short=lambda: "Sunny, 62°", notice=notes.append,
                       clock=lambda: now or _at(7, 30), state_file=state)


def _wait(b):
    for _ in range(200):
        if not b.morning._fetching:
            return
        time.sleep(0.01)


def test_start_time_setting(monkeypatch=None):
    os.environ.pop("CHATTY_MORNING_HOUR", None)
    for raw, want in [("", 450), ("7:30", 450), ("6", 360), ("06:45", 405), ("6:30am", 390),
                      ("1:15 pm", 795), ("nonsense", 450)]:
        os.environ["CHATTY_MORNING_TIME"] = raw
        assert mb.start_minute() == want, raw
    os.environ.pop("CHATTY_MORNING_TIME")
    os.environ["CHATTY_MORNING_HOUR"] = "8"
    assert mb.start_minute() == 480
    os.environ.pop("CHATTY_MORNING_HOUR")


def test_full_briefing_is_kind_and_short():
    now = _at(7, 30)
    b = _briefing(_all_online(now), now=now)
    text, screen = b.build(now)
    assert text.startswith("Good morning! It's Sunday, November 8th.")
    assert "Sunny, with a high near 62." in text
    assert "No rain expected today." in text
    assert "All three nodes checked in." in text
    assert "The greenhouse is 58 degrees and the soil is at 52 percent." in text
    assert text.split(". ")[-1].rstrip("!.") in [c.rstrip("!.").split(". ")[-1] for c in mb.CLOSERS]
    assert len(text) < 450
    assert screen == "Good morning! Sunny, 62° · No rain today · Nodes 3/3 online"


def test_rain_chances_today():
    now = _at(7, 30)
    said, short = mb.rain_today(_hours([0, 10, 20, 30, 70, 40], now), now)
    assert said.startswith("Rain is likely around 11:30 AM, about a 70 percent chance")
    assert short == "Rain 70% ~11:30 AM"
    said, short = mb.rain_today(_hours([0, 10, 30, 0], now), now)
    assert said == "There's a small chance of rain today, up to 30 percent."
    said, _ = mb.rain_today(_hours([60], now, "Chance Showers And Thunderstorms"), now)
    assert said.startswith("Thunderstorms are likely soon")
    # rain tomorrow doesn't count for today
    said, _ = mb.rain_today(_hours([0] * 17 + [90], now), now)
    assert said == "No rain expected today."


def test_quiet_and_missing_nodes():
    now = _at(7, 30)
    m = FakeMesh(now)
    m.hear("greenhouse", {"state": "online", "every": 60, "ts": now},
           {"air_temperature_f": 61, "soil_moisture_percent": 20, "soil_voltage": 1.1})
    m.hear("rain", {"state": "online", "every": 60, "ts": now - 3600})   # stale: quiet
    said, short = mb.node_report(m, now=now)
    assert said.startswith("The greenhouse is online.")
    assert "The rain gauge has been quiet since 6:30 AM." in said
    assert "I haven't heard from the lightning node yet." in said
    assert "so the plants are thirsty" in said
    assert short == "Nodes 1/3 online"


def test_probe_unplugged_lightning_and_rain_now():
    now = _at(7, 30)
    m = _all_online(now)
    m.hear("greenhouse", data={"air_temperature_f": 55, "soil_moisture_percent": 100, "soil_voltage": 0.0})
    m.hear("lightning", data={"sensor": "ok", "strikes_today": 4})
    said, _ = mb.node_report(m, raining=True, now=now)
    assert "The greenhouse is 55 degrees, but I can't feel the soil probe." in said
    assert "100 percent" not in said
    assert "The lightning node counted 4 strikes since midnight." in said
    assert "The rain gauge says it's raining right now." in said
    m.hear("lightning", data={"sensor": "missing", "strikes_today": 0})
    said, _ = mb.node_report(m, now=now)
    assert "its sensor still isn't answering" in said


def test_network_off_or_unreachable():
    now = _at(7, 30)
    off = FakeMesh(now)
    off.client = None
    assert mb.node_report(off, now=now) == ("", "")
    down = _all_online(now)
    down.connected = False
    said, _ = mb.node_report(down, now=now)
    assert said.startswith("I can't reach my message board right now")


def test_said_once_at_seven_thirty_with_a_notice():
    os.environ.pop("CHATTY_MORNING_TIME", None)
    notes = []
    now = _at(7, 30)
    b = _briefing(_all_online(now), notes=notes, now=now)
    assert b.due("sleep", _at(7, 10)) is None and not b.morning._fetching   # too early
    assert b.due("sleep", _at(7, 31)) is None                               # starts the lookup
    _wait(b)
    assert b.due("active", _at(7, 32)) is None                              # busy: wait
    said = b.due("sleep", _at(7, 33))
    assert said and said.startswith("Good morning!")
    assert notes == ["Good morning! Sunny, 62° · No rain today · Nodes 3/3 online"]
    assert b.due("sleep", _at(8)) is None                                   # once a day


def test_weather_down_retries_then_goes_without():
    def boom():
        raise OSError("offline")
    now = _at(7, 30)
    b = _briefing(_all_online(now), weather=boom, now=now)
    for i in range(3):
        b.due("sleep", _at(7, 31) + i * 301)
        _wait(b)
    said = b.due("sleep", _at(7, 50))
    assert said and "I couldn't reach the weather service just now." in said
    assert "All three nodes checked in." in said


def test_on_request():
    now = _at(18, 0)
    b = _briefing(_all_online(now), now=now)
    assert b.answer().startswith("Good evening! Here's your briefing for Sunday, November 8th.")
    for p in ["morning briefing", "give me my briefing", "brief me", "what's the daily rundown"]:
        assert mb.asked(p), p
    for p in ["good morning", "what's the weather", "brief"]:
        assert not mb.asked(p), p


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
