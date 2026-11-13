"""Chatty's "here I am" note for the nodes (src/hub_note.py)."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import hub_note  # noqa: E402

IP_OUT = """1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever
3: wlan0    inet 192.168.1.77/24 brd 192.168.1.255 scope global dynamic noprefixroute wlan0\\       valid_lft 85000sec
4: tailscale0    inet 100.69.130.79/32 scope global tailscale0\\       valid_lft forever preferred_lft forever
5: docker0    inet 169.254.3.1/16 scope link docker0
"""


def test_addresses():
    assert hub_note.addresses(IP_OUT) == (["192.168.1.77"], "100.69.130.79")
    assert hub_note.addresses("") == ([], "")
    assert hub_note.addresses("garbage inet nope") == ([], "")


def _hub(path, where, clock=None):
    return hub_note.HubNote(path=path, look=lambda: (where[0][1], "100.69.130.79"),
                            wifi=lambda: where[0][0], clock=clock or (lambda: 1000.0))


def test_remembers_each_wifi_across_restarts():
    path = os.path.join(tempfile.mkdtemp(), "hub.json")
    where = [("GF-Home", ["192.168.1.50"])]
    h = _hub(path, where)
    first = h.due()
    assert first["wifi"] == "GF-Home" and first["ts"] == 1000
    where[0] = ("AVC-2G", ["192.168.1.77"])
    h.due()
    again = _hub(path, where)
    assert again.note()["known"] == {"GF-Home": "192.168.1.50", "AVC-2G": "192.168.1.77"}
    assert os.stat(path).st_mode & 0o077 == 0


def test_only_posts_when_changed_or_now_and_then():
    t = [1000.0]
    where = [("GF-Home", ["192.168.1.50"])]
    h = _hub(os.path.join(tempfile.mkdtemp(), "hub.json"), where, clock=lambda: t[0])
    assert h.due()
    t[0] += 60
    assert h.due() is None
    assert h.due(force=True)
    t[0] += hub_note.REFRESH + 1
    assert h.due()
    where[0] = ("GF-Home", ["192.168.1.51"])
    t[0] += 1
    assert h.due()["lan"] == ["192.168.1.51"]


def test_no_wifi_no_known_entry():
    where = [("", ["192.168.1.9"])]
    h = _hub(os.path.join(tempfile.mkdtemp(), "hub.json"), where)
    assert h.note()["known"] == {}


def test_wifi_name_from_keeper_status():
    f = os.path.join(tempfile.mkdtemp(), "wifi.json")
    with open(f, "w") as fh:
        json.dump({"online": True, "ssid": "AVC-2G"}, fh)
    old = hub_note.WIFI_STATUS
    hub_note.WIFI_STATUS = f
    try:
        assert hub_note.wifi_name() == "AVC-2G"
    finally:
        hub_note.WIFI_STATUS = old


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
