import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import mesh  # noqa: E402

T0 = 1_000_000.0


def _status(state="online", ts=None, every=60):
    body = {"state": state, "every": every}
    if ts is not None:
        body["ts"] = ts
    return json.dumps(body).encode()


def _tracker(phone_minutes=30):
    return mesh.Tracker(misses=3, phone_minutes=phone_minutes)


def _kinds(events):
    return [(k, n.name) for k, n in events]


def test_titles():
    assert mesh.title_for("rain") == "Rain node"
    assert mesh.title_for("rain-node") == "Rain node"
    assert mesh.title_for("wordclock") == "Wordclock node"


def test_first_news_is_silent():
    t = _tracker()
    assert t.message("chatty/nodes/rain/status", _status(ts=T0), T0) == []
    assert t.nodes["rain"].online
    # a node that was already offline when Chatty started: no notice, no phone later
    assert t.message("chatty/nodes/clock/status", _status("offline"), T0) == []
    assert not t.nodes["clock"].online
    assert t.tick(T0 + 3600) == [("quiet", t.nodes["rain"])]
    assert _kinds(t.tick(T0 + 4000)) == []


def test_last_will_means_quiet_right_away_then_back():
    t = _tracker()
    t.message("chatty/nodes/rain/status", _status(ts=T0), T0)
    assert _kinds(t.message("chatty/nodes/rain/status", _status("offline"), T0 + 10)) == [("quiet", "rain")]
    assert _kinds(t.message("chatty/nodes/rain/status", _status(ts=T0 + 70), T0 + 70)) == [("back", "rain")]


def test_missed_heartbeats_then_phone_once():
    t = _tracker(phone_minutes=30)
    t.message("chatty/nodes/rain/status", _status(ts=T0), T0)
    assert t.tick(T0 + 170) == []                       # under 3 x 60 s
    assert _kinds(t.tick(T0 + 200)) == [("quiet", "rain")]
    assert t.tick(T0 + 200 + 60) == []
    assert _kinds(t.tick(T0 + 200 + 1800)) == [("phone", "rain")]
    assert t.tick(T0 + 200 + 3600) == []                # only once
    events = t.message("chatty/nodes/rain/status", _status(ts=T0 + 4000), T0 + 4000)
    assert _kinds(events) == [("back", "rain")] and events[0][1].phoned


def test_phone_off():
    t = _tracker(phone_minutes=0)
    t.message("chatty/nodes/rain/status", _status(ts=T0), T0)
    t.tick(T0 + 200)
    assert t.tick(T0 + 99999) == []


def test_own_heartbeat_and_junk_ignored():
    t = _tracker()
    assert t.message("chatty/nodes/chatty/status", _status(ts=T0), T0) == []
    assert t.message("something/else", b"hi", T0) == []
    assert t.message("chatty/nodes/rain/status", b"not json", T0) == []   # treated as online
    assert "chatty" not in t.nodes and t.nodes["rain"].online


def test_data_and_summary():
    t = _tracker()
    assert t.summary() == "No other nodes have checked in with me yet."
    t.message("chatty/nodes/rain/status", _status(ts=T0), T0)
    t.message("chatty/nodes/rain/data", json.dumps({"rain_in": 0.12}).encode(), T0 + 5)
    assert t.latest("rain", now=T0 + 10) == {"rain_in": 0.12}
    assert t.latest("rain", max_age=60, now=T0 + 100) is None
    t.message("chatty/nodes/clock/status", _status(ts=T0), T0)
    t.message("chatty/nodes/clock/status", _status("offline"), T0 + 20)
    text = t.summary()
    assert text.startswith("Rain node is online. Clock node has been quiet since "), text


def test_handle_shows_and_phones():
    shown, sent = [], []
    t = _tracker()
    t.message("chatty/nodes/rain/status", _status(ts=T0), T0)
    mesh.handle(t.tick(T0 + 200), shown.append, sent.append)
    assert shown[0].startswith("Rain node went quiet (last heard ") and not sent
    mesh.handle(t.tick(T0 + 2100), shown.append, sent.append)
    assert len(sent) == 1 and "quiet for 30 minutes" in sent[0]
    mesh.handle(t.message("chatty/nodes/rain/status", _status(ts=T0 + 2200), T0 + 2200),
                shown.append, sent.append)
    assert shown[-1] == "Rain node is back" and sent[-1] == "Chatty: Rain node is back online."


def test_nodes_on_tailscale_are_mentioned():
    t = _tracker()
    body = json.dumps({"state": "online", "every": 60, "ts": T0, "via": "tailscale"}).encode()
    t.message("chatty/nodes/rain/status", body, T0)
    t.message("chatty/nodes/greenhouse/status",
              json.dumps({"state": "online", "ts": T0, "via": "lan"}).encode(), T0)
    text = t.summary()
    assert "Greenhouse node and Rain node are online" in text
    assert "Rain node is reaching me through Tailscale" in text
    assert "Greenhouse node is reaching" not in text


def test_hub_note_is_posted_on_connect_and_on_change():
    import hub_note
    sent = []

    class C:
        def subscribe(self, *a, **k):
            pass

        def publish(self, topic, payload, qos=0, retain=False):
            sent.append((topic, payload, retain))

    lan = [["192.168.1.50"]]
    folder = __import__("tempfile").mkdtemp()
    m = mesh.Mesh(on_events=lambda e: None)
    m.client = C()
    m.hub = hub_note.HubNote(path=os.path.join(folder, "hub.json"), look=lambda: (lan[0], "100.69.130.79"),
                             wifi=lambda: "GF-Home" if lan[0] == ["192.168.1.50"] else "AVC-2G")
    m._on_connect(m.client, None, {}, 0)
    hubs = [p for t, p, r in sent if t == "chatty/hub" and r]
    assert len(hubs) == 1 and json.loads(hubs[0])["wifi"] == "GF-Home"
    m._post_hub()
    assert len([1 for t, p, r in sent if t == "chatty/hub"]) == 1     # nothing new
    lan[0] = ["192.168.1.77"]
    m._post_hub()
    note = json.loads(sent[-1][1])
    assert note["wifi"] == "AVC-2G" and note["lan"] == ["192.168.1.77"]
    assert note["known"] == {"GF-Home": "192.168.1.50", "AVC-2G": "192.168.1.77"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
