"""'It rained, you can skip watering' for the outdoor hoses (src/watering_tip.py)."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["CHATTY_NIGHT_MODE"] = "0"
import watering_tip  # noqa: E402
from watering_tip import WaterTip  # noqa: E402

# 1 PM local time on some day, so the daytime window is easy to reason about
NOON = time.mktime((2026, 7, 1, 13, 0, 0, 0, 0, -1))
H = 3600


class Outlook:
    def __init__(self, starts, chance):
        self.starts, self.chance = starts, chance


def _tip(path=None, outlook=None, raining=False):
    notes = []
    w = WaterTip(notice=notes.append, raining=lambda: raining, outlook=lambda: outlook,
                 is_night=lambda now: False,
                 state_file=path or Path(tempfile.mkdtemp()) / "tip.json")
    return w, notes


def _rain(w, start, mm_list, every=600, base=10.0):
    """Feed a gauge whose running total starts at `base` and rises by each step."""
    total, t = base, start
    w.on_data("rain", {"rain_mm": total}, t)
    for mm in mm_list:
        t += every
        total += mm
        w.on_data("rain", {"rain_mm": total}, t)
    return t


def test_amount_words():
    assert watering_tip.amount_words(0.27) == "about a quarter of an inch"
    assert watering_tip.amount_words(0.5) == "about half an inch"
    assert watering_tip.amount_words(1.4) == "about 1.4 inches"


def test_tip_once_after_a_good_soaking():
    w, notes = _tip()
    end = _rain(w, NOON - 3 * H, [4, 4, 4])          # 12 mm, about half an inch
    assert abs(w.inches(end) - 12 / 25.4) < 1e-6
    assert w.due("sleep", end + 60) is None            # just stopped: wait 30 min
    text = w.due("sleep", end + 31 * 60)
    assert "about half an inch" in text and "skip watering" in text
    assert notes and "skip watering" in notes[0]
    assert w.due("sleep", end + 2 * H) is None         # once a day


def test_not_while_busy_at_night_or_for_a_sprinkle():
    w, _ = _tip()
    end = _rain(w, NOON - 3 * H, [1, 1])               # 2 mm: a sprinkle
    assert w.due("sleep", end + H) is None
    w2, _ = _tip()
    end = _rain(w2, NOON - 3 * H, [5, 5])
    assert w2.due("active", end + H) is None           # she's talking with someone
    late = time.mktime((2026, 7, 1, 21, 30, 0, 0, 0, -1))
    w3, _ = _tip()
    end = _rain(w3, late - 2 * H, [5, 5])
    assert w3.due("sleep", late) is None               # after 8 pm: the morning briefing says it


def test_gauge_reset_is_a_new_start_and_restart_remembers():
    path = Path(tempfile.mkdtemp()) / "tip.json"
    w, _ = _tip(path)
    _rain(w, NOON - 5 * H, [3, 3], base=40)            # 6 mm
    w.on_data("rain", {"rain_mm": 0.0}, NOON - 4 * H)  # the gauge's total reset
    w.on_data("rain", {"rain_mm": 2.0}, NOON - 3.9 * H)
    assert abs(w.inches(NOON) - 8 / 25.4) < 1e-6
    again, _ = _tip(path)                              # Chatty restarted
    assert abs(again.inches(NOON) - 8 / 25.4) < 1e-6
    assert again.due("sleep", NOON) is not None


def test_rain_in_works_too_and_old_rain_drops_off():
    w, _ = _tip()
    w.on_data("rain", {"rain_in": 1.0}, NOON - 30 * H)
    w.on_data("rain", {"rain_in": 1.5}, NOON - 29 * H)
    assert w.inches(NOON - 28 * H) == 0.5
    assert w.inches(NOON) == 0.0                       # more than a day ago


def test_morning_briefing_line_counts_as_the_tip():
    w, _ = _tip()
    end = _rain(w, NOON - 8 * H, [4, 4])
    line = w.briefing_line(end + 2 * H)
    assert "skip watering" in line
    assert w.due("sleep", end + 3 * H) is None
    dry, _ = _tip()
    assert dry.briefing_line(NOON) == ""


def test_answers():
    w, _ = _tip()
    end = _rain(w, NOON - 3 * H, [5, 5])
    assert w.answer(end + H).startswith("No need")
    dry, _ = _tip(outlook=Outlook(NOON + 2 * H, 70))
    a = dry.answer(NOON)
    assert "rain is likely in about 2 hours" in a and "70 percent" in a
    dry, _ = _tip()
    assert "could use their watering" in dry.answer(NOON)
    wet, _ = _tip(raining=True)
    assert "raining right now" in wet.answer(NOON)


def test_asked():
    assert watering_tip.asked("should i water the garden")
    assert watering_tip.asked("do i need to water today")
    assert not watering_tip.asked("should i water the greenhouse")
    assert not watering_tip.asked("are the plants thirsty")


def test_morning_briefing_includes_it():
    import morning_briefing
    b = morning_briefing.Briefing(weather=lambda: "Sunny.", hourly=lambda: [],
                                  today_short=lambda: "Sunny", notice=lambda t: None,
                                  state_file=Path(tempfile.mkdtemp()) / "m.json",
                                  water_tip=lambda: "We got about half an inch of rain since "
                                                    "yesterday, so you can skip watering the outdoor plants today.")
    said, screen = b.build(NOON)
    assert "skip watering the outdoor plants" in said and "Skip watering today" in screen


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
