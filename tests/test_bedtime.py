import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CHATTY_NIGHT_END", "7")
import backlight  # noqa: E402
import bedtime as bt  # noqa: E402
import mesh  # noqa: E402


def _at(hour, minute=0, day=11):
    return time.mktime((2026, 11, day, hour, minute, 0, 0, 0, -1))


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _forecast(low=38, high=61, short="Sunny", night_start=None):
    ns = night_start or _at(18)
    tomorrow = _at(6, day=12)
    return [
        {"name": "Tonight", "isDaytime": False, "temperature": low, "shortForecast": "Clear",
         "startTime": _iso(ns), "endTime": _iso(tomorrow)},
        {"name": "Thursday", "isDaytime": True, "temperature": high, "shortForecast": short,
         "startTime": _iso(tomorrow), "endTime": _iso(_at(18, day=12)),
         "probabilityOfPrecipitation": {"value": 60}},
        {"name": "Thursday Night", "isDaytime": False, "temperature": 40, "shortForecast": "Cloudy",
         "startTime": _iso(_at(18, day=12)), "endTime": _iso(_at(6, day=13))},
    ]


def _hourly(chances, start=None, summary="Chance Showers"):
    start = start or _at(6, day=12)
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
    m.hear("lightning", beat, {"sensor": "missing", "strikes_today": 0})
    m.hear("wordclock", beat)
    return m


def _wind(m=None, now=None, hourly=None, forecast=None, home=lambda: None, notes=None, rest=False):
    now = now or _at(21, 30)
    notes = [] if notes is None else notes
    state = Path(tempfile.mkdtemp()) / "b.json"
    return bt.WindDown(mesh=m, raining=lambda: False, home=home,
                       forecast=forecast or (lambda: _forecast()),
                       hourly=hourly or (lambda: _hourly([0, 10, 30, 60, 40, 0])),
                       notice=notes.append, clock=lambda: now,
                       start=lambda: 21 * 60 + 30, state_file=state, rest=rest)


def _wait(w):
    for _ in range(200):
        if not w._fetching:
            return
        time.sleep(0.01)


def test_tomorrow_and_swing():
    now = _at(21, 30)
    said, screen = bt.outlook(_forecast(), now)
    text = " ".join(said)
    assert text.startswith("Tomorrow: sunny, with a high around 61 degrees."), text
    assert "60 percent" not in text            # the hourly peak says the rain
    assert "23 degree swing. Twenty-three degrees! That's a big number." in text
    assert screen == "Tomorrow: Sunny 61°"
    said, _ = bt.outlook(_forecast(low=29, high=35), now)
    assert "only a 6 degree spread" in " ".join(said)
    assert "Frost watch" in " ".join(said)


def test_after_midnight_tomorrow_is_today():
    now = _at(1, 0, day=12)
    said, _ = bt.outlook(_forecast(), now)
    assert said[0].startswith("Today: sunny"), said


def test_afternoon_skips_this_afternoon():
    now = _at(14, 0)
    periods = [{"name": "This Afternoon", "isDaytime": True, "temperature": 55, "shortForecast": "Cloudy",
                "startTime": _iso(_at(13)), "endTime": _iso(_at(18))}] + _forecast()
    tonight, day = bt.pick_periods(periods, now)
    assert tonight["name"] == "Tonight" and day["name"] == "Thursday"


def test_rain_peak():
    now = _at(21, 30)
    day = _forecast()[1]
    said, screen = bt.rain_tomorrow(_hourly([0, 10, 30, 60, 40, 0]), day, now)
    assert "top out at 60 percent around 9 AM" in said and "coin flip" in said, said
    assert screen == "Rain 60%"
    said, _ = bt.rain_tomorrow(_hourly([0, 0, 0]), day, now)
    assert said.startswith("Zero percent"), said
    said, _ = bt.rain_tomorrow(_hourly([80], summary="Thunderstorms Likely"), day, now)
    assert said.startswith("Storm chances peak at 80 percent"), said
    said, _ = bt.rain_tomorrow([], day, now)       # no hourly: the day's own chance
    assert "60 percent" in said
    # tonight's hours don't count for tomorrow
    said, _ = bt.rain_tomorrow(_hourly([90, 90], start=_at(22)) + _hourly([5]), day, now)
    assert "5 percent or less" in said, said


def test_roll_call_perfect_attendance():
    now = _at(21, 30)
    said, screen = bt.roll_call(_all_online(now), now=now, tiny=False,
                                names=["greenhouse", "rain", "lightning", "wordclock"])
    assert "Greenhouse? Present! 58 degrees, soil at 52 percent." in said, said
    assert "Rain gauge? Present, and dry." in said
    assert "sensor is still snoozing" in said
    assert "Word clock? Present, and right on time." in said
    assert said.endswith("That's 4 for 4. Perfect attendance!"), said
    assert screen == "Nodes 4/4"


def test_roll_call_someone_quiet():
    now = _at(21, 30)
    m = _all_online(now)
    m.hear("rain", {"state": "offline"}, at=_at(18))
    said, screen = bt.roll_call(m, now=now, tiny=True,
                                names=["greenhouse", "rain", "lightning", "wordclock", "fruitjam"])
    assert "Rain gauge? ... Rain gauge? Quiet since" in said and "porch light" in said, said
    assert "Fruitjam node? No answer tonight." in said
    assert "That's 3 of 5, 60 percent attendance." in said
    assert "Tiny" in said
    assert screen == "Nodes 3/5"
    assert "isn't running" in bt.roll_call(None, now=now, names=["rain"])[0]


