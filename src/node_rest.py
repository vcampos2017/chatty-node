"""Which nodes said goodbye properly, and when Chatty should start to worry.

A node that powers down or restarts properly (node_goodbye.py in each node's
repo) posts a retained goodbye on MQTT instead of vanishing:

    chatty/nodes/<name>/status   {"state": "offline", "clean": true,
                                  "reason": "reboot", "ts": ..., "back_within": 600}

mesh.py waits quietly for it to come back (see its docstring for how long) and
keeps the list here, in ~/.local/share/chatty/node_rest.json:

    {"greenhouse": {"until": 1731770000, "since": 1731766400, "reason": "shutdown"}}

so the other checkers on the Pi (chatty_core.py's greenhouse check runs as its
own service) don't send their own "offline" alert during that time either.

resting(name) -> the entry while it's still in its wait, else None.
stop_reason() -> what this Pi is doing right now: "reboot", "shutdown",
"restart" (only this service) or "stop"; asks systemd's job list, no root needed.

Settings:
    CHATTY_NODE_REST_FILE   where the list is kept
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Dict, Optional

import storage

FILE = os.path.expanduser(os.getenv("CHATTY_NODE_REST_FILE",
                                    "~/.local/share/chatty/node_rest.json"))


def save(nodes: Dict[str, dict], path: str = None) -> None:
    storage.save_json(path or FILE, nodes)


def load(path: str = None) -> Dict[str, dict]:
    data = storage.load_json(path or FILE, {})
    return data if isinstance(data, dict) else {}


def resting(name: str, now: Optional[float] = None, path: str = None) -> Optional[dict]:
    """The node's goodbye entry while Chatty is still waiting for it, else None."""
    now = time.time() if now is None else now
    entry = load(path).get(name)
    if not isinstance(entry, dict):
        return None
    try:
        if float(entry.get("until", 0)) > now:
            return entry
    except (TypeError, ValueError):
        pass
    return None


def reason_from_jobs(jobs: str) -> str:
    """Read `systemctl list-jobs --no-legend` (JOB UNIT TYPE STATE per line)."""
    units, types = set(), set()
    for line in jobs.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            units.add(parts[1])
            types.add(parts[2])
    if units & {"reboot.target", "kexec.target", "soft-reboot.target"}:
        return "reboot"
    if units & {"poweroff.target", "halt.target", "shutdown.target"}:
        return "shutdown"
    if "restart" in types:
        return "restart"
    return "stop"


def stop_reason(run=subprocess.run) -> str:
    try:
        out = run(["systemctl", "list-jobs", "--no-legend", "--no-pager"],
                  capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return "stop"
    return reason_from_jobs(out or "")


if __name__ == "__main__":
    # On the Pi:  python3 src/node_rest.py     (who Chatty is waiting on)
    now = time.time()
    entries = load()
    if not entries:
        print("No node is away after a goodbye.")
    for name, e in sorted(entries.items()):
        left = (float(e.get("until", 0)) - now) / 60
        print(f"{name}: {e.get('reason')}, " +
              (f"waiting {left:.0f} more min" if left > 0 else "overdue"))
