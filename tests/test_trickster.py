"""Who's the Trickster? The mystery game on Chatty's face: pranks and clues, the
meeting and the vote (tap, panel, voice), pausing while she talks, and the score."""
import ast
import os
import random
import re
import sys
import tempfile

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))
os.environ["CHATTY_CURIOSITY"] = "0"
os.environ["CHATTY_NIGHT_MODE"] = "0"
os.environ["CHATTY_TRICKSTER_SCORES"] = os.path.join(tempfile.mkdtemp(), "trickster.json")
import face_model  # noqa: E402
import panel  # noqa: E402
import trickster  # noqa: E402
from face_model import FaceModel  # noqa: E402

T = 1_000_000.0
STEP = 1 / 15


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


def run(game, until, now=T, limit=400.0):
    """Step the game until until(game) is true; returns the time."""
    t = now
    while not until(game) and t - now < limit:
        t += STEP
        game.update(t)
    assert until(game), f"stuck in {game.phase}"
    return t


def test_a_whole_game_plays_out_kindly():
    for seed in range(12):
        g = trickster.Mystery(random.Random(seed), T)
        canvas = Recorder()
        t = T
        while not g.done:
            t += STEP
            g.update(t)
            if int((t - T) * 15) % 30 == 0:
                g.draw(canvas, 800, 480, t)
            assert t - T < 200, "a game should be over in a few minutes"
        assert 1 <= len(g.clues) <= trickster.PRANKS
        for clue in g.clues:
            assert g.trickster in clue["near"]          # the trickster is always seen nearby
        assert g.accused in g.names and g.solved == (g.accused == g.trickster)
        assert canvas.calls > 100
        said = " ".join(canvas.texts).lower()
        for word in ("impostor", "kill", "eject", "dead", "sus"):
            assert not re.search(r"\b" + word + r"\b", said), word
    data = trickster.load_scores()
    assert data["games"] >= 12 and sum(data["tricksters"].values()) == data["games"]
    assert "mysteries" in trickster.score_text()


def test_trickster_fibs_and_chatty_reads_the_clues():
    g = trickster.Mystery(random.Random(5), T)
    run(g, lambda g: g.phase == "vote")
    assert len(g.alibis) == len(g.names)
    if g.trickster in g.claims and g.clues:
        assert g.claims[g.trickster] != g.clues[-1]["station"]      # "I was far away!"
    guesses = {g.best_guess() for _ in range(10)}
    top = max(g.suspicion(n) for n in g.names)
    assert all(g.suspicion(n) == top for n in guesses)


def test_you_can_vote_by_tapping_a_character():
    g = trickster.Mystery(random.Random(3), T, human=True)
    t = run(g, lambda g: g.phase == "vote")
    pick = next(n for n in g.names if n != g.trickster)          # a wrong guess, on purpose
    x, y, r = g.seats(800, 480)[pick]
    assert g.tap((x, y), 800, 480) is True
    assert g.you == pick
    assert g.tap((x, y), 800, 480) is True and g.you == pick       # one vote each
    run(g, lambda g: g.phase == "reveal", now=t)
    assert g.ballots["you"] == pick and g.ballots["chatty"] == pick   # she goes with your hunch
    t = run(g, lambda g: g.done, now=t)


def test_waits_for_your_vote_when_you_asked_for_the_game():
    waits = {}
    for human in (False, True):
        g = trickster.Mystery(random.Random(4), T, human=human)
        t = run(g, lambda g: g.phase == "vote")
        start = g.t
        run(g, lambda g: g.phase == "reveal", now=t)
        waits[human] = g.t - start
        assert "you" not in g.ballots and "chatty" in g.ballots     # she voted herself
    assert waits[True] > waits[False] + 10


def test_bell_calls_the_meeting_and_a_stray_tap_hides_the_game():
    g = trickster.Mystery(random.Random(1), T)
    bx, by, r = g.bell_box(800, 480)
    assert g.tap((bx + r, by), 800, 480) is True
    assert g.phase == "gather" and g.meeting_by == "you"
    g2 = trickster.Mystery(random.Random(1), T)
    assert g2.tap((200, 200), 800, 480) is None


