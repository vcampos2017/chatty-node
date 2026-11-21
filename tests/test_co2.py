"""Greenhouse CO2 (the SCD-40 on the greenhouse node): answers, face card, briefing.
Run: python3 tests/test_co2.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import co2  # noqa: E402
import local_skills  # noqa: E402
import morning_briefing  # noqa: E402
import nodes  # noqa: E402
from words import normalize  # noqa: E402

BASE = {"air_temperature_f": 72.0, "soil_moisture_percent": 55, "soil_voltage": 1.6,
        "soil_moisture_band": "wet"}


def _fake(metrics):
    real = nodes.read_greenhouse

    def read(fetch=None, rain=None):
        return real(fetch=lambda url: {"metrics": metrics}, rain=lambda: None)
    return read


def _ask(q, metrics):
    saved = nodes.read_greenhouse
    nodes.read_greenhouse = _fake(metrics)
    try:
        return local_skills.handle(normalize(q))
    finally:
        nodes.read_greenhouse = saved


def test_reading_uses_the_nodes_label_first():
    assert co2.reading({"co2_ppm": 640, "co2_band": "normal"}) == (640, "normal")
    assert co2.reading({"co2_ppm": 640, "co2_band": "high"}) == (640, "high")
    assert co2.reading({"co2_ppm": 2000}) == (2000, "high")
    assert co2.reading({"co2_ppm": 300}) == (300, "low")
    assert co2.reading({}) == (None, None)
    assert co2.reading({"co2_ppm": "junk"}) == (None, None)


def test_spoken_co2_questions():
    for q in ["What's the CO2 in the greenhouse?", "how much carbon dioxide is there",
              "what is the c o 2 level", "Hey, what's the CO two?"]:
        assert co2.is_question(normalize(q)), q
    assert not co2.is_question("what time is it")


def test_co2_question_answered_locally():
    a = _ask("What's the CO2 in the greenhouse?", dict(BASE, co2_ppm=640, co2_band="normal"))
    assert "640 parts per million" in a and "normal" in a
    a = _ask("how much carbon dioxide is there", dict(BASE, co2_ppm=1800, co2_band="high"))
    assert "high" in a and "vent" in a


def test_no_sensor_says_so():
    a = _ask("what's the co2 level", BASE)
    assert "plugged in" in a


def test_greenhouse_answer_adds_co2_only_with_a_sensor():
    a = _ask("how is the greenhouse", dict(BASE, co2_ppm=640, co2_band="normal"))
    assert "55 percent" in a and "640 parts per million" in a
    a = _ask("how is the greenhouse", BASE)
    assert "55 percent" in a and "CO2" not in a


def test_face_card_detail():
    r = _fake(dict(BASE, co2_ppm=640, co2_band="normal"))()
    assert r.detail == "72 F inside, CO2 640"
    r = _fake(dict(BASE, co2_ppm=1800, co2_band="high"))()
    assert r.detail.endswith("CO2 1800 high")
    assert _fake(BASE)().detail == "72 F inside"


def test_morning_briefing_mentions_co2_only_when_not_normal():
    line = morning_briefing._greenhouse_line({"metrics": dict(BASE, co2_ppm=640, co2_band="normal")})
    assert "CO2" not in line
    line = morning_briefing._greenhouse_line({"metrics": dict(BASE, co2_ppm=1800, co2_band="high")})
    assert "CO2 is high" in line


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
