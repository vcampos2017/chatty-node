"""
Night vision: at night Chatty's whole screen glows a soft, dim red, like the red
lights in a submarine or an astronomer's red flashlight. Red light keeps your eyes
used to the dark, so a glance at her at 2 AM doesn't blind you.

When:
  - From the bedtime wind-down (bedtime.py) or night mode (quiet_hours: 10 PM),
    whichever comes first, until night mode ends in the morning (CHATTY_NIGHT_END, 7 AM).
  - "Hey Chatty, turn on the red light" / "night vision on" turns it on now (until the
    morning); "turn off the red light" / "show me your true colors" turns it off for
    tonight; "red light automatic" goes back to the clock. The remote panel has buttons too.
  - Red Alert (a tornado warning, red_alert.py) ALWAYS wins: the red glow steps aside so
    the alert shows in its own colors, flashing, at full brightness. The night glow is the
    opposite on purpose: dim, calm, steady, nothing ever flashes.

How it looks: everything she draws is turned into shades of one red (her bright eyes
stay bright, the dark background stays black; blue and green parts keep their shape
because the brightest of the three colors counts, not just the red part). While she's
talking at night the screen goes no higher than CHATTY_NIGHT_RED_BRIGHT, so the red
stays gentle. A brightness picked on the remote panel still wins.

All on the Pi, nothing new to install (numpy if it's there, pygame's own tools otherwise).

Settings (in /etc/chatty/secrets.env):
    CHATTY_NIGHT_RED=0          never glow red (=1 the default: at night; =always for testing)
    CHATTY_NIGHT_RED_BRIGHT     highest screen brightness while red, 0..1 (default 0.4)
    CHATTY_NIGHT_RED_COLOR      the red, as R,G,B (default 255,0,0: pure red is kindest
                                to night vision; 255,40,0 is a warmer ember)
"""
from __future__ import annotations

import os
import re
import time
from typing import Callable, Optional, Tuple

try:
    import quiet_hours
except ImportError:  # running from another folder
    from . import quiet_hours  # type: ignore


def _level(name: str, default: float) -> float:
    try:
        return max(0.02, min(1.0, float(os.getenv(name, str(default)))))
    except ValueError:
        return default


def _color(text: str) -> Tuple[int, int, int]:
    try:
        r, g, b = (max(0, min(255, int(v))) for v in text.split(","))
        return (r, g, b) if r else (255, 0, 0)
    except ValueError:
        return (255, 0, 0)


MODE = os.getenv("CHATTY_NIGHT_RED", "1").strip().lower()
ENABLED = MODE != "0"
BRIGHT = _level("CHATTY_NIGHT_RED_BRIGHT", 0.4)
COLOR = _color(os.getenv("CHATTY_NIGHT_RED_COLOR", "255,0,0"))


def red_level(r: int, g: int, b: int) -> int:
    """How bright a pixel stays once it's red (0..255): mostly its brightest color,
    a little of its overall lightness, so white stays bright and blue isn't lost."""
    lum = (299 * r + 587 * g + 114 * b) // 1000
    return (3 * max(r, g, b) + 2 * lum) // 5


