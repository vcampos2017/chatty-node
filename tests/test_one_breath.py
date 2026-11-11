"""'Hey Chatty, what time is it?' in one breath.

The voice node runs as soon as it's imported (it opens the mic), so these tests
lift just the one-breath helpers out of it and run them with a fake recognizer."""
import ast
import json
import os
import re

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")
NAMES = {"keep_sleep_audio", "audio_after", "question_in", "wake_phrase_end",
         "normalize", "strip_wake", "fix_name"}
RATE = 16000
SEC = 2 * RATE          # bytes per second


class FakeRec:
    """Hears whatever 'words' were written into the audio as text."""
    def __init__(self):
        self.buf = b""
    def Reset(self):
        self.buf = b""
    def AcceptWaveform(self, data):
        self.buf += data
        return False
    def FinalResult(self):
        text = self.buf.replace(b"\0", b" ").decode("ascii", "ignore")
        return json.dumps({"text": " ".join(text.split())})


def load():
    tree = ast.parse(open(SRC).read())
    ns = {"os": os, "json": json, "re": re, "VOSK_RATE": RATE, "rec": FakeRec()}
    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in NAMES:
            keep.append(node)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if set(targets) & {"ONE_BREATH", "ONE_BREATH_MIN_SECONDS", "NOT_A_QUESTION",
                               "sleep_audio", "SLEEP_AUDIO_MAX", "sleep_audio_start",
                               "wake_fed", "WAKE_PHRASE", "FILLER_WORDS", "WAKE_VARIANTS", "NAME_AFTER",
                               "POLITE_WORDS"}:
                keep.append(node)
    exec(compile(ast.Module(body=keep, type_ignores=[]), SRC, "exec"), ns)
    return ns


def speech(words: str, seconds: float) -> bytes:
    """Fake audio: the words, padded with silence to the given length."""
    raw = words.encode()
    n = int(seconds * SEC)
    return (raw + b"\0" * n)[:max(n, len(raw))]


def test_question_after_her_name_is_heard():
    ns = load()
    ns["keep_sleep_audio"](speech("hey chatty", 1.0))
    ns["keep_sleep_audio"](speech("what time is it", 2.0))
    words = [{"word": "hey", "end": 0.4}, {"word": "chatty", "end": 1.0}]
    end = ns["wake_phrase_end"](words)
    tail, whole = ns["audio_after"](end)
    assert len(tail) == 2 * SEC and len(whole) == 3 * SEC
    text, _ = ns["question_in"](tail)
    assert text == "what time is it"
    assert len(ns["sleep_audio"]) == 0            # forgotten right away


def test_just_her_name_still_says_yes():
    ns = load()
    ns["keep_sleep_audio"](speech("hey chatty", 1.0))
    ns["keep_sleep_audio"](speech("", 0.8))       # the pause before Vosk calls it done
    tail, _ = ns["audio_after"](1.0)
    assert ns["question_in"](tail) == ("", {})


def test_a_grunt_after_her_name_is_not_a_question():
    ns = load()
    ns["keep_sleep_audio"](speech("hey chatty", 1.0))
    ns["keep_sleep_audio"](speech("um", 1.0))
    assert ns["question_in"](ns["audio_after"](1.0)[0]) == ("", {})


def test_timing_that_includes_her_name_is_stripped():
    ns = load()
    ns["keep_sleep_audio"](speech("hey chatty", 1.0))
    ns["keep_sleep_audio"](speech("", 1.0))
    # if the word times were off and the tail starts at the top, her name alone is no question
    assert ns["question_in"](ns["audio_after"](-5)[0])[0] == ""


def test_long_chatter_is_capped_and_timing_still_lines_up():
    ns = load()
    for _ in range(30):                           # 30 s of TV with no name
        ns["keep_sleep_audio"](speech("", 1.0))
    assert len(ns["sleep_audio"]) == ns["SLEEP_AUDIO_MAX"]
    assert abs(ns["sleep_audio_start"] - 10.0) < 1e-6
    ns["keep_sleep_audio"](speech("hey chatty", 1.0))
    ns["keep_sleep_audio"](speech("tell me a joke", 1.5))
    text, _ = ns["question_in"](ns["audio_after"](31.0)[0])
    assert text == "tell me a joke"


def test_turned_off():
    ns = load()
    ns["ONE_BREATH"] = False
    ns["keep_sleep_audio"](speech("hey chatty", 1.0))
    ns["keep_sleep_audio"](speech("what time is it", 2.0))
    assert ns["question_in"](ns["audio_after"](1.0)[0]) == ("", {})


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)


def test_just_thanks_is_answered_on_the_pi():
    tree = ast.parse(open(SRC).read())
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "is_just_thanks"]
    ns = {"re": re}
    exec(compile(ast.Module(body=fn, type_ignores=[]), SRC, "exec"), ns)
    t = ns["is_just_thanks"]
    for p in ("thanks i did not know that about the raspberry pi", "thank you uga muga",
              "ok thanks chatty that was helpful"):
        assert t(p), p
    for p in ("thanks but what about tomorrow", "thank you can you set a timer",
              "thanks and tell me a joke", "what is the time"):
        assert not t(p), p
