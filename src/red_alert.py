"""
Red Alert: Chatty's mode for one thing only, a National Weather Service
TORNADO WARNING for her own location (CHATTY_LAT / CHATTY_LON).

A Tornado Watch, a thunderstorm warning or anything else still goes the usual
way (alerts.py). Only a Tornado Warning (including a "Tornado Emergency", which
the NWS sends as a Tornado Warning) turns on Red Alert:

  - Her face: eyes go red and wide, a red frame pulses around the screen and a
    banner reads TORNADO WARNING / Take shelter now / until 7:45 PM. The screen
    goes to full brightness and stays there, whatever the dimming, bedtime or
    night mode says. Doodles, chess and games are put away.
  - Her alarm: an original tone made on the Pi (earcons.red_alert(): three quick
    beeps and her own two-note "listening" chime, three times). Loud, even with
    CHATTY_SOUNDS=0.
  - Her voice: "Red alert! Red alert! There's a tornado warning for our area
    until 7:45 PM. Please go to your safe place now..." Day or night, resting or
    not, even in the middle of a conversation.
  - Your phone: an IFTTT `chatty_alert` buzz ("RED ALERT from Chatty: ..."),
    unless CHATTY_ALERTS_PHONE=off.

The alarm and the line repeat every CHATTY_RED_ALERT_REPEAT minutes (5), up to
CHATTY_RED_ALERT_RINGS times (3), until someone taps her screen or says "Hey
Chatty" ("Okay, I'll stop the alarm..."). The red screen stays until the
warning ends: when the NWS drops it or it expires she says "The tornado warning
is over" and the face goes back to normal.

Why the location and not a ZIP code: NWS tornado warnings are drawn as a
polygon around the storm's path, often smaller than a county. Chatty asks for
alerts at her exact point (api.weather.gov/alerts/active?point=LAT,LON), so she
only goes red when the warning box covers your house, not your whole ZIP code.

Test it safely (nothing is fetched from the NWS and nothing is real), on the Pi
while chatty-voice is running:
    python3 src/red_alert.py --test            face + alarm + voice, ends after 2 minutes
    python3 src/red_alert.py --test --phone    the same, plus a phone buzz marked TEST
Everything a test says or shows is marked TEST, and it rings at most twice.

Settings (in /etc/chatty/secrets.env):
    CHATTY_RED_ALERT=0            no Red Alert: tornado warnings are spoken like other urgent warnings
    CHATTY_RED_ALERT_REPEAT=5     minutes between alarms until someone answers
    CHATTY_RED_ALERT_RINGS=3      how many times at most
    CHATTY_RED_ALERT_VOLUME=0.6   alarm tone loudness (0..1; other chimes use 0.25)

The red mode is an original design ("red alert" is just the plain words): no
sounds, pictures or lines from any show.
"""
from __future__ import annotations

import os
import socket
import time
from typing import Optional

ENABLED = os.getenv("CHATTY_RED_ALERT", "1") != "0"
REPEAT = max(60.0, float(os.getenv("CHATTY_RED_ALERT_REPEAT", "5")) * 60)
RINGS = max(1, int(os.getenv("CHATTY_RED_ALERT_RINGS", "3")))
TEST_SECONDS = 120        # a test ends by itself after this
TEST_REPEAT = 45          # and rings again once, sooner, so the repeat can be heard
TEST_RINGS = 2
TEST_MESSAGE = "redalert:test"


def is_red(event: str) -> bool:
    """Only a Tornado Warning (not a Watch, not anything else)."""
    return ENABLED and event.strip().lower() == "tornado warning"


def _until_words(expires: float) -> str:
    if not expires:
        return ""
    d = time.localtime(expires)
    minute = "" if d.tm_min == 0 else f":{d.tm_min:02d}"
    return f" until {d.tm_hour % 12 or 12}{minute} {'a m' if d.tm_hour < 12 else 'p m'}"


def _until_written(expires: float) -> str:
    if not expires:
        return ""
    d = time.localtime(expires)
    return f"until {d.tm_hour % 12 or 12}:{d.tm_min:02d} {'AM' if d.tm_hour < 12 else 'PM'}"


