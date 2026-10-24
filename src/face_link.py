"""
Tell Chatty's face what's happening. Fire-and-forget UDP, so the voice node
never waits on (or breaks because of) the face.
"""
import os
import socket

_ADDR = ("127.0.0.1", int(os.getenv("CHATTY_FACE_PORT", "47474")))
_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def _send(msg: str) -> None:
    try:
        _sock.sendto(msg.encode("utf-8"), _ADDR)
    except OSError:
        pass  # face not running: that's fine


def state(name: str) -> None:
    """idle, listening, thinking, speaking, puzzled, sleepy, resting,
    mischief, mischief_talk, love, love_talk,
    actually, actually_talk,
    snapped, snapped_talk, tiny or tiny_talk"""
    _send(f"state:{name}")


def level(value: float) -> None:
    """Mouth openness while speaking, 0..1."""
    _send(f"level:{max(0.0, min(1.0, value)):.2f}")


def ponder(node: str = "") -> None:
    """Have the face wonder about another node now ('' = the next one)."""
    _send(f"ponder:{node}")


def caption(text: str) -> None:
    """Show the words Chatty heard at the top of the screen ('' clears)."""
    _send(f"heard:{(text or '')[:300]}")


def notice(text: str) -> None:
    """Show a notice on screen (night mode: shown instead of spoken). It
    stays until someone taps the screen, which dismisses it."""
    _send(f"notice:{(text or '')[:300]}")


def listen(seconds: float) -> None:
    """Show the listening timer bar for this many seconds."""
    _send(f"listen:{seconds:.1f}")


def rec(mode: str) -> None:
    """Recording indicator: 'full' (REC), 'private', 'stats' or 'off'."""
    _send(f"rec:{mode}")


def play() -> None:
    """Start a tic-tac-toe game with the person (they tap squares)."""
    _send("play:1")
