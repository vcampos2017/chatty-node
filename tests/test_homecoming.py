import ipaddress
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["CHATTY_NIGHT_MODE"] = "0"
import homecoming  # noqa: E402

MAC = "aa:bb:cc:dd:ee:01"
T = 1_800_000_000.0


class Rig:
    def __init__(self, night=lambda now: False, speak=True, extras=None):
        self.table, self.knocked, self.notes = [], [], []
        self.now = T
        self.h = homecoming.Homecoming(
            people={"Vincent": {MAC}}, neighbors=lambda: list(self.table),
            knock=lambda ips: self.knocked.append(list(ips)) or 0,
            subnets=lambda: [ipaddress.ip_network("192.168.1.0/29")],
            notice=self.notes.append, extras=extras, is_night=night,
            clock=lambda: self.now, settle=0, away=30 * 60, speak=speak)

    def phone(self, here, state="REACHABLE", ip="192.168.1.5"):
        self.table = [(ip, MAC, state)] if here else []

    def step(self, minutes, here=None):
        self.now += minutes * 60
        if here is not None:
            self.phone(here)
        self.h.check_once()


def test_parse_people():
    p = homecoming.parse_people("Vincent=AA-BB-CC-DD-EE-01, 11:22:33:44:55:66; Sam=aabbccddee02;bad=zz")
    assert p == {"Vincent": {"aa:bb:cc:dd:ee:01", "11:22:33:44:55:66"}, "Sam": {"aa:bb:cc:dd:ee:02"}}
    assert homecoming.parse_people("") == {}


def test_no_greeting_at_startup_then_greets_after_real_absence():
    r = Rig()
    r.step(0, here=True)
    assert r.h.people["Vincent"].home is True and r.h.due("sleep") is None
    r.step(10, here=False)
    r.step(25, here=False)            # 35 min gone: away
    assert r.h.people["Vincent"].home is False
    r.step(60 * 3, here=True)
    text, mood = r.h.due("sleep")
    assert "Vincent" in text and mood == "speaking"
    assert r.h.due("sleep") is None   # only once
    assert r.notes == []


def test_short_trip_is_not_greeted():
    r = Rig()
    r.step(0, here=True)
    r.step(20, here=False)
    r.step(5, here=True)
    assert r.h.due("sleep") is None


def test_stale_entry_does_not_count():
    r = Rig()
    r.step(0, here=True)
    r.step(40, here=False)
    r.phone(True, state="STALE")
    r.step(1)
    assert r.h.people["Vincent"].home is False


def test_night_return_is_a_notice_and_night_departure_is_ignored():
    nights = []      # (start, end) windows

    def night(now):
        return any(a <= now < b for a, b in nights)
    r = Rig(night=night)
    r.step(0, here=True)
    r.step(40, here=False)                    # left in the daytime
    nights.append((r.now + 30 * 60, r.now + 12 * 3600))
    r.step(60, here=True)                     # came home at night
    assert r.h.due("sleep") is None and len(r.notes) == 1 and "Vincent came home" in r.notes[0]
    r.step(60, here=False)                    # phone naps at night...
    r.step(60, here=False)
    r.step(12 * 60, here=True)                # ...and wakes up in the morning: no greeting
    assert r.h.due("sleep") is None and len(r.notes) == 1


def test_busy_or_late_greeting_is_dropped():
    r = Rig()
    r.step(0, here=True)
    r.step(40, here=False)
    r.step(1, here=True)
    assert r.h.due("active") is None and r.h.due("sleep") is None
    r.step(40, here=False)
    r.step(1, here=True)
    r.now += 10 * 60
    assert r.h.due("sleep") is None


def test_long_absence_adds_extras_and_love():
    r = Rig(extras=lambda: "Just so you know, Rain Node is quiet.")
    r.step(0, here=True)
    r.step(40, here=False)
    r.step(60 * 9, here=True)
    text, mood = r.h.due("sleep")
    assert text.endswith("Rain Node is quiet.") and mood == "love_talk"


def test_sweeps_while_away_and_knocks_known_ip():
    r = Rig()
    r.step(0, here=True)
    assert "192.168.1.1" in r.knocked[0]          # first look sweeps the subnet
    r.knocked.clear()
    r.step(1, here=True)
    assert r.knocked[-1] == ["192.168.1.5"]       # home: only the phone's own address


def test_answers():
    r = Rig()
    assert "haven't spotted" in r.h.answer()
    r.step(0, here=True)
    assert r.h.answer("vincent") == "Vincent's phone is here."
    assert homecoming.asked_who("is vincent home", ["Vincent"]) == "Vincent"
    assert homecoming.asked_who("whos home", ["Vincent"]) == ""
    assert homecoming.asked_who("what time is it", ["Vincent"]) is None
    empty = homecoming.Homecoming(people={})
    assert not empty.enabled and "CHATTY_HOME_PHONES" in empty.answer()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
