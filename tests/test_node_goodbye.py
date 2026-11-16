"""A node that shuts down or restarts properly says goodbye; Chatty waits quietly."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import mesh  # noqa: E402
import node_rest  # noqa: E402

T0 = 1_000_000.0
TOPIC = "chatty/nodes/rain/status"


def _online(ts):
    return json.dumps({"state": "online", "every": 60, "ts": ts}).encode()


def _goodbye(reason="reboot", **extra):
    body = {"state": "offline", "clean": True, "reason": reason, "ts": T0}
    body.update(extra)
    return json.dumps(body).encode()


def _tracker(**kw):
    rests = []
    kw.setdefault("on_rest", lambda nodes: rests.append(dict(nodes)))
    kw.setdefault("clean", True)
    t = mesh.Tracker(misses=3, phone_minutes=30, grace=180,
                     reboot_wait=600, shutdown_wait=3600, rest_max=24 * 3600, **kw)
    t.message(TOPIC, _online(T0), T0)
    return t, rests


def _kinds(events):
    return [(k, n.name) for k, n in events]


def test_reboot_back_in_time_makes_no_notice():
    t, rests = _tracker()
    assert t.message(TOPIC, _goodbye("reboot"), T0 + 10) == []
    assert rests[-1]["rain"]["reason"] == "reboot"
    assert rests[-1]["rain"]["until"] == T0 + 10 + 600
    for m in range(1, 10):
        assert t.tick(T0 + 10 + m * 60) == []            # past the usual 3 min grace: still quiet
    assert "restarting" in t.summary()
    assert _kinds(t.message(TOPIC, _online(T0 + 400), T0 + 400)) == [("rested", "rain")]
    assert rests[-1] == {}
    assert t.nodes["rain"].online
    # the last will after the goodbye (the clean leave failed) changes nothing
    t2, _ = _tracker()
    t2.message(TOPIC, _goodbye("reboot"), T0 + 10)
    assert t2.message(TOPIC, json.dumps({"state": "offline"}).encode(), T0 + 12) == []
    assert t2.tick(T0 + 300) == []


def test_not_back_in_time_is_quiet_then_phone():
    t, rests = _tracker()
    t.message(TOPIC, _goodbye("shutdown"), T0)
    assert t.tick(T0 + 3599) == []
    assert _kinds(t.tick(T0 + 3600)) == [("quiet", "rain")]
    assert rests[-1] == {}                               # overdue: other checkers may speak up
    assert t.tick(T0 + 3600 + 1799) == []                # phone counts from the end of the wait
    assert _kinds(t.tick(T0 + 3600 + 1800)) == [("phone", "rain")]
    assert _kinds(t.message(TOPIC, _online(T0 + 7000), T0 + 7000)) == [("back", "rain")]


def test_back_within_and_its_cap():
    t, _ = _tracker()
    t.message(TOPIC, _goodbye("shutdown", back_within=3 * 3600), T0)
    assert t.tick(T0 + 3 * 3600 - 1) == []
    assert _kinds(t.tick(T0 + 3 * 3600)) == [("quiet", "rain")]
    t, _ = _tracker()
    t.message(TOPIC, _goodbye("shutdown", back_within=999 * 3600), T0)
    assert t.nodes["rain"].rest_until == T0 + 24 * 3600
    t, _ = _tracker()
    t.message(TOPIC, _goodbye("restart", back_within="soon"), T0)
    assert t.nodes["rain"].rest_until == T0 + 600


def test_turned_off_or_first_news_is_like_before():
    t, _ = _tracker(clean=False)
    t.message(TOPIC, _goodbye("reboot"), T0)
    assert _kinds(t.tick(T0 + 180)) == [("quiet", "rain")]
    # a goodbye already on the board when Chatty starts: noted silently, as always
    t = mesh.Tracker(misses=3, phone_minutes=30, grace=180, clean=True, on_rest=lambda n: None)
    assert t.message(TOPIC, _goodbye("shutdown"), T0) == []
    assert t.tick(T0 + 10 * 3600) == []


def test_notice_and_phone_words():
    t, _ = _tracker()
    t.message(TOPIC, _goodbye("shutdown"), T0)
    shown, sent = [], []
    mesh.handle(t.tick(T0 + 3600), show=shown.append, send=sent.append)
    assert "shut down properly" in shown[0] and "hasn't come back" in shown[0]
    mesh.handle(t.tick(T0 + 5400), show=shown.append, send=sent.append)
    assert "hasn't come back" in sent[0]
    mesh.handle([("rested", t.nodes["rain"])], show=shown.append, send=sent.append)
    assert len(shown) == 1 and len(sent) == 1           # back in time: nothing shown


def test_node_rest_file_round_trip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "node_rest.json")
        node_rest.save({"greenhouse": {"until": T0 + 60, "since": T0, "reason": "reboot"}}, path)
        assert node_rest.resting("greenhouse", now=T0 + 30, path=path)["reason"] == "reboot"
        assert node_rest.resting("greenhouse", now=T0 + 61, path=path) is None
        assert node_rest.resting("rain", now=T0, path=path) is None
        assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert node_rest.resting("x", path="/nonexistent/node_rest.json") is None


def test_stop_reason_from_systemd_jobs():
    r = node_rest.reason_from_jobs
    assert r("1 reboot.target start waiting\n2 shutdown.target start waiting\n") == "reboot"
    assert r("5 poweroff.target start waiting\n") == "shutdown"
    assert r("9 chatty-voice.service restart running\n") == "restart"
    assert r("") == "stop"

    class Out:
        stdout = "7 halt.target start waiting\n"
    assert node_rest.stop_reason(run=lambda *a, **k: Out()) == "shutdown"

    def boom(*a, **k):
        raise OSError("no systemctl")
    assert node_rest.stop_reason(run=boom) == "stop"


def test_chatty_says_goodbye_without_her_last_will():
    calls = []

    class Info:
        def wait_for_publish(self, timeout):
            calls.append(("wait", timeout))

    class Client:
        def publish(self, topic, payload, qos=0, retain=False):
            calls.append(("publish", topic, json.loads(payload), retain))
            return Info()

        def disconnect(self):
            calls.append(("disconnect",))

        def loop_stop(self):
            calls.append(("loop_stop",))

    m = mesh.Mesh(tracker=mesh.Tracker(on_rest=lambda n: None))
    assert m.goodbye("reboot") is False                  # not connected: nothing to do
    m.client, m.connected = Client(), True
    assert m.goodbye("reboot") is True
    kind, topic, body, retain = calls[0]
    assert topic == "chatty/nodes/chatty/status" and retain
    assert body["state"] == "offline" and body["clean"] is True and body["reason"] == "reboot"
    assert [c[0] for c in calls] == ["publish", "wait", "disconnect", "loop_stop"]
    assert not m.connected


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
