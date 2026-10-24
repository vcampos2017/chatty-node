"""
Night mode: the hours when Chatty shows things on her screen instead of
saying them out loud. She still answers when you wake her ("Hey Chatty" or
a tap); this only covers things she would say on her own.

Settings (environment or /etc/chatty/*.env):

  CHATTY_NIGHT_START   hour night mode begins, 0-23 (default 22 = 10 pm)
  CHATTY_NIGHT_END     hour night mode ends, 0-23 (default 7 = 7 am)
  CHATTY_NIGHT_MODE    "0" to turn night mode off (speak at any hour)
"""
import os
import time


def _hour_setting(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if 0 <= value <= 23 else default


def night_hours() -> tuple[int, int]:
    return _hour_setting("CHATTY_NIGHT_START", 22), _hour_setting("CHATTY_NIGHT_END", 7)


def is_night(now: float | None = None) -> bool:
    """True during night mode. Handles ranges that cross midnight (22 -> 7)."""
    if os.getenv("CHATTY_NIGHT_MODE", "1") == "0":
        return False
    start, end = night_hours()
    if start == end:
        return False
    hour = time.localtime(now if now is not None else time.time()).tm_hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end
