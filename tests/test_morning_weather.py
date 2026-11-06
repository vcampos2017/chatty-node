import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import morning_weather  # noqa: E402


def _at(hour, day=6):
    return time.mktime((2026, 11, day, hour, 5, 0, 0, 0, -1))


def _wait(m):
    for _ in range(100):
        if not m._fetching:
            return
        time.sleep(0.01)


def _morning():
    state = Path(tempfile.mkdtemp()) / "m.json"
    return morning_weather.Morning(report=lambda: "Sunny, high of 80.", state_file=state), state


def test_quiet_at_night_then_once_in_the_morning():
    m, state = _morning()
    assert m.due("sleep", _at(5)) is None          # still night mode
    assert m.due("sleep", _at(7)) is None          # starts the lookup
    _wait(m)
    said = m.due("sleep", _at(7))
    assert said.endswith("Sunny, high of 80.")
    assert m.due("sleep", _at(8)) is None          # only once a day
    # survives a restart
    again = morning_weather.Morning(report=lambda: "x", state_file=state)
    assert again.due("sleep", _at(9)) is None


def test_waits_while_busy_and_skips_afternoon():
    m, _ = _morning()
    m.due("active", _at(7))
    _wait(m)
    assert m.due("active", _at(7)) is None         # mid-conversation: wait
    assert m.due("resting", _at(7)) is None        # put to bed: wait
    assert m.due("sleep", _at(7)) is not None
    m2, _ = _morning()
    assert m2.due("sleep", _at(13)) is None and not m2._fetching


def test_lookup_failure_is_quiet():
    state = Path(tempfile.mkdtemp()) / "m.json"

    def boom():
        raise OSError("offline")
    m = morning_weather.Morning(report=boom, state_file=state)
    m.due("sleep", _at(7))
    _wait(m)
    assert m.due("sleep", _at(7)) is None
