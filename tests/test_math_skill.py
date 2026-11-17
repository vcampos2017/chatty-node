"""Simple math worked out exactly on the Pi, and no cloud double-check when she's sure."""
import math
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.modules.setdefault("requests", types.SimpleNamespace(post=None, get=None))
import math_skill as ms  # noqa: E402
import local_skills  # noqa: E402
import local_llm  # noqa: E402
import words  # noqa: E402
import panel_link  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")


def test_the_question_from_the_pi():
    typed = panel_link.typed_question("what is the answer to 1 + 1 =")
    assert ms.handle(words.strip_wake(typed)) == "1 plus 1 is 2."
    assert local_skills.handle("what is the answer to 1 plus 1 equals") == "1 plus 1 is 2."


def test_sums():
    cases = {
        "whats 12 times 7": "12 times 7 is 84.",
        "what is 7 x 8": "7 times 8 is 56.",
        "what is seven times eight": "7 times 8 is 56.",
        "twenty five plus seventeen": "25 plus 17 is 42.",
        "what is one hundred minus thirty": "100 minus 30 is 70.",
        "100 divided by 8": "100 divided by 8 is 12.5.",
        "2 to the power of 10": "2 to the power of 10 is 1024.",
        "what is 2 plus 3 times 4": "2 plus 3 times 4 is 14.",
        "square root of 81": "The square root of 81 is 9.",
        "15 percent of 80": "15 percent of 80 is 12.",
        "10 divided by 3": "10 divided by 3 is 3.3333.",
    }
    for q, want in cases.items():
        assert ms.handle(q) == want, (q, ms.handle(q))
    assert "undefined" in ms.handle("10 divided by 0")


def test_not_math():
    for q in ("what time is it", "set a timer for 10 minutes", "i have 2 cats", "i was born in 1980",
              "how many legs does a spider have", "tell me a joke", "me and 2 friends went out",
              "what is 2 to the power of 1000000"):
        assert ms.handle(q) is None, (q, ms.handle(q))
    ms.ENABLED = False
    try:
        assert ms.handle("1 plus 1") is None
    finally:
        ms.ENABLED = True


def test_confidence_from_logprobs():
    body = {"logprobs": [{"token": "Paris", "logprob": math.log(0.99)},
                         {"token": ".", "logprob": math.log(0.97)}]}
    assert 0.97 < local_llm.confidence(body) < 0.99
    assert local_llm.confidence({}) is None          # older Ollama: no logprobs, no guess
    assert local_llm.confidence({"logprobs": [{"token": "x"}]}) is None


def test_no_double_check_offer_when_highly_confident():
    src = open(SRC).read()
    i = src.index("def offer_double_check")
    body = src[i:src.index("def double_check", i)]
    assert "local_llm.last_confidence" in body and "local_llm.SURE" in body
    assert '"logprobs": True' in open(os.path.join(os.path.dirname(SRC), "local_llm.py")).read()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
