"""The 10-minute greenhouse check (src/greenhouse_status.py, run by cron):
read-only, alerts only on a change of state."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

calls = {"get": [], "post": []}
reading = {"soil": 30.0}
last = {"status": None}


class _Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def _get(url, timeout=None):
    calls["get"].append(url)
    return _Resp({"metrics": {"soil_moisture_percent": reading["soil"], "air_temperature_f": 70.0}})


def _post(url, json=None, timeout=None):
    calls["post"].append((url, json))
    return _Resp({})


sys.modules["requests"] = types.SimpleNamespace(get=_get, post=_post)
sys.modules["db"] = types.SimpleNamespace(
    log_sensor=lambda node, soil, temp, status: last.update(status=status),
    log_action=lambda *a: None,
    get_last_status=lambda: last["status"])
os.environ["IFTTT_KEY"] = "test-key"
import greenhouse_status as gs  # noqa: E402


def _check(soil):
    reading["soil"] = soil
    calls["post"].clear()
    return gs.run_greenhouse_check()


def test_never_sends_the_greenhouse_a_command():
    for soil in (30, 30, 60, 40, 20, 80):
        _check(soil)
        assert not any("/command" in url for url, _ in calls["post"])
    assert not hasattr(gs, "send_command")


def test_dry_soil_alerts_once_and_says_it_may_need_water():
    last["status"] = "good"
    r = _check(20)
    assert r["status"] == "critically dry" and r["action"] == "none"
    assert len(calls["post"]) == 1 and "ifttt" in calls["post"][0][0]
    assert "may need water" in calls["post"][0][1]["value1"]
    _check(20)
    assert calls["post"] == []                  # same state: quiet


def test_back_to_good_after_dry():
    last["status"] = "critically dry"
    _check(70)
    assert "back to good" in calls["post"][0][1]["value1"]


def test_unplugged_probe_is_not_dry():
    r = _check(0)
    assert r["status"] == "offline" and calls["post"] == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
