"""Imagination: 'Hey Chatty, imagine a dragon', the rainbow mood and daydreams."""
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["CHATTY_CURIOSITY"] = "0"
os.environ["CHATTY_GAMES"] = "0"
os.environ["CHATTY_DOODLES"] = "0"
os.environ["CHATTY_CHESS"] = "0"
os.environ["CHATTY_TRICKSTER"] = "0"
import imagine  # noqa: E402
import face_model  # noqa: E402
from face_model import FaceModel  # noqa: E402


def _noon():
    d = time.localtime()
    return time.mktime((d.tm_year, d.tm_mon, d.tm_mday, 12, 0, 0, 0, 0, -1))


T = _noon()


def _face():
    face = FaceModel(800, 480, rng=random.Random(1))
    face.last_activity = T
    return face


class FakeCanvas:
    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        def call(*a, **k):
            self.calls += 1
        return call

    def measure(self, txt, size):
        return len(txt) * size * 0.5


def test_what_counts_as_imagine():
    assert imagine.asked("imagine") == ""
    assert imagine.asked("imagine something") == ""
    assert imagine.asked("use your imagination") == ""
    assert imagine.asked("surprise me") == ""
    assert imagine.asked("can you imagine a dragon for me") == "a dragon"
    assert imagine.asked("lets imagine if dogs could fly") == "if dogs could fly"
    assert imagine.asked("what time is it") is None
    assert imagine.asked("what's the weather") is None
    assert imagine.asked("play imagine dragons") is None      # a band, not a request


def test_ideas_are_made_up_and_kind():
    rng = random.Random(7)
    for _ in range(200):
        text = imagine.idea(rng)
        assert 20 < len(text) < 240 and "{" not in text
    for topic in ("a dragon", "pizza", "elephants", "tiny", "you", "me as a pirate",
                  "if dogs could fly", "you were a cloud", "a world where everyone sang"):
        for _ in range(20):
            text = imagine.idea(rng, topic)
            assert "{" not in text and len(text) < 280, text


def test_topic_words_turn_around():
    rng = random.Random(3)
    assert "If I were a cloud" in imagine.idea(rng, "you were a cloud")
    assert "Tiny the cat" in imagine.idea(rng, "tiny")
    assert " me as a pirate" in imagine.idea(rng, "you as a pirate")
    assert "a dragon" in imagine.idea(rng, "dragon")


def test_mood_sweeps_the_rainbow():
    face = _face()
    face.set_state("imagine", now=T)
    assert face.imagine_since == T
    face.set_state("imagine_talk", now=T + 1)
    assert face.imagine_since == T            # same sweep while she talks
    assert face.busy()
    for i in range(10):
        face.update(0.1, T + 1 + i / 10)
    c = FakeCanvas()
    face.draw(c, T + 2)
    assert c.calls > 20
    assert imagine.sweep(0) == 0 and imagine.sweep(imagine.SWEEP) == 1


def test_daydream_lives_in_the_doodle_slot_and_a_tap_stops_it():
    face = _face()
    assert face.start_daydream(now=T)
    assert face.activity() == "doodle:imagine"
    face.draw(FakeCanvas(), T + 5)
    assert face.handle_tap((10, 10), now=T + 6)
    assert face.doodle is None


def test_daydream_said_once_in_the_daytime_then_waits():
    face = _face()
    face.start_daydream(now=T)
    text = face.doodle.text
    for i in range(200):
        face.update(0.1, T + i / 10)
    assert face.outbox == ["notify:imagine:" + text]
    face.outbox.clear()
    face.start_daydream(now=T + 60)
    for i in range(200):
        face.update(0.1, T + 60 + i / 10)
    assert face.outbox == []                  # at most every CHATTY_IMAGINE_GAP


def test_daydream_stays_quiet_at_night():
    face = _face()
    night = T + 12 * 3600                      # midnight
    face.last_activity = night
    face.start_daydream(now=night)
    for i in range(200):
        face.update(0.1, night + i / 10)
    assert face.outbox == []


def test_bored_she_sometimes_daydreams():
    old = imagine.SHARE
    imagine.SHARE = 1.0
    try:
        face = _face()
        face.update(0.1, T + face_model.BORED_AFTER + 1)
        assert face.activity() == "doodle:imagine"
    finally:
        imagine.SHARE = old


def test_panel_can_start_a_daydream():
    import panel
    assert "imagine" in panel.FACE_THINGS


def test_voice_node_sweeps_then_speaks():
    """Lift imagine_out_loud() out of the voice node (it opens the mic when imported)."""
    import ast
    src = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")
    tree = ast.parse(open(src).read())
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "imagine_out_loud"]
    calls = []

    class Face:
        def state(self, s):
            calls.append(("face", s))

    class Clock:
        def sleep(self, s):
            calls.append(("wait", s))

    ns = {"face": Face(), "time": Clock(), "random": random.Random(0), "imagine": imagine,
          "say": lambda text, mood="speaking": calls.append(("say", mood, text))}
    exec(compile(ast.Module(body=fn, type_ignores=[]), src, "exec"), ns)
    ns["imagine_out_loud"]("What if pancakes could fly?")
    assert calls[0] == ("face", "imagine") and calls[1][0] == "wait"
    assert calls[2][0] == "say" and calls[2][1] == "imagine_talk"
    assert calls[2][2].endswith("What if pancakes could fly?")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
