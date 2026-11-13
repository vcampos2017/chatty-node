import os
import random
import sys
import tempfile
import time
import wave

os.environ["CHATTY_ALERTS_SEEN"] = os.path.join(tempfile.mkdtemp(), "seen.json")
os.environ["CHATTY_CURIOSITY"] = "0"
os.environ["CHATTY_GAMES"] = "0"
os.environ["CHATTY_DOODLES"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import alerts  # noqa: E402
import red_alert  # noqa: E402
from face_model import FaceModel  # noqa: E402

T = 1_000_000.0


def _feature(id_, event, severity="Extreme", minutes=45, refs=()):
    ends = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + minutes * 60))
    return {"properties": {
        "id": id_, "event": event, "severity": severity, "status": "Actual",
        "messageType": "Alert", "ends": ends, "instruction": "Take cover now.",
        "description": "A tornado was seen.", "references": [{"identifier": r} for r in refs]}}


class Canvas:
    """Records what gets drawn (enough to see the banner)."""
    def __init__(self):
        self.texts = []

    def text(self, txt, pos, size, color):
        self.texts.append(txt)

    def measure(self, txt, size):
        return len(txt) * size * 0.5

    def __getattr__(self, name):
        return lambda *a, **k: None


# ----- only a Tornado Warning -----

def test_only_tornado_warning_is_red():
    assert alerts.parse(_feature("a", "Tornado Warning")).red
    assert not alerts.parse(_feature("b", "Tornado Watch", severity="Severe")).red
    assert not alerts.parse(_feature("c", "Severe Thunderstorm Warning")).red
    assert not alerts.parse(_feature("d", "Flash Flood Warning")).red
    assert alerts.screen_text(alerts.parse(_feature("e", "Tornado Warning"))).startswith("RED ALERT: Tornado Warning until")


def test_red_alert_is_not_said_twice():
    got, sent = [], []
    feats = [_feature("r1", "Tornado Warning"), _feature("s1", "Severe Thunderstorm Warning")]
    w = alerts.Watcher(fetch=lambda: feats, on_new=got.append)
    w.check_once()
    assert [a.event for a in got] == ["Tornado Warning", "Severe Thunderstorm Warning"]
    assert [a.event for a in w.pending] == ["Severe Thunderstorm Warning"]   # red one: Red Alert says it
    assert w.red_warning().id == "r1"
    feats[:] = []                       # the NWS dropped it (cancelled)
    w.check_once()
    assert w.red_warning() is None


def test_feed_trouble_keeps_red_alert():
    feats = [_feature("r2", "Tornado Warning")]
    def fetch():
        if not feats:
            raise OSError("no internet")
        return feats
    w = alerts.Watcher(fetch=fetch, on_new=lambda a: None)
    w.check_once()
    feats.clear()
    w.check_once()
    assert w.red_warning() is not None


def test_red_alert_always_buzzes_the_phone():
    shown, sent = [], []
    a = alerts.parse(_feature("p", "Tornado Warning"))
    old = alerts.PHONE
    try:
        for mode, want in (("urgent", 1), ("tornado", 1), ("all", 1), ("off", 0)):
            alerts.PHONE = mode
            sent.clear()
            alerts.show_and_send(a, show=shown.append, send=sent.append)
            assert len(sent) == want, mode
        assert sent == [] and shown[-1].startswith("RED ALERT")
        alerts.PHONE = "urgent"
        alerts.show_and_send(a, show=shown.append, send=sent.append)
        assert sent[0].startswith("RED ALERT from Chatty: Tornado Warning for home until")
    finally:
        alerts.PHONE = old


# ----- the red mode -----

class W:
    def __init__(self, expires):
        self.expires = expires