def test_unplugged_probe_and_thirsty():
    assert "soil probe isn't reporting" in bt._greenhouse({"metrics": {"air_temperature_f": 50,
                                                                       "soil_voltage": 0.0}})
    assert "job for the morning" in bt._greenhouse({"soil_moisture_percent": 10})


def test_scheduled_once_an_evening():
    now = _at(21, 30)
    notes = []
    w = _wind(_all_online(now), now=now, notes=notes)
    assert w.due("sleep", now) is None          # building in the background
    _wait(w)
    assert w.due("active", now + 1) is None     # busy: waits
    text = w.due("sleep", now + 2)
    assert text and text.split("!")[0] + "!" in bt.OPENERS or any(text.startswith(o) for o in bt.OPENERS), text
    assert "First, the outlook." in text and "Now, the node roll call!" in text
    assert notes and notes[0].startswith("Goodnight! Tomorrow: Sunny 61°"), notes
    assert w.due("sleep", now + 60) is None     # once
    # a restart the same evening doesn't repeat it
    w2 = bt.WindDown(mesh=None, forecast=lambda: [], hourly=lambda: [], notice=lambda t: None,
                     clock=lambda: now, start=lambda: 21 * 60 + 30, state_file=w.state_file)
    assert w2.due("sleep", now + 600) is None and not w2._fetching


def test_outside_window_and_off():
    w = _wind(now=_at(19))
    assert w.due("sleep", _at(19)) is None and not w._fetching
    assert w.due("sleep", _at(23, 30)) is None and not w._fetching   # 2 h late: let it go
    off = _wind()
    off.start = lambda: None
    assert off.due("sleep", _at(21, 30)) is None and not off._fetching


def test_nobody_home_only_the_notice():
    now = _at(21, 30)
    notes = []
    w = _wind(_all_online(now), now=now, home=lambda: False, notes=notes)
    w.due("sleep", now)
    _wait(w)
    assert w.due("sleep", now + 1) is None
    assert len(notes) == 1
    assert w.due("sleep", now + 2) is None and not w._fetching


def test_weather_down_still_does_roll_call():
    now = _at(21, 30)

    def down():
        raise OSError("offline")
    w = _wind(_all_online(now), now=now, forecast=down, hourly=down)
    text, screen = w.build(now)
    assert "tomorrow stays a mystery" in text and "Perfect attendance" in text
    assert screen == "Goodnight! Nodes 4/4"


def test_rest_tail_and_on_request():
    now = _at(21, 0)
    w = _wind(_all_online(now), now=now, rest=True)
    text, tonight = w.answer(now)
    assert tonight and text.endswith("Tap me if you need me.")
    assert w.due("sleep", _at(21, 30)) is None and not w._fetching    # already done tonight
    text, tonight = _wind(now=_at(14)).answer(_at(14))
    assert not tonight
    for p in ["wind down", "lets wind down", "bedtime routine", "tuck me in", "evening briefing",
              "give me the bedtime numbers"]:
        assert bt.asked(p), p
    for p in ["roll call", "do a roll call", "take attendance"]:
        assert bt.asked_roll_call(p) and not bt.asked(p), p
    for p in ["good night", "what's the weather tomorrow", "morning briefing", "down the hall"]:
        assert not bt.asked(p) and not bt.asked_roll_call(p), p


def test_screen_stays_dim_until_morning():
    d = backlight.Dimmer(is_night=lambda now: False)
    now = _at(21, 30)
    assert d.target("sleepy", now - 60, now) == 1.0
    d.bedtime(now)
    assert d.target("sleepy", now - 60, now) == backlight.NIGHT_LEVEL
    assert d.target("speaking", now - 60, now) == 1.0
    morning = _at(7, 5, day=12)
    assert d.target("idle", morning - 400, morning) == backlight.IDLE_LEVEL
    late = backlight.Dimmer(is_night=lambda now: False)
    late.bedtime(_at(1, 0, day=12))           # after midnight: until 7 the same morning
    assert late.bed_until == _at(7, 0, day=12)


def _lift(*names):
    """Lift functions out of the voice node (it opens the mic when imported)."""
    import ast
    src = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")
    tree = ast.parse(open(src).read())
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(fns) == len(names)
    return compile(ast.Module(body=fns, type_ignores=[]), src, "exec")


def test_voice_node_tucks_her_in():
    calls = []

    class Face:
        def state(self, s):
            calls.append(("state", s))

        def send(self, m):
            calls.append(("send", m))

    class Chat:
        def forget(self):
            calls.append("forget")

    class Ear:
        def lullaby(self):
            calls.append("lullaby")

    for rest, want_mode, want_face in [(False, "sleep", "sleepy"), (True, "resting", "resting")]:
        calls.clear()
        ns = {"face": Face(), "chat": Chat(), "earcons": Ear(), "mode": "active",
              "bedtime": type("B", (), {"REST": rest})}
        exec(_lift("tuck_in"), ns)
        ns["tuck_in"]()
        assert ns["mode"] == want_mode
        assert calls[:2] == ["lullaby", ("send", "bedtime")] and ("state", want_face) in calls


def test_voice_node_knows_when_nobody_is_home():
    from types import SimpleNamespace as NS
    for people, want in [({}, None), ({"V": NS(home=False)}, False), ({"V": NS(home=True)}, None),
                         ({"V": NS(home=None)}, None), ({"V": NS(home=False), "A": NS(home=True)}, None)]:
        ns = {"welcome": NS(enabled=bool(people), people=people)}
        exec(_lift("anyone_home"), ns)
        assert ns["anyone_home"]() is want, (people, want)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
