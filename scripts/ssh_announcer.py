#!/usr/bin/env python3
"""Chatty SSH announcer.

Watches the system journal for SSH activity on the Chatty Pi and has Chatty
say so out loud:

  "User pi logged on, from Tailscale."
  "SSH session ended."
  "Possible suspicious activity. A failed SSH login for admin, from the internet."
  "... Requesting your assistance, please."   (repeated attempts, or a login
                                               from the internet)

At night (see src/quiet_hours.py: CHATTY_NIGHT_START / CHATTY_NIGHT_END) she
stays quiet and shows these on her screen instead, until someone taps it.
Phone alerts are sent day or night.

Runs as its own small systemd service, separate from the voice loop, so it
works no matter which Chatty loop is running.

Settings (all optional, via environment or /etc/chatty/ssh_announcer.env):

  CHATTY_SSH_COOLDOWN       seconds before the same user+address is announced
                            again (default 120; deploy_pi.sh opens several
                            SSH sessions back to back, this keeps it to one)
  CHATTY_SSH_KNOWN          friendly names for addresses, comma separated,
                            e.g. "100.101.102.103=Vincent's PC,192.168.1.50=laptop"
  CHATTY_SSH_ANNOUNCE_FAILED  "0" to stop announcing failed login attempts
                            (default on; rate limited to once per 5 minutes
                            per address so a bot can't make her talk nonstop)
  CHATTY_SSH_ANNOUNCE_LOGOUT  "0" to stop saying "SSH session ended" (default on)
  CHATTY_SSH_HELP_AFTER     failed attempts within 10 minutes before she adds
                            "Requesting your assistance, please" (default 5);
                            at most once every 30 minutes
  CHATTY_SSH_NIGHT_SPEAK    what she still says out loud at night: "none"
                            (default: screen only) or "help" (speak when she's
                            requesting your assistance, even at night)
  CHATTY_SSH_PHONE_ALERTS   which events also go to your phone via IFTTT:
                            "risky" (default: failed attempts and logins from
                            the internet), "all" (every login too), or "off"
  CHATTY_SSH_IFTTT_EVENT    IFTTT Webhooks event name (default chatty_alert,
                            the same one the greenhouse alerts use)
  IFTTT_KEY                 your IFTTT Webhooks key (read from Chatty's
                            secrets files by the systemd service)
  CHATTY_SSH_DRY_RUN        "1" to print instead of speaking / alerting
"""

import ipaddress
import os
import re
import shutil
import subprocess
import sys
import json
import random
import socket
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

# OpenSSH logs as "sshd" on older systems and "sshd-session" on OpenSSH 9.8+.
JOURNAL_CMD = [
    "journalctl", "--follow", "--lines=0", "--output=cat",
    "-t", "sshd", "-t", "sshd-session",
]

# Written when a logged-in user's session closes (not for failed or
# unfinished logins, which say "invalid user" / "authenticating user").
ENDED_RE = re.compile(
    r"Disconnected from user (?P<user>\S+) (?P<ip>\S+) port \d+"
)
ACCEPTED_RE = re.compile(
    r"Accepted (?P<method>\S+) for (?P<user>\S+) from (?P<ip>\S+) port \d+"
)
FAILED_RE = re.compile(
    r"Failed (?P<method>\S+) for (?:invalid user )?(?P<user>\S+) from (?P<ip>\S+) port \d+"
)

TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def parse_line(line: str):
    """Return ("accepted"|"failed"|"ended", user, ip) for an sshd log line, else None."""
    m = ACCEPTED_RE.search(line)
    if m:
        return ("accepted", m["user"], m["ip"])
    m = FAILED_RE.search(line)
    if m:
        return ("failed", m["user"], m["ip"])
    m = ENDED_RE.search(line)
    if m:
        return ("ended", m["user"], m["ip"])
    return None


def parse_known(spec: str) -> dict:
    known = {}
    for item in (spec or "").split(","):
        if "=" in item:
            ip, name = item.split("=", 1)
            if ip.strip() and name.strip():
                known[ip.strip()] = name.strip()
    return known


