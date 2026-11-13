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
    assert text.startswith("RED ALERT: Tornado Warning until ")  # Red Alert (red_alert.py)
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
    assert shown and shown[0].startswith("RED ALERT: Tornado Warning")
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


def test_one_odd_entry_does_not_hide_the_rest():
    got = []
    feats = [{"properties": None}, {"properties": {"references": ["x"]}}, "junk",
             {"properties": dict(_feature("h1", "Tornado Warning")["properties"],
                                 references=["old-id", {"identifier": "z"}])}]
    w = _watcher(feats, got)
    w.check_once()
    assert [a.event for a in got] == ["Tornado Warning"] and w.ok
    assert w.red_warning() is not None


def test_checker_keeps_going_after_a_surprise():
    calls = []

    def fetch():
        calls.append(1)
        if len(calls) == 1:
            return 42                        # not a list at all
        raise KeyboardInterrupt              # stop the test loop
    w = alerts.Watcher(fetch=fetch, on_new=lambda a: None)
    real_sleep, alerts.time.sleep = alerts.time.sleep, lambda s: None
    try:
        w.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        alerts.time.sleep = real_sleep
    assert len(calls) == 2                   # the first surprise didn't stop it
    assert not w.ok                          # and it counted as a failed check


def test_garbled_feed_keeps_the_last_list():
    feed = {"x": [_feature("k1", "Tornado Warning")]}
    w = alerts.Watcher(fetch=lambda: feed["x"], on_new=lambda a: None)
    w.check_once()
    feed["x"] = {"oops": True}
    w.check_once()
    assert w.red_warning() is not None       # a bad answer never ends a Red Alert early


def test_long_outage_shows_one_notice_then_all_clear():
    shown, now = [], [1000.0]

    def broken():
        raise OSError("no internet")
    feed = {"fetch": broken}
    w = alerts.Watcher(fetch=lambda: feed["fetch"](), on_new=lambda a: None,
                       clock=lambda: now[0], notice=shown.append)
    w.check_once()
    assert shown == []                       # one miss is normal
    now[0] += alerts.STALE + 1
    w.check_once()
    w.check_once()
    assert shown == [alerts.STALE_NOTICE]    # once, not every 3 minutes
    assert "can't reach" in w.summary()
    feed["fetch"] = lambda: []
    w.check_once()
    assert shown == [alerts.STALE_NOTICE, alerts.BACK_NOTICE]
    w.check_once()
    assert len(shown) == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
