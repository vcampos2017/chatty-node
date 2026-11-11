"""Chatty's short conversation memory: she follows along for a few exchanges."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import chat_memory as cm  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0
    def __call__(self):
        return self.t


def test_keeps_the_last_few_exchanges():
    m = cm.ChatMemory(turns=3, idle_seconds=300, enabled=True, clock=Clock())
    for i in range(5):
        m.add(f"q{i}", f"a{i}")
    msgs = m.messages()
    assert [x["content"] for x in msgs] == ["q2", "a2", "q3", "a3", "q4", "a4"]
    assert [x["role"] for x in msgs[:2]] == ["user", "assistant"]


def test_forgets_after_quiet_minutes_and_starts_a_new_session():
    clock = Clock()
    m = cm.ChatMemory(turns=3, idle_seconds=300, enabled=True, clock=clock)
    sid = m.session_id()
    m.add("chatty im not at home right now", "Thanks for letting me know!")
    clock.t += 200
    assert m.session_id() == sid and m.fresh()      # still the same conversation
    m.add("what is the temperature in the greenhouse", "It's 65 degrees in there.")
    clock.t += 299                                    # counted from the last words
    assert m.fresh()
    clock.t += 2
    assert not m.fresh() and m.messages() == []
    assert m.session_id() != sid


def test_long_lines_are_trimmed_for_the_pi():
    m = cm.ChatMemory(enabled=True, clock=Clock())
    m.add("word " * 200, "ok")
    assert len(m.messages()[0]["content"]) <= cm.MAX_CHARS + 3


def test_off_and_empty_replies_keep_nothing():
    m = cm.ChatMemory(enabled=False, clock=Clock())
    m.add("hi", "hello")
    assert m.messages() == []
    m = cm.ChatMemory(enabled=True, clock=Clock())
    m.add("hi", "")
    assert m.messages() == []


def test_short_follow_up_goes_up_with_its_context():
    m = cm.ChatMemory(enabled=True, clock=Clock())
    assert m.for_relay("please") == "please"          # nothing to go with yet
    m.add("can you tell me a fun fact", "Want one about octopuses?")
    text = m.for_relay("yes please")
    assert "octopuses" in text and text.endswith("yes please")
    long_q = "please say hello to andie for me and tell her about the greenhouse"
    assert m.for_relay(long_q) == long_q


def test_change_the_subject():
    for p in ("change the subject", "let's change the subject", "new topic", "forget that",
              "forget what i just said", "start over"):
        assert cm.ChatMemory.wants_new_subject(p), p
    for p in ("forget my voice", "forget it", "what is the subject of the book"):
        assert not cm.ChatMemory.wants_new_subject(p), p


def test_pi_model_sees_the_conversation():
    sent = {}

    class Resp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"message": {"content": "Sure! I'll say hello to Andie for you."}}

    def post(url, json=None, timeout=None):
        sent["messages"] = json["messages"]
        return Resp()

    sys.modules["requests"] = types.SimpleNamespace(post=post)
    sys.modules.pop("local_llm", None)
    import local_llm
    m = cm.ChatMemory(enabled=True, clock=Clock())
    m.add("thank you", "You're welcome! Want me to pass along a message?")
    reply = local_llm.ask("please", "s1", history=m.messages())
    assert reply.startswith("Sure")
    contents = [x["content"] for x in sent["messages"]]
    assert contents[1:] == ["thank you", "You're welcome! Want me to pass along a message?", "please"]
    assert local_llm._history.get("s1") is None        # the shared memory keeps it, not this one
    # the door still uses the model's own per-sender memory
    local_llm.ask("hi", "door-claude")
    assert len(local_llm._history["door-claude"]) == 2
    local_llm.ask("and you?", "door-claude")
    assert [x["content"] for x in sent["messages"]][1:3] == ["hi", "Sure! I'll say hello to Andie for you."]


def test_another_one_repeats_the_last_question():
    m = cm.ChatMemory(enabled=True, clock=Clock())
    assert m.expand("another one") == "another one"          # nothing to repeat yet
    m.add("tell me a fun fact about cats", "Cats sleep a lot.")
    for p in ("another one", "please tell me another one", "please go on", "one more please",
              "more", "keep going", "another"):
        assert m.expand(p) == "tell me a fun fact about cats, a different one than before", p
    m.add(m.expand("another one"), "Cats have whiskers.")
    assert m.expand("another one") == "tell me a fun fact about cats, a different one than before"
    for p in ("another day", "tell me more about dogs", "what is the weather"):
        assert m.expand(p) == p, p
