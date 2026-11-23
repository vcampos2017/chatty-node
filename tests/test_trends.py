"""Weather trend heads-ups: pressure dropping, the greenhouse cooling fast (src/trends.py)."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["CHATTY_NIGHT_MODE"] = "0"
os.environ["CHATTY_TREND_PHONE"] = "frost"
import trends  # noqa: E402

NOON = time.mktime((2026, 3, 1, 13, 0, 0, 0, 0, -1))
H = 3600


def _watch(nws=None, night=False, tucked=False, path=None):
    notes, posts, buzz = [], [], []
    w = trends.Trends(notice=notes.append, publish=lambda t, b: posts.append((t, b)),
                      phone=buzz.append, nws=nws or (lambda: []),
                      is_night=lambda now: night, tucked_in=lambda now: tucked,
                      clock=lambda: NOON, state_file=path or Path(tempfile.mkdtemp()) / "t.json")
    w.nws_at = 1e12 if nws is None else -1e12     # no background station reads unless a test wants one
    return w, notes, posts, buzz


def _feed(w, start, minutes, temp=None, pressure=None, humidity=None, every=5):
    """Readings every `every` minutes; each argument is a function of minutes since start."""
    t = start
    for m in range(0, minutes + 1, every):
        t = start + m * 60
        body = {}
        if temp:
            body["air_temperature_f"] = temp(m)
        if pressure:
            body["air_pressure_hpa"] = pressure(m)
        if humidity:
            body["air_humidity"] = humidity(m)
        w.clock = lambda t=t: t
        w.on_data("greenhouse", body, t)
    return t


def test_change_needs_both_ends():
    s = [(NOON - 3 * H + i * 300, 1010 - i * 0.1) for i in range(37)]
    assert abs(trends.change(s, NOON, 3 * H) - (-3.6)) < 0.3
    assert trends.change(s, NOON, 5 * H) is None        # no readings from back then
    assert trends.change(s, NOON + H, 3 * H) is None    # nothing fresh


def test_pressure_drop_told_once_with_notice_and_post():
    w, notes, posts, buzz = _watch()
    end = _feed(w, NOON - 3 * H, 180, pressure=lambda m: 1012 - m * 4 / 180, temp=lambda m: 60)
    said = w.due("sleep", end)
    assert said and "pressure is dropping" in said and "4 millibars" in said
    assert notes == ["Pressure dropping: -4 mb in 3 h"]
    assert not buzz                                    # phone only for frost here
    topic, body = posts[-1]
    assert topic == "chatty/trends" and body["pressure_source"] == "greenhouse"
    assert "pressure" in body["advisories"] and body["pressure_3h"] < -3
    assert w.due("sleep", end + 60) is None
    _feed(w, end + 300, 60, pressure=lambda m: 1008 - m * 2 / 60)
    assert len(notes) == 1                             # still dropping: no repeat


def test_fast_drop_and_humidity():
    w, notes, _, _ = _watch()
    end = _feed(w, NOON - 3 * H, 180, pressure=lambda m: 1010 - m * 7 / 180,
                humidity=lambda m: 60 + m / 9)
    said = w.due("sleep", end)
    assert "falling fast" in said and "more humid" in said
    assert "falling fast" in notes[0] and "humidity rising" in notes[0]


def test_steady_pressure_says_nothing():
    w, notes, _, _ = _watch()
    end = _feed(w, NOON - 3 * H, 180, pressure=lambda m: 1015 + (m % 10) * 0.05, temp=lambda m: 70)
    assert w.due("sleep", end) is None and not notes
    assert "holding steady" in w.answer("is the pressure dropping", end)


def test_frost_watch_buzzes_phone_and_wins():
    w, notes, _, buzz = _watch()
    end = _feed(w, NOON - 2 * H, 120, temp=lambda m: 48 - m * 4.5 / 60)   # 48 -> 39, 4.5 F an hour
    said = w.due("sleep", end)
    assert said and "cooling fast" in said and "freezing around" in said
    assert buzz and "freeze" in buzz[0]
    assert "cold" not in w.told                        # frost covers it


def test_already_near_freezing():
    w, notes, _, _ = _watch()
    end = _feed(w, NOON - H, 60, temp=lambda m: 36 - m * 3 / 60)
    assert "Frost watch" in w.due("sleep", end)


def test_cold_snap():
    w, notes, _, _ = _watch()
    end = _feed(w, NOON - 2 * H, 120, temp=lambda m: 80 - m * 18 / 120)
    said = w.due("sleep", end)
    assert "degrees in the last 2 hours" in said and "cold front" in said


def test_warm_sunset_cooling_is_not_news():
    w, notes, _, _ = _watch()
    end = _feed(w, NOON - 2 * H, 120, temp=lambda m: 85 - m * 8 / 120)
    assert w.due("sleep", end) is None and not notes


def test_night_and_bedtime_only_notice():
    for night, tucked in ((True, False), (False, True)):
        w, notes, _, _ = _watch(night=night, tucked=tucked)
        end = _feed(w, NOON - 3 * H, 180, pressure=lambda m: 1012 - m * 4 / 180)
        assert notes and w.due("sleep", end) is None


def test_waits_while_busy_then_goes_stale():
    w, notes, _, _ = _watch()
    end = _feed(w, NOON - 3 * H, 180, pressure=lambda m: 1012 - m * 4 / 180)
    assert w.due("active", end) is None
    assert w.due("sleep", end + 46 * 60) is None       # old news: the notice says it


def test_rearms_after_clear_and_gap():
    w, notes, _, _ = _watch()
    end = _feed(w, NOON - 3 * H, 180, pressure=lambda m: 1012 - m * 4 / 180)
    end = _feed(w, end + 300, 7 * 60, pressure=lambda m: 1008)            # steady for 7 h
    end = _feed(w, end + 300, 180, pressure=lambda m: 1008 - m * 4 / 180)
    assert len(notes) == 2


def test_remembers_across_restarts():
    path = Path(tempfile.mkdtemp()) / "t.json"
    w, notes, _, _ = _watch(path=path)
    end = _feed(w, NOON - 3 * H, 180, pressure=lambda m: 1012 - m * 4 / 180)
    w._save(end)
    w2, notes2, _, _ = _watch(path=path)
    assert len(w2.series["pressure"]) == len(w.series["pressure"]) and "pressure" in w2.told
    _feed(w2, end + 300, 30, pressure=lambda m: 1008 - m / 60)
    assert not notes2                                   # already told before the restart


def test_station_pressure_when_greenhouse_has_none():
    readings = [(NOON - (4 - i) * H, 1015 - i * 1.5) for i in range(5)]   # hourly, 6 hPa down in 4 h
    w, notes, _, _ = _watch(nws=lambda: readings)
    w.check(NOON)
    for _ in range(50):
        if not w._fetching and w.nws_series:
            break
        time.sleep(0.02)
    s = w.snapshot(NOON)
    assert s["pressure_source"] == "weather station" and abs(s["pressure_3h"] + 4.5) < 0.01
    assert "at the weather station" in w.answer("what's the barometer", NOON)
    assert notes and "dropping" in notes[0]


def test_glitches_ignored():
    w, notes, _, _ = _watch()
    w.on_data("greenhouse", {"air_pressure_hpa": 0, "air_temperature_f": "n/a"}, NOON)
    w.on_data("rain", {"air_pressure_hpa": 1000}, NOON)
    assert not any(w.series.values())


def test_answers():
    w, _, _, _ = _watch()
    assert "not getting an air pressure" in w.answer("is the pressure dropping", NOON)
    end = _feed(w, NOON - 3 * H, 180, temp=lambda m: 69 - m * 3 / 60)
    assert "down 6 in the last 2 hours" in w.answer("is it getting colder in the greenhouse", end)


def test_asked():
    for q in ("is the pressure dropping", "what's the barometer", "what's the air pressure",
              "weather trends", "is a storm coming", "is it getting colder in the greenhouse",
              "what's the barometric pressure doing"):
        assert trends.asked(q), q
    for q in ("check my blood pressure", "what's the weather", "is rain coming", "red alert"):
        assert not trends.asked(q), q


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
