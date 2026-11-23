"""Thanksgiving: the date, the toast to the nodes, the gratitude jar, what you might ask,
once a year at midday, the hat and leaves on her face, the waltz, and the voice node's wiring."""
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CHATTY_NIGHT_MODE", "0")
os.environ.pop("CHATTY_FORCE_THANKSGIVING", None)
os.environ["CHATTY_SONGS_DIR"] = os.path.join(tempfile.mkdtemp(), "songs")
import mesh  # noqa: E402
import piano  # noqa: E402
import thanksgiving as tg  # noqa: E402
from face_model import FaceModel  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")


def _at(month, day, hour=12, minute=0, year=2026):
    return time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))


class FakeMesh:
    def __init__(self, now):
        self.tracker = mesh.Tracker()
        self.now = now

    def hear(self, name):
        beat = {"state": "online", "every": 60, "ts": self.now}
        self.tracker.message(f"chatty/nodes/{name}/status", json.dumps(beat).encode(), self.now)


def test_fourth_thursday():
    assert tg.thanksgiving_day(2026) == 26
    assert tg.thanksgiving_day(2027) == 25
    assert tg.thanksgiving_day(2028) == 23
    assert tg.thanksgiving_day(2029) == 22
    assert tg.is_thanksgiving(_at(11, 26))
    assert not tg.is_thanksgiving(_at(11, 25))
    assert not tg.is_thanksgiving(_at(11, 26, year=2027))


def test_when_text():
    assert "3 days" in tg.when_text(_at(11, 23)) and "November 26th" in tg.when_text(_at(11, 23))
    assert "tomorrow" in tg.when_text(_at(11, 25))
    assert "today" in tg.when_text(_at(11, 26)).lower()
    later = tg.when_text(_at(11, 30))     # after this year's: next year's
    assert "November 25th" in later


def test_toast_thanks_each_node_and_saves_a_plate():
    now = _at(11, 26)
    m = FakeMesh(now)
    for name in ("rain", "greenhouse", "wordclock", "matrix"):
        m.hear(name)
    text, screen = tg.toast(m, now, rng=random.Random(1))
    assert "Rain gauge" in text and "Greenhouse" in text and "Word clock" in text and "Matrix clock" in text
    assert "Lightning node, you're quiet today" in text and "save you a plate" in text
    assert "Tiny" in text and "Happy Thanksgiving" in text
    assert "4/5 here" in screen


def test_toast_without_a_network_thanks_everyone():
    text, screen = tg.toast(None, _at(11, 26), rng=random.Random(2))
    assert "quiet today" not in text and "5/5" in screen


def test_jar_is_ram_only_and_daily():
    clock = [_at(11, 26, 10)]
    jar = tg.Jar(clock=lambda: clock[0])
    assert jar.add("pie chatty") == "pie"
    assert jar.add("my family and my friends") == "your family and your friends"
    assert jar.add("tiny") == "Tiny"
    jar.add("pie")
    assert jar.list() == ["pie", "your family and your friends", "Tiny"]
    assert jar.summary() == "Today you were thankful for pie, your family and your friends and Tiny. Me too."
    for i in range(20):
        jar.add(f"thing {i}")
    assert len(jar.list()) == tg.JAR_MAX
    clock[0] = _at(11, 27, 0, 5)      # past midnight: forgotten
    assert jar.list() == [] and jar.summary() == ""
    assert not hasattr(jar, "save") and not hasattr(jar, "state_file")


def test_what_you_might_ask():
    a = tg.asked
    assert a("im thankful for pie") == ("thankful", "pie")
    assert a("i am so grateful for my family") == ("thankful", "my family")
    assert a("what am i thankful for")[0] == "jar"
    assert a("what are you thankful for")[0] == "hers"
    assert a("happy thanksgiving")[0] == "happy"
    assert a("when is thanksgiving")[0] == "when"
    assert a("how many days until thanksgiving")[0] == "when"
    assert a("why are you wearing a hat")[0] == "hat"
    assert a("give thanks")[0] == "toast"
    assert a("thank the nodes")[0] == "toast"
    for no in ("thank you", "thanks chatty", "what time is it", "play the piano", "whats the weather"):
        assert a(no) is None, no


