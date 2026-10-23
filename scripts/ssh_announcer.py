#!/usr/bin/env python3
"""Chatty SSH announcer.

Watches the system journal for SSH logins on the Chatty Pi and has Chatty
say so out loud ("Heads up. Someone just logged in over SSH as pi, from
Tailscale."). Runs as its own small systemd service, separate from the
voice loop, so it works no matter which Chatty loop is running.

Settings (all optional, via environment or /etc/chatty/ssh_announcer.env):

  CHATTY_SSH_COOLDOWN       seconds before the same user+address is announced
                            again (default 120; deploy_pi.sh opens several
                            SSH sessions back to back, this keeps it to one)
  CHATTY_SSH_KNOWN          friendly names for addresses, comma separated,
                            e.g. "100.101.102.103=Vincent's PC,192.168.1.50=laptop"
  CHATTY_SSH_ANNOUNCE_FAILED  "1" to also announce failed login attempts
                            (default off; these are rate limited separately)
  CHATTY_SSH_DRY_RUN        "1" to print announcements instead of speaking
"""

import ipaddress
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

# OpenSSH logs as "sshd" on older systems and "sshd-session" on OpenSSH 9.8+.
JOURNAL_CMD = [
    "journalctl", "--follow", "--lines=0", "--output=cat",
    "-t", "sshd", "-t", "sshd-session",
]

ACCEPTED_RE = re.compile(
    r"Accepted (?P<method>\S+) for (?P<user>\S+) from (?P<ip>\S+) port \d+"
)
FAILED_RE = re.compile(
    r"Failed (?P<method>\S+) for (?:invalid user )?(?P<user>\S+) from (?P<ip>\S+) port \d+"
)

TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def parse_line(line: str):
    """Return ("accepted"|"failed", user, ip) for an sshd log line, else None."""
    m = ACCEPTED_RE.search(line)
    if m:
        return ("accepted", m["user"], m["ip"])
    m = FAILED_RE.search(line)
    if m:
        return ("failed", m["user"], m["ip"])
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


def build_message(kind: str, user: str, ip: str, known: dict) -> str:
    source = describe_source(ip, known)
    if kind == "accepted":
        msg = f"Heads up. Someone just logged in over SSH as {user}, from {source}."
        if source == "the internet":
            msg += " That was not from the home network or Tailscale."
        return msg
    return f"Warning. A failed SSH login attempt for {user}, from {source}."


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


def main() -> None:
    cooldown = float(os.getenv("CHATTY_SSH_COOLDOWN", "120"))
    known = parse_known(os.getenv("CHATTY_SSH_KNOWN", ""))
    announce_failed = os.getenv("CHATTY_SSH_ANNOUNCE_FAILED", "0") == "1"
    dry_run = os.getenv("CHATTY_SSH_DRY_RUN", "0") == "1"

    login_gate = Debouncer(cooldown)
    failed_gate = Debouncer(max(cooldown, 300))

    print("Chatty SSH announcer watching the journal...", flush=True)
    proc = subprocess.Popen(JOURNAL_CMD, stdout=subprocess.PIPE, text=True)
    for line in proc.stdout:
        parsed = parse_line(line)
        if not parsed:
            continue
        kind, user, ip = parsed
        if kind == "failed":
            # Failed attempts are keyed by address only, so a bot cycling
            # through usernames can't make Chatty talk nonstop.
            if announce_failed and failed_gate.allow(ip):
                speak(build_message(kind, user, ip, known), dry_run)
            continue
        if login_gate.allow((user, ip)):
            speak(build_message(kind, user, ip, known), dry_run)
    sys.exit(proc.wait() or 1)  # journalctl exited; let systemd restart us


if __name__ == "__main__":
    main()