def describe_source(ip: str, known: dict) -> str:
    if ip in known:
        return known[ip]
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "an unknown address"
    if addr.is_loopback:
        return "this machine"
    if addr.version == 4 and addr in TAILSCALE_NET:
        return "Tailscale"
    if addr.is_private or addr.is_link_local:
        return "the home network"
    return "the internet"


HELP_LINE = "Requesting your assistance, please."


def build_message(kind: str, user: str, ip: str, known: dict, need_help: bool = False) -> str:
    source = describe_source(ip, known)
    if kind == "ended":
        msg = "SSH session ended." if user == "pi" else f"SSH session ended for {user}."
    elif kind == "accepted":
        msg = f"User {user} logged on, from {source}."
        if source in ("the internet", "an unknown address"):
            msg = ("Possible suspicious activity. " + msg +
                   " That was not from the home network or Tailscale.")
    else:
        msg = f"Possible suspicious activity. A failed SSH login for {user}, from {source}."
    if need_help:
        msg += " " + HELP_LINE
    return msg


def is_risky(kind: str, ip: str, known: dict) -> bool:
    if kind == "ended":
        return False
    return kind == "failed" or describe_source(ip, known) in ("the internet", "an unknown address")


class FailureCounter:
    """Counts failed attempts (from any address) in a sliding window, so a
    steady stream of guesses can be escalated to "requesting your assistance"."""

    def __init__(self, threshold: int, window: float = 600, clock=time.monotonic):
        self.threshold = max(1, threshold)
        self.window = window
        self.clock = clock
        self._times = []

    def add(self) -> int:
        now = self.clock()
        self._times = [t for t in self._times if now - t < self.window]
        self._times.append(now)
        return len(self._times)

    def over(self) -> bool:
        now = self.clock()
        return sum(1 for t in self._times if now - t < self.window) >= self.threshold


def phone_alert_wanted(mode: str, kind: str, ip: str, known: dict) -> bool:
    if mode == "all":
        return True
    if mode == "risky":
        return is_risky(kind, ip, known)
    return False


def build_phone_text(kind: str, user: str, ip: str, known: dict) -> str:
    host = socket.gethostname()
    source = describe_source(ip, known)
    what = {"accepted": "SSH login", "ended": "SSH session ended",
            "failed": "FAILED SSH login (possible suspicious activity)"}[kind]
    return f"Chatty ({host}): {what} as {user} from {ip} ({source})"


