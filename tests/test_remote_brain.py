"""The optional bigger brain: an Ollama on another computer (CHATTY_REMOTE_OLLAMA_URL),
asked before the Pi model, with a timeout and a fall back to the Pi."""
import os
import sys
import types

os.environ["CHATTY_REMOTE_OLLAMA_URL"] = "http://bigger-brain.example:11434/"
os.environ["CHATTY_REMOTE_MODEL"] = "qwen2.5:3b"

calls = []
behaviour = {}   # url prefix -> "ok" | "timeout" | "down" | "escalate"


class Timeout(Exception):
    pass


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self.text}}


def _post(url, json=None, timeout=None):
    calls.append((url, json, timeout))
    remote = url.startswith("http://bigger-brain.example")
    how = behaviour.get("remote" if remote else "pi", "ok")
    if how == "timeout":
        raise Timeout("read timed out")
    if how == "down":
        raise ConnectionError("refused")
    if how == "escalate":
        return _Resp("ESCALATE")
    return _Resp("From the big brain. Sentence two. Sentence three. Four." if remote
                 else "From the Pi. Second. Third.")


sys.modules["requests"] = types.SimpleNamespace(post=_post)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import local_llm  # noqa: E402


def _reset(**how):
    calls.clear()
    behaviour.clear()
    behaviour.update(how)
    local_llm._remote_down_until = 0.0


def test_off_without_a_url():
    # the setting's default is empty: nothing changes for anyone who doesn't set it
    assert "CHATTY_REMOTE_OLLAMA_URL\", \"\")" in open(local_llm.__file__).read()


def test_bigger_brain_answers_first():
    _reset()
    reply = local_llm.ask("why do cats purr", "t1")
    assert reply == "From the big brain. Sentence two. Sentence three."
    assert len(calls) == 1
    url, body, timeout = calls[0]
    assert url == "http://bigger-brain.example:11434/api/chat"   # trailing slash trimmed
    assert body["model"] == "qwen2.5:3b" and timeout == local_llm.REMOTE_TIMEOUT
    assert body["messages"][0]["content"] == local_llm.REMOTE_SYSTEM
    assert local_llm.last_model == "remote:qwen2.5:3b"


def test_explain_questions_go_to_the_bigger_brain_only():
    # the Pi model always passes "explain" up; the bigger brain gets a try
    _reset()
    assert local_llm.should_skip("explain how rainbows form")
    assert local_llm.ask("explain how rainbows form", "t2")
    _reset(remote="down")
    assert local_llm.ask("explain how rainbows form", "t2") is None
    assert all(c[0].startswith("http://bigger-brain") for c in calls)


def test_slow_or_down_falls_back_to_the_pi_and_rests():
    for how in ("timeout", "down"):
        _reset(remote=how)
        assert local_llm.ask("why do cats purr", "t3") == "From the Pi. Second."
        assert [c[0].startswith("http://bigger-brain") for c in calls] == [True, False]
        assert local_llm.last_model == local_llm.MODEL
        # for a while she doesn't knock again
        calls.clear()
        assert not local_llm.remote_ready()
        assert local_llm.ask("why is the sky blue", "t3") == "From the Pi. Second."
        assert len(calls) == 1 and not calls[0][0].startswith("http://bigger-brain")


def test_escalate_goes_up_without_asking_the_pi():
    _reset(remote="escalate")
    assert local_llm.ask("why do cats purr", "t4") is None
    assert len(calls) == 1
    assert local_llm.remote_ready()   # a pass isn't a failure


def test_private_questions_stay_on_the_pi():
    _reset()
    q = "remember my phone number is 555 123 4567"
    assert not local_llm.remote_suits(q)
    local_llm.ask(q, "t5")
    assert not any(c[0].startswith("http://bigger-brain") for c in calls)


def test_fresh_news_skips_both():
    _reset()
    assert not local_llm.remote_suits("what's the weather right now")
    assert local_llm.ask("what's the weather right now", "t6") is None
    assert calls == []


def test_will_try_and_the_address_is_never_printed():
    assert local_llm.will_try("explain how rainbows form")
    src = open(local_llm.__file__).read()
    assert "REMOTE_URL}" not in src.split("def ask(")[1].split("def _ask_pi(")[0].replace(
        "url=REMOTE_URL", "")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
