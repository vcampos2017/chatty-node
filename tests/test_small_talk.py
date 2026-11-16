"""Small talk stays on the Pi: hellos, "how are you?", "I'm not home right now"."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.modules.setdefault("requests", types.SimpleNamespace(post=None, get=None))
import small_talk as st  # noqa: E402
import local_llm  # noqa: E402
import words  # noqa: E402

FIRST = lambda lines: lines[0]   # noqa: E731
# 4:19 PM local time on some day, the way the panel screenshot was
from datetime import datetime  # noqa: E402
AFTERNOON = datetime(2026, 11, 16, 16, 19).timestamp()
SRC = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")


def heard(typed):
    """What handle_command gets from the panel: tidied, her filler words taken off."""
    return words.strip_wake(words.normalize(typed))


def test_the_panel_message_from_the_screenshot_stays_on_the_pi():
    p = heard("hello im not at home right now")
    line = st.reply(p, now=AFTERNOON, pick=FIRST)
    assert line and line.startswith("Okay! I'll hold down the fort"), line
    assert "cloud" not in line.lower()
    # and even without small talk, the Pi model now gets a go ("right now" isn't news)
    assert not local_llm.should_skip(p)


def test_away_knows_when_the_phone_left():
    left = AFTERNOON - 3600
    line = st.reply("im not home right now", people=[("Sam", False, left)], now=AFTERNOON, pick=FIRST)
    assert "your phone left the home WiFi around 3:19 PM" in line, line
    # phone still home, or two people listed: no guessing about phones
    for people in ([("Sam", True, 0.0)], [("Sam", False, left), ("Alex", False, left)]):
        line = st.reply("im not home right now", people=people, now=AFTERNOON, pick=FIRST)
        assert "phone" not in line, line
    line = st.reply("im at work", news="Just so you know, Rain is quiet.", now=AFTERNOON, pick=FIRST)
    assert line.endswith("Rain is quiet."), line


def test_away_phrasings():
    for s in ("im not at home", "i am away", "im out and about", "im at work", "im at the store",
              "i left", "im on my way", "heading out", "im out of town right now", "i'm driving"):
        assert st.reply(s, now=AFTERNOON, pick=FIRST) in st.AWAY_LINES, s
    # wanting something while away is not small talk
    for s in ("im at work can you set a timer", "remind me when im at the store"):
        assert st.reply(s, now=AFTERNOON) is None, s


def test_greetings_and_how_are_you():
    assert st.reply("im back", pick=FIRST) == st.BACK_LINES[0]
    assert st.reply("i'm home", pick=FIRST) == st.BACK_LINES[0]
    assert st.reply("how are you", now=AFTERNOON, pick=FIRST) in st.HOW_LINES["afternoon"]
    for s in ("hows it going", "what's up", "how was your day", "how have you been chatty"):
        assert st.reply(s, now=AFTERNOON), s
    assert st.reply("good afternoon", now=AFTERNOON, pick=FIRST) == "Good afternoon to you too!"
    assert "actually the afternoon" in st.reply("good morning", now=AFTERNOON)
    assert st.reply("what are you doing", pick=FIRST) == st.DOING_LINES[0]
    assert st.reply("youre so funny", pick=FIRST) == st.NICE_LINES[0]
    assert st.reply("i missed you", pick=FIRST) == st.MISSED_LINES[0]
    assert st.reply("im bored", pick=FIRST) == st.BORED_LINES[0]
    assert st.reply("im feeling sad", pick=FIRST) == st.LOW_LINES[0]


def test_questions_and_requests_are_left_alone():
    for s in ("what time is it", "tell me a joke", "is it going to rain", "what is a cat",
              "how are you feeling", "set a timer for ten minutes", "who is eliza",
              "how are the plants", "i need a timer", ""):
        assert st.reply(s, now=AFTERNOON) is None, s


def test_bare_hello_on_the_panel():
    for s in ("hello", "Hi there!", "hey", "howdy"):
        assert st.greeting_only(s), s
    for s in ("hey chatty", "hello what time is it", ""):
        assert not st.greeting_only(s), s


def test_im_good_after_how_about_you_is_an_answer():
    asked = st.HOW_LINES["afternoon"][0]
    assert asked.endswith("How about you?")
    assert st.follow_up("im good", asked, pick=FIRST) == st.FEEL_GOOD_LINES[0]
    assert st.follow_up("not bad thanks", asked, pick=FIRST) == st.FEEL_GOOD_LINES[0]
    assert st.follow_up("im tired", asked, pick=FIRST) == st.TIRED_LINES[0]
    # without her question, "I'm good" stays a polite no
    assert st.follow_up("im good", "It's 4:19 PM.") is None
    assert st.follow_up("what time is it", asked) is None


def test_chitchat_never_goes_to_the_cloud_offer():
    for s in ("i painted the fence today", "my tomatoes are finally red", "we went to the lake",
              "today i fixed the greenhouse door"):
        assert st.chitchat(s), s
    for s in ("what is the capital of france", "tell me about bats", "i want to know the weather",
              "can you explain fractals", "i fell down", "my cat is sick", "is it raining?",
              "remind me to call mom", "i wonder why the sky is blue"):
        assert not st.chitchat(s), s


def test_pi_model_still_skips_real_fresh_questions():
    for s in ("what's the latest news", "what is the weather right now", "who won the game",
              "how do i bake bread", "explain gravity", "what is the price of gold"):
        assert local_llm.should_skip(s), s
    for s in ("im not home right now", "im currently in the car", "the weather is lovely today"):
        assert not local_llm.should_skip(s), s


def test_turned_off():
    st.ENABLED = False
    try:
        assert st.reply("how are you") is None and not st.chitchat("i painted the fence")
    finally:
        st.ENABLED = True


def test_voice_node_uses_small_talk():
    src = open(SRC).read()
    assert "import small_talk" in src
    assert "small_talk.reply(" in src and "small_talk.chitchat(prompt)" in src
    assert "small_talk.follow_up(" in src and "small_talk.greeting_only(" in src
    # small talk comes before the Pi model, and the chit-chat line before the cloud offer
    assert src.index("reply = chit_chat(prompt)") < src.index("reply = unless_red(local_llm.ask")
    assert src.index("small_talk.listening_line()") < src.index("ask_cloud(prompt, local_guess)")
    # follow_up runs before "I'm good" can be taken as a polite no
    assert src.index("small_talk.follow_up(") < src.index("if prompt in STOP_PHRASES or is_just_no")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
