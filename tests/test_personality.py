"""Her lines and moods (src/personality.py), tested without the voice node."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import personality as p  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")


def test_love_requests():
    for s in ("i love you", "blow me a kiss", "happy valentines day", "youre so cute"):
        assert p.is_love_request(s), s
    for s in ("how do you say i love you in spanish",
              "i love you more than all the stars in the whole wide sky tonight"):
        assert not p.is_love_request(s), s


def test_fed_up_and_skeptical():
    assert p.is_fed_up("Absolutely not. Do your own dishes.")
    assert p.is_fed_up("Sorry, that's not my job.")
    assert not p.is_fed_up("Sure, here you go.")
    assert p.is_skeptical("That sounds fishy to me.")
    assert not p.is_skeptical("The sky is blue.")


def test_jokes_chores_insults_tiny():
    assert p.is_joke_request("tell me a joke") and not p.is_joke_request("tell me the time")
    assert p.CHORE_PATTERN.search("do the dishes")
    assert p.INSULT_PATTERN.search("youre so dumb")
    assert p.TINY_PATTERN.search("meow") and p.TINY_PATTERN.search("hows tiny")


def test_well_actually():
    assert p.well_actually("Actually, bats can see quite well.") == \
        "Well, actually... Bats can see quite well."
    assert p.well_actually("Bats are actually not blind.") == "Well, actually... Bats are not blind."
    assert p.well_actually("Bats can see.") is None
    assert p.well_actually("") is None


def test_special_days():
    os.environ["CHATTY_FORCE_SPOOKY"] = "1"
    os.environ["CHATTY_FORCE_VALENTINE"] = "1"
    assert p.spooky_day() and p.valentines_day()
    del os.environ["CHATTY_FORCE_SPOOKY"], os.environ["CHATTY_FORCE_VALENTINE"]
    real = time.localtime
    try:
        time.localtime = lambda *a: time.struct_time((2026, 10, 31, 12, 0, 0, 5, 304, 0))
        assert p.spooky_day() and not p.valentines_day()
        time.localtime = lambda *a: time.struct_time((2027, 2, 14, 12, 0, 0, 6, 45, 0))
        assert p.valentines_day() and not p.spooky_day()
        time.localtime = lambda *a: time.struct_time((2026, 11, 13, 9, 0, 0, 4, 317, 0))
        assert p.spooky_day()                     # Friday the 13th
        assert p.good_morning().startswith("Good morning!")
        time.localtime = lambda *a: time.struct_time((2026, 11, 13, 19, 0, 0, 4, 317, 0))
        assert p.good_morning().startswith("Good evening!")
    finally:
        time.localtime = real


def test_lines_are_filled_in():
    for name in ("GREETINGS", "GOODBYES", "THANKS_REPLIES", "ERROR_LINES", "CHEEKY_LINES",
                 "SPOOKY_LINES", "LOVE_LINES", "CHORE_LINES", "INSULT_LINES", "TINY_LINES",
                 "GOODNIGHTS", "POWER_OFF_GOODBYES"):
        lines = getattr(p, name)
        assert lines and all(isinstance(s, str) and s for s in lines), name


def test_voice_node_imports_them_back():
    src = open(SRC).read()
    assert "from personality import (" in src
    for gone in ("GREETINGS = [", "LOVE_PATTERN = re.compile", "def well_actually", "def spooky_day"):
        assert gone not in src, gone


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