def test_replies():
    jar = tg.Jar(clock=lambda: _at(11, 26))
    said, mood = tg.reply_for("thankful", "pie", jar, _at(11, 26), random.Random(1))
    assert "Pie" in said and mood == "love_talk"
    assert "pie" in tg.reply_for("jar", "", jar, _at(11, 26))[0]
    said, mood = tg.reply_for("hat", "", jar, _at(11, 26))
    assert "buckles" in said and mood == "actually_talk"
    assert "Thanksgiving" in tg.reply_for("hat", "", jar, _at(11, 20))[0]
    assert "early" in tg.reply_for("happy", "", jar, _at(11, 23))[0]
    assert tg.face_message("pie: and\ncake") == "thanks:pie  and cake"


def _feast(home=lambda: None):
    notes = []
    state = Path(tempfile.mkdtemp()) / "t.json"
    return tg.Feast(home=home, notice=notes.append, start=lambda: 12 * 60, state_file=state), notes, state


def test_toast_once_a_year_at_midday_while_free():
    f, notes, state = _feast()
    assert f.due("sleep", _at(11, 25, 12, 30)) is None          # not Thanksgiving
    assert f.due("sleep", _at(11, 26, 11, 0)) is None           # too early
    assert f.due("active", _at(11, 26, 12, 30)) is None         # busy
    text = f.due("sleep", _at(11, 26, 12, 30))
    assert text and "Happy Thanksgiving" in text and notes
    assert f.due("sleep", _at(11, 26, 13, 0)) is None           # once
    assert json.loads(state.read_text()) == {"year": 2026}
    again = tg.Feast(notice=notes.append, start=lambda: 12 * 60, state_file=state)
    assert again.due("sleep", _at(11, 26, 14, 0)) is None       # remembered across restarts
    f2, _, _ = _feast()
    assert f2.due("sleep", _at(11, 26, 19, 30)) is None         # window over


def test_nobody_home_only_a_notice():
    f, notes, _ = _feast(home=lambda: False)
    assert f.due("sleep", _at(11, 26, 12, 30)) is None
    assert notes and "Thanksgiving" in notes[0]


def test_waltz_is_a_good_song_file():
    song = piano.load(tg.SONG)
    assert song and song.title == "Harvest Thank-You Waltz" and song.about
    assert 15 < song.seconds < piano.MAX_SECONDS
    assert any(m is None for _, _, m, _ in song.notes)       # the thank-you snap


def test_face_hat_and_leaves_only_on_the_day():
    face = FaceModel(800, 480, rng=random.Random(1))
    day, other = _at(11, 26), _at(11, 25)
    assert face.hat_on(day) and not face.hat_on(other)
    face.set_state("tiny", now=day)
    assert not face.hat_on(day)                 # not over the cat ears
    face.set_state("idle", now=day)
    face.update(0.1, day)
    assert face.leaves.items
    face.add_thanks("pie", now=day)
    assert face.thanks[1] == "pie"


def test_face_draws_thanks_leaf_then_forgets_it():
    calls = []

    class C:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append(name) or 10

    face = FaceModel(800, 480, rng=random.Random(1))
    day = _at(11, 26)
    face.add_thanks("pie", now=day)
    face.draw(C(), day + 2)
    assert "text" in calls and face.thanks
    face.draw(C(), day + tg.THANKS_SECONDS + 1)
    assert face.thanks is None


def test_voice_node_wiring():
    src = open(SRC).read()
    assert 'Announcer("thanksgiving", "Thanksgiving", feast.due, after="thanksgiving")' in src
    assert src.index("thanks_ask = thanksgiving.asked(prompt)") < src.index("piano_ask = piano.asked(prompt)")
    assert "extra=gratitude.summary" in src
    assert 'news.after == "thanksgiving"' in src


def test_bedtime_reads_the_jar():
    import bedtime as bt
    state = Path(tempfile.mkdtemp()) / "b.json"
    w = bt.WindDown(mesh=None, forecast=lambda: [], hourly=lambda: [], notice=lambda t: None,
                    state_file=state, extra=lambda: "Today you were thankful for pie. Me too.")
    text, _ = w.build(_at(11, 26, 21, 30))
    assert "thankful for pie" in text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
