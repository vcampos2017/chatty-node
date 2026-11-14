"""Morse code: the code table, reading spoken and typed dots and dashes, the beeps,
hearing beeps on the mic, the face's telegraph tape, and the voice node's handling.
Only numpy is needed (the beeps are made and decoded in memory)."""
import ast
import os
import queue
import random
import re
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("CHATTY_NIGHT_MODE", "0")
import morse  # noqa: E402
import panel_link  # noqa: E402
import door  # noqa: E402
from face_model import FaceModel  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")


# ----- the code -----

def test_round_trip_letters_digits_punctuation():
    text = "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG 0123456789 ?!.,"
    assert morse.decode(morse.encode(text)) == "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG 0123456789 ?!.,"


def test_known_codes():
    assert morse.encode("sos") == "... --- ..."
    assert morse.encode("Hi there") == ".... .. / - .... . .-. ."
    assert morse.decode("...---...") == "SOS"              # sent as one run
    assert morse.decode(".- -... / -.-.") == "AB C"


def test_unknown_marks_are_question_marks():
    assert morse.decode_detail(".... ........ ..") == ("H?I", 1)


def test_typed_lookalikes_are_tidied():
    assert morse.clean_code("·−·  —·· | ...") == ".-. -.. / ..."
    assert morse.clean_code(".-   -...") == ".- / -..."     # a long gap is a new word


def test_spoken_form():
    assert morse.spoken("... --- ...") == "dit dit dit, dah dah dah, dit dit dit"
    assert morse.to_words(".- / -") == "dot dash new word dash"


def test_long_messages_are_cut_at_a_word():
    text, cut = morse.fit("one two three four five six seven eight nine ten eleven twelve")
    assert cut and len(text) <= morse.MAX_CHARS and text.startswith("one two")
    assert morse.fit("hello") == ("hello", False)


# ----- understanding the question -----

def test_send_questions():
    assert morse.asked("say hello in morse") == ("send", "hello")
    assert morse.asked("how do you say i love you in morse code") == ("send", "i love you")
    assert morse.asked("whats tiny in morse") == ("send", "tiny")
    assert morse.asked("morse code for the word chatty") == ("send", "chatty")
    assert morse.asked("send an sos") == ("send", "sos")


def test_read_spoken_dots_and_dashes():
    assert morse.asked("what does dot dot dot next dash dash dash next dot dot dot mean") == \
        ("read", "... --- ...")
    assert morse.asked("dit dah next dah dit dit dit") == ("read", ".- -...")
    assert morse.asked("read morse dot dot dot dot next dot dot new word dot dash") == \
        ("read", ".... .. / .-")


def test_listen_teach_about():
    assert morse.asked("listen for morse") == ("listen", "")
    assert morse.asked("decode morse code") == ("listen", "")
    assert morse.asked("teach me morse code") == ("teach", "")
    assert morse.asked("what is morse code") == ("about", "")
    assert morse.asked("can you read morse code") == ("about", "")
    assert morse.asked("who invented morse code") == ("about", "")


def test_everyday_questions_are_left_alone():
    for p in ("what time is it", "tell me about the dot com bubble", "whats the weather in moscow",
              "set a timer for ten minutes", "imagine a dragon", "dash to the store"):
        assert morse.asked(p) is None, p


def test_typed_code_is_found_but_an_ellipsis_is_not():
    assert morse.find_code("what does .... .. mean?") == ".... .."
    assert morse.find_code("morse: .- -...") == ".- -..."
    assert morse.find_code("... --- ...") == "... --- ..."
    assert morse.find_code("Hi... how are you") is None
    assert morse.find_code("well -- maybe") is None


def test_read_replies():
    assert morse.read_reply(".... ..") == "That spells H, I."
    assert "hello world" in morse.read_reply(".... . .-.. .-.. --- / .-- --- .-. .-.. -..")
    assert "911" in morse.read_reply("... --- ...")
    assert "next between letters" in morse.read_reply("....----....--")


# ----- the panel and the message door -----

def test_panel_turns_typed_code_into_her_words():
    typed = panel_link.typed_question("... --- ...")
    assert typed == "read morse dot dot dot next dash dash dash next dot dot dot"
    assert morse.asked(typed) == ("read", "... --- ...")
    assert panel_link.typed_question("Rain-node?") == "rain node"     # unchanged otherwise


def test_door_answers_morse_in_writing():
    reply = door.own_answer(".... . .-.. .-.. ---")
    assert '"HELLO"' in reply and ".... .." in reply
    assert door.own_answer("How do you say hi in Morse code?") == '"hi" in Morse code: .... ..'
    assert door.own_answer("What's the weather like?") is None
    assert "911" in door.own_answer("... --- ...")


