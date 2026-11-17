"""The piano: song files, understanding requests, the piano sound, the keyboard on her
face, and the voice node's handling. Only numpy is needed (the sound is made in memory)."""
import ast
import os
import random
import re
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CHATTY_NIGHT_MODE", "0")
os.environ["CHATTY_SONGS_DIR"] = os.path.join(tempfile.mkdtemp(), "songs")   # no songs of yours
import piano  # noqa: E402
from face_model import FaceModel  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")
T = 1_000_000.0

SONG = """
# a test song
title: Test Tune
by: Nobody
names: test tune, the testing song
tempo: 120
time: 4/4
right: C4 D4 E4:0.5 F#4 G4:1 | C4+E4+G4:2 r:1 x   # a chord, a rest, a snap
left:  C3:2 G2 | C3:1/3 D3 E3 r:1 r:2
"""


def _reset():
    piano.last.update(key="", at=0.0, listed=0.0)


# ----- song files -----

def test_note_numbers():
    assert piano.midi("C4") == 60 and piano.midi("A4") == 69
    assert piano.midi("F#3") == 54 and piano.midi("Bb2") == 46
    assert piano.note_name(61) == "C#4"
    for bad in ("H4", "C", "C9", "x4"):
        try:
            piano.midi(bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def test_parse_lengths_chords_rests_and_snaps():
    song = piano.parse(SONG, "test")
    assert song.title == "Test Tune" and song.tempo == 120
    right = [(round(t, 3), round(d, 3), n) for t, d, n, h in song.notes if h == "right"]
    # 120 a minute: a beat is half a second; a note without a length keeps the one before
    assert right[:5] == [(0.0, 0.5, 60), (0.5, 0.5, 62), (1.0, 0.25, 64), (1.25, 0.25, 66), (1.5, 0.5, 67)]
    assert [n for t, d, n in right if t == 2.0] == [60, 64, 67]          # the chord
    assert (3.5, 0.5, None) in right                                     # the snap, after the rest
    left = [(round(t, 3), n) for t, d, n, h in song.notes if h == "left"]
    assert left[2:5] == [(2.0, 48), (2.167, 50), (2.333, 52)]            # a triplet
    assert song.bars == []                                               # it all adds up
    assert song.seconds == 4.0
    assert "test tune" in song.names and "the testing song" in song.names


def test_mistakes_name_the_line():
    for text, words in (("title: x\nright: C4 Q4", "line 2"), ("right: C4:zero", "line 1"),
                        ("color: blue", "unknown field"), ("tempo: 5\nright: C4", "tempo"),
                        ("title: only a title", "no notes")):
        try:
            piano.parse(text)
            raise AssertionError(text)
        except ValueError as e:
            assert words in str(e), (text, str(e))


def test_counting_is_checked():
    song = piano.parse("time: 4/4\nright: C4 D4 E4 | F4 G4 A4 B4 | C5:4\nleft: C3:3 | C3:4 | C3:4", "x")
    assert song.bars == []          # the first bar may be short (a pickup)
    song = piano.parse("time: 4/4\nright: C4:4 | D4:1 E4 F4 | G4:4 | C5:4\nleft: C3:4 | C3:4 | C3:4 | C3:4", "x")
    assert any("right hand, bar 2: 3 beats" in p for p in song.bars)
    assert any("different lengths" in p for p in song.bars)


def test_built_in_songs_are_clean():
    songs = piano.library()
    assert {"ode-to-joy", "twinkle-twinkle", "fur-elise", "jingle-bells", "mary-had-a-little-lamb",
            "chattys-tune"} <= set(songs)
    for key, song in songs.items():
        assert song.bars == [], (key, song.bars)
        assert 5 < song.seconds < piano.MAX_SECONDS, key
        assert song.title.isascii() and song.by, key      # the Pi's font is basic
        lo, hi = song.keys_range()
        assert 21 <= lo <= hi <= 108


def test_your_own_songs_folder_adds_and_replaces():
    folder = tempfile.mkdtemp()
    with open(os.path.join(folder, "spooky-tune.txt"), "w") as f:
        f.write("title: Spooky Tune\nnames: spooky\nright: A3 C4 E4 A4")
    with open(os.path.join(folder, "ode-to-joy.txt"), "w") as f:
        f.write("title: My Ode\nright: E4 E4 F4 G4")
    with open(os.path.join(folder, "broken.txt"), "w") as f:
        f.write("right: not a note")
    old, piano.SONGS_DIR = piano.SONGS_DIR, folder
    try:
        songs = piano.library()
        assert songs["spooky-tune"].local and songs["ode-to-joy"].title == "My Ode"
        assert "broken" not in songs
        assert piano.asked("play spooky on the piano") == ("play", "spooky-tune")
        assert piano.song_list(songs).startswith("I can play My Ode, Spooky Tune, ")   # yours first
    finally:
        piano.SONGS_DIR = old


# ----- understanding the question -----

def test_requests():
    _reset()
    cases = {
        "can you play the piano": ("any", ""),
        "can chatty play the piano": ("any", ""),
        "play me a song": ("any", ""),
        "play something on the piano": ("any", ""),
        "play ode to joy": ("play", "ode-to-joy"),
        "play owed to joy": ("play", "ode-to-joy"),           # misheard
        "play fur elise": ("play", "fur-elise"),
        "play for elise on the piano please": ("play", "fur-elise"),
        "play twinkle twinkle": ("play", "twinkle-twinkle"),
        "play your song": ("play", "chattys-tune"),
        "what songs can you play": ("list", ""),
        "how do i teach you a new song": ("how", ""),
        "play stairway to heaven on the piano": ("unknown", "stairway to heaven"),
    }
    for prompt, want in cases.items():
        assert piano.asked(prompt) == want, (prompt, piano.asked(prompt))


def test_other_kinds_of_play_are_left_alone():
    _reset()
    for prompt in ("play chess", "play a game", "play tic tac toe", "play chess with the rain node",
                   "lets play", "play hello in morse code", "play the trickster", "what time is it",
                   "what games can you play", "again"):
        assert piano.asked(prompt) is None, prompt


def test_again_and_a_name_after_the_list():
    _reset()
    assert piano.asked("play it again") is None
    piano.remember("fur-elise", now=T)
    assert piano.asked("play it again", now=T + 30) == ("again", "")
    assert piano.asked("one more time", now=T + 30) == ("again", "")
    assert piano.asked("play it again", now=T + 400) is None           # too long ago
    assert piano.asked("ode to joy", now=T) is None
    piano.listed(now=T)
    assert piano.asked("ode to joy", now=T + 10) == ("play", "ode-to-joy")
    assert piano.asked("ode to joy", now=T + 100) is None
    _reset()


def test_switched_off():
    old, piano.ENABLED = piano.ENABLED, False
    try:
        assert piano.asked("play the piano") is None
    finally:
        piano.ENABLED = old


# ----- the sound -----

def test_render_is_the_right_length_and_never_too_loud():
    song = piano.parse(SONG, "test")
    audio = piano.render(song, volume=0.3)
    assert abs(len(audio) / piano.RATE - (song.seconds + 1.5)) < 0.05
    assert np.all(np.isfinite(audio)) and np.max(np.abs(audio)) <= 0.3 + 1e-6
    lead = int(piano.RATE * 0.05)
    assert np.max(np.abs(audio[lead + 100:lead + 2000])) > 0.05        # the first note sounds at once
    # the pitch is right: middle C's strongest frequency is near 261.6 Hz
    note = piano._note_samples(60, 1.0)[:piano.RATE // 2]
    spectrum = np.abs(np.fft.rfft(note))
    peak = np.argmax(spectrum) * piano.RATE / len(note)
    assert abs(peak - 261.6) < 4, peak


def test_long_songs_are_cut_with_a_fade():
    song = piano.parse("tempo: 120\nright: " + "C4 " * 40, "long")      # 20 s
    audio = piano.render(song, max_seconds=5)
    assert len(audio) / piano.RATE < 7
    assert np.max(np.abs(audio[int(piano.RATE * 5.2):])) < 1e-6


def test_play_file_stops_on_a_tap_and_cleans_up():
    calls = []

    class Proc:
        returncode = None

        def __init__(self, args, **kw):
            calls.append(args)

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    path = os.path.join(tempfile.mkdtemp(), "song.wav")
    open(path, "wb").close()
    old = piano.subprocess.Popen
    piano.subprocess.Popen = Proc
    taps = iter([False, False, True])
    started = []
    try:
        result = piano.play_file(path, 30, stop=lambda: next(taps), on_start=started.append)
    finally:
        piano.subprocess.Popen = old
    assert result == "stopped" and calls[0][0] == "aplay" and len(started) == 1
    assert not os.path.exists(path)


# ----- the keyboard on her face -----

class Canvas:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append((name,) + a)

    def measure(self, text, size):
        return len(text) * size * 0.5


def test_face_lights_the_keys_in_time():
    face = FaceModel(800, 480, rng=random.Random(1))
    face.set_state("piano", now=T)
    face.set_piano(f"{T}:ode-to-joy", now=T)
    p = face.piano
    assert p and p["lo"] % 12 == 0 and p["hi"] % 12 == 11 and p["hi"] - p["lo"] >= 35
    t, down, newest = face.piano_now(T + 0.1)
    assert down.get(64) == "right" and newest[0] == 64      # the first E
    assert any(hand == "left" for hand in down.values())
    face.update(1 / 30, T + 0.1)
    c = Canvas()
    face.draw(c, T + 0.1)
    texts = [a[1] for a in c.calls if a[0] == "text"]
    assert "Ode to Joy" in texts
    assert face.busy()
    # the keyboard stays a moment after the end, then goes
    end = p["end"]
    assert face.piano_now(T + end + 1) is not None
    assert face.piano_now(T + end + 3) is None and face.piano is None


def test_face_snaps_off_and_unknown_songs():
    face = FaceModel(800, 480, rng=random.Random(1))
    face.set_piano(f"{T}:no-such-song", now=T)
    assert face.piano is None
    face.set_piano(f"{T}:jingle-bells", now=T)
    assert face.piano
    face.set_piano("off")
    assert face.piano is None
    old = piano.SONGS_DIR
    piano.SONGS_DIR = tempfile.mkdtemp()
    with open(os.path.join(piano.SONGS_DIR, "snappy.txt"), "w") as f:
        f.write("tempo: 60\nright: x C4 x C4")
    try:
        face.set_piano(f"{T}:snappy", now=T)
        c = Canvas()
        face.draw(c, T + 0.1)
        assert "snap!" in [a[1] for a in c.calls if a[0] == "text"]
    finally:
        piano.SONGS_DIR = old


def test_face_hears_the_message():
    src = open(os.path.join(os.path.dirname(SRC), "chatty_face.py")).read()
    assert 'elif key == "piano"' in src and "face.set_piano(value)" in src


# ----- the voice node -----

def voice(result="done", taps=()):
    """piano_command and friends lifted out of the voice node, with stand-ins."""
    tree = ast.parse(open(SRC).read())
    names = {"piano_stop", "play_song", "piano_command"}
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    said, sent, played, logged, listened = [], [], [], [], []

    class Face:
        def __getattr__(self, name):
            return lambda *a, **k: sent.append((name,) + a)

    class Panel:
        hush = False

    class Watchdog:
        def ping(self):
            pass

    fake = type(sys)("piano_stub")
    fake.__dict__.update(piano.__dict__)
    fake.render_file = lambda song: "/nowhere.wav"

    def play_file(path, seconds, stop=None, on_start=None):
        played.append(path)
        if on_start:
            on_start(T)
        return result
    fake.play_file = play_file
    fake.discard = lambda path: None
    tap_list = list(taps)

    ns = {"piano": fake, "face": Face(), "panel": Panel(), "watchdog": Watchdog(),
          "time": type(sys)("t"), "random": random.Random(0), "re": re,
          "threading": __import__("threading"), "LISTEN_SECONDS": 8,
          "say": lambda text, mood="speaking": said.append(text),
          "pick": lambda lines: lines[0], "red_waiting": lambda: False,
          "touch_event": lambda: tap_list.pop(0) if tap_list else None,
          "flush_audio": lambda: None, "go_to_sleep": lambda: None,
          "start_listening": lambda s: listened.append(s),
          "log_turn": lambda *a, **k: logged.append((a, k))}
    ns["time"].sleep = lambda s: None
    ns["time"].time = __import__("time").time
    exec(compile(ast.Module(body=body, type_ignores=[]), SRC, "exec"), ns)
    return ns, said, sent, played, logged, listened


def test_can_you_play_the_piano():
    _reset()
    ns, said, sent, played, logged, _ = voice()
    ns["piano_command"]("can you play the piano", *piano.asked("can you play the piano"))
    assert said[0].startswith("I sure can! ") and played == ["/nowhere.wav"]
    assert ("state", "piano") in sent
    assert any(s[0] == "send" and re.match(r"^piano:\d+\.\d\d:[a-z-]+$", s[1]) for s in sent)
    assert logged[-1][1]["notes"] == "done"
    assert piano.last["key"]
    _reset()


def test_a_named_song_and_again():
    _reset()
    ns, said, sent, played, logged, _ = voice()
    ns["piano_command"]("play ode to joy", "play", "ode-to-joy")
    assert "Ode to Joy" in said[0]
    assert ("send", f"piano:{T:.2f}:ode-to-joy") in sent
    ns["piano_command"]("play it again", *piano.asked("play it again"))
    assert any(line.startswith("Encore! ") and "Ode to Joy" in line for line in said)
    assert len(played) == 2
    _reset()


def test_a_tap_stops_it():
    _reset()
    ns, said, sent, played, logged, _ = voice(result="stopped")
    ns["piano_command"]("play jingle bells", "play", "jingle-bells")
    assert ("send", "piano:off") in sent and said[-1] == piano.STOPPED[0]
    assert ns["piano_stop"]() is False
    ns2 = voice(taps=["wake"])[0]
    assert ns2["piano_stop"]() is True
    _reset()


def test_quiet_panel_question_doesnt_play():
    ns, said, sent, played, _, _ = voice()
    ns["panel"].hush = True
    ns["piano_command"]("play ode to joy", "play", "ode-to-joy")
    assert played == [] and "out loud" in said[0]


def test_list_then_listen_for_a_name():
    _reset()
    ns, said, _, _, _, listened = voice()
    ns["piano_command"]("what songs can you play", "list", "")
    assert said[0].startswith("I can play ") and said[0].endswith("Which one would you like?")
    assert listened == [8] and piano.last["listed"] > 0
    _reset()


def test_voice_node_checks_piano_after_morse():
    src = open(SRC).read()
    i, j = src.index("piano_ask = piano.asked(prompt)"), src.index("    if morse_ask:\n        morse_command")
    assert i < j


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
