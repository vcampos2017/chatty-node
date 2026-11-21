"""
Screen dimming: Chatty turns her screen down when nobody needs it.

  - Talking with her (listening, thinking, speaking, any mood): full brightness.
  - Daytime, nothing happening for CHATTY_DIM_AFTER seconds: soft (CHATTY_DIM_IDLE).
  - Night (quiet_hours: 10 pm to 7 am) or put to bed, after a short pause:
    very dim (CHATTY_DIM_NIGHT), so the room stays dark.
  - After the bedtime wind-down (bedtime.py): night dimming until morning, even
    before night mode starts.
  - A tap or "Hey Chatty" brings it right back. When the screen is very dim,
    the first tap only lights it up (so checking on her at night doesn't
    wake her); tap again to talk.
  - Changes fade over about a second instead of jumping.

It writes /sys/class/backlight/<screen>/brightness, which needs permission:
run `bash scripts/install_backlight.sh` once. Without it she prints a note and
the screen just stays as it is.

Settings (in /etc/chatty/secrets.env), levels are 0.0 to 1.0 of full:
    CHATTY_DIM=0            never dim
    CHATTY_DIM_AFTER        idle seconds before dimming in the daytime (default 300)
    CHATTY_DIM_IDLE         daytime idle level (default 0.35)
    CHATTY_DIM_NIGHT        night / resting level (default 0.06; 0 = screen dark)
    CHATTY_BACKLIGHT        backlight folder (default: the first in /sys/class/backlight)
    CHATTY_DIM_HOLD_HOURS   how long a brightness picked on the remote panel lasts (default 2)

Test on the Pi:  python3 src/backlight.py 0.3   (then 1.0 to put it back)
"""
from __future__ import annotations

import glob
import os
import time
from typing import Callable, Optional

try:
    import quiet_hours
except ImportError:  # running from another folder
    from . import quiet_hours  # type: ignore


def _level(name: str, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(os.getenv(name, str(default)))))
    except ValueError:
        return default


ENABLED = os.getenv("CHATTY_DIM", "1") != "0"
DIM_AFTER = float(os.getenv("CHATTY_DIM_AFTER", "300"))
IDLE_LEVEL = _level("CHATTY_DIM_IDLE", 0.35)
NIGHT_LEVEL = _level("CHATTY_DIM_NIGHT", 0.06)
NIGHT_AFTER = 30            # seconds of quiet at night before going dark
FULL = 1.0
FADE_SECONDS = 1.0
DARK = 0.2                  # at or below this, a tap only lights the screen
QUIET = ("idle", "sleepy", "resting")
HOLD_HOURS = float(os.getenv("CHATTY_DIM_HOLD_HOURS", "2"))   # how long a panel brightness lasts


class Dimmer:
    """Decides how bright the screen should be (no hardware; easy to test)."""

    def __init__(self, is_night: Optional[Callable[[float], bool]] = None):
        self.is_night = is_night or quiet_hours.is_night
        self.poked = 0.0        # last tap that only lit the screen
        self.held = None        # (level, until): brightness picked on the remote panel
        self.bed_until = 0.0    # after the bedtime wind-down: night dimming until morning

    def hold(self, level: Optional[float], now: float, hours: float = HOLD_HOURS) -> None:
        """Keep the screen at this level for a while (the remote panel's slider);
        None goes back to dimming on its own."""
        if level is None:
            self.held = None
        else:
            self.held = (max(0.02, min(1.0, float(level))), now + hours * 3600)

    def bedtime(self, now: float) -> None:
        """The bedtime wind-down is over: dim like at night until night mode ends
        in the morning (CHATTY_NIGHT_END), even if it's earlier than night mode."""
        end = quiet_hours.night_hours()[1]
        d = time.localtime(now)
        until = time.mktime((d.tm_year, d.tm_mon, d.tm_mday, end, 0, 0, 0, 0, -1))
        if until <= now:
            until = time.mktime((d.tm_year, d.tm_mon, d.tm_mday + 1, end, 0, 0, 0, 0, -1))
        self.bed_until = until

    def target(self, state: str, last_activity: float, now: float) -> float:
        if self.held and now < self.held[1]:
            return self.held[0] if state in QUIET else max(self.held[0], IDLE_LEVEL)
        self.held = None
        if not ENABLED:
            return FULL
        if state not in QUIET:
            return FULL                      # she's talking or listening
        quiet_for = now - max(last_activity, self.poked)
        if state == "resting" or now < self.bed_until or self.is_night(now):
            return FULL if quiet_for < NIGHT_AFTER else NIGHT_LEVEL
        return FULL if quiet_for < DIM_AFTER else IDLE_LEVEL

    def poke(self, now: float) -> None:
        """A tap that only lights the screen up."""
        self.poked = now


class Backlight:
    """Fades the real backlight toward a level. Never raises."""

    def __init__(self, path: Optional[str] = None):
        path = path or os.getenv("CHATTY_BACKLIGHT") or next(iter(sorted(glob.glob("/sys/class/backlight/*"))), None)
        self.path = path
        self.max = 0
        self.level = FULL           # where the fade is now (0..1)
        self.written = None
        self.ok = False
        if not path:
            print("Screen dimming: no backlight found", flush=True)
            return
        try:
            with open(os.path.join(path, "max_brightness")) as f:
                self.max = int(f.read().strip())
            with open(os.path.join(path, "brightness")) as f:
                self.level = int(f.read().strip()) / self.max if self.max else FULL
            self.ok = self.max > 0
        except (OSError, ValueError) as e:
            print(f"Screen dimming: can't read the backlight ({e})", flush=True)

    def _write(self, level: float) -> None:
        value = int(round(level * self.max))
        if level > 0:
            value = max(1, value)            # 0 would turn some panels fully off
        if value == self.written:
            return
        try:
            with open(os.path.join(self.path, "brightness"), "w") as f:
                f.write(str(value))
            self.written = value
        except OSError as e:
            print(f"Screen dimming off: can't change the backlight ({e}). "
                  "Run: bash scripts/install_backlight.sh", flush=True)
            self.ok = False

    def step(self, target: float, dt: float) -> None:
        """Move toward target; call every frame."""
        if not self.ok:
            return
        if abs(target - self.level) < 1e-3:
            self.level = target
        else:
            step = max(dt, 0.0) / FADE_SECONDS
            self.level += max(-step, min(step, target - self.level))
        self._write(self.level)

    def busy(self, target: float) -> bool:
        return self.ok and abs(target - self.level) > 1e-3


if __name__ == "__main__":
    import sys
    b = Backlight()
    if not b.ok:
        sys.exit(1)
    goal = float(sys.argv[1]) if len(sys.argv) > 1 else FULL
    print(f"{b.path}: max {b.max}, now {b.level:.2f}, fading to {goal:.2f}")
    last = time.time()
    while abs(b.level - goal) > 1e-3 and b.ok:
        time.sleep(1 / 30)
        now = time.time()
        b.step(goal, now - last)
        last = now
