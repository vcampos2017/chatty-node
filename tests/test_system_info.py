"""About herself: processor, Python version, uptime. All read on the Pi, no model."""
import os
import platform
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import system_info as si  # noqa: E402
import local_skills  # noqa: E402

STAT_A = "cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 2 3 4\n"
STAT_B = "cpu  200 0 200 1000 0 0 0 0 0 0\ncpu0 1 2 3 4\n"


def test_cpu_percent_from_proc_stat():
    a, b = si.cpu_times(STAT_A), si.cpu_times(STAT_B)
    assert a == (200, 1000) and b == (400, 1400)
    seq = iter([a, b])
    pct = si.cpu_percent(sample=lambda: next(seq), sleep=lambda s: None)
    assert round(pct) == 50
    assert si.cpu_percent(sample=lambda: None, sleep=lambda s: None) is None


def test_processor_answer():
    text = si.processor_answer(23.4, 4, 1.5, 52.2)
    assert text == ("My processor is at 23 percent right now, across 4 cores, running at 1.5 gigahertz. "
                    "I'm barely breaking a sweat. I'm at 52 degrees Celsius.")
    assert "flat out" in si.processor_answer(97, 4, None, None)
    assert "load average is 1.2" in si.processor_answer(None, 4, None, None, load=1.2)


def test_python_version_is_spoken_clearly():
    want = platform.python_version().split(".")
    reply = si.handle("what version of python are you using")
    assert reply == f"I'm running on Python {want[0]} point {want[1]} point {want[2]}.", reply
    for q in ("python version", "which python do you run", "whats your python version"):
        assert si.handle(q).startswith("I'm running on Python"), q
    assert si.handle("what is python") is None and si.handle("teach me python") is None


def test_uptime_words():
    assert si.spoken_duration(3 * 86400 + 4 * 3600 + 59) == "3 days and 4 hours"
    assert si.spoken_duration(3600) == "1 hour"
    assert si.spoken_duration(90 * 60) == "1 hour and 30 minutes"
    assert si.spoken_duration(20) == "1 minute"


def test_questions_it_answers_and_leaves_alone():
    for q in ("how busy is your processor", "whats your cpu usage", "how hard are you working",
              "how much cpu are you using", "processor load"):
        assert si.CPU_Q.search(q), q
    for q in ("how long have you been on", "whats your uptime"):
        assert si.UPTIME_Q.search(q), q
    for q in ("what time is it", "how are the plants", "tell me a joke", "how are you"):
        assert si.handle(q) is None, q


def test_local_skills_answers_it_on_the_pi():
    assert local_skills.handle("what version of python are you using").startswith("I'm running on Python")
    si.ENABLED = False
    try:
        assert local_skills.handle("what version of python are you using") is None
    finally:
        si.ENABLED = True


def test_ollama_version_is_asked_never_guessed():
    for q in ("where version of ollama are you using l", "what version of ollama are you using",
              "what model are you using", "which llm do you run", "what is your local model"):
        assert si.OLLAMA_Q.search(q), q
    assert si.handle("what is a model train") is None
    assert si.ollama_answer("0.12.11", "qwen2.5 1.5b") == \
        "I'm using the qwen2.5 1.5b model on Ollama version 0 point 12 point 11."
    assert "isn't answering" in si.ollama_answer(None, "qwen2.5 1.5b")
    seen = {}
    real = si.ollama_version
    si.ollama_version = lambda: seen.setdefault("asked", "0.13.0")
    try:
        assert "0 point 13 point 0" in local_skills.handle("where version of ollama are you using l")
    finally:
        si.ollama_version = real
    assert seen == {"asked": "0.13.0"}


def test_shaky_answers_are_said_as_guesses():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")).read()
    assert "not_sure() and asks_question(prompt)" in src and "reply = unsure_words(reply)" in src
    i = src.index("def offer_double_check")
    body = src[i:src.index("def double_check", i)]
    assert "shaky = not_sure() and not ABOUT_HER.search(prompt)" in body


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
