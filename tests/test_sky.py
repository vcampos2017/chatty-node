import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["CHATTY_CURIOSITY"] = "0"
os.environ["CHATTY_GAMES"] = "0"
os.environ["CHATTY_DOODLES"] = "0"
os.environ["CHATTY_NIGHT_MODE"] = "0"
import mesh  # noqa: E402
import sky  # noqa: E402
from face_model import FaceModel  # noqa: E402

T = 1_000_000.0


def _watch(night=False):
    sent, notes = [], []
    w = sky.SkyWatch(face=sent.append, notice=notes.append, is_night=lambda now: night)
    return w, sent, notes


def test_rain_starts_and_is_said_once():
    w, sent, _ = _watch()
    w.on_data("rain", {"rain_in": 0, "rate_mm_hr": 0, "tip_count": 10}, T)
    assert sent == ["sky:dry"] and not w.raining
    w.on_data("rain", {"rain_in": 0.01, "rate_mm_hr": 0, "tip_count": 11}, T + 60)
    assert sent[-1] == "sky:rain" and w.raining
    assert "raining" in w.due("sleep")
    w.on_data("rain", {"rain_in": 0.02, "rate_mm_hr": 0.5, "tip_count": 12}, T + 120)
    assert w.due("sleep") is None            # not said again for the same rain


def test_rain_stops_after_quiet_bucket():
    w, sent, _ = _watch()
    w.on_data("rain", {"rate_mm_hr": 0, "tip_count": 1}, T)
    w.on_data("rain", {"rate_mm_hr": 0, "tip_count": 2}, T + 60)
    w.on_data("rain", {"rate_mm_hr": 0, "tip_count": 2}, T + 60 + 21 * 60)
    assert sent[-1] == "sky:dry" and not w.raining


def test_only_new_lightning_counts():
    w, sent, notes = _watch()
    old = {"last_strike": {"ts": T - 3600, "distance_mi": 5.0}}
    w.on_data("lightning", old, T)            # retained from an hour ago
    assert sent == [] and w.due("sleep") is None
    new = {"last_strike": {"ts": T + 5, "distance_km": 6, "distance_mi": 3.7}}
    w.on_data("lightning", new, T + 6)
    assert sent == ["sky:strike:3.7"]
    text = w.due("sleep")
    assert "about 4 miles away" in text and "come in" in text
    w.on_data("lightning", new, T + 66)       # same strike repeated with the heartbeat
    assert sent == ["sky:strike:3.7"]
    w.on_data("lightning", {"last_strike": {"ts": T + 100, "distance_mi": 3.0}}, T + 101)
    assert sent[-1] == "sky:strike:3.0" and w.due("sleep") is None   # same storm: flash only


def test_lightning_at_night_is_a_notice():
    w, sent, notes = _watch(night=True)
    w.on_data("lightning", {"last_strike": {"ts": T, "distance_mi": 12}}, T + 1)
    assert w.due("sleep") is None and notes and "12 miles" in notes[0]


def test_waits_until_she_is_free():
    w, _, _ = _watch()
    w.on_data("lightning", {"last_strike": {"ts": T, "distance_mi": 2}}, T + 1)
    assert w.due("active") is None
    assert w.due("sleep")


def test_bad_readings_are_ignored():
    w, sent, _ = _watch()
    w.on_data("lightning", {"last_strike": "nope"}, T)
    w.on_data("rain", {"rate_mm_hr": "wet", "tip_count": "x"}, T)
    w.on_data("lightning", {"last_strike": {"ts": "soon"}}, T)


def test_mesh_hands_readings_over():
    got = []
    m = mesh.Mesh(on_events=lambda e: None, clock=lambda: T, on_data=lambda *a: got.append(a))
    msg = type("M", (), {"topic": "chatty/nodes/rain/data", "payload": json.dumps({"tip_count": 3}).encode()})
    m._on_message(None, None, msg)
    msg.topic = "chatty/nodes/chatty/data"
    m._on_message(None, None, msg)
    assert got == [("rain", {"tip_count": 3}, T)]


def _face():
    f = FaceModel(800, 480, rng=random.Random(1))
    f.last_activity = T
    return f


def _count_text(f, at):
    return f._thunder_text(at)[0]


def test_face_counts_mississippi_then_boom():
    f = _face()
    f.set_sky("strike:1.2", now=T)          # 6 seconds of counting
    assert f.busy()
    assert _count_text(f, T + 1.0) == "One Mississippi..."
    assert _count_text(f, T + 3.7) == "Four Mississippi..."
    assert _count_text(f, T + 7.0).startswith("Boom! About 1 mile away")
    f.update(0.1, T + 12)
    assert f.thunder is None


def test_face_far_lightning_and_hurried_count():
    f = _face()
    f.set_sky("strike:14", now=T)
    assert _count_text(f, T + 2) == "Lightning, about 14 miles away"
    f = _face()
    f.set_sky("strike:4", now=T)            # 20 s: real seconds to 10, then fast
    assert _count_text(f, T + 0.6 + 10.3) == "Twelve Mississippi..."
    assert _count_text(f, T + 0.6 + 12.6).startswith("Boom!")


def test_face_rain_drops_come_and_go():
    f = _face()
    f.set_sky("rain", now=T)
    f.update(0.1, T + 1)
    assert f.raining(T + 1) and f.drops
    f.set_sky("dry", now=T + 2)
    f.update(0.1, T + 3)
    assert not f.raining(T + 3) and f.drops == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