def test_start_ring_heard_end():
    r = red_alert.RedAlert(clock=lambda: T)
    assert r.step(None, T) is None
    assert r.step(W(T + 3000), T) == "start" and r.on and not r.test
    assert r.step(W(T + 3000), T + 10) is None
    assert r.step(W(T + 3000), T + red_alert.REPEAT) == "ring"
    assert r.acknowledge() and not r.acknowledge()
    assert r.step(W(T + 3000), T + 2 * red_alert.REPEAT) is None       # heard: no more alarms
    assert r.face_message().startswith(f"redalert:{int(T + 3000)}::")
    assert r.step(None, T + 2500) == "end" and not r.on
    assert r.face_message() == "redalert:off"


def test_rings_at_most_three_times_and_expires():
    r = red_alert.RedAlert()
    steps = [r.step(W(T + 9000), T + i * red_alert.REPEAT) for i in range(6)]
    assert steps.count("start") == 1 and steps.count("ring") == red_alert.RINGS - 1
    assert r.step(W(T + 9000), T + 9001) == "end"      # past its end time, even if still listed


def test_extended_warning_is_not_a_new_alarm():
    r = red_alert.RedAlert()
    r.step(W(T + 1000), T)
    assert r.step(W(T + 2000), T + 5) is None and r.expires == T + 2000


def test_safe_test_and_a_real_warning_takes_over():
    r = red_alert.RedAlert()
    r.start_test(T)
    assert r.step(None, T) == "start" and r.test
    assert ":test:" in r.face_message()
    assert r.step(None, T + red_alert.TEST_REPEAT) == "ring"
    assert r.step(None, T + 2 * red_alert.TEST_REPEAT) is None          # a test rings twice at most
    assert r.step(None, T + red_alert.TEST_SECONDS) == "end"
    r.start_test(T + 500)
    r.step(None, T + 500)
    assert r.step(W(T + 4000), T + 501) == "start" and not r.test      # the real thing


def test_words():
    first = red_alert.spoken(T + 600, first=True)
    assert first.startswith("Red alert! Red alert! There's a tornado warning for our area until")
    assert "safe place" in first and "test" not in first.lower()
    t = red_alert.spoken(T + 600, first=True, test=True)
    assert t.startswith("This is only a test.") and t.endswith("This was only a test.")
    assert "TEST" in red_alert.phone_text(T, test=True)
    assert "over" in red_alert.over_line()


# ----- her face -----

def test_face_goes_red_and_stays_awake():
    N = time.time()
    face = FaceModel(800, 480, rng=random.Random(1))
    face.state = "resting"
    face.doodle = object()
    face.add_notice("RED ALERT: Tornado Warning until 7:45 PM", now=N)
    face.set_red_alert(f"{N + 1800}::Tornado Warning", now=N)
    assert face.red_on(N) and face.doodle is None
    face.update(0.5, N + 1)
    assert face.state == "idle" and face.busy()
    for _ in range(20):
        face.update(0.1, N + 2)
    assert face.color[0] > 200 and face.color[1] < 120          # red eyes
    c = Canvas()
    face.draw(c, N + 3)
    assert "TORNADO WARNING" in c.texts and any(t.startswith("Take shelter now") for t in c.texts)
    assert face.handle_tap((400, 240), N + 4) is False          # a tap goes on to stop the alarm
    assert face.notices == []
    assert face.panel_info()["red_alert"]
    face.set_red_alert("off")
    assert not face.red_on(N + 5)


def test_face_test_banner_and_stale_red_goes_away():
    N = time.time()
    face = FaceModel(800, 480, rng=random.Random(1))
    face.set_red_alert(f"{N + 120}:test:Tornado Warning", now=N)
    c = Canvas()
    face.draw(c, N)
    assert "TEST - TORNADO WARNING" in c.texts
    assert not face.red_on(N + 601)           # the voice node went quiet: no stuck red screen


# ----- her alarm -----

def test_alarm_tone_is_made_here():
    import earcons
    path = os.path.join(tempfile.mkdtemp(), "red.wav")
    earcons._red_alert_wav(path)
    with wave.open(path) as w:
        seconds = w.getnframes() / w.getframerate()
    assert 3 < seconds < 6


# ----- the voice node -----