def send_phone_alert(text: str, dry_run: bool = False) -> None:
    key = os.getenv("IFTTT_KEY", "").strip()
    event = os.getenv("CHATTY_SSH_IFTTT_EVENT", "chatty_alert").strip()
    if dry_run:
        print(f"Phone alert: {text}", flush=True)
        return
    if not key:
        print("Phone alert skipped: IFTTT_KEY is not set", flush=True)
        return
    req = urllib.request.Request(
        f"https://maker.ifttt.com/trigger/{event}/with/key/{key}",
        data=json.dumps({"value1": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
        print("Phone alert sent", flush=True)
    except Exception as e:
        # Never print the URL here: it contains the key.
        print(f"Phone alert failed: {type(e).__name__}", flush=True)


class Debouncer:
    def __init__(self, cooldown: float, clock=time.monotonic):
        self.cooldown = cooldown
        self.clock = clock
        self._last = {}

    def allow(self, key) -> bool:
        now = self.clock()
        last = self._last.get(key)
        if last is not None and now - last < self.cooldown:
            return False
        self._last[key] = now
        return True


def speak(text: str, dry_run: bool = False) -> None:
    print(f"Announce: {text}", flush=True)
    if dry_run:
        return
    # Prefer Chatty's Piper voice. If the speaker is busy (Chatty is mid
    # sentence), wait a moment and try again before falling back to espeak-ng.
    try:
        from tts_piper import speak as speak_piper
    except Exception as e:
        speak_piper = None
        print(f"Piper unavailable: {e}", flush=True)
    if speak_piper:
        for attempt in range(3):
            try:
                speak_piper(text)
                return
            except Exception as e:
                print(f"Piper attempt {attempt + 1} failed: {e}", flush=True)
                time.sleep(2)
    if shutil.which("espeak-ng"):
        subprocess.run(["espeak-ng", text], check=False)


# A little something for whoever is up late (screen only, never spoken).
LATE_NIGHT_SIGNOFFS = [
    "Get some rest.",
    "The cats have the night watch now.",
    "Even nodes need sleep. Goodnight.",
    "I'll keep an eye on things. Sleep well.",
]


def late_night_signoff(rng=random) -> str:
    return rng.choice(LATE_NIGHT_SIGNOFFS)


def show_on_screen(text: str, dry_run: bool = False) -> None:
    print(f"Night mode, on screen: {text}", flush=True)
    if dry_run:
        return
    try:
        import face_link
        face_link.notice(text)
    except Exception as e:
        print(f"Couldn't reach the face: {e}", flush=True)


def speak_now(need_help: bool, night: bool, night_speak: str) -> bool:
    """Out loud, or (at night) on screen only?"""
    if not night:
        return True
    return night_speak == "help" and need_help


def notify(kind, user, ip, known, say_it, phone_mode, dry_run,
           need_help=False, night=False, night_speak="none") -> None:
    # Phone first: it's quick, and it matters most when nobody is home to hear.
    if phone_alert_wanted(phone_mode, kind, ip, known) or need_help:
        text = build_phone_text(kind, user, ip, known)
        if need_help:
            text += " - Chatty is requesting your assistance"
        send_phone_alert(text, dry_run)
    if not say_it:
        return
    message = build_message(kind, user, ip, known, need_help)
    if kind == "ended" and night:
        message += " " + late_night_signoff()
    if speak_now(need_help, night, night_speak):
        speak(message, dry_run)
    else:
        show_on_screen(message, dry_run)


def main() -> None:
    cooldown = float(os.getenv("CHATTY_SSH_COOLDOWN", "120"))
    known = parse_known(os.getenv("CHATTY_SSH_KNOWN", ""))
    announce_failed = os.getenv("CHATTY_SSH_ANNOUNCE_FAILED", "1") == "1"
    dry_run = os.getenv("CHATTY_SSH_DRY_RUN", "0") == "1"
    phone_mode = os.getenv("CHATTY_SSH_PHONE_ALERTS", "risky").strip().lower()
    announce_logout = os.getenv("CHATTY_SSH_ANNOUNCE_LOGOUT", "1") == "1"
    night_speak = os.getenv("CHATTY_SSH_NIGHT_SPEAK", "none").strip().lower()
    try:
        help_after = int(os.getenv("CHATTY_SSH_HELP_AFTER", "5"))
    except ValueError:
        help_after = 5

    from quiet_hours import is_night

    login_gate = Debouncer(cooldown)
    ended_gate = Debouncer(cooldown)
    failed_gate = Debouncer(max(cooldown, 300))
    help_gate = Debouncer(1800)   # "requesting your assistance" at most every 30 min
    failures = FailureCounter(help_after)

    print("Chatty SSH announcer watching the journal...", flush=True)
    proc = subprocess.Popen(JOURNAL_CMD, stdout=subprocess.PIPE, text=True)
    for line in proc.stdout:
        parsed = parse_line(line)
        if not parsed:
            continue
        kind, user, ip = parsed
        night = is_night()
        if kind == "ended":
            if announce_logout and ended_gate.allow((user, ip)):
                notify(kind, user, ip, known, True, "off", dry_run, night=night)
            continue
        if kind == "failed":
            failures.add()
            # Many attempts in a short time: ask for help (even if this
            # address was just announced), at most every 30 minutes.
            need_help = failures.over() and help_gate.allow("failed")
            # Otherwise failed attempts are keyed by address only, so a bot
            # cycling through usernames can't make Chatty talk nonstop.
            if need_help or failed_gate.allow(ip):
                notify(kind, user, ip, known, announce_failed or need_help, phone_mode,
                       dry_run, need_help, night, night_speak)
            continue
        if login_gate.allow((user, ip)):
            # a login from outside home and Tailscale is worth a person's attention
            need_help = is_risky(kind, ip, known) and help_gate.allow(("login", ip))
            notify(kind, user, ip, known, True, phone_mode, dry_run,
                   need_help, night, night_speak)
    sys.exit(proc.wait() or 1)  # journalctl exited; let systemd restart us


if __name__ == "__main__":
    main()
