import importlib.util
import os
import sys
import tempfile
from types import SimpleNamespace

_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "wifi_keeper.py")
_spec = importlib.util.spec_from_file_location("wifi_keeper", _path)
wk = importlib.util.module_from_spec(_spec)
sys.modules["wifi_keeper"] = wk
_spec.loader.exec_module(wk)
wk.STATUS_FILE = os.path.join(tempfile.mkdtemp(), "wifi.json")


class FakeAir:
    """A pretend NetworkManager + the air around the Pi."""

    def __init__(self, saved, signals, internet, current=None):
        self.saved_list = saved                  # [(name, uuid, ssid, autoconnect)]
        self.signals = signals                   # ssid -> signal
        self.internet = internet                 # ssid -> has internet?
        self.current = current                   # ssid in use
        self.calls = []
        self.wired = False

    def by_uuid(self, uuid):
        return next(s for s in self.saved_list if s[1] == uuid)

    def __call__(self, cmd, **kw):
        assert cmd[0] == "nmcli"
        assert "--show-secrets" not in cmd and "-s" not in cmd   # never ask for passwords
        args = cmd[1:]
        self.calls.append(args)
        out, rc = "", 0
        if args[-2:] == ["device", "status"]:
            rows = ["wlan0:wifi:%s:%s" % (("connected", self.name_of(self.current))
                                          if self.current else ("disconnected", ""))]
            rows.append("eth0:ethernet:%s:" % ("connected" if self.wired else "unavailable"))
            rows.append("lo:loopback:connected (externally):lo")
            out = "\n".join(rows)
        elif args[:5] == ["-t", "-f", "NAME,UUID,TYPE", "connection", "show"]:
            out = "\n".join(f"{n.replace(':', chr(92) + ':')}:{u}:802-11-wireless"
                            for n, u, _, _ in self.saved_list) + "\nWired connection 1:w1:802-3-ethernet"
        elif args[0] == "-g":
            n, u, ssid, auto = self.by_uuid(args[-1])
            out = {"802-11-wireless.ssid": ssid.replace(":", "\\:"),
                   "802-11-wireless.mode": "infrastructure",
                   "connection.autoconnect": "yes" if auto else "no"}[args[1]] + "\n"
        elif "wifi" in args and "list" in args:
            out = "\n".join(f"{'*' if s == self.current else ' '}:{s.replace(':', chr(92) + ':')}:{sig}"
                            for s, sig in self.signals.items())
        elif "up" in args:
            uuid = args[args.index("uuid") + 1]
            ssid = self.by_uuid(uuid)[2]
            if ssid in self.signals:
                self.current = ssid
            else:
                rc = 4
        return SimpleNamespace(returncode=rc, stdout=out, stderr="Error: no network" if rc else "")

    def name_of(self, ssid):
        return next(n for n, _, s, _ in self.saved_list if s == ssid)

    def online(self):
        return bool(self.current and self.internet.get(self.current))


SAVED = [("ExtenderWiFi", "u1", "ExtenderWiFi", True),
         ("AVC-5G", "u2", "AVC-5G", True),
         ("Cafe: Guest", "u3", "Cafe: Guest", True)]


def make(air, t):
    notices = []
    k = wk.Keeper(wk.NM(run=air), online=air.online, notice=notices.append,
                  clock=lambda: t[0], settle=lambda: None)
    return k, notices


def test_split_terse_handles_escaped_colons():
    assert wk.split_terse(r"*:Cafe\: Guest:71") == ["*", "Cafe: Guest", "71"]
    assert wk.split_terse(r" :back\\slash:5") == [" ", "back\\slash", "5"]


def test_stays_put_when_all_is_well():
    air = FakeAir(SAVED, {"ExtenderWiFi": 70, "AVC-5G": 90}, {"ExtenderWiFi": True, "AVC-5G": True}, "ExtenderWiFi")
    t = [1000.0]
    k, notices = make(air, t)
    for _ in range(5):
        k.step()
        t[0] += 60
    assert air.current == "ExtenderWiFi"         # 70% is fine, no hopping around
    assert not notices
    assert not any("up" in c for c in air.calls)


