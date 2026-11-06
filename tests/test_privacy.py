import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import privacy  # noqa: E402

PRIVATE = {
    "call me at 512-555-0142": "phone",
    "call five five five one two three four five six seven": "phone",
    "my email is vince@example.com": "email",
    "email me at bob at gmail dot com": "email",
    "i live at 42 elm street": "address",
    "my ssn is 123-45-6789": "ssn",
    "my card is 4111 1111 1111 1111": "card",
    "my password is tiny123": "secret",
    "the wifi password is hunter2": "secret",
    "whats my bank account number": "bank",
    "i was born on march third": "birth",
    "my doctor said my blood pressure is high": "health",
    "i was at the clinic today": "health",
}

ORDINARY = [
    "what time is it", "tell me a joke", "how do i make a strong password",
    "what are the symptoms of the flu", "who was born on july fourth",
    "tell me a joke about one two three", "whats the weather this weekend",
    "how many miles to the moon", "is 4111 a prime number",
]


def test_private_things_are_found():
    for text, kind in PRIVATE.items():
        assert kind in privacy.find(text), (text, privacy.find(text))


def test_ordinary_questions_pass():
    for text in ORDINARY:
        assert privacy.find(text) == [], (text, privacy.find(text))


def test_card_needs_luhn():
    assert "card" not in privacy.find("my card is 4111 1111 1111 1112")


def test_question_names_the_kind_not_the_thing():
    q = privacy.cloud_question(privacy.find("my password is tiny123 call 512-555-0142"))
    assert "a password or code and a phone number" in q
    assert "tiny123" not in q and "555" not in q


def test_off_switch():
    old = privacy.ENABLED
    privacy.ENABLED = False
    try:
        assert privacy.needs_asking("my password is x") == []
    finally:
        privacy.ENABLED = old


def test_door_send_refuses_private_message_without_a_tty():
    script = os.path.join(os.path.dirname(__file__), "..", "scripts", "door_send.py")
    r = subprocess.run([sys.executable, script, "--as", "claude", "--key", "00" * 32,
                        "my password is tiny123"], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    assert r.returncode != 0 and "Not sent" in r.stderr


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
