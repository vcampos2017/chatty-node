import os
import sys
import tempfile
import time

os.environ["CHATTY_ALERTS_SEEN"] = os.path.join(tempfile.mkdtemp(), "seen.json")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import alerts  # noqa: E402


def _feature(id_, event, severity="Severe", refs=()):
    ends = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 3600))
    return {"properties": {
        "id": id_, "event": event, "severity": severity, "status": "Actual",
        "messageType": "Alert", "ends": ends, "instruction": "Take shelter now.",
        "description": "A tornado was seen.", "references": [{"identifier": r} for r in refs]}}


def _watcher(features, got):
    return alerts.Watcher(fetch=lambda: features, on_new=got.append)


def test_new_alert_is_handed_off_once():
    got = []
    feats = [_feature("a1", "Tornado Warning")]
    w = _watcher(feats, got)
    w.check_once()
    w.check_once()
    assert [a.event for a in got] == ["Tornado Warning"]


def test_updates_are_not_repeated():
    got = []
    feats = [_feature("b1", "Severe Thunderstorm Warning")]
    w = _watcher(feats, got)
    w.check_once()
    feats[:] = [_feature("b2", "Severe Thunderstorm Warning", refs=("b1",))]
    w.check_once()
    assert len(got) == 1


def test_screen_text():
    a = alerts.parse(_feature("c1", "Tornado Warning"))
    text = alerts.screen_text(a)
    assert text.startswith("WEATHER ALERT: Tornado Warning until ")
    info = alerts.parse(_feature("c2", "Wind Advisory", severity="Moderate"))
    assert alerts.screen_text(info).startswith("Heads up: Wind Advisory")


def test_phone_modes():
    tornado = alerts.parse(_feature("d1", "Tornado Warning"))
    storm = alerts.parse(_feature("d2", "Severe Thunderstorm Warning"))
    watch = alerts.parse(_feature("d3", "Tornado Watch", severity="Moderate"))
    assert alerts.phone_wanted(tornado, "urgent") and alerts.phone_wanted(storm, "urgent")
    assert not alerts.phone_wanted(watch, "urgent")
    assert alerts.phone_wanted(tornado, "tornado") and not alerts.phone_wanted(storm, "tornado")
    assert not alerts.phone_wanted(watch, "tornado")
    assert alerts.phone_wanted(watch, "all") and not alerts.phone_wanted(tornado, "off")


def test_show_and_send():
    shown, sent = [], []
    a = alerts.parse(_feature("e1", "Tornado Warning"))
    alerts.show_and_send(a, show=shown.append, send=sent.append)
    assert shown and shown[0].startswith("WEATHER ALERT: Tornado Warning")
    assert sent and "Tornado Warning" in sent[0]


def test_active_list_goes_on_the_node_network():
    posted = []
    feats = [_feature("f1", "Wind Advisory", severity="Moderate"),
             _feature("f2", "Tornado Warning"), _feature("f3", "Tornado Warning")]
    w = alerts.Watcher(fetch=lambda: feats, on_new=lambda a: None,
                       publish=lambda t, b: posted.append((t, b)))
    w.check_once()
    topic, body = posted[-1]
    assert topic == "chatty/alerts/active"
    assert [a["event"] for a in body["alerts"]] == ["Tornado Warning", "Wind Advisory"]
    assert body["alerts"][0]["kind"] == "urgent" and body["alerts"][0]["expires_ts"] > time.time()
    assert "description" not in str(body) and "seen" not in str(body)
    feats[:] = []
    w.check_once()
    assert posted[-1][1]["alerts"] == []


def test_failed_check_posts_nothing():
    posted = []

    def broken():
        raise OSError("no internet")
    w = alerts.Watcher(fetch=broken, on_new=lambda a: None,
                       publish=lambda t, b: posted.append(b))
    w.check_once()
    assert posted == []


def test_broker_trouble_is_harmless():
    def boom(t, b):
        raise RuntimeError("broker down")
    w = alerts.Watcher(fetch=lambda: [_feature("g1", "Tornado Warning")], on_new=lambda a: None,
                       publish=boom)
    w.check_once()   # no exception
    assert w.ok


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
