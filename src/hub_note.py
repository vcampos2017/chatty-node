"""Chatty's "here I am" note for the other nodes: `chatty/hub` (retained).

Her WiFi keeper can move her from GF-Home to the AVC-2G extender and back.
Her home address changes with it, and "chatty-node.local" often doesn't make
it across the extender, so on 2026-11-13 the rain node, greenhouse and word
clock lost her. Now she tells the nodes where to find her:

    chatty/hub  {"host": "chatty-node", "wifi": "AVC-2G",
                 "lan": ["192.168.1.77"], "tailscale": "100.69.130.79",
                 "known": {"GF-Home": "192.168.1.50", "AVC-2G": "192.168.1.77"},
                 "port": 1883, "ts": 1794600000}

"known" is the home address she had on each WiFi she has used, so a node
knows where to look for her on the other one before she even moves. The
nodes (broker_link.py in their repos) keep the note, try those addresses,
then Tailscale, and follow her back home when she answers there.

Only where she is: no passwords, no commands. The note is posted to her own
broker, which is open to the home network and Tailscale only.

Kept in ~/.local/share/chatty/hub.json (the "known" list).
Settings: CHATTY_HUB_NOTE=0 turns it off.
Check on the Pi: python3 src/hub_note.py
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import time
from typing import Dict, List, Optional, Tuple

ENABLED = os.getenv("CHATTY_HUB_NOTE", "1") != "0"
TOPIC = "chatty/hub"
STATE = os.path.expanduser("~/.local/share/chatty/hub.json")
WIFI_STATUS = os.getenv("CHATTY_WIFI_STATUS_FILE", "/run/chatty-wifi.json")
REFRESH = 900       # post again at least this often (seconds), even unchanged
TAILNET = ipaddress.ip_network("100.64.0.0/10")
MAX_KNOWN = 6


def addresses(ip_output: Optional[str] = None) -> Tuple[List[str], str]:
    """(home addresses, Tailscale address) from `ip -4 -o addr show`."""
    if ip_output is None:
        try:
            ip_output = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True,
                                       text=True, timeout=5).stdout
        except Exception:
            ip_output = ""
    lan, tail = [], ""
    for line in ip_output.splitlines():
        parts = line.split()
        if "inet" not in parts:
            continue
        try:
            ip = ipaddress.ip_interface(parts[parts.index("inet") + 1]).ip
        except (ValueError, IndexError):
            continue
        if ip.is_loopback or ip.is_link_local:
            continue
        if ip in TAILNET:
            tail = tail or str(ip)
        elif ip.is_private and str(ip) not in lan:
            lan.append(str(ip))
    return lan, tail


def wifi_name() -> str:
    """The WiFi she's on: from her WiFi keeper's status, else iwgetid."""
    try:
        with open(WIFI_STATUS) as f:
            ssid = json.load(f).get("ssid")
        if ssid:
            return str(ssid)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        return subprocess.run(["iwgetid", "-r"], capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except Exception:
        return ""


class HubNote:
    def __init__(self, path: str = STATE, port: int = 1883, clock=time.time,
                 look=None, wifi=None):
        self.path = path
        self.port = port
        self.clock = clock
        self.look = look or addresses
        self.wifi = wifi or wifi_name
        self.known: Dict[str, str] = {}
        self.last_sent: dict = {}
        self.last_sent_at = 0.0
        try:
            from storage import load_json
            saved = load_json(path, {}) or {}
            if isinstance(saved.get("known"), dict):
                self.known = {str(k): str(v) for k, v in saved["known"].items()}
        except Exception:
            pass

    def note(self) -> dict:
        lan, tail = self.look()
        wifi = self.wifi()
        if wifi and lan and self.known.get(wifi) != lan[0]:
            self.known.pop(wifi, None)
            self.known[wifi] = lan[0]
            while len(self.known) > MAX_KNOWN:
                self.known.pop(next(iter(self.known)))
            self._save()
        return {"host": socket.gethostname(), "wifi": wifi, "lan": lan, "tailscale": tail,
                "known": dict(self.known), "port": self.port}

    def _save(self) -> None:
        try:
            from storage import save_json
            save_json(self.path, {"known": self.known})
        except Exception as e:
            print("Hub note: couldn't save:", repr(e), flush=True)

    def due(self, force: bool = False) -> Optional[dict]:
        """The note to post now (with "ts"), or None if nothing changed lately."""
        body = self.note()
        now = self.clock()
        if not force and body == self.last_sent and now - self.last_sent_at < REFRESH:
            return None
        if body != self.last_sent and self.last_sent:
            print(f"Hub note: now on {body['wifi'] or 'no WiFi'} "
                  f"({', '.join(body['lan']) or 'no home address'})", flush=True)
        self.last_sent, self.last_sent_at = body, now
        return dict(body, ts=int(now))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    print(json.dumps(HubNote().due(force=True), indent=2))
