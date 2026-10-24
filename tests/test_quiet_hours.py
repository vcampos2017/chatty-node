import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import quiet_hours  # noqa: E402


def _at(hour):
    return time.mktime((2026, 10, 24, hour, 30, 0, 0, 0, -1))


def test_overnight_range(monkeypatch=None):
    os.environ.pop("CHATTY_NIGHT_MODE", None)
    os.environ["CHATTY_NIGHT_START"], os.environ["CHATTY_NIGHT_END"] = "22", "7"
    assert quiet_hours.is_night(_at(23))
    assert quiet_hours.is_night(_at(3))
    assert not quiet_hours.is_night(_at(7))
    assert not quiet_hours.is_night(_at(15))


def test_off_switch():
    os.environ["CHATTY_NIGHT_MODE"] = "0"
    assert not quiet_hours.is_night(_at(3))
    os.environ.pop("CHATTY_NIGHT_MODE")