def test_no_internet_moves_to_the_best_working_one():
    air = FakeAir(SAVED, {"ExtenderWiFi": 80, "AVC-5G": 60, "Cafe: Guest": 75},
                  {"ExtenderWiFi": False, "AVC-5G": True, "Cafe: Guest": False}, "ExtenderWiFi")
    t = [1000.0]
    k, notices = make(air, t)
    assert "1 of" in k.step()               # one miss isn't enough
    t[0] += 60
    assert k.step() == "switched to AVC-5G"  # tried the cafe (stronger) first, then 5G
    assert air.current == "AVC-5G"
    assert notices == ["I moved to the AVC-5G WiFi: ExtenderWiFi had no internet."]
    # The bad one is skipped for a while even though it's strongest.
    assert k.bad["u1"] > t[0]


def test_weak_signal_moves_to_a_much_stronger_one():
    air = FakeAir(SAVED, {"ExtenderWiFi": 25, "AVC-5G": 80}, {"ExtenderWiFi": True, "AVC-5G": True}, "ExtenderWiFi")
    t = [1000.0]
    k, notices = make(air, t)
    for _ in range(wk.ROAM_CHECKS - 1):
        k.step()
        t[0] += 60
    assert air.current == "ExtenderWiFi"
    assert k.step() == "moved to stronger AVC-5G"
    assert air.current == "AVC-5G"
    assert "stronger" in notices[0]


def test_goes_back_if_the_stronger_one_has_no_internet():
    air = FakeAir(SAVED, {"ExtenderWiFi": 25, "AVC-5G": 80}, {"ExtenderWiFi": True, "AVC-5G": False}, "ExtenderWiFi")
    t = [1000.0]
    k, notices = make(air, t)
    for _ in range(wk.ROAM_CHECKS):
        r = k.step()
        t[0] += 60
    assert r == "stayed on ExtenderWiFi"
    assert air.current == "ExtenderWiFi"
    assert not notices
    for _ in range(10):                      # and doesn't keep trying it
        k.step()
        t[0] += 60
    assert air.current == "ExtenderWiFi"


def test_nothing_works_tells_the_face_once_and_reconnects():
    air = FakeAir(SAVED, {"ExtenderWiFi": 80, "AVC-5G": 60}, {}, "ExtenderWiFi")
    t = [1000.0]
    k, notices = make(air, t)
    k.step()
    t[0] += 60
    assert k.step() == "offline, nothing better found"
    assert air.current == "ExtenderWiFi"           # back on the usual one
    assert len(notices) == 1 and "offline" in notices[0]
    for _ in range(10):
        k.step()
        t[0] += 60
    assert len(notices) == 1                 # not nagging every few minutes
    air.internet["ExtenderWiFi"] = True            # the router comes back
    k.step()
    assert notices[-1] == "Back online on the ExtenderWiFi WiFi."


def test_skips_avoided_and_autoconnect_off_networks():
    saved = SAVED[:2] + [("Neighbor", "u4", "Neighbor", False)]
    air = FakeAir(saved, {"ExtenderWiFi": 80, "AVC-5G": 60, "Neighbor": 99},
                  {"AVC-5G": True, "Neighbor": True}, "ExtenderWiFi")
    t = [1000.0]
    k, notices = make(air, t)
    old = wk.AVOID
    wk.AVOID = {"AVC-5G"}
    try:
        k.step()
        t[0] += 60
        assert k.step() == "offline, no other saved network in range"
    finally:
        wk.AVOID = old
    assert air.current == "ExtenderWiFi"
    assert not any("u4" in c or "u2" in c for c in air.calls if "up" in c)


def test_leaves_wifi_alone_on_a_cable():
    air = FakeAir(SAVED, {"ExtenderWiFi": 10, "AVC-5G": 90}, {"ExtenderWiFi": False}, "ExtenderWiFi")
    air.wired = True
    k, _ = make(air, [1000.0])
    k.online = lambda: True
    for _ in range(5):
        assert k.step() == "on a cable, leaving WiFi alone"
    assert air.current == "ExtenderWiFi"


