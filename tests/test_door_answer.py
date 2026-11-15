"""How Chatty works out her answer to a door letter (src/door_answer.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import door_answer as da  # noqa: E402


class RedCutIn(BaseException):
    pass


def run(text, skill=None, local=None, relay=None, cloud=False, sender="claude"):
    calls = []

    def skills(prompt):
        calls.append(("skill", prompt))
        return skill

    def ask_local(prompt, sid):
        calls.append(("local", sid))
        if isinstance(local, BaseException):
            raise local
        return local

    def ask_relay(t, sid, **kw):
        calls.append(("relay", sid))
        if isinstance(relay, BaseException):
            raise relay
        return relay(t) if callable(relay) else relay

    a = da.work_out({"from": sender, "text": text}, skills, ask_local, ask_relay, cloud=cloud)
    return a, calls


def test_skill_answers_first():
    a, calls = run("What time is it?", skill="It's 3 PM.")
    assert (a.reply, a.tier, a.private) == ("It's 3 PM.", "skill", False)
    assert calls == [("skill", "what time is it")]


def test_pi_model_with_the_senders_session():
    a, calls = run("tell me about clouds", local="Clouds are water.")
    assert (a.reply, a.tier) == ("Clouds are water.", "local_llm")
    assert ("local", "door-claude") in calls and not any(c[0] == "relay" for c in calls)


def test_no_cloud_by_default():
    a, calls = run("tell me about quasars", local=None, relay="never")
    assert a.reply == da.FALLBACK and not any(c[0] == "relay" for c in calls)


def test_cloud_when_allowed():
    a, _ = run("tell me about quasars", local=None, relay="OK", cloud=True)
    assert a.tier == "relay" and a.reply


def test_private_letters_never_go_to_the_cloud():
    a, calls = run("my phone number is 555 123 4567, what is it?", local=None,
                   relay="never", cloud=True)
    assert a.private and not any(c[0] == "relay" for c in calls)


def test_relay_down_falls_back_to_the_hedged_guess():
    guess = "Bats are always the best fliers, super duper fast."     # stretchy: goes up
    a, _ = run("tell me about bats", local=guess, relay=RuntimeError("down"), cloud=True)
    assert a.tier == "local_llm" and a.reply != da.FALLBACK and "fliers" in a.reply


def test_yes_no_facts_skip_the_pi_when_the_cloud_is_allowed():
    a, calls = run("are bats blind", local="Yes.", relay=RuntimeError("down"), cloud=True)
    assert not any(c[0] == "local" for c in calls)      # the Pi isn't asked to guess
    assert a.reply == da.FALLBACK and a.failed


def test_a_failure_gives_the_fallback_line():
    a, _ = run("tell me about clouds", local=RuntimeError("ollama down"))
    assert a.reply == da.FALLBACK and a.failed


def test_red_alert_passes_straight_through():
    try:
        run("tell me about clouds", local=RedCutIn())
    except RedCutIn:
        return
    raise AssertionError("RedCutIn was swallowed")


def test_nothing_private_goes_back_over_the_network():
    assert da.safe_to_send("Sure, it's sunny.") == "Sure, it's sunny."
    assert da.safe_to_send("Call me at 555 123 4567") == da.NOT_OVER_THE_NETWORK


def test_voice_node_uses_door_answer():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")).read()
    assert "door_answer.work_out(" in src and "door_answer.safe_to_send(" in src
    assert "door_mod.own_answer(" not in src


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