# ----- the beeps, and hearing them -----

def _pcm(code, wpm, freq, noise=0.02, seed=1, rate=16000):
    s = morse.samples(code, wpm=wpm, freq=freq, rate=rate, volume=0.25)
    s = np.concatenate([np.zeros(rate // 2), s, np.zeros(rate)])
    s = s + np.random.default_rng(seed).normal(0, noise, len(s))
    return (np.clip(s, -1, 1) * 32767).astype(np.int16).tobytes()


def test_timing_is_standard():
    # PARIS is 50 dits long, including the word gap after it
    assert sum(n for _, n, _ in morse.elements(morse.encode("paris"))) == 43
    assert abs(morse.unit_seconds(12) - 0.1) < 1e-9


def test_hears_beeps_at_many_speeds_and_pitches():
    code = morse.encode("cq de chatty 73")
    for wpm in (8, 13, 20, 28):
        for freq in (500, 700, 950):
            got = morse.decode_audio(_pcm(code, wpm, freq), 16000)
            assert got and got["text"] == "CQ DE CHATTY 73", (wpm, freq, got)
            assert abs(got["wpm"] - wpm) < 1.5 and abs(got["tone"] - freq) <= 50


def test_hears_practice_app_timing_and_a_shaky_hand():
    """Farnsworth timing (letters fast, gaps stretched) and a hand key that's off by up to 20%."""
    rng = np.random.default_rng(3)

    def keyed(text, wpm, gap_wpm, jitter):
        unit, gap = 1.2 / wpm, 1.2 / gap_wpm
        parts = [np.zeros(8000)]
        for on, n, _ in morse.elements(morse.encode(text)):
            d = (n * unit if on or n == 1 else n * gap) * (1 + rng.uniform(-jitter, jitter))
            t = np.arange(int(d * 16000)) / 16000
            parts.append(0.25 * np.sin(2 * np.pi * 700 * t) if on else np.zeros(len(t)))
        parts.append(np.zeros(16000))
        s = np.concatenate(parts)
        s = s + rng.normal(0, 0.02, len(s))
        return (np.clip(s, -1, 1) * 32767).astype(np.int16).tobytes()

    assert morse.decode_audio(keyed("hello world", 20, 10, 0), 16000)["text"] == "HELLO WORLD"
    assert morse.decode_audio(keyed("cq cq de chatty", 15, 15, 0.2), 16000)["text"] == "CQ CQ DE CHATTY"


def test_hears_single_letters():
    for word in ("e", "t", "sos", "k"):
        got = morse.decode_audio(_pcm(morse.encode(word), 13, 650), 16000)
        assert got["text"] == word.upper(), (word, got)


def test_noise_and_silence_are_not_morse():
    rng = np.random.default_rng(5)
    hiss = (rng.normal(0, 0.05, 16000 * 4) * 32767).astype(np.int16).tobytes()
    assert morse.decode_audio(hiss, 16000) is None
    assert morse.decode_audio(bytes(16000 * 2 * 3), 16000) is None


def test_quiet_after_tells_when_they_stopped():
    got = morse.decode_audio(_pcm("... ---", 15, 650), 16000)
    assert 0.9 < got["quiet_after"] < 1.3


def test_wav_file():
    path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "test_morse.wav")
    morse.write_wav("... ---", path)
    try:
        assert os.path.getsize(path) > 1000
    finally:
        os.remove(path)


# ----- the face -----

class Canvas:
    def __init__(self):
        self.texts, self.calls = [], 0

    def __getattr__(self, name):
        def draw(*a, **k):
            self.calls += 1
        return draw

    def text(self, txt, pos, size, color):
        self.texts.append(txt)

    def measure(self, txt, size):
        return len(txt) * size * 0.6


def test_face_tape_follows_the_beeps():
    face = FaceModel(800, 480, rng=random.Random(1))
    t0 = 1000.0
    face.set_state("morse", now=t0)
    face.set_morse(f"{t0}:0.1:.... ..", now=t0)          # "HI" at 12 WPM
    assert face.busy()
    t, on = face.morse_now(t0 + 0.05)
    assert on and abs(t - 0.5) < 1e-6                     # first dit sounding
    assert face.morse_now(t0 + 0.15)[1] is False          # the gap after it
    c = Canvas()
    face.draw(c, t0 + 0.15)
    assert "H" not in c.texts                             # H isn't finished yet
    c = Canvas()
    face.draw(c, t0 + 1.2)                                # after H (7 dits) and the gap
    assert "H" in c.texts and "I" not in c.texts
    c = Canvas()
    face.draw(c, t0 + 1.6)
    assert "H" in c.texts and "I" in c.texts and "Morse code" in c.texts


def test_face_eyes_flash_with_a_beep():
    face = FaceModel(800, 480, rng=random.Random(1))
    t0 = 1000.0
    face.set_state("morse", now=t0)
    for i in range(10):
        face.update(1 / 30, t0 + i / 30)
    calm = face.color
    face.set_morse(f"{t0 + 1}:0.1:-", now=t0)
    face.update(1 / 30, t0 + 1.1)
    assert sum(face.color) > sum(calm) + 20


def test_face_tape_goes_away_and_off_clears():
    face = FaceModel(800, 480, rng=random.Random(1))
    face.set_morse("1000:0.1:.", now=1000)
    assert face.morse_now(1000.05)
    assert face.morse_now(1000 + 0.1 + 3.5) is None and face.morse is None
    face.set_morse("1000:0.1:.", now=1000)
    face.set_morse("off")
    assert face.morse is None
    face.set_morse("garbage")
    assert face.morse is None


# ----- the voice node -----

def voice(heard_audio=b""):
    """morse_command and friends lifted out of the voice node, with stand-ins."""
    tree = ast.parse(open(SRC).read())
    names = {"play_morse", "listen_for_morse", "morse_command"}
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    said, sent, played, logged = [], [], [], []

    class Face:
        def __getattr__(self, name):
            return lambda *a, **k: sent.append((name,) + a)

    class Panel:
        hush = False
        def said(self, text):
            said.append("[panel] " + text)

    class Watchdog:
        def ping(self):
            pass

    class Earcons:
        def listening(self):
            pass

    q = queue.Queue()
    for i in range(0, len(heard_audio), 4096):
        q.put(heard_audio[i:i + 4096])

    fake_morse = type(sys)("morse_stub")
    fake_morse.__dict__.update(morse.__dict__)
    fake_morse.play = lambda code, wpm=None: played.append(code) or True
    fake_morse.LISTEN_SECONDS = 4
    fake_morse.GIVE_UP = 2

    ns = {"morse": fake_morse, "face": Face(), "panel": Panel(), "watchdog": Watchdog(),
          "earcons": Earcons(), "q": queue, "time": __import__("time"), "random": random,
          "queue": queue, "CAPTURE_RATE": 16000, "re": re,
          "say": lambda text, mood="speaking": said.append(text),
          "pick": lambda lines: lines[0], "red_waiting": lambda: False,
          "flush_audio": lambda: None, "go_to_sleep": lambda: None,
          "log_turn": lambda *a, **k: logged.append(a)}
    exec(compile(ast.Module(body=body, type_ignores=[]), SRC, "exec"), ns)
    ns["q"] = q
    ns["time"] = type(sys)("t")
    real = __import__("time")
    ns["time"].time = real.time
    ns["time"].sleep = lambda s: None
    return ns, said, sent, played


def test_say_sos_in_morse_beeps_and_shows_the_tape():
    ns, said, sent, played = voice()
    ns["morse_command"]("say sos in morse", *morse.asked("say sos in morse"))
    assert played == ["... --- ..."]
    assert said[0].startswith("Here's sos in Morse code")
    assert said[-1] == "dit dit dit, dah dah dah, dit dit dit."
    assert ("state", "morse") in sent
    assert any(s[0] == "send" and s[1].startswith("morse:") and s[1].endswith(":... --- ...") for s in sent)


def test_quiet_panel_question_shows_the_code_without_beeping():
    ns, said, sent, played = voice()
    ns["panel"].hush = True
    ns["morse_command"]("say hi in morse", "send", "hi")
    assert played == [] and said == ['"hi" in Morse code: .... ..']


def test_reading_spoken_morse():
    ns, said, _, played = voice()
    ns["morse_command"]("x", *morse.asked("dot dot dot dot next dot dot"))
    assert said == ["That spells H, I."] and played == []


def test_listening_reads_real_beeps():
    audio = _pcm(morse.encode("hi"), 13, 650)
    ns, said, sent, _ = voice(audio)
    ns["morse_command"]("listen for morse", "listen", "")
    assert said[-1].startswith("That spells H, I.") and "words a minute" in said[-1]
    assert ("caption", ".... ..") in sent


def test_listening_to_nothing_says_so():
    ns, said, _, _ = voice(bytes(16000 * 2 * 3))
    ns["listen_for_morse"]()
    assert "didn't hear any beeps" in said[-1]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
