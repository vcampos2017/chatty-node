"""
Conversation log for improving Chatty: what was heard, which part of Chatty
answered, how long it took, and (in full mode) what Chatty said back.

    CHATTY_LOG_MODE=full     words + replies (default)
    CHATTY_LOG_MODE=private  statistics only: timing, which tier answered, phrase hashes
    CHATTY_LOG_MODE=off      nothing

Only conversations after Chatty is woken are logged; nothing is recorded while it
waits for its name, except wake statistics: when it woke (wake phrase or tap) and
the confidence of near-misses (no words). These are kept in private mode too. Logs stay on the Pi in ~/.local/share/chatty/logs/
(CHATTY_LOG_DIR), rotating at about 1 MB per file and keeping the last 5 files.

By voice: "Hey Chatty, privacy mode" pauses logging (it stays paused across
restarts) and "Hey Chatty, resume logging" turns it back on.
"""
import os
from pathlib import Path

from interaction_logger import InteractionLogger

MODE = os.getenv("CHATTY_LOG_MODE", "full").lower()
LOG_DIR = Path(os.getenv("CHATTY_LOG_DIR", os.path.expanduser("~/.local/share/chatty/logs")))
_PAUSE_FLAG = LOG_DIR / "PAUSED"

PAUSE_PHRASES = {"privacy mode", "privacy mode on", "pause logging", "stop logging",
                 "dont log this", "do not log this", "stop recording conversations",
                 "turn off logging", "logging off"}
RESUME_PHRASES = {"resume logging", "start logging", "privacy mode off", "turn on logging",
                  "logging on", "you can log again"}

_logger = None
if MODE in ("full", "private"):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _logger = InteractionLogger(log_dir=str(LOG_DIR), log_name="conversations.jsonl",
                                    max_bytes=1_000_000, keep_rotated=5,
                                    debug_mode=(MODE == "full"))
        # conversations are private: only the pi user can read the log folder
        os.chmod(LOG_DIR, 0o700)
    except Exception as e:
        print(f"(conversation log unavailable: {e!r})", flush=True)


def indicator() -> str:
    """What the screen's recording indicator should show right now."""
    if _logger is None:
        return "off"
    if paused():
        return "private"
    return "full" if MODE == "full" else "stats"


def paused() -> bool:
    return _PAUSE_FLAG.exists()


def pause() -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _PAUSE_FLAG.touch()
    except OSError:
        pass


def resume() -> None:
    try:
        _PAUSE_FLAG.unlink()
    except OSError:
        pass


def turn(kind: str, heard: str = "", reply: str = "", *, session: str = None,
         wake: str = None, wake_conf: float = None, seconds: float = None,
         cloud: bool = None, notes: str = None, speaker: str = None,
         name_heard: str = None) -> None:
    """Record one exchange. kind says what happened, e.g. 'skill', 'memory',
    'local_llm', 'relay', 'command:rest', 'filtered_background', 'no_question',
    'error'. Never raises: logging must not break Chatty."""
    if _logger is None or paused():
        return
    try:
        _logger.log_event(
            wake_word=wake, wake_confidence=wake_conf,
            normalized_phrase=heard or None, intent=kind,
            handled=not kind.startswith(("error", "no_question", "filtered")),
            response_type=kind, duration_s=seconds,
            fulfillment_mode="cloud" if cloud else "local", cloud_required=cloud,
            notes=notes, transcript=heard or None, reply=reply or None, session=session,
            speaker=speaker, name_heard=name_heard,
        )
    except Exception as e:
        print(f"(conversation log write failed: {e!r})", flush=True)


def wake(kind: str, source: str = None, conf: float = None) -> None:
    """Wake statistics: kind is 'woke' or 'near_miss' (heard her wake phrase, but not
    confidently enough). Only how and how confident; never any words."""
    if _logger is None or paused():
        return
    try:
        _logger.log_event(wake_word=source, wake_confidence=conf, intent=f"wake:{kind}",
                          response_type=f"wake:{kind}", handled=(kind == "woke"))
    except Exception as e:
        print(f"(conversation log write failed: {e!r})", flush=True)
