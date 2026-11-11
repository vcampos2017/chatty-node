"""A tribute to ELIZA: "Please go on." now and then, and "who is ELIZA?"."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import eliza  # noqa: E402

ALWAYS = lambda: 0.0   # noqa: E731
NEVER = lambda: 0.99   # noqa: E731


def test_about_eliza():
    for q in ("who is eliza", "do you know eliza", "tell me about eliza", "who was eliza"):
        assert "Weizenbaum" in eliza.about(q) or "MIT" in eliza.about(q), q
    assert eliza.about("what time is it") is None


def test_please_go_on_for_a_calm_statement():
    for s in ("i had a long day at work", "my tomatoes are finally red", "im going to the store later",
              "today i fixed the greenhouse door"):
        assert eliza.go_on(s, roll=ALWAYS).startswith(("Please go on", "Mm-hmm")), s
        assert eliza.go_on(s, roll=NEVER) is None, s


def test_questions_requests_and_hard_times_get_a_real_answer():
    for s in ("what time is it", "is it going to rain", "tell me a joke", "i want to know the weather",
              "i need a timer for ten minutes", "i feel sad today", "my cat is sick",
              "i fell down", "im worried about the storm", "please go on", "hi chatty",
              "were you asleep", "i dont know what to do"):
        assert eliza.go_on(s, roll=ALWAYS) is None, s


def test_tell_me_more_gives_new_facts_not_the_same_blurb():
    import chat_memory as cm
    m = cm.ChatMemory(enabled=True, clock=lambda: 1000.0)
    eliza._more_next = 0
    q = "who is eliza"
    first = eliza.about(q)
    m.add(q, first)
    seen = [first]
    for p in ("another one", "please go on", "tell me more please"):
        follow = m.expand(p)
        assert follow == "tell me more about eliza", p
        line = eliza.about(follow)
        assert line not in seen, p
        seen.append(line)
        m.add(follow, line)
    for _ in range(10):
        assert eliza.about("tell me more about eliza")      # wraps around, never None
