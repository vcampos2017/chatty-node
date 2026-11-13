"""The 10-minute greenhouse check (src/greenhouse_status.py, run by cron):
read-only, alerts only on a change of state."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

calls = {"get": [], "post": [], "phone": []}
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
sys.modules["phone"] = types.SimpleNamespace(send=lambda text, event=None: calls["phone"].append(text))
import greenhouse_status as gs  # noqa: E402


def _check(soil):
    reading["soil"] = soil
    calls["post"].clear()
    calls["phone"].clear()
    return gs.run_greenhouse_check()


def test_never_sends_the_greenhouse_a_command():
    for soil in (30, 30, 60, 40, 20, 80):
        _check(soil)
        assert calls["post"] == []           # no POST to anything, ever
    assert not hasattr(gs, "send_command")


def test_dry_soil_alerts_once_and_says_it_may_need_water():
    last["status"] = "good"
    r = _check(20)
    assert r["status"] == "critically dry" and r["action"] == "none"
    assert len(calls["phone"]) == 1 and "may need water" in calls["phone"][0]
    _check(20)
    assert calls["phone"] == []                 # same state: quiet


def test_back_to_good_after_dry():
    last["status"] = "critically dry"
    _check(70)
    assert "back to good" in calls["phone"][0]


def test_unplugged_probe_is_not_dry():
    r = _check(0)
    assert r["status"] == "offline" and calls["phone"] == []


def test_settings_file_read_without_dotenv():
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "secrets.env")
    with open(path, "w") as f:
        f.write("# comment\nCHATTY_GH_TEST=http://192.168.1.227:5000/status\n"
                "CHATTY_GH_TEST=http://100.114.76.44:5000/status\nexport QUOTED_GH='a b'\n")
    os.environ.pop("CHATTY_GH_TEST", None)
    gs._load_settings(path)
    assert os.environ["CHATTY_GH_TEST"] == "http://100.114.76.44:5000/status"   # last one wins
    assert os.environ["QUOTED_GH"] == "a b"
    os.environ["CHATTY_GH_TEST"] = "kept"
    gs._load_settings(path)
    assert os.environ["CHATTY_GH_TEST"] == "kept"                                # environment wins


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
