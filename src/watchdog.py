"""
A heartbeat for systemd, so a frozen Chatty gets restarted by itself.

The voice node calls ping() from its main loop. When chatty-voice runs with
WatchdogSec= (deploy/systemd/chatty-voice.service.d/chatty-safety.conf), systemd
restarts her if no ping arrives for that long, the way it already restarts her
after a crash. Run by hand (no NOTIFY_SOCKET) ping() does nothing.

No extra packages: it is one tiny datagram to systemd's notify socket, sent at
most every few seconds.
"""
from __future__ import annotations

import os
import socket
import time

EVERY = 5.0          # seconds between heartbeats (WatchdogSec is minutes)
_last = 0.0


def _notify(message: str) -> bool:
    path = os.environ.get("NOTIFY_SOCKET", "")
    if not path:
        return False
    if path.startswith("@"):            # an abstract socket
        path = "\0" + path[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(path)
            s.sendall(message.encode())
        return True
    except OSError:
        return False


def ping(now: float = None) -> bool:
    """'Still alive.' Cheap enough to call on every pass of the main loop."""
    global _last
    now = time.monotonic() if now is None else now
    if now - _last < EVERY:
        return False
    _last = now
    return _notify("WATCHDOG=1")


def ready() -> bool:
    """'Started up' (only matters for Type=notify; harmless otherwise)."""
    return _notify("READY=1")
