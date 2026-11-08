"""Fact check: she double-checks factual answers before saying them."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import fact_check as fc  # noqa: E402

FACTUAL = ["are bats blind", "is it true that goldfish have a three second memory",
           "how far away is the moon", "who invented the light bulb",
           "why is the sky blue", "do we only use ten percent of our brains",
           "tell me about octopuses"]
NOT_FACTUAL = ["how are you", "tell me a joke", "what's your favorite color",
               "do you like cats", "good morning", "thank you chatty",
               "play chess", "set a timer for ten minutes"]


def test_factual_questions():
    for q in FACTUAL:
        assert fc.is_factual(q), q
    for q in NOT_FACTUAL:
        assert not fc.is_factual(q), q


def test_myth_questions():
    assert fc.is_myth_question("are bats blind")
    assert fc.is_myth_question("is it true that lightning never strikes twice")
    assert fc.is_myth_question("do goldfish really forget everything")
    assert not fc.is_myth_question("how far away is the moon")
    assert not fc.is_myth_question("are you awake")


def test_bat_answer_is_not_trusted_from_the_pi():
    assert fc.skip_local("are bats blind")
    assert not fc.keep_local("are bats blind", "Bats are super duper good at seeing!")
    assert fc.is_stretchy("Bats are super duper good at seeing!")


def test_small_talk_stays_local_and_unchecked():
    assert not fc.skip_local("how are you")
    assert fc.keep_local("how are you", "I'm doing great, thanks for asking!")
    assert not fc.should_check("tell me a joke", "Why did the robot cross the road?")


def test_stretchy_or_correcting_local_reply_goes_up_even_in_myths_mode():
    old = fc.MODE
    fc.MODE = "myths"
    try:
        assert fc.keep_local("how far away is the moon", "About 239,000 miles.")
        assert not fc.keep_local("how far away is the moon", "It's always exactly 239,000 miles.")
        assert not fc.keep_local("what do penguins eat", "Actually, it's a common myth that...")
        assert fc.should_check("what is a fun fact", "Actually, that's a common myth.")
        assert not fc.should_check("how far away is the moon", "About 239,000 miles.")
    finally:
        fc.MODE = old


def test_off_switch():
    old = fc.MODE
    fc.MODE = "off"
    try:
        assert not fc.skip_local("are bats blind")
        assert fc.keep_local("are bats blind", "Super duper good!")
        assert not fc.should_check("are bats blind", "Actually, they see fine.")
    finally:
        fc.MODE = old


def test_parse_verdict():
    assert fc.parse_verdict("OK") == ("ok", None)
    assert fc.parse_verdict("ok.") == ("ok", None)
    assert fc.parse_verdict("FIX: Bats aren't blind, but many see only modestly.") == \
        ("fix", "Bats aren't blind, but many see only modestly.")
    assert fc.parse_verdict('Ha, fair! FIX: "Most bats can see."')[0] == "fix"
    assert fc.parse_verdict("UNSURE: Scientists still argue about it.")[0] == "unsure"
    assert fc.parse_verdict("Ooh, great question about bats!") == (None, None)
    assert fc.parse_verdict("FIX:") == (None, None)


def test_review_uses_the_fix():
    sent = []
    def ask(text):
        sent.append(text)
        return "FIX: Bats aren't blind, but many see only modestly and use echolocation."
    said, verdict = fc.review("are bats blind", "Bats are super duper good at seeing!", ask)
    assert verdict == "fix" and "echolocation" in said
    assert "are bats blind" in sent[0] and "super duper" in sent[0]


def test_review_keeps_ok_answers_and_survives_errors():
    a = "Actually, bats aren't blind; many see fairly well."
    assert fc.review("are bats blind", a, lambda t: "OK") == (a, "ok")
    def boom(t):
        raise TimeoutError("slow")
    assert fc.review("are bats blind", a, boom) == (a, "failed")
    assert fc.review("are bats blind", a, lambda t: "hmm") == (a, "failed")
    assert fc.review("how are you", "Great!", boom) == ("Great!", "skipped")


def test_hedge():
    assert fc.hedge("Actually, bats can see.") == \
        "I can't double-check right now, but I think bats can see."
    assert fc.hedge("") == ""


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("fact check tests passed")
