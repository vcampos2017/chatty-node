"""The soil monitor timer: dry soil in Chatty's own voice by day, a quiet notice at night."""
import os
import socket
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

voice = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # stands in for the voice node
voice.bind(("127.0.0.1", 0))
voice.settimeout(0.5)
os.environ["CHATTY_VOICE_PORT"] = str(voice.getsockname()[1])

from scripts import real_status_monitor as mon  # noqa: E402

shown = []
mon.face_link.notice = shown.append


def heard():
    try:
        return voice.recvfrom(512)[0].decode()
    except socket.timeout:
        return None


def test_daytime_she_says_it():
    shown.clear()
    mon.quiet_hours.is_night = lambda now=None: False
    assert mon.tell_her(mon.DRY_TEXT) == "said"
    assert heard() == "notify:" + mon.DRY_TEXT
    assert shown == [mon.DRY_TEXT]


def test_night_is_silent():
    shown.clear()
    mon.quiet_hours.is_night = lambda now=None: True
    assert mon.tell_her(mon.DRY_TEXT) == "notice"
    assert heard() is None
    assert shown == [mon.DRY_TEXT]


def test_no_espeak_left():
    src = open(os.path.join(ROOT, "scripts", "real_status_monitor.py")).read()
    assert "espeak" not in src.replace("with espeak at any hour", "")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
