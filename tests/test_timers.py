import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import timers  # noqa: E402
from face_model import FaceModel  # noqa: E402

NOW = datetime(2026, 11, 6, 15, 0).timestamp()     # a Friday, 3 pm


def hm(ts):
    d = datetime.fromtimestamp(ts)
    return d.strftime("%a %H:%M")


def test_durations():
    cases = {
        "set a timer for ten minutes": 600, "start a 90 second timer": 90,
        "timer for an hour and a half": 5400, "set a timer for half an hour": 1800,
        "remind me in 5 minutes": 300, "set a timer for twenty five minutes": 1500,
        "set a timer for two and a half minutes": 150, "set a timer for 1 hour 30 minutes": 5400,
        "set a timer for a minute": 60, "timer for 10min": 600,
    }
    for text, secs in cases.items():
        assert timers.understand(text, NOW) == {"do": "timer", "seconds": secs}, text
    assert timers.understand("set a timer", NOW) == {"do": "timer", "seconds": None}


def test_alarms():
    cases = {
        "set an alarm for 7 am": "Sat 07:00", "wake me up at six thirty": "Fri 18:30",
        "alarm for 7:45 pm": "Fri 19:45", "set an alarm for seven": "Fri 19:00",
        "wake me up in 20 minutes": "Fri 15:20", "set an alarm for noon": "Sat 12:00",
        "alarm at half past seven": "Fri 19:30", "set an alarm for quarter to eight": "Fri 19:45",
        "set an alarm for six in the morning": "Sat 06:00", "wake me up at seven oh five am": "Sat 07:05",
    }
    for text, when in cases.items():
        u = timers.understand(text, NOW)
        assert u["do"] == "alarm" and hm(u["when"]) == when, (text, u and hm(u["when"]))


def test_other_requests_and_non_requests():
    assert timers.understand("how much time is left", NOW) == {"do": "left"}
    assert timers.understand("cancel the timer", NOW) == {"do": "cancel", "kind": "timer", "all": False}
    assert timers.understand("cancel all alarms", NOW) == {"do": "cancel", "kind": "alarm", "all": True}
    for text in ("what time is it", "tell me a joke", "whats the weather tomorrow"):
        assert timers.understand(text, NOW) is None, text


class Clock:
    def __init__(self):
        self.now = NOW
    def __call__(self):
        return self.now


def _timers(tmp):
    c, sent = Clock(), []
    return timers.Timers(path=Path(tmp) / "timers.json", clock=c, face=sent.append), c, sent


def test_timer_rings_once_and_face_counts_down():
    with tempfile.TemporaryDirectory() as tmp:
        t, c, sent = _timers(tmp)
        item = t.add_timer(600)
        assert item["label"] == "10 minute" and sent[-1].startswith(f"timer:{NOW + 600:.0f}:timer:")
        assert t.due() is None
        c.now += 601
        rung = t.due()
        assert rung["label"] == "10 minute" and timers.ring_text(rung) == "Ding! Your 10 minute timer is done."
        assert t.due() is None and sent[-1] == "timer:"


def test_alarm_rings_again_until_silenced():
    with tempfile.TemporaryDirectory() as tmp:
        t, c, _ = _timers(tmp)
        t.add_alarm(NOW + 60)
        c.now += 61
        assert t.due()["kind"] == "alarm"
        c.now += 61
        again = t.due()
        assert again and again["again"]
        assert t.silence() and t.due() is None
        c.now += 600
        assert t.due() is None


def test_alarm_stops_after_three_rings():
    with tempfile.TemporaryDirectory() as tmp:
        t, c, _ = _timers(tmp)
        t.add_alarm(NOW + 1)
        rings = 0
        for _ in range(10):
            c.now += 61
            if t.due():
                rings += 1
        assert rings == timers.ALARM_RINGS


def test_saved_across_restarts_and_cancel():
    with tempfile.TemporaryDirectory() as tmp:
        t, c, _ = _timers(tmp)
        t.add_timer(300)
        t.add_alarm(NOW + 3600)
        t2, _, _ = _timers(tmp)
        assert [i["kind"] for i in t2.items] == ["timer", "alarm"]
        assert oct(os.stat(Path(tmp) / "timers.json").st_mode & 0o777) == "0o600"
        assert "5 minutes left" in t2.summary() and "4:00 PM" in t2.summary()
        assert t2.cancel("timer")[0]["label"] == "5 minute"
        assert t2.cancel("timer") == []


def test_limit():
    with tempfile.TemporaryDirectory() as tmp:
        t, _, _ = _timers(tmp)
        for i in range(timers.MAX_ITEMS):
            t.add_timer(60 * (i + 1))
        assert t.full()


def test_face_chip():
    f = FaceModel(800, 480)
    f.set_timer(f"{NOW + 582}:timer:10 minute")
    assert f.timer_text(NOW) == "Timer 9:42"
    f.set_timer(f"{NOW + 3700}:timer:1 hour 2 minute")
    assert f.timer_text(NOW) == "Timer 1:01:40"
    f.set_timer(f"{NOW + 3600}:alarm:7:00 AM")
    assert f.timer_text(NOW) == "Alarm 7:00 AM"
    f.set_timer("")
    assert f.timer_text(NOW) == ""


if __name__ == "__main__":
    os.environ.setdefault("CHATTY_GAMES", "0")
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
