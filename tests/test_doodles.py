import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["CHATTY_CURIOSITY"] = "0"
os.environ["CHATTY_GAMES"] = "0"          # bored -> she always draws
os.environ["CHATTY_CHESS"] = "0"          # (and never picks chess)
os.environ["CHATTY_TRICKSTER"] = "0"      # (or the mystery game)
os.environ["CHATTY_NIGHT_MODE"] = "0"
import doodles  # noqa: E402
import face_model  # noqa: E402
from face_model import FaceModel  # noqa: E402

T = 1_000_000.0


class Recorder:
    """A canvas that only counts calls, so drawing can run without a screen."""

    def __init__(self):
        self.calls = 0
        self.texts = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls += 1
            if name == "text":
                self.texts.append(args[0])
            return 10
        return call


def _face():
    face = FaceModel(800, 480, rng=random.Random(2))
    face.last_activity = T
    return face


def test_bored_face_starts_doodling():
    face = _face()
    face.next_game_at = 0
    face.update(0.1, T + face_model.BORED_AFTER + 1)
    assert face.doodle is not None
    assert face.busy()


def test_tap_stops_doodle_without_waking():
    face = _face()
    assert face.start_doodle("spiro", now=T)
    assert face.handle_tap((400, 240), now=T + 1) is True
    assert face.doodle is None


def test_conversation_stops_doodle():
    face = _face()
    face.start_doodle("rain", now=T)
    face.set_state("listening", now=T + 1)
    assert face.doodle is None


def test_every_style_draws_for_a_whole_piece():
    for style in doodles.ALL_STYLES + ("portrait",):
        d = doodles.Doodle(random.Random(4), T, style)
        for i in range(int(d.duration * 4)):          # 4 frames a second is enough to check
            c = Recorder()
            d.draw(c, 800, 480, T + i / 4)
            assert c.calls < 900, (style, c.calls)    # stays cheap for the Pi
        d.update(T + d.duration + 1)
        assert d.done


def test_hidden_word_shows_up_in_the_rain():
    d = doodles.Doodle(random.Random(5), T, "rain")
    d.WORDS = ["BE KIND"]
    d.draw(Recorder(), 800, 480, T)
    d.layout["next_word"] = 1e12
    d._place_word(d.layout)
    seen = []
    for i in range(60):
        c = Recorder()
        d.draw(c, 800, 480, T + i / 15)
        seen = c.texts
    assert all(ch in seen for ch in "BEKIND")



if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