def _lift(*names):
    import ast
    src = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")
    tree = ast.parse(open(src).read())
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(fns) == len(names)
    return compile(ast.Module(body=fns, type_ignores=[]), src, "exec")


def test_voice_node_sounds_the_alarm():
    calls = []
    from types import SimpleNamespace as NS
    r = red_alert.RedAlert()
    r.start_test(T)
    r.step(None, T)
    ns = {"red": r, "red_alert": red_alert, "red_test_phone": True,
          "face": NS(send=lambda m: calls.append(("face", m)), caption=lambda t: None,
                     state=lambda s: calls.append(("state", s))),
          "earcons": NS(red_alert=lambda: calls.append("tone")),
          "alerts": NS(send_phone_alert=lambda t: calls.append(("phone", t))),
          "say": lambda t: calls.append(("say", t)),
          "log_turn": lambda *a, **k: None,
          "go_to_sleep": lambda: calls.append("sleep")}
    exec(_lift("red_alert_moment"), ns)
    ns["red_alert_moment"]("start")
    kinds = [c if isinstance(c, str) else c[0] for c in calls]
    assert kinds.index("tone") < kinds.index("say") and kinds[-1] == "sleep"
    assert calls[0][1].startswith("redalert:") and ":test:" in calls[0][1]
    assert any(c[0] == "phone" and c[1].startswith("TEST") for c in calls if isinstance(c, tuple))
    assert ns["red_test_phone"] is False
    calls.clear()
    ns["red_alert_moment"]("ring")
    assert not any(c[0] == "phone" for c in calls if isinstance(c, tuple))


def _lift_with_classes(*names):
    import ast
    src = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")
    tree = ast.parse(open(src).read())
    keep = [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    assert len(keep) == len(names)
    return compile(ast.Module(body=keep, type_ignores=[]), src, "exec")


class _Watch:
    def __init__(self):
        self.warning = None

    def red_warning(self):
        return self.warning


def _cut_in_ns():
    import threading
    import watchdog
    ns = {"threading": threading, "watchdog": watchdog, "red": red_alert.RedAlert(), "alert_watch": _Watch(),
          "red_test_wanted": None}
    exec(_lift_with_classes("RedCutIn", "red_waiting", "unless_red"), ns)
    return ns


def test_a_slow_answer_gives_way_to_red_alert():
    ns = _cut_in_ns()
    assert ns["unless_red"](lambda x: x * 2, 21) == 42          # nothing waiting: just the answer

    def slow():
        time.sleep(30)                 # the Pi model thinking it over
        return "an answer nobody hears"
    import threading
    threading.Timer(0.3, lambda: setattr(ns["alert_watch"], "warning", "Tornado Warning")).start()
    started = time.time()
    try:
        ns["unless_red"](slow)
        raise AssertionError("the answer should have been dropped")
    except ns["RedCutIn"]:
        pass
    assert time.time() - started < 2                             # not 30 s


def test_cut_in_gets_past_ordinary_error_handlers():
    ns = _cut_in_ns()
    ns["alert_watch"].warning = "Tornado Warning"
    try:
        try:
            ns["unless_red"](lambda: "x")
        except Exception:
            raise AssertionError("an `except Exception` must not swallow it")
    except ns["RedCutIn"]:
        pass


def test_no_cut_in_once_red_alert_is_on_or_without_a_watcher():
    ns = _cut_in_ns()
    ns["alert_watch"].warning = "Tornado Warning"
    ns["red"].on = True                     # Red Alert itself is talking: let it
    assert not ns["red_waiting"]() and ns["unless_red"](lambda: "ok") == "ok"
    ns["red"].on, ns["red_test_wanted"] = False, True
    assert ns["red_waiting"]()              # a test counts too
    del ns["alert_watch"]                   # very early at start-up
    assert not ns["red_waiting"]()


def test_errors_from_the_slow_call_come_back():
    ns = _cut_in_ns()

    def broken():
        raise TimeoutError("ollama")
    try:
        ns["unless_red"](broken)
        raise AssertionError("expected the timeout")
    except TimeoutError:
        pass


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
