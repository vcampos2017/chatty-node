"""The systemd heartbeat (src/watchdog.py) and where the voice node sends it."""
import os
import socket
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import watchdog  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "chatty_voice_node.py")
CONF = os.path.join(os.path.dirname(__file__), "..", "deploy", "systemd",
                    "chatty-voice.service.d", "chatty-safety.conf")


def _listener():
    path = os.path.join(tempfile.mkdtemp(), "notify")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(path)
    s.settimeout(1)
    return s, path


def test_pings_reach_systemd_but_not_too_often():
    s, path = _listener()
    os.environ["NOTIFY_SOCKET"] = path
    watchdog._last = 0.0
    try:
        assert watchdog.ping(now=100.0)
        assert s.recv(64) == b"WATCHDOG=1"
        assert not watchdog.ping(now=101.0)          # throttled
        assert watchdog.ping(now=100.0 + watchdog.EVERY)
        assert watchdog.ready() and s.recv(64) == b"WATCHDOG=1" and s.recv(64) == b"READY=1"
    finally:
        del os.environ["NOTIFY_SOCKET"]
        s.close()


def test_run_by_hand_it_does_nothing():
    os.environ.pop("NOTIFY_SOCKET", None)
    watchdog._last = 0.0
    assert not watchdog.ping(now=500.0)
    os.environ["NOTIFY_SOCKET"] = "/nonexistent/socket"
    try:
        assert not watchdog.ping(now=1000.0)         # a bad socket never raises
    finally:
        del os.environ["NOTIFY_SOCKET"]


def test_voice_node_pings_from_its_main_loop_and_slow_waits():
    src = open(SRC).read()
    loop = src.index("\nwhile True:\n    watchdog.ping()")
    assert src.index("watchdog.ready()") < loop
    assert "watchdog.ping()        # waiting on an answer" in src


def test_watchdog_is_much_longer_than_her_slowest_answer():
    conf = open(CONF).read()
    secs = int(conf.split("WatchdogSec=")[1].split()[0])
    assert secs >= 240                  # a slow answer is ~1.5 min; never cut one off
    assert "Restart=always" in conf and "NotifyAccess=all" in conf


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