def test_status_file_has_no_secrets():
    air = FakeAir(SAVED, {"ExtenderWiFi": 70}, {"ExtenderWiFi": True}, "ExtenderWiFi")
    k, _ = make(air, [1000.0])
    k.step()
    import json
    data = json.load(open(wk.STATUS_FILE))
    assert data["ssid"] == "ExtenderWiFi" and data["online"] is True and data["signal"] == 70
    assert set(data) == {"online", "ssid", "signal", "ts"}


class home:
    """Set CHATTY_WIFI_HOME for one test."""

    def __init__(self, ssid):
        self.ssid = ssid

    def __enter__(self):
        self.old = wk.HOME
        wk.HOME = self.ssid

    def __exit__(self, *a):
        wk.HOME = self.old


HOME_SAVED = [("HomeWiFi", "h1", "HomeWiFi", True), ("ExtenderWiFi", "u1", "ExtenderWiFi", True)]


def test_moves_back_home_when_home_is_usable():
    air = FakeAir(HOME_SAVED, {"HomeWiFi": 55, "ExtenderWiFi": 80},
                  {"HomeWiFi": True, "ExtenderWiFi": True}, "ExtenderWiFi")
    t = [10000.0]
    k, notices = make(air, t)
    with home("HomeWiFi"):
        for _ in range(wk.ROAM_CHECKS - 1):
            assert "home HomeWiFi is in range" in k.step()
            t[0] += 60
        assert air.current == "ExtenderWiFi"           # not on the first glimpse
        assert k.step() == "moved home to HomeWiFi"
        assert air.current == "HomeWiFi"
        assert "home WiFi, HomeWiFi" in notices[0]
        for _ in range(30):                      # and stays, though ExtenderWiFi is stronger
            k.step()
            t[0] += 60
    assert air.current == "HomeWiFi"
    assert len(notices) == 1


def test_home_too_weak_is_left_alone():
    air = FakeAir(HOME_SAVED, {"HomeWiFi": 20, "ExtenderWiFi": 80},
                  {"HomeWiFi": True, "ExtenderWiFi": True}, "ExtenderWiFi")
    t = [10000.0]
    k, notices = make(air, t)
    with home("HomeWiFi"):
        for _ in range(10):
            k.step()
            t[0] += 60
    assert air.current == "ExtenderWiFi" and not notices


def test_home_without_internet_backs_off():
    air = FakeAir(HOME_SAVED, {"HomeWiFi": 60, "ExtenderWiFi": 80},
                  {"HomeWiFi": False, "ExtenderWiFi": True}, "ExtenderWiFi")
    t = [10000.0]
    k, notices = make(air, t)
    tries = []
    with home("HomeWiFi"):
        for minute in range(6 * 60):
            r = k.step()
            if r.startswith("stayed on ExtenderWiFi"):
                tries.append(minute)
            t[0] += 60
    assert air.current == "ExtenderWiFi" and not notices
    gaps = [b - a for a, b in zip(tries, tries[1:])]
    assert len(tries) >= 3 and gaps == sorted(gaps) and gaps[-1] > gaps[0]


def test_on_home_only_very_weak_signal_moves_her():
    air = FakeAir(HOME_SAVED, {"HomeWiFi": 35, "ExtenderWiFi": 90},
                  {"HomeWiFi": True, "ExtenderWiFi": True}, "HomeWiFi")
    t = [10000.0]
    k, notices = make(air, t)
    with home("HomeWiFi"):
        for _ in range(10):                      # 35% is weak, but fine for home
            k.step()
            t[0] += 60
        assert air.current == "HomeWiFi"
        air.signals["HomeWiFi"] = 15              # really bad now
        for _ in range(wk.ROAM_CHECKS):
            r = k.step()
            t[0] += 60
    assert r == "moved to stronger ExtenderWiFi"


def test_offline_tries_home_first():
    saved = HOME_SAVED + [("AVC-5G", "u2", "AVC-5G", True)]
    air = FakeAir(saved, {"HomeWiFi": 50, "ExtenderWiFi": 70, "AVC-5G": 90},
                  {"HomeWiFi": True, "ExtenderWiFi": False, "AVC-5G": True}, "ExtenderWiFi")
    t = [10000.0]
    k, notices = make(air, t)
    with home("HomeWiFi"):
        k.step()
        t[0] += 60
        assert k.step() == "switched to HomeWiFi"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
