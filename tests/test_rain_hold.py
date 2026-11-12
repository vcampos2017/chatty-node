"""No "the plants are thirsty" nag right after rain, or just before it (src/rain_hold.py)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["CHATTY_RAIN_HOLD_STATE"] = os.path.join(tempfile.mkdtemp(), "rain_hold.json")
import rain_hold  # noqa: E402

assert not rain_hold.ENABLED          # off by default: the greenhouse soil is under cover
rain_hold.ENABLED = True
import nodes  # noqa: E402
import rain_watch  # noqa: E402
import sky  # noqa: E402

T = 1_000_000.0
H = 3600


def _file():
    p = Path(tempfile.mkdtemp()) / "hold.json"
    return p


def test_nothing_saved_means_no_hold():
    assert rain_hold.reason(T, _file()) is None


def test_after_rain_holds_for_a_few_hours():
    p = _file()
    rain_hold.note_wet(T, p)
    assert rain_hold.reason(T + 60, p) == "it's raining right now"
    assert rain_hold.reason(T + 2 * H, p) == "it rained about 2 hours ago"
    assert rain_hold.reason(T + 7 * H, p) is None          # default 6 hours


def test_rain_time_is_saved_at_most_every_few_minutes_but_moves_on():
    p = _file()
    rain_hold.note_wet(T, p)
    rain_hold.note_wet(T + 60, p)                          # same shower, not written again
    assert rain_hold._read(p)["last_wet"] == T
    rain_hold.note_wet(T + 10 * 60, p)
    assert rain_hold._read(p)["last_wet"] == T + 10 * 60


def test_forecast_rain_holds_but_not_forever():
    p = _file()
    rain_hold.note_forecast(T + H, T, p)
    assert rain_hold.reason(T, p) == "rain is on the way in about an hour"
    rain_hold.note_forecast(T + 4 * H, T + 3 * H, p)       # still "coming"...
    assert rain_hold.reason(T + 3 * H, p).startswith("rain is on the way")
    rain_hold.note_forecast(T + 8 * H, T + 7 * H, p)       # ...7 hours on and it never came
    assert rain_hold.reason(T + 7 * H, p) is None
    rain_hold.note_forecast(None, T + 8 * H, p)            # dry forecast: the count starts over
    rain_hold.note_forecast(T + 9 * H, T + 8.5 * H, p)
    assert rain_hold.reason(T + 8.5 * H, p).startswith("rain is on the way")


def test_old_forecast_note_is_ignored():
    p = _file()
    rain_hold.note_forecast(T + H, T, p)
    assert rain_hold.reason(T + 2 * H, p) is None          # rain_watch stopped checking


def test_switched_off():
    p = _file()
    rain_hold.note_wet(T, p)
    rain_hold.ENABLED = False
    try:
        assert rain_hold.reason(T + 60, p) is None
    finally:
        rain_hold.ENABLED = True


def _dry(_url):
    return {"metrics": {"soil_moisture_percent": 20, "soil_voltage": 1.1, "air_temperature_f": 70}}


def test_greenhouse_card_holds_the_nag_after_rain():
    r = nodes.read_greenhouse(fetch=_dry, rain=lambda: "it rained about 2 hours ago")
    assert r.spoken == "" and r.hold == "it rained about 2 hours ago"
    assert r.comment == "Dry, but it rained about 2 hours ago."
    r = nodes.read_greenhouse(fetch=_dry, rain=lambda: None)
    assert "thirsty" in r.spoken and r.mood == "worried"


def test_hot_greenhouse_still_speaks_after_rain():
    hot = lambda _u: {"metrics": {"soil_moisture_percent": 20, "soil_voltage": 1.1,
                                  "air_temperature_f": 104}}
    r = nodes.read_greenhouse(fetch=hot, rain=lambda: "it rained about an hour ago")
    assert "104 degrees" in r.spoken


def test_spoken_answer_says_why():
    import local_skills
    old = nodes.read_greenhouse
    nodes.read_greenhouse = lambda: old(fetch=_dry, rain=lambda: "rain is on the way in about an hour")
    try:
        a = local_skills._greenhouse("is the greenhouse thirsty")
    finally:
        nodes.read_greenhouse = old
    assert "thirsty, but rain is on the way in about an hour, so the sky may do the watering" in a


def test_sky_and_rain_watch_feed_it():
    wet = []
    w = sky.SkyWatch(face=lambda m: None, notice=lambda t: None, is_night=lambda n: False,
                     on_wet=wet.append)
    w.on_data("rain", {"rate_mm_hr": 0, "tip_count": 3}, T)
    assert wet == []
    w.on_data("rain", {"rate_mm_hr": 1.2, "tip_count": 4}, T + 60)
    assert wet == [T + 60]

    seen = []
    period = {"startTime": "2001-09-09T03:00:00+00:00", "endTime": "2001-09-09T04:00:00+00:00",
              "probabilityOfPrecipitation": {"value": 80}, "shortForecast": "Rain"}
    rw = rain_watch.RainWatch(fetch=lambda: [period], notice=lambda t: None, phone=lambda t: None,
                              is_night=lambda n: False, state_file=None,
                              on_outlook=lambda s, n: seen.append((s, n)))
    now = rain_watch._ts(period["startTime"]) - 1800
    rw.check_once(now)
    assert seen == [(now + 1800, now)]
    rw.fetch = lambda: []
    rw.check_once(now + 900)
    assert seen[-1] == (None, now + 900)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