def redden_rgb(r: int, g: int, b: int, color=COLOR) -> Tuple[int, int, int]:
    v = red_level(r, g, b)
    return (v * color[0] // 255, v * color[1] // 255, v * color[2] // 255)


def _next_morning(now: float) -> float:
    end = quiet_hours.night_hours()[1]
    d = time.localtime(now)
    until = time.mktime((d.tm_year, d.tm_mon, d.tm_mday, end, 0, 0, 0, 0, -1))
    if until <= now:
        until = time.mktime((d.tm_year, d.tm_mon, d.tm_mday + 1, end, 0, 0, 0, 0, -1))
    return until


class NightRed:
    """Decides whether the screen glows red (no pygame here; easy to test)."""

    def __init__(self, is_night: Optional[Callable[[float], bool]] = None, mode: str = MODE):
        self.is_night = is_night or quiet_hours.is_night
        self.mode = mode
        self.manual = None          # (on, until): asked for by voice or the panel

    def set(self, value: str, now: float) -> None:
        """'on' (until the morning), 'off' (for tonight) or 'auto'."""
        v = (value or "").strip().lower()
        if v in ("on", "off"):
            self.manual = (v == "on", _next_morning(now))
        elif v == "auto":
            self.manual = None

    def on(self, now: float, bed_until: float = 0.0, red_alert: bool = False) -> bool:
        if red_alert:
            return False                     # Red Alert always shows in its own colors
        if self.manual and now < self.manual[1]:
            return self.manual[0]
        self.manual = None
        if self.mode == "0":
            return False
        if self.mode == "always":
            return True
        return now < bed_until or self.is_night(now)

    @staticmethod
    def cap(target: float, held: bool) -> float:
        """The screen brightness while red: gentle, unless the panel picked one."""
        return target if held else min(target, BRIGHT)


# ----- asking for it by voice (the voice node) -----

_RED = r"(red|night ?time) (light|lights|glow|mode|screen)|night (light|glow)|night ?vision( mode)?|submarine mode|" \
       r"astronomy mode|dark ?sky mode|red ?shift mode"
_OFF = re.compile(r"\b((turn|switch|shut) off|stop|no more|cancel|end|disable) (the |your |that )?(" + _RED + r")\b|"
                  r"\b(" + _RED + r") (off|please off)\b|\b(show me |back to )?your (true|real|normal) colou?rs\b")
_AUTO = re.compile(r"\b(" + _RED + r") (on )?(auto|automatic|automatically|by itself|on a schedule|schedule)\b|"
                   r"\b(set|put) (the |your )?(" + _RED + r") (to|on) (auto|automatic|the schedule)\b")
_ON = re.compile(r"\b((turn|switch|put) on|start|use|go to|switch to|enable) (the |your |a |some )?(" + _RED + r")\b|"
                 r"\b(" + _RED + r") on\b|\bgo red\b|\bglow red\b|^(" + _RED + r")( please)?$")
_WHY = re.compile(r"\bwhy (is|are) (you|your (face|screen)|the screen) (so )?red\b|"
                  r"\bwhat (is|are|s) (the |your )?(" + _RED + r")\b|\bwhy (do|does) (submarines|astronomers)\b.*\bred\b|"
                  r"\bhow does (the )?(" + _RED + r") work\b")


def request(prompt: str) -> Optional[str]:
    """'on', 'off', 'auto', 'why' or None for a spoken (normalized) question.
    Never matches "red alert": that's the tornado warning, not this."""
    p = " ".join((prompt or "").lower().split())
    if not p or "alert" in p:
        return None
    for name, rx in (("why", _WHY), ("off", _OFF), ("auto", _AUTO), ("on", _ON)):
        if rx.search(p):
            return name
    return None


def _clock(hour: int) -> str:
    return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"


def reply(kind: str) -> str:
    start, end = quiet_hours.night_hours()
    if kind == "on":
        return ("Red night light on, until " + _clock(end) + ". Easy on the eyes, like the lights in a "
                "submarine.")
    if kind == "off":
        return "Back to my true colors, just for tonight. Say red light on if your eyes want the dark again."
    if kind == "auto":
        return (f"Okay! I'll glow red after my bedtime wind-down, or from {_clock(start)}, until {_clock(end)}.")
    return ("Red light is gentle on your night vision. Your eyes take about twenty minutes to get used to the "
            "dark, and white or blue light undoes that in a blink, but dim red barely touches it. That's why "
            "submarines and astronomers use it, and why I glow red at night. If there's ever a tornado warning, "
            "I switch back to full color so you can't miss it.")


# ----- drawing (pygame, in the face process) -----

def redden_surface(surface, color=COLOR) -> None:
    """Turn the whole frame into shades of red, in place. Never raises."""
    try:
        _redden_numpy(surface, color)
        return
    except Exception:
        pass
    try:
        _redden_pygame(surface, color)
    except Exception:
        pass


def _redden_numpy(surface, color) -> None:
    import pygame
    px = pygame.surfarray.pixels3d(surface)          # a view: changes go straight to the screen
    red_array(px, color)
    del px


def red_array(px, color=COLOR) -> None:
    """The same as redden_rgb, for a whole (..., 3) uint8 numpy array, in place."""
    import numpy as np
    r = px[..., 0].astype(np.uint16)
    g = px[..., 1].astype(np.uint16)
    b = px[..., 2].astype(np.uint16)
    lum = (r * 77 + g * 150 + b * 29) >> 8                # close to redden_rgb's, in 16 bits
    v = (np.maximum(np.maximum(r, g), b) * 3 + lum * 2) // 5
    for i, c in enumerate(color):
        px[..., i] = (v * c // 255).astype(np.uint8) if c else 0


def _redden_pygame(surface, color) -> None:
    import pygame
    gray = getattr(pygame.transform, "grayscale", None)    # pygame 2.1.4+
    if gray is not None:
        surface.blit(gray(surface), (0, 0))
    surface.fill(color, special_flags=pygame.BLEND_RGB_MULT)


if __name__ == "__main__":
    n = NightRed()
    now = time.time()
    print("Night red:", "ON" if n.on(now) else "off", f"(mode {MODE}, brightness cap {BRIGHT:.2f}, color {COLOR})")