def test_on_the_face_and_from_the_panel():
    face = FaceModel(800, 480, rng=random.Random(2))
    assert face.mystery_message("")                       # "trickster" from the panel or voice
    assert face.mystery and face.mystery.human and face.activity() == "trickster"
    assert face.busy()
    info = face.panel_info()["mystery"]
    assert info["phase"] == "intro" and info["can_vote"] and info["trickster"] == ""
    face.draw(Recorder(), T)
    # a vote before any meeting rings the bell first
    assert face.mystery_message("vote:the rain node")
    assert face.mystery.phase == "gather" and face.mystery.you == "rain"
    assert not face.mystery_message("vote:nobody")
    assert "trickster:vote:rain" in panel.FACE_THINGS and "trickster:meeting" in panel.FACE_THINGS
    face.calm()
    assert face.mystery is None


def test_waits_while_she_talks_and_is_forgotten_after_a_long_while():
    face = FaceModel(800, 480, rng=random.Random(2))
    face.start_mystery(now=T)
    face.update(STEP, T + 1)
    g = face.mystery
    played = g.t
    face.set_state("speaking", T + 2)
    face.update(STEP, T + 30)
    assert face.mystery is g and g.t == played             # paused, not gone
    face.set_state("idle", T + 31)
    face.update(STEP, T + 31.1)
    assert face.mystery is g and 0 < g.t - played <= 0.25   # picks up where it was
    face.set_state("listening", T + 32)
    face.update(STEP, T + 32 + trickster.FORGET_AFTER + 5)
    assert face.mystery is None


def test_a_tap_on_the_face_votes_or_hides():
    face = FaceModel(800, 480, rng=random.Random(7))
    face.start_mystery(human=True, now=T)
    assert face.handle_tap((300, 200), T + 1)               # hides it, doesn't wake her
    assert face.mystery is None


def test_bored_face_sometimes_hosts_a_mystery():
    old = trickster.SHARE
    trickster.SHARE = 1.0
    try:
        face = FaceModel(800, 480, rng=random.Random(2))
        face.last_activity = T
        face.next_game_at = 0
        face.update(0.1, T + face_model.BORED_AFTER + 1)
        assert face.mystery is not None and not face.mystery.human
    finally:
        trickster.SHARE = old


def test_names_from_voice():
    assert trickster.node_key("I think it's the rain node") == "rain"
    assert trickster.node_key("vote for the word clock") == "wordclock"
    assert trickster.node_key("it was greenhouse") == "greenhouse"
    assert trickster.node_key("my brain hurts") == ""


def _voice_mystery_command():
    """Lift mystery_command out of the voice node (it opens the mic when imported)."""
    src = os.path.join(HERE, "..", "src", "chatty_voice_node.py")
    tree = ast.parse(open(src).read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "mystery_command")
    said, sent, logged = [], [], []

    class Face:
        @staticmethod
        def trickster(what=""):
            sent.append(what)

    ns = {"re": re, "trickster": trickster, "say": said.append, "go_to_sleep": lambda: None,
          "face": Face, "pick": lambda lines: lines[0], "log_turn": lambda kind, *a, **k: logged.append(kind)}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), src, "exec"), ns)
    return ns["mystery_command"], said, sent, logged


def test_voice_commands():
    cmd, said, sent, logged = _voice_mystery_command()
    cmd("who's the trickster")
    assert sent[-1] == "" and "trickster" in said[-1].lower()
    cmd("i think the trickster is the rain node")
    assert sent[-1] == "vote:rain" and "Rain" in said[-1]
    cmd("i vote for the word clock")
    assert sent[-1] == "vote:wordclock"
    n = len(sent)
    cmd("what's the trickster score")
    assert len(sent) == n and logged[-1] == "command:trickster_score"
    src = open(os.path.join(HERE, "..", "src", "chatty_voice_node.py")).read()
    assert "face.trickster(\"meeting\")" in src


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
