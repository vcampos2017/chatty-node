"""The line-up of things Chatty says on her own (src/announcements.py)."""
import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import announcements as an  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")


def make(answers, asked):
    def due_for(name):
        def due(mode):
            asked.append((name, mode))
            return answers.get(name)
        return due
    return an.Lineup([
        an.Announcer("morning_briefing", "Morning briefing", due_for("morning")),
        an.Announcer("bedtime", "Bedtime", due_for("bedtime"), after="tuck_in"),
        an.Announcer("homecoming", "Homecoming", due_for("home")),
    ])


def test_nothing_due():
    asked = []
    assert make({}, asked).next_due("sleep") is None
    assert asked == [("morning", "sleep"), ("bedtime", "sleep"), ("home", "sleep")]


def test_first_one_wins_and_the_rest_wait():
    asked = []
    news = make({"bedtime": "Goodnight!", "home": "Welcome home"}, asked).next_due("sleep")
    assert news.kind == "bedtime" and news.label == "Bedtime"
    assert news.text == "Goodnight!" and news.say_args == ("Goodnight!",)
    assert news.after == "tuck_in"
    assert [a[0] for a in asked] == ["morning", "bedtime"]     # homecoming not asked this round


def test_text_with_a_mood():
    news = make({"home": ("Welcome home, Vincent!", "love")}, []).next_due("sleep")
    assert news.say_args == ("Welcome home, Vincent!", "love")
    assert news.text == "Welcome home, Vincent!" and news.after == "sleep"


def test_busy_mode_is_passed_along():
    asked = []
    make({}, asked).next_due("red alert")
    assert {m for _, m in asked} == {"red alert"}


def test_voice_node_order_is_unchanged():
    """Same order as the old chain in the main loop."""
    tree = ast.parse(open(SRC).read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "extras":
            kinds = [c.args[0].value for c in node.value.args[0].elts]
            assert kinds == ["morning_briefing", "bedtime", "rain_ahead", "sky", "self_care",
                             "homecoming"], kinds
            break
    else:
        raise AssertionError("no extras line-up in the voice node")
    src = open(SRC).read()
    for gone in ("forecast = morning.due", "goodnight = winddown.due", "hello = welcome.due"):
        assert gone not in src, gone


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
