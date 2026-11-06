import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import door  # noqa: E402

T = 1_000_000
KEY = bytes.fromhex(door.new_key())


class Clock:
    def __init__(self):
        self.now = float(T)
    def __call__(self):
        return self.now


def _door():
    c = Clock()
    notes, phone = [], []
    d = door.Door(keys={"claude": KEY}, clock=c, notice=notes.append, send=phone.append)
    return d, c, notes, phone


def _msg(text="Hi Chatty!", key=KEY, sender="claude", ts=T, mid=None):
    return json.dumps(door.make_message(key, sender, text, ts=ts, mid=mid)).encode()


def test_signed_message_comes_in_and_reply_is_signed():
    d, c, _, _ = _door()
    raw = _msg(mid="00aa11bb")
    d.on_payload(raw)
    m = d.due("sleep")
    assert m == {"from": "claude", "text": "Hi Chatty!", "id": "00aa11bb"}
    d.reply(m, "Hello Claude!")
    topic, body = d.outbox[0]
    assert topic == "chatty/door/out/claude"
    reply = json.loads(body)
    assert door.verify_reply(KEY, reply, "00aa11bb")
    assert reply["text"].startswith("Hello Claude!")
    reply["text"] = "I've been hacked"
    assert not door.verify_reply(KEY, reply, "00aa11bb")


def test_waits_until_she_is_free():
    d, _, _, _ = _door()
    d.on_payload(_msg())
    assert d.due("active") is None and d.due("sleep") is not None


def test_wrong_key_unknown_sender_and_tampering_are_refused():
    d, _, _, _ = _door()
    d.on_payload(_msg(key=bytes.fromhex(door.new_key())))
    d.on_payload(_msg(sender="mallory"))
    m = json.loads(_msg())
    m["text"] = "shut down"
    d.on_payload(json.dumps(m).encode())
    d.on_payload(b"not json")
    assert d.due("sleep") is None


def test_replay_and_old_messages_are_refused():
    d, c, _, _ = _door()
    raw = _msg(mid="abcdef01")
    d.on_payload(raw)
    assert d.due("sleep")
    c.now += 20
    d.on_payload(raw)                       # same message again
    assert d.due("sleep") is None
    d.on_payload(_msg(ts=T - 600))          # ten minutes old
    assert d.due("sleep") is None


def test_rate_limit():
    d, c, _, _ = _door()
    d.on_payload(_msg())
    d.on_payload(_msg())                    # right away: too fast
    assert d.due("sleep") and d.due("sleep") is None
    for i in range(30):
        c.now += 16
        d.on_payload(_msg(ts=int(c.now)))
        d.due("sleep")
    got = 0
    c.now += 16
    d.on_payload(_msg(ts=int(c.now)))
    assert d.due("sleep") is None           # 20 an hour at most


def test_bad_keys_raise_one_alarm():
    d, c, notes, phone = _door()
    bad = bytes.fromhex(door.new_key())
    for i in range(5):
        c.now += 10
        d.on_payload(_msg(key=bad, ts=int(c.now)))
    assert len(notes) == 1 and len(phone) == 1 and "wrong key" in notes[0]


def test_text_is_cleaned_and_capped():
    d, _, _, _ = _door()
    d.on_payload(_msg(text="hi\x00\x07 there\n\n" + "x" * 500))
    m = d.due("sleep")
    assert m["text"].startswith("hi there ") and len(m["text"]) == door.MAX_TEXT


def test_closed_without_keys():
    with tempfile.TemporaryDirectory() as tmp:
        assert door.load_keys(os.path.join(tmp, "nope")) == {}
        assert not door.Door(keys={}).open


def test_add_and_remove_sender_with_the_script():
    script = os.path.join(os.path.dirname(__file__), "..", "scripts", "door_send.py")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "door_keys")
        out = subprocess.run([sys.executable, script, "--add-sender", "claude",
                              "--keys-file", path], capture_output=True, text=True).stdout
        keys = door.load_keys(path)
        assert list(keys) == ["claude"] and keys["claude"].hex() in out
        assert oct(os.stat(path).st_mode & 0o777) == "0o600"
        subprocess.run([sys.executable, script, "--remove-sender", "claude",
                        "--keys-file", path], capture_output=True, text=True)
        assert door.load_keys(path) == {}


def test_easter_eggs():
    assert door.announce("claude", "Hi").startswith("A letter from Claude!")
    assert door.announce("word-clock", "Tick").startswith("Message from Word Clock:")
    assert "Treat others" in door.own_answer("What's the golden rule?")
    assert door.own_answer("what time is it") is None
    assert "golden_rule" in door.WELCOME and "key" in door.WELCOME["note"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