def spoken(expires: float, first: bool, test: bool = False) -> str:
    until = _until_words(expires)
    if first:
        text = (f"Red alert! Red alert! There's a tornado warning for our area{until}. "
                "Please go to your safe place now: the lowest floor, in an inside room, "
                "away from windows. Bring Tiny if you can. "
                "Tap my screen when you're safe, and I'll stop the alarm. "
                "I'll keep watch and tell you when it's over.")
    else:
        text = (f"Red alert. The tornado warning is still on{until}. "
                "Please stay in your safe place. Tap my screen to tell me you heard me.")
    if test:
        text = "This is only a test. " + text + " This was only a test."
    return text


def acknowledged_line(test: bool = False) -> str:
    line = "Okay, I'll stop the alarm. My screen stays red until the warning is over. Stay safe."
    return ("Test alarm off. " + line) if test else line


def over_line(test: bool = False) -> str:
    if test:
        return "The test is over. Red alert is off. Thanks for checking on me!"
    return ("The tornado warning is over, so red alert is off. "
            "Still, be careful when you go outside. I'm glad you're safe.")


def phone_text(expires: float, test: bool = False) -> str:
    until = _until_written(expires)
    text = f"RED ALERT from Chatty: Tornado Warning for home {until}. Take shelter now.".replace("  ", " ")
    return ("TEST - " + text + " (only a test)") if test else text


class RedAlert:
    """Keeps track of the red mode for the voice node (no sound, no screen: easy to test).

    step(warning, now) is called from the main loop with the Tornado Warning in
    effect (alerts.Watcher.red_warning(), or None) and returns what to do now:
        "start"  a new warning: show it, buzz the phone, sound the alarm, say it
        "ring"   still no answer: alarm and the reminder line again
        "end"    the warning is over
        None     nothing new
    """

    def __init__(self, clock=time.time):
        self.clock = clock
        self.on = False
        self.test = False
        self.expires = 0.0
        self.rings = 0
        self.next_ring = 0.0
        self.heard = False          # someone tapped / said "Hey Chatty"
        self.test_until = 0.0
        self.shown_at = 0.0

    def start_test(self, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        self.test_until = now + TEST_SECONDS

    def step(self, warning, now: Optional[float] = None) -> Optional[str]:
        now = self.clock() if now is None else now
        test_on = now < self.test_until
        if warning is not None and warning.expires and warning.expires <= now:
            warning = None               # expired, even if the feed still lists it
        if warning is not None:
            expires = warning.expires
        elif test_on:
            expires = self.test_until
        else:
            expires = None
        if expires is None:
            if self.on:
                self.on = False
                return "end"
            return None
        if not self.on or (self.test and warning is not None):
            # a new red alert (a real warning always takes over from a test)
            self.on, self.test = True, warning is None
            self.expires = expires
            self.rings, self.heard = 1, False
            self.next_ring = now + (TEST_REPEAT if self.test else REPEAT)
            self.shown_at = 0.0
            return "start"
        if expires != self.expires:      # the NWS extended (or shortened) it
            self.expires = expires
            self.shown_at = 0.0
        limit = TEST_RINGS if self.test else RINGS
        if not self.heard and self.rings < limit and now >= self.next_ring:
            self.rings += 1
            self.next_ring = now + (TEST_REPEAT if self.test else REPEAT)
            return "ring"
        return None

    def acknowledge(self) -> bool:
        """A tap or "Hey Chatty": stop the alarm. True if it was still ringing."""
        if self.on and not self.heard:
            self.heard = True
            return True
        return False

    def face_message(self) -> str:
        if not self.on:
            return "redalert:off"
        return f"redalert:{int(self.expires)}:{'test' if self.test else ''}:Tornado Warning"

    def face_due(self, now: Optional[float] = None) -> bool:
        """Time to (re)send the face message? (the face may have restarted)"""
        now = self.clock() if now is None else now
        if now - self.shown_at >= 30:
            self.shown_at = now
            return True
        return False


def send_test(phone: bool = False) -> None:
    """Ask the running voice node for a test red alert (UDP on this Pi only)."""
    port = int(os.getenv("CHATTY_VOICE_PORT", "47475"))
    msg = TEST_MESSAGE + (":phone" if phone else "")
    socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(msg.encode(), ("127.0.0.1", port))


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        send_test(phone="--phone" in sys.argv)
        print("Asked Chatty for a TEST red alert (about 2 minutes). "
              "If nothing happens, is chatty-voice running?  journalctl -u chatty-voice -f")
    else:
        print(__doc__)
