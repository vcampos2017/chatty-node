"""Saying which brain she's using: "Let me run that through my local brain", and
"Want me to double-check that with the cloud?" after a fact from the Pi model."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.modules.setdefault("requests", types.SimpleNamespace(post=None, get=None))
import fact_check  # noqa: E402
import personality  # noqa: E402

FIRST = lambda lines: lines[0]   # noqa: E731
SRC = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")


def test_lines_exist_and_mention_the_cost():
    assert personality.LOCAL_THINKING_LINES and personality.DOUBLE_CHECK_QUESTIONS
    for q in personality.DOUBLE_CHECK_QUESTIONS:
        assert "cloud" in q and "costs a little" in q and q.endswith("tap me.")


def test_second_opinion_is_one_call():
    calls = []

    def ask(text):
        calls.append(text)
        return "OK"
    said, verdict = fact_check.second_opinion("how far is the moon", "About 239,000 miles.", ask, pick=FIRST)
    assert verdict == "ok" and said == fact_check.AGREE_LINES[0] and len(calls) == 1
    assert "how far is the moon" in calls[0] and "239,000" in calls[0]


def test_second_opinion_fix_unsure_and_trouble():
    said, v = fact_check.second_opinion("q", "a", lambda t: "FIX: Bats can see quite well.")
    assert v == "fix" and said == "The cloud has a correction. Bats can see quite well."
    said, v = fact_check.second_opinion("q", "a", lambda t: "UNSURE: Nobody knows for sure.")
    assert v == "unsure" and said.startswith("The cloud isn't so sure.")
    said, v = fact_check.second_opinion("q", "a", lambda t: "hmm, maybe")
    assert v == "failed" and "go with mine" in said

    def down(t):
        raise RuntimeError("no internet")
    said, v = fact_check.second_opinion("q", "a", down)
    assert v == "failed" and "couldn't reach the cloud" in said


def test_kind_words_about_your_day_stay_on_the_pi():
    # seen on the Pi: the Pi model's warm reply had "always" in it and went to the cloud offer
    assert fact_check.keep_local("i painted the fence today",
                                 "That's great! Painting fences is always a fun project.")
    # a stretchy answer to a real question still goes up
    assert not fact_check.keep_local("what do bats eat", "Bats always eat the best bugs.")


def test_voice_node_wiring():
    src = open(SRC).read()
    # the thinking line comes right before the Pi model, and only when it will really run
    i = src.index("say(pick(REMOTE_THINKING_LINES if local_llm.remote_suits(prompt)")
    assert src.index("local_llm.will_try(prompt)") < i < src.index("reply = unless_red(local_llm.ask")
    # the double-check offer comes after her answer, only for Pi-model facts
    assert src.index('say(reply or "Hmm, I drew a blank') < src.index("offer_double_check(prompt, reply)")
    assert 'tier == "local_llm" and reply and mood == "speaking"' in src
    assert "fact_check.is_factual(prompt)" in src and "privacy.needs_asking(f\"{prompt} {reply}\")" in src
    assert "CHATTY_TIER_LINES" in src and "CHATTY_DOUBLE_CHECK" in src


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
