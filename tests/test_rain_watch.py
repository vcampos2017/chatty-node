import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["CHATTY_NIGHT_MODE"] = "0"
import rain_watch  # noqa: E402

T = 1_800_000_000.0   # a whole hour


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _hours(chances, start=T, summary="Chance Showers"):
    out = []
    for i, c in enumerate(chances):
        out.append({"startTime": _iso(start + i * 3600), "endTime": _iso(start + (i + 1) * 3600),
                    "shortForecast": summary if c else "Sunny",
                    "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": c}})
    return out


class Rig:
    def __init__(self, night=False, raining=False):
        self.periods = _hours([0] * 12)
        self.posts, self.notes, self.night, self.wet = [], [], night, raining
        self.w = rain_watch.RainWatch(fetch=lambda: self.periods,
                                      publish=lambda t, b: self.posts.append((t, b)),
                                      raining=lambda: self.wet, notice=self.notes.append,
                                      phone=lambda text: None, is_night=lambda now: self.night,
                                      state_file=None)


def test_assess_finds_first_rainy_hour_in_window():
    o = rain_watch.assess(_hours([10, 20, 70, 90]), T + 600)
    assert o and o.starts == T + 2 * 3600 and o.chance == 70 and o.kind == "rain"
    assert rain_watch.assess(_hours([0, 0, 0, 80]), T) is None        # beyond 3 hours
    assert rain_watch.assess(_hours([40, 40, 40]), T) is None               # never likely
    storm = rain_watch.assess(_hours([60], summary="Showers And Thunderstorms Likely"), T)
    assert storm.kind == "storms" and storm.starts == T


def test_heads_up_said_once_before_the_rain():
    r = Rig()
    r.periods = _hours([0, 80, 80, 80, 0, 0])
    r.w.check_once(T)
    assert r.notes and "Close the windows" in r.notes[0]
    text = r.w.due("sleep", T + 60)
    assert text.startswith(("Hey, hey!", "Heads up!")) and "about an hour" in text
    assert r.w.due("sleep", T + 120) is None
    for k in range(1, 8):                      # it keeps raining in the forecast: no nagging
        r.w.check_once(T + k * 900)
    assert len(r.notes) == 1 and r.w.due("sleep", T + 8 * 900) is None


def test_waits_until_free_and_skips_if_rain_already_here():
    r = Rig()
    r.periods = _hours([0, 90])
    r.w.check_once(T)
    assert r.w.due("active", T + 10) is None      # busy talking: later
    r.wet = True
    assert r.w.due("sleep", T + 20) is None       # the gauge feels it already


def test_night_shows_notice_only():
    r = Rig(night=True)
    r.periods = _hours([0, 90])
    r.w.check_once(T)
    assert len(r.notes) == 1 and r.w.due("sleep", T + 10) is None


def test_rearms_after_a_dry_spell_and_gap():
    r = Rig()
    r.periods = _hours([0, 80])
    r.w.check_once(T)
    r.periods = _hours([0] * 12, start=T + 3 * 3600)
    for k in range(4):                             # dry, 3 to 6 hours later
        r.w.check_once(T + 3 * 3600 + k * 3600)
    r.periods = _hours([0, 80], start=T + 7 * 3600)
    r.w.check_once(T + 7 * 3600)
    assert len(r.notes) == 2


def test_no_warning_while_the_gauge_already_feels_rain():
    r = Rig(raining=True)
    r.periods = _hours([90, 90])
    r.w.check_once(T)
    assert r.notes == [] and r.posts[-1][1]["raining_now"] is True


def test_posts_news_for_the_other_nodes():
    r = Rig()
    r.w.check_once(T)
    topic, body = r.posts[-1]
    assert topic == "chatty/forecast/rain" and body["rain_expected"] is False and body["starts_ts"] is None
    r.periods = _hours([0, 75], summary="Rain Likely")
    r.w.check_once(T + 600)
    body = r.posts[-1][1]
    assert body["rain_expected"] and body["starts_ts"] == int(T + 3600) and body["minutes"] == 50
    assert body["chance"] == 75 and body["kind"] == "rain" and body["summary"] == "Rain Likely"


def test_survives_a_failed_fetch_and_answers():
    r = Rig()
    r.w.fetch = lambda: (_ for _ in ()).throw(OSError("offline"))
    r.w.check_once(T)
    assert r.posts == [] and "can't reach" in r.w.answer(T)
    r.w.fetch = lambda: _hours([0, 0, 65])
    r.w.check_once(T)
    assert r.w.answer(T) == "Rain in about 2 hours, about a 65 percent chance."


def test_state_survives_restart(tmp=None):
    import tempfile
    from pathlib import Path
    path = Path(tempfile.mkdtemp()) / "rain.json"
    notes = []
    mk = lambda: rain_watch.RainWatch(fetch=lambda: _hours([0, 80]), publish=None,
                                      notice=notes.append, is_night=lambda n: False,
                                      state_file=path)
    mk().check_once(T)
    mk().check_once(T + 300)                      # restarted: no second heads-up
    assert len(notes) == 1


def test_when_words():
    assert rain_watch.when_words(5) == "any minute now"
    assert rain_watch.when_words(30) == "in less than an hour"
    assert rain_watch.when_words(60) == "in about an hour"
    assert rain_watch.when_words(150) == "in about 2 hours"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
