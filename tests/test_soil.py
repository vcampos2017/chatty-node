"""One answer for "how dry is the greenhouse?" (src/soil.py): the greenhouse
node's own label first, Chatty's percentages only without one."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import soil  # noqa: E402
import nodes  # noqa: E402
import morning_briefing  # noqa: E402


def test_the_greenhouse_label_wins():
    assert soil.state(31, "moderate") == "okay"          # was "critically dry" by Chatty's 35%
    assert soil.state(60, "dry") == "dry"
    assert soil.state(20, "Very Dry") == "dry"
    assert soil.state(20, "wet") == "wet"
    assert soil.state(45, "not dry") == "okay"


def test_percent_only_without_a_label():
    assert soil.state(20, None) == "dry"
    assert soil.state(40, "") == "okay"
    assert soil.state(70, "unknown") == "wet"
    assert soil.state(40, "sparkly") == "okay"          # a label we don't know: percentages
    assert soil.state(None, None) is None
    assert soil.of({"soil_moisture_percent": 31, "soil_moisture_band": "moderate"}) == "okay"


def test_face_and_answers_follow_it():
    m = {"soil_moisture_percent": 31, "soil_moisture_band": "moderate", "air_temperature_f": 62,
         "soil_voltage": 1.9}
    r = nodes.read_greenhouse(fetch=lambda url: {"metrics": m}, rain=lambda: None)
    assert r.state == "okay" and "thirsty" not in r.comment and not r.spoken
    m2 = dict(m, soil_moisture_percent=60, soil_moisture_band="dry")
    r2 = nodes.read_greenhouse(fetch=lambda url: {"metrics": m2}, rain=lambda: None)
    assert r2.state == "dry" and "thirsty" in r2.comment
    line = morning_briefing._greenhouse_line({"metrics": m})
    assert "31 percent" in line and "thirsty" not in line


def test_greenhouse_cron_check_follows_it():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "greenhouse_status.py")).read()
    assert "soil_mod.state(soil, band)" in src
    core = open(os.path.join(os.path.dirname(__file__), "..", "chatty_core.py")).read()
    assert "soil_mod.state(soil" in core and "if soil < 35:" not in core


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
