"""The relay client (src/relay.py): the paid cloud tier, tested without the network."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["CHATTY_ENDPOINT"] = "https://relay.example/"
os.environ["CHATTY_TOKEN"] = "t0ken"

calls = []
answer = {}


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _post(url, json=None, headers=None, timeout=None):
    calls.append((url, json, headers, timeout))
    return Resp(*answer["r"])


sys.modules["requests"] = types.SimpleNamespace(post=_post)
import relay  # noqa: E402


def ask(status, body, **kw):
    answer["r"] = (status, body)
    calls.clear()
    return relay.post_chat("are bats blind", "s1", **kw)


def test_reply_is_trimmed_and_sent_with_the_token():
    assert ask(200, {"reply": "  No, they can see.  "}) == "No, they can see."
    url, body, headers, timeout = calls[0]
    assert url == "https://relay.example/chat"
    assert body == {"text": "are bats blind", "session_id": "s1"}
    assert headers == {"X-Chatty-Token": "t0ken"} and timeout == 30


def test_out_of_credits():
    for status, body in ((402, {}), (500, {"error": "credits"}), (503, {"detail": "Quota exceeded"})):
        try:
            ask(status, body)
        except relay.OutOfCredits:
            continue
        raise AssertionError((status, body))


def test_other_errors_are_not_credits():
    for status, body in ((500, ValueError("not json")), (401, {})):
        try:
            ask(status, body)
        except relay.OutOfCredits:
            raise AssertionError(status)
        except RuntimeError:
            pass


def test_odd_reply_and_timeout():
    assert ask(200, {"reply": 42}, timeout=5) == "42"
    assert calls[0][3] == 5
    assert ask(200, {}) == ""


def test_voice_node_uses_relay_py():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")).read()
    assert "import relay" in src and "post_chat = relay.post_chat" in src
    assert "requests.post(" not in src and "class OutOfCredits" not in src


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
